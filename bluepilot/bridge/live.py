"""Live state: a JSON snapshot of the car and device, plus drive event detection."""
import math
import threading
import time

from bluepilot.bridge.store import EventLog, iso_now
from bluepilot.bridge import segments as seg_index

LIVE_SERVICES = ["carState", "carStateBP", "selfdriveState", "carControl", "deviceState",
                 "gpsLocationExternal", "gpsLocation", "userBookmark", "thumbnail"]
# Subscribed only when this build's cereal has them (stream B's offroad charging monitor).
OPTIONAL_SERVICES = ["chargingStateBP"]


def _num(v, digits: int = 3):
  try:
    f = float(v)
  except (TypeError, ValueError):
    return None
  if math.isnan(f) or math.isinf(f):
    return None
  return round(f, digits)


def _enum_name(v) -> str | None:
  if v is None:
    return None
  s = str(v)
  return s.split(".")[-1] if s else None


NETWORK_NAMES = {"none": "none", "wifi": "wifi", "ethernet": "ethernet", "cell2G": "cell", "cell3G": "cell",
                 "cell4G": "cell", "cell5G": "cell"}


def build_snapshot(sm, gps_service: str, onroad: bool, route: str | None, segment: int | None) -> dict:
  """sm: mapping-like of service -> capnp reader (or None), with optional `seen` set of services received."""
  def get(name):
    try:
      return sm[name]
    except (KeyError, AttributeError):
      return None

  def seen(name) -> bool:
    s = getattr(sm, "seen", None)
    return name in s if s is not None else get(name) is not None

  ds = get("deviceState")
  device = {
    "cpuTempC": _num(getattr(ds, "maxTempC", None), 1) if seen("deviceState") else None,
    "freeSpacePct": _num(getattr(ds, "freeSpacePercent", None), 1) if seen("deviceState") else None,
    "memPct": _num(getattr(ds, "memoryUsagePercent", None), 1) if seen("deviceState") else None,
    "network": NETWORK_NAMES.get(_enum_name(getattr(ds, "networkType", None)) or "", None) if seen("deviceState") else None,
  }
  snap = {"t": iso_now(), "onroad": onroad, "route": route if onroad else None, "segment": segment if onroad else None,
          "gps": None, "car": None, "ev": None, "engaged": None, "latActive": None, "experimental": None, "device": device}
  if not onroad:
    # Parked but awake (e.g. charging): chargingStateBP is the offroad source; carStateBP may still be fresh.
    if seen("chargingStateBP"):
      snap["ev"] = _ev_snapshot(get("chargingStateBP"))
    elif seen("carStateBP"):
      snap["ev"] = _ev_snapshot(get("carStateBP"))
    return snap

  gps = get(gps_service) if seen(gps_service) else None
  if gps is None and seen("gpsLocation"):
    gps = get("gpsLocation")
  if gps is not None:
    ts = getattr(gps, "unixTimestampMillis", 0) or 0
    snap["gps"] = {
      "lat": _num(gps.latitude, 7), "lon": _num(gps.longitude, 7), "alt": _num(gps.altitude, 1),
      "speed": _num(gps.speed, 2), "bearing": _num(gps.bearingDeg, 1), "acc": _num(gps.horizontalAccuracy, 1),
      "fix": bool(getattr(gps, "hasFix", False)), "t": iso_now(ts / 1000.0) if ts > 0 else None,
    }

  if seen("carState"):
    cs = get("carState")
    cruise = getattr(cs, "cruiseState", None)
    snap["car"] = {
      "speed": _num(cs.vEgo, 2), "aEgo": _num(cs.aEgo, 2), "gear": _enum_name(cs.gearShifter),
      "steeringDeg": _num(cs.steeringAngleDeg, 1), "brake": bool(cs.brakePressed), "gasPressed": bool(cs.gasPressed),
      "leftBlinker": bool(cs.leftBlinker), "rightBlinker": bool(cs.rightBlinker), "standstill": bool(cs.standstill),
      "cruise": {"enabled": bool(cruise.enabled), "speed": _num(cruise.speed, 2)} if cruise is not None else None,
    }

  if seen("carStateBP"):
    snap["ev"] = _ev_snapshot(get("carStateBP"))

  if seen("selfdriveState"):
    ss = get("selfdriveState")
    snap["engaged"] = bool(ss.enabled)
    snap["experimental"] = bool(getattr(ss, "experimentalMode", False))
  if seen("carControl"):
    snap["latActive"] = bool(get("carControl").latActive)
  return snap


def _ev_snapshot(bp) -> dict:
  """Prefer stream B's ungated evBattery; fall back to the HEV-gated hybridBattery."""
  try:
    ev = bp.evBattery
  except (AttributeError, KeyError):
    ev = None
  if ev is not None and bool(getattr(ev, "dataAvailable", False)):
    out = {"available": True, "socPct": _num(ev.socPercent, 2), "packV": _num(ev.packVoltage, 1),
           "packA": _num(ev.packCurrent, 2), "powerKw": _num(ev.powerKw, 2)}
    for src, dst, d in (("rangeKm", "rangeKm", 1), ("packTempC", "packTempC", 1), ("coolantTempC", "coolantTempC", 1)):
      out[dst] = _num(getattr(ev, src, None), d)
    out.update(_charging_fields(bp))
    return out
  hb = getattr(bp, "hybridBattery", None)
  if hb is None or not bool(hb.dataAvailable):
    return {"available": False, "socPct": None, "packV": None, "packA": None, "powerKw": None}
  v, a = _num(hb.voltActual, 1), _num(hb.ampsActual, 2)
  return {"available": True, "socPct": _num(hb.socActual, 2), "packV": v, "packA": a,
          "powerKw": round(v * a / 1000.0, 2) if v is not None and a is not None else None}


CHARGE_TYPES = {"ac": "ac", "dc": "dc", "other": "other"}


def _charging_fields(bp) -> dict:
  """Stream B's `charging` struct (on carStateBP and chargingStateBP), when this build has it."""
  try:
    ch = bp.charging
  except (AttributeError, KeyError):
    return {}
  if ch is None:
    return {}
  charging = bool(getattr(ch, "charging", False))
  out = {"charging": charging, "chargeMode": CHARGE_TYPES.get(_enum_name(getattr(ch, "chargeType", None)) or ""),
         "chargeState": _enum_name(getattr(ch, "state", None)),
         "chargePowerKw": _num(getattr(ch, "powerKw", None), 2) if getattr(ch, "powerAvailable", False) else None,
         "timeToFullH": _num(getattr(ch, "timeToFullHours", None), 2) if getattr(ch, "timeToFullAvailable", False) else None}
  sleep_s = getattr(bp, "sleepInSeconds", None)  # chargingStateBP only
  if sleep_s is not None:
    out["sleepInS"] = _num(sleep_s, 0)
  return out


class _View(dict):
  def __init__(self, data: dict, seen: set[str]):
    super().__init__(data)
    self.seen = seen


class DriveTracker:
  """Turns onroad edges, segment lock changes and bookmarks into events."""

  def __init__(self, events: EventLog):
    self.events = events
    self.onroad = False
    self.locked: set[str] = set()
    self.current_route: str | None = None
    self.current_segment: int | None = None

  def update_onroad(self, onroad: bool) -> None:
    if onroad and not self.onroad:
      self.events.append("drive_started", self.current_route, self.current_segment)
    elif self.onroad and not onroad:
      self.events.append("drive_finished", self.current_route, self.current_segment)
    self.onroad = onroad

  def update_segments(self, segments: list[seg_index.Segment]) -> None:
    now_locked = {s.dir for s in segments if s.locked}
    by_dir = {s.dir: s for s in segments}
    for d in sorted(self.locked - now_locked):
      s = by_dir.get(d)
      if s is not None:
        self.events.append("segment_closed", s.route, s.n)
    self.locked = now_locked
    if now_locked:
      newest = max((by_dir[d] for d in now_locked), key=lambda s: (s.mtime, s.n))
      self.current_route, self.current_segment = newest.route, newest.n

  def bookmark(self) -> None:
    self.events.append("bookmark", self.current_route, self.current_segment)


class LiveMonitor(threading.Thread):
  """Polls cereal at ~5 Hz; keeps the latest snapshot and thumbnail."""

  def __init__(self, events: EventLog, log_root: str, allowed_files, gps_service: str, on_modem_bytes=None):
    super().__init__(daemon=True, name="bp_bridge_live")
    self.on_modem_bytes = on_modem_bytes  # called with (wwanTx, wwanRx) on each deviceState
    self.network: dict = {}
    self.tracker = DriveTracker(events)
    self.log_root = log_root
    self.allowed_files = allowed_files
    self.gps_service = gps_service
    self.lock = threading.Lock()
    self.snapshot: dict = build_snapshot({}, gps_service, False, None, None)
    self.thumbnail: bytes | None = None
    self.stop_event = threading.Event()

  def latest(self) -> dict:
    with self.lock:
      return self.snapshot

  def latest_network(self) -> dict:
    """deviceState network fields as enum names: {type, metered, strength}; {} until deviceState arrives."""
    with self.lock:
      return self.network

  def latest_thumbnail(self) -> bytes | None:
    with self.lock:
      return self.thumbnail

  def run(self) -> None:
    import cereal.messaging as messaging  # device-only import

    from cereal.services import SERVICE_LIST
    services = LIVE_SERVICES + [s for s in OPTIONAL_SERVICES if s in SERVICE_LIST]
    sm = messaging.SubMaster(services)
    last_update: dict[str, float] = {}

    last_scan = 0.0
    while not self.stop_event.is_set():
      sm.update(200)
      now = time.monotonic()
      for name in services:
        if sm.updated[name]:
          last_update[name] = now
      seen = {name for name, t in last_update.items() if now - t < 5.0}
      onroad = bool(sm["deviceState"].started) if "deviceState" in seen else False
      network = {}
      if "deviceState" in seen:
        ds = sm["deviceState"]
        ni = ds.networkInfo
        network = {"type": _enum_name(ds.networkType), "metered": bool(ds.networkMetered),
                   "strength": _enum_name(ds.networkStrength),
                   "info": {"technology": ni.technology, "operator": ni.operator, "band": ni.band,
                            "channel": int(ni.channel), "state": ni.state}}
        if sm.updated["deviceState"] and self.on_modem_bytes is not None:
          self.on_modem_bytes(int(ds.networkStats.wwanTx), int(ds.networkStats.wwanRx))

      if now - last_scan > 5.0:
        last_scan = now
        self.tracker.update_segments(seg_index.scan(self.log_root, self.allowed_files))
      self.tracker.update_onroad(onroad)
      if sm.updated["userBookmark"]:
        self.tracker.bookmark()
      view = _View({name: sm[name] for name in services}, seen)
      snap = build_snapshot(view, self.gps_service, onroad, self.tracker.current_route, self.tracker.current_segment)
      thumb = None
      if sm.updated["thumbnail"] and _enum_name(sm["thumbnail"].encoding) == "jpeg":
        thumb = bytes(sm["thumbnail"].thumbnail)
      with self.lock:
        self.snapshot = snap
        self.network = network
        if thumb:
          self.thumbnail = thumb
        if not onroad:
          self.thumbnail = None
