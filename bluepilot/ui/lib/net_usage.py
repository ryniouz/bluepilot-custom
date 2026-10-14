"""
LTE data usage, kept per calendar month across reboots.

deviceState.networkStats carries the modem's tx/rx byte counters since boot. The UI calls
tick() about once a minute; each call adds the growth since the last call to this month's
total in BPLteUsage. A counter that went backwards means the device rebooted, so the new
counter value itself is the growth.
"""

from __future__ import annotations

import json
import time

from openpilot.common.params import Params

PARAM = "BPLteUsage"
TICK_S = 60.0


class LteUsage:
  def __init__(self, params: Params | None = None):
    self._params = params or Params()
    self._last_tick = 0.0
    self.month = ""
    self.month_bytes = 0
    self.boot_bytes = 0
    self._last_total = 0
    self._load()

  def _load(self):
    try:
      raw = self._params.get(PARAM)
      data = json.loads(raw) if isinstance(raw, (str, bytes)) else (raw or {})
    except Exception:
      data = {}
    self.month = str(data.get("month", ""))
    self.month_bytes = int(data.get("bytes", 0))
    self._last_total = int(data.get("last_total", 0))

  def _save(self):
    try:
      self._params.put(PARAM, json.dumps({"month": self.month, "bytes": self.month_bytes,
                                                      "last_total": self._last_total}))
    except Exception:
      pass

  def tick(self, device_state, force: bool = False):
    now = time.monotonic()
    if not force and now - self._last_tick < TICK_S:
      return
    self._last_tick = now
    try:
      stats = device_state.networkStats
      total = int(stats.wwanTx) + int(stats.wwanRx)
    except Exception:
      return
    if total < 0:
      return
    self.boot_bytes = total
    month = time.strftime("%Y-%m")
    if month != self.month:
      self.month, self.month_bytes = month, 0
    growth = total - self._last_total if total >= self._last_total else total
    self._last_total = total
    if growth > 0:
      self.month_bytes += growth
    self._save()


_usage: LteUsage | None = None


def usage() -> LteUsage:
  global _usage
  if _usage is None:
    _usage = LteUsage()
  return _usage


# -- the Cellular page's "this month" view ---------------------------------------------------------

# Display order and names of the data export bridge's usage.categories (bluepilot/bridge/usage.py)
CATEGORIES = (("citadel", "Citadel uploads"), ("commaConnect", "comma connect"), ("live", "Live data"),
              ("link", "Remote link"), ("other", "Other and system"))


def fmt_data(n: float) -> str:
  """Carrier units: decimal MB below 1 GB, GB above (1 GB = 1000 MB, as plans count)."""
  n = max(0.0, float(n))
  if n >= 1e9:
    return f"{n / 1e9:.2f} GB" if n < 10e9 else f"{n / 1e9:.1f} GB"
  if n < 0.05e6:
    return "0 MB"
  return f"{n / 1e6:.1f} MB" if n < 10e6 else f"{n / 1e6:.0f} MB"


def month_breakdown(bridge_usage: dict | None, own_month: int) -> tuple[int, dict[str, int] | None]:
  """(bytes this month, {category: bytes} or None when nothing measured a breakdown).

  With the bridge running its count wins (it knows the billing day); its categories are clamped so they never
  add up to more than the month and `other` is the rest. An older bridge without categories still knows its
  own uploads. Without the bridge only the UI's own modem total is known: no breakdown, never a guess."""
  if not isinstance(bridge_usage, dict) or not isinstance(bridge_usage.get("cell"), dict):
    return max(0, int(own_month)), None
  month = max(0, int(bridge_usage["cell"].get("monthBytes") or 0))
  raw = bridge_usage.get("categories")
  if not isinstance(raw, dict):
    up = bridge_usage.get("uploader")
    raw = {"citadel": int(up.get("cellBytesMonth") or 0)} if isinstance(up, dict) else {}
  out, left = {}, month
  for key, _ in CATEGORIES[:-1]:
    try:
      v = int(raw.get(key) or 0)
    except (TypeError, ValueError):
      v = 0
    v = min(max(0, v), left)
    out[key] = v
    left -= v
  out["other"] = left
  return month, out


def next_reset(today, reset_day: int):
  """The date the data count starts over: the next `reset_day` (clamped to the month's length) after today."""
  import calendar
  import datetime as dt
  day = max(1, min(31, int(reset_day or 1)))

  def on(y: int, m: int):
    return dt.date(y, m, min(day, calendar.monthrange(y, m)[1]))

  d = on(today.year, today.month)
  if d > today:
    return d
  y, m = (today.year + 1, 1) if today.month == 12 else (today.year, today.month + 1)
  return on(y, m)
