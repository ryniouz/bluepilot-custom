"""Connectivity and storage status, served at /v1/connectivity and /v1/storage and written to status.json
to tmpfs for the on-device UI (which reads the file instead of calling HTTP)."""
import json
import os
import threading
from collections.abc import Callable

from bluepilot.bridge import segments as seg_index
from bluepilot.bridge.store import SyncedStore, iso_now

# tmpfs: rewritten every 2 s, so keep it off flash. The on-device UI reads this path.
STATUS_PATH = os.environ.get("BP_BRIDGE_STATUS_PATH", "/dev/shm/bp_bridge_status.json")
WRITE_EVERY_S = 2.0
STORAGE_EVERY_S = 30.0

NETWORK_TYPES = {"none": "none", "wifi": "wifi", "ethernet": "ethernet", "cell2G": "cell", "cell3G": "cell",
                 "cell4G": "cell", "cell5G": "cell"}
STRENGTHS = {"unknown", "poor", "moderate", "good", "great"}

VIDEO = {"fcamera.hevc", "ecamera.hevc", "dcamera.hevc"}
VIDEO_LOW = {"qcamera.ts"}
LOGS = {"rlog.zst", "rlog", "qlog.zst", "qlog"}


def network_view(raw: dict | None) -> dict:
  """deviceState fields (enum names) -> {type, metered, strength}."""
  raw = raw or {}
  strength = raw.get("strength")
  return {"type": NETWORK_TYPES.get(raw.get("type") or "", "none"), "metered": bool(raw.get("metered")),
          "strength": strength if strength in STRENGTHS else "unknown"}


def storage_breakdown(segments: list[seg_index.Segment], synced: SyncedStore, total: int | None,
                      free: int | None) -> dict:
  cats = {"video": 0, "videoLowRes": 0, "logs": 0, "unsynced": 0, "system": 0}
  for s in segments:
    seg_bytes = 0
    for f in s.files:
      size = int(f.get("size") or 0)
      name = f["name"]
      if name in VIDEO:
        cats["video"] += size
      elif name in VIDEO_LOW:
        cats["videoLowRes"] += size
      elif name in LOGS:
        cats["logs"] += size
      else:
        continue
      seg_bytes += size
    if synced.level(s.dir) is None:
      cats["unsynced"] += seg_bytes
  if total is not None and free is not None:
    recorded = cats["video"] + cats["videoLowRes"] + cats["logs"]
    cats["system"] = max(0, total - free - recorded)
  return {"totalBytes": total, "freeBytes": free, "categories": cats}


def disk_usage(path: str) -> tuple[int | None, int | None]:
  try:
    st = os.statvfs(path)
  except OSError:
    return None, None
  return st.f_blocks * st.f_frsize, st.f_bavail * st.f_frsize


def cellular_view(network_info: dict | None, strength: str, sim: dict | None, modem_version: str | None,
                  roaming: bool, apn: str, metered: bool) -> dict:
  """What the modem reports, for a phone-style cellular page. Read-only except the three stock settings
  (GsmRoaming, GsmApn, GsmMetered), which the stock network settings already apply through NetworkManager."""
  ni = network_info or {}
  sim = sim or {}
  sim_state = (sim.get("sim_state") or ["UNKNOWN"])[0]
  return {
    "technology": ni.get("technology") or None, "operator": ni.get("operator") or None,
    "band": ni.get("band") or None, "channel": ni.get("channel") or None, "state": ni.get("state") or None,
    "strength": strength,
    "sim": {"present": sim_state != "ABSENT", "state": sim_state.lower(), "mccMnc": sim.get("mcc_mnc"),
            "dataConnected": bool(sim.get("data_connected"))},
    "modemVersion": modem_version or None,
    "settings": {"roaming": roaming, "apn": apn or None, "metered": metered},
  }


def connectivity(network: dict, roadtrip_status: dict, usage_summary: dict, comma_status: dict,
                 keep_until_synced: bool, unsynced_segments: int, last_synced: str | None,
                 cellular: dict | None = None, link_status: dict | None = None) -> dict:
  rt = roadtrip_status["roadTrip"]
  citadel = {"enabled": rt["enabled"], "cellular": rt.get("cellular", True), "video": rt["video"],
             "state": rt["state"], "pausedReason": rt["pausedReason"], "queue": rt["queue"],
             "current": rt["current"], "lastUpload": rt["lastUpload"], "uploadedToday": rt["uploadedToday"],
             "server": roadtrip_status["server"], "link": link_status}
  return {
    "t": iso_now(), "network": network, "cellular": cellular,
    "services": {"commaConnect": comma_status, "citadel": citadel},
    # kept for readers written against the first version of this file
    "server": roadtrip_status["server"], "roadTrip": rt, "commaConnect": comma_status["enabled"],
    "usage": usage_summary,
    "homeSync": {"keepUntilSynced": keep_until_synced, "unsyncedSegments": unsynced_segments,
                 "lastSynced": last_synced},
  }


class StatusWriter(threading.Thread):
  """Rebuilds the status every 2 s (storage every 30 s) and writes status.json atomically."""

  def __init__(self, path: str, build_connectivity: Callable[[], dict], build_storage: Callable[[], dict]):
    super().__init__(daemon=True, name="bp_bridge_status")
    self.path = path
    self.build_connectivity = build_connectivity
    self.build_storage = build_storage
    self.stop_event = threading.Event()
    self.lock = threading.Lock()
    self.storage: dict | None = None
    self.last: dict | None = None

  def latest_storage(self) -> dict:
    with self.lock:
      if self.storage is None:
        self.storage = self.build_storage()
      return self.storage

  def write_once(self, refresh_storage: bool) -> dict:
    if refresh_storage or self.storage is None:
      storage = self.build_storage()
      with self.lock:
        self.storage = storage
    doc = {**self.build_connectivity(), "storage": self.latest_storage()}
    tmp = f"{self.path}.tmp"
    with open(tmp, "w") as f:
      f.write(json.dumps(doc, separators=(",", ":")))
    os.replace(tmp, self.path)
    with self.lock:
      self.last = doc
    return doc

  def run(self) -> None:
    ticks_per_storage = int(STORAGE_EVERY_S / WRITE_EVERY_S)
    tick = 0
    while not self.stop_event.is_set():
      try:
        self.write_once(refresh_storage=tick % ticks_per_storage == 0)
      except Exception:
        pass
      tick += 1
      self.stop_event.wait(WRITE_EVERY_S)
