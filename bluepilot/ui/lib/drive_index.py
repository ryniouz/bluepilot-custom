"""
Index of recorded drives and storage, for the Console Drives pages (Previous drives, Offloading, Storage).

Scans the log root on a background thread (a few thousand stat calls on a full disk), so a page
only ever reads the latest finished snapshot. Sync state comes from the data-export bridge's
synced.json when that build has it; distance and place names come from the BluePilot Portal's
route metrics cache when the portal has processed a drive.
"""

from __future__ import annotations

import json
import os
import shutil
import threading
import time
from dataclasses import dataclass, field

from openpilot.system.hardware.hw import Paths

BRIDGE_SYNCED = os.environ.get("BP_BRIDGE_STATE_DIR", "/data/bluepilot/bridge") + "/synced.json"
PORTAL_METRICS = "/data/bluepilot/routes/metrics_cache" if os.path.exists("/data") else \
  os.path.expanduser("~/comma_data/bluepilot/routes/metrics_cache")
PRESERVE_ATTR = "user.preserve"
REFRESH_S = 30.0
SEGMENT_S = 60.0
CAMERA_FILES = ("fcamera.hevc", "ecamera.hevc", "dcamera.hevc", "qcamera.ts")
VIDEO_FILES = ("fcamera.hevc", "ecamera.hevc", "dcamera.hevc")
LOW_RES_FILES = ("qcamera.ts",)
LOG_FILES = ("rlog", "rlog.zst", "rlog.bz2", "qlog", "qlog.zst", "qlog.bz2")
# What comma's uploader sends on its own (qlogs always, the small road video on Wi-Fi); it marks each sent file
# with the user.upload xattr (system/loggerd/uploader.py). Full video and rlogs only go when requested from connect.
CONNECT_FILES = ("qlog", "qlog.zst", "qcamera.ts")
CONNECT_ATTR = "user.upload"
SUMMARY_FILE = "console_storage.json"   # next to the log root: the last scan's sizes, so Storage opens at once
SUMMARY_KEYS = ("drive_bytes", "unsynced_bytes", "bookmarked_bytes", "video_bytes", "low_res_bytes", "log_bytes",
                "sync_known")


@dataclass
class Drive:
  route: str
  start_wall: float            # seconds since epoch, from the first segment dir; 0 when the clock was unset
  segments: int
  bytes: int
  camera_bytes: int
  synced_segments: int
  recording: bool
  bookmarked: bool
  distance_m: float | None = None
  start_place: str = ""
  end_place: str = ""

  @property
  def duration_s(self) -> float:
    return self.segments * SEGMENT_S

  @property
  def synced(self) -> bool:
    return self.synced_segments >= self.segments > 0


@dataclass
class DriveIndex:
  drives: list[Drive] = field(default_factory=list)
  disk_total: int = 0
  disk_free: int = 0
  drive_bytes: int = 0
  unsynced_bytes: int = 0
  bookmarked_bytes: int = 0
  video_bytes: int = 0          # full-res cameras
  low_res_bytes: int = 0        # qcamera
  log_bytes: int = 0            # rlog / qlog
  connect_pending: int = 0      # files comma's uploader will still send
  connect_pending_bytes: int = 0
  connect_sent: int = 0
  sync_known: bool = False     # the export bridge has written synced.json on this device
  scanned_at: float = 0.0      # monotonic; 0 = never

  @property
  def other_bytes(self) -> int:
    return max(0, self.disk_total - self.disk_free - self.drive_bytes)


def _split(name: str) -> tuple[str, int] | None:
  route, sep, n = name.rpartition("--")
  if not sep or not route or not n.isdigit():
    return None
  return route, int(n)


def _has_preserve(path: str) -> bool:
  try:
    return os.getxattr(path, PRESERVE_ATTR) == b"1"
  except (OSError, AttributeError):
    return False


def _connect_sent(path: str) -> bool:
  try:
    return os.getxattr(path, CONNECT_ATTR) == b"1"
  except (OSError, AttributeError):
    return False


def _load_synced() -> tuple[dict[str, str], bool]:
  try:
    with open(BRIDGE_SYNCED) as f:
      data = json.load(f)
    return ({str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}), True
  except (OSError, ValueError):
    return {}, False


def _portal_metrics(route: str) -> dict:
  try:
    with open(os.path.join(PORTAL_METRICS, f"{route}.json")) as f:
      data = json.load(f)
    return data if isinstance(data, dict) else {}
  except (OSError, ValueError):
    return {}


def scan(log_root: str | None = None) -> DriveIndex:
  root = log_root or Paths.log_root()
  idx = DriveIndex()
  try:
    usage = shutil.disk_usage(root)
    idx.disk_total, idx.disk_free = usage.total, usage.free
  except OSError:
    pass
  synced, idx.sync_known = _load_synced()
  try:
    names = os.listdir(root)
  except OSError:
    names = []

  by_route: dict[str, list[tuple[int, str, float, int, int, bool, bool]]] = {}
  for name in names:
    parsed = _split(name)
    path = os.path.join(root, name)
    if parsed is None or not os.path.isdir(path):
      continue
    size = cam = 0
    locked = False
    cats = [0, 0, 0]
    connect: list[tuple[str, int]] = []
    try:
      with os.scandir(path) as it:
        for e in it:
          if e.name.endswith(".lock"):
            locked = True
          elif e.is_file():
            sz = e.stat().st_size
            size += sz
            if e.name in CAMERA_FILES:
              cam += sz
            if e.name in VIDEO_FILES:
              cats[0] += sz
            elif e.name in LOW_RES_FILES:
              cats[1] += sz
            elif e.name in LOG_FILES:
              cats[2] += sz
            if e.name in CONNECT_FILES:
              connect.append((e.path, sz))
      mtime = os.path.getmtime(path)
    except OSError:
      continue
    if not locked:
      for fp, sz in connect:
        if _connect_sent(fp):
          idx.connect_sent += 1
        else:
          idx.connect_pending += 1
          idx.connect_pending_bytes += sz
    idx.video_bytes += cats[0]
    idx.low_res_bytes += cats[1]
    idx.log_bytes += cats[2]
    by_route.setdefault(parsed[0], []).append((parsed[1], name, mtime, size, cam, locked, _has_preserve(path)))

  for route, segs in by_route.items():
    segs.sort()
    total = sum(s[3] for s in segs)
    n_synced = sum(1 for s in segs if s[1] in synced)
    unsynced = sum(s[3] for s in segs if s[1] not in synced)
    bookmarked = any(s[6] for s in segs)
    # A segment dir's mtime is close to when it was opened; before a GPS/NTP fix the clock can be 1970
    start = min(s[2] for s in segs)
    start = start if time.gmtime(start).tm_year >= 2020 else 0.0
    d = Drive(route, start, len(segs), total, sum(s[4] for s in segs), n_synced,
              any(s[5] for s in segs), bookmarked)
    m = _portal_metrics(route)
    if m.get("has_gps_data") and isinstance(m.get("total_distance_meters"), (int, float)):
      d.distance_m = float(m["total_distance_meters"])
    d.start_place = str(m.get("start_location") or "")
    d.end_place = str(m.get("end_location") or "")
    idx.drives.append(d)
    idx.drive_bytes += total
    idx.unsynced_bytes += unsynced
    if bookmarked:
      idx.bookmarked_bytes += total

  idx.drives.sort(key=lambda d: (d.start_wall, d.route), reverse=True)
  idx.scanned_at = time.monotonic()
  save_summary(idx, root)
  return idx


def _summary_path(root: str) -> str:
  return os.path.join(os.path.dirname(root.rstrip("/")), SUMMARY_FILE)


def save_summary(idx: DriveIndex, root: str) -> None:
  try:
    tmp = _summary_path(root) + ".tmp"
    with open(tmp, "w") as f:
      json.dump({k: getattr(idx, k) for k in SUMMARY_KEYS}, f)
    os.replace(tmp, _summary_path(root))
  except OSError:
    pass


def cached_index(log_root: str | None = None) -> DriveIndex:
  """Sizes from the last finished scan (any boot) with free space read now; no drive list (scanned_at stays 0).
  Disk total and free are always there, so Storage never waits on a full scan to show something."""
  root = log_root or Paths.log_root()
  idx = DriveIndex()
  try:
    usage = shutil.disk_usage(root)
    idx.disk_total, idx.disk_free = usage.total, usage.free
  except OSError:
    pass
  try:
    with open(_summary_path(root)) as f:
      saved = json.load(f)
    for k in SUMMARY_KEYS:
      if k in saved:
        setattr(idx, k, type(getattr(idx, k))(saved[k]))
  except (OSError, ValueError, TypeError):
    pass
  return idx


class DriveIndexer:
  """Rescans in the background while some page wants fresh data (request() each frame it is shown)."""

  def __init__(self, log_root: str | None = None):
    self._root = log_root
    self._lock = threading.Lock()
    self._index = cached_index(log_root)
    self._busy = False
    self._wanted_at = 0.0

  @property
  def index(self) -> DriveIndex:
    with self._lock:
      return self._index

  @property
  def busy(self) -> bool:
    return self._busy

  def request(self, force: bool = False):
    now = time.monotonic()
    self._wanted_at = now
    idx = self.index
    if self._busy or (not force and idx.scanned_at and now - idx.scanned_at < REFRESH_S):
      return
    self._busy = True
    threading.Thread(target=self._run, name="console-drive-index", daemon=True).start()

  def _run(self):
    try:
      idx = scan(self._root)
      with self._lock:
        self._index = idx
    finally:
      self._busy = False


_indexer: DriveIndexer | None = None


def indexer() -> DriveIndexer:
  global _indexer
  if _indexer is None:
    _indexer = DriveIndexer()
  return _indexer
