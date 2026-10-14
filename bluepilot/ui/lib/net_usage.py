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
      self._params.put_nonblocking(PARAM, json.dumps({"month": self.month, "bytes": self.month_bytes,
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
