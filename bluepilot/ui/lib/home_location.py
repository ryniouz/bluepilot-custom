"""
Home location from GPS, for the Connectivity page (and later, location-triggered automations).

GPS only runs while the truck is on, so the last good fix is kept in BPLastLocation; once parked,
that is where the truck is. "Set home here" copies it to BPHomeLocation. at_home() compares
the two (HOME_RADIUS_M).
"""

from __future__ import annotations

import json
import math
import time

from openpilot.common.params import Params

HOME_RADIUS_M = 200.0
SAVE_EVERY_S = 30.0


def _load(params: Params, key: str) -> dict | None:
  try:
    raw = params.get(key)
    data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    if isinstance(data, dict) and "lat" in data and "lon" in data:
      return data
  except Exception:
    pass
  return None


def distance_m(a: dict, b: dict) -> float:
  lat1, lon1, lat2, lon2 = map(math.radians, (a["lat"], a["lon"], b["lat"], b["lon"]))
  h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
  return 2 * 6371000.0 * math.asin(math.sqrt(h))


class HomeLocation:
  def __init__(self, params: Params | None = None):
    self._params = params or Params()
    self.last = _load(self._params, "BPLastLocation")
    self.home = _load(self._params, "BPHomeLocation")
    self._saved_at = 0.0
    self.fresh = False           # a live fix this session (truck on, GPS locked)

  def tick(self, sm):
    g = None
    for svc in ("gpsLocationExternal", "gpsLocation"):  # u-blox units / the 3X's own qcom GPS
      try:
        if svc in sm.data and sm.alive[svc] and sm[svc].hasFix and sm[svc].horizontalAccuracy <= 50:
          g = sm[svc]
          break
      except Exception:
        continue
    if g is None:
      self.fresh = False
      return
    self.fresh = True
    self.last = {"lat": round(float(g.latitude), 6), "lon": round(float(g.longitude), 6),
                 "t": time.strftime("%Y-%m-%dT%H:%M:%S")}
    now = time.monotonic()
    if now - self._saved_at > SAVE_EVERY_S:
      self._saved_at = now
      try:
        self._params.put_nonblocking("BPLastLocation", json.dumps(self.last))
      except Exception:
        pass

  def set_home_here(self) -> bool:
    if self.last is None:
      return False
    self.home = {"lat": self.last["lat"], "lon": self.last["lon"]}
    try:
      self._params.put("BPHomeLocation", json.dumps(self.home))
    except Exception:
      return False
    return True

  def clear_home(self):
    self.home = None
    try:
      self._params.remove("BPHomeLocation")
    except Exception:
      pass

  def at_home(self) -> bool | None:
    if self.home is None or self.last is None:
      return None
    return distance_m(self.home, self.last) <= HOME_RADIUS_M


_home: HomeLocation | None = None


def home_location() -> HomeLocation:
  global _home
  if _home is None:
    _home = HomeLocation()
  return _home
