"""Cellular data usage: accumulates the modem's byte counters and the bridge's own uploads.

The modem counters (deviceState.networkStats.wwanTx/wwanRx) are cumulative since the modem came up and
restart from zero on a modem or device restart, so usage is kept as accumulated deltas.

Where the month's cellular data went, per category (bytes sent while on cellular or a metered link):
  citadel       Citadel uploads: finished segments pushed by Road Trip Mode
  live          live data: the snapshot Road Trip Mode pushes while driving
  link          remote link: answers sent back to Citadel over the long-poll
  commaConnect  comma connect uploads, from the stock uploader's meter (bluepilot.bridge.meter)
Everything the modem counted beyond these (athena, map tiles, updates, DNS ...) is "other", never negative.
"""
import calendar
import datetime as dt
import json
import os
import threading
from collections.abc import Callable

from bluepilot.bridge.store import _atomic_write

CATEGORIES = ("commaConnect", "citadel", "live", "link")
SAVE_EVERY_BYTES = 1_000_000  # limit flash writes: save after ~1 MB of new usage, or on a day change


def month_start(today: dt.date, reset_day: int) -> dt.date:
  """The most recent billing-period start on or before `today` (reset_day clamped to the month's length)."""
  reset_day = max(1, min(31, int(reset_day or 1)))

  def start_in(year: int, month: int) -> dt.date:
    return dt.date(year, month, min(reset_day, calendar.monthrange(year, month)[1]))

  s = start_in(today.year, today.month)
  if s <= today:
    return s
  year, month = (today.year - 1, 12) if today.month == 1 else (today.year, today.month - 1)
  return start_in(year, month)


def breakdown(month_total: int, counted: dict) -> dict:
  """Per-category bytes for the month plus `other` (the modem total minus what was accounted for, never
  negative). The categories are clamped so they never add up to more than the modem counted: a metered
  Wi-Fi hotspot counts as cellular for the uploads but never reaches the modem's counters."""
  out, left = {}, max(0, int(month_total))
  for k in CATEGORIES:
    v = min(max(0, int(counted.get(k, 0))), left)
    out[k] = v
    left -= v
  out["other"] = left
  return out


def _empty(today: dt.date, start: dt.date) -> dict:
  return {"day": today.isoformat(), "monthStart": start.isoformat(),
          "cell": {"today": 0, "month": 0, "total": 0},
          "uploader": {"cellToday": 0, "cellMonth": 0, "wifiToday": 0, "wifiMonth": 0},
          "categories": dict.fromkeys(CATEGORIES, 0),
          "lastTx": None, "lastRx": None, "lastComma": None}


class DataUsage:
  def __init__(self, path: str, reset_day: Callable[[], int] = lambda: 1,
               today: Callable[[], dt.date] = dt.date.today):
    self.path = path
    self.reset_day = reset_day
    self.today = today
    self.lock = threading.Lock()
    self.unsaved = 0
    t = today()
    self.state = _empty(t, month_start(t, reset_day()))
    try:
      with open(path) as f:
        loaded = json.load(f)
      for k in ("cell", "uploader", "categories"):
        self.state[k].update({kk: int(v) for kk, v in loaded.get(k, {}).items() if kk in self.state[k]})
      self.state["day"] = loaded.get("day", self.state["day"])
      self.state["monthStart"] = loaded.get("monthStart", self.state["monthStart"])
      # lastTx/lastRx/lastComma are deliberately not restored: after a restart the counters may have reset.
    except (OSError, ValueError, AttributeError):
      pass
    self._roll()

  def _roll(self) -> bool:
    t = self.today()
    start = month_start(t, self.reset_day()).isoformat()
    changed = False
    if self.state["day"] != t.isoformat():
      self.state["day"] = t.isoformat()
      self.state["cell"]["today"] = 0
      self.state["uploader"]["cellToday"] = self.state["uploader"]["wifiToday"] = 0
      changed = True
    if self.state["monthStart"] != start:
      self.state["monthStart"] = start
      self.state["cell"]["month"] = 0
      self.state["uploader"]["cellMonth"] = self.state["uploader"]["wifiMonth"] = 0
      self.state["categories"] = dict.fromkeys(CATEGORIES, 0)
      changed = True
    return changed

  def observe_modem(self, tx: int | None, rx: int | None) -> None:
    if tx is None or rx is None or tx < 0 or rx < 0:
      return
    with self.lock:
      rolled = self._roll()
      last_tx, last_rx = self.state["lastTx"], self.state["lastRx"]
      self.state["lastTx"], self.state["lastRx"] = tx, rx
      if last_tx is None or last_rx is None:
        delta = 0  # first sample since start: we can't know what came before
      else:
        d_tx = tx - last_tx if tx >= last_tx else tx  # counter restarted from zero
        d_rx = rx - last_rx if rx >= last_rx else rx
        delta = d_tx + d_rx
      if delta:
        for k in ("today", "month", "total"):
          self.state["cell"][k] += delta
        self.unsaved += delta
      if rolled or self.unsaved >= SAVE_EVERY_BYTES:
        self._save()

  def add_upload(self, nbytes: int, cellular: bool, category: str = "citadel") -> None:
    """Bytes the bridge sent. `category` is one of CATEGORIES (not commaConnect, which is metered separately)."""
    with self.lock:
      self._roll()
      kind = "cell" if cellular else "wifi"
      self.state["uploader"][kind + "Today"] += nbytes
      self.state["uploader"][kind + "Month"] += nbytes
      if cellular and category in self.state["categories"]:
        self.state["categories"][category] += nbytes
      self.unsaved += nbytes
      if self.unsaved >= SAVE_EVERY_BYTES:
        self._save()

  def observe_comma(self, total: int | None) -> None:
    """The comma connect uploader's cellular byte meter (cumulative since boot, restarts from zero)."""
    if total is None or total < 0:
      return
    with self.lock:
      self._roll()
      last = self.state["lastComma"]
      self.state["lastComma"] = total
      if last is None:
        return  # first sample since start: what came before was already counted, or is unknowable
      delta = total - last if total >= last else total
      if delta:
        self.state["categories"]["commaConnect"] += delta
        self.unsaved += delta

  def month_bytes(self) -> int:
    with self.lock:
      self._roll()
      return self.state["cell"]["month"]

  def summary(self, limit_bytes: int = 0) -> dict:
    with self.lock:
      self._roll()
      month = self.state["cell"]["month"]
      up = self.state["uploader"]
      return {
        "cell": {"todayBytes": self.state["cell"]["today"], "monthBytes": month,
                 "totalBytes": self.state["cell"]["total"], "monthStart": self.state["monthStart"]},
        "uploader": {"cellBytesToday": up["cellToday"], "cellBytesMonth": up["cellMonth"],
                     "wifiBytesToday": up["wifiToday"], "wifiBytesMonth": up["wifiMonth"]},
        "categories": breakdown(month, self.state["categories"]),
        "limitBytes": limit_bytes,
        "remainingBytes": max(0, limit_bytes - month) if limit_bytes > 0 else None,
        "overLimit": limit_bytes > 0 and month >= limit_bytes,
      }

  def save(self) -> None:
    with self.lock:
      self._save()

  def _save(self) -> None:
    self.unsaved = 0
    os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
    _atomic_write(self.path, json.dumps({k: v for k, v in self.state.items() if k not in ("lastTx", "lastRx", "lastComma")}))
