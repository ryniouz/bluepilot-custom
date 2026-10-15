"""Read-only status of the stock comma connect service (athenad + system/loggerd/uploader.py).

The stock uploader marks each uploaded file with the xattr `user.upload` = b"1"; athenad stores the time of the
server's last websocket ping in the `LastAthenaPingTime` param (monotonic ns) and removes it on disconnect.
Nothing here changes comma connect's behaviour.
"""
import os

from bluepilot.bridge import segments as seg_index

UPLOAD_ATTR = "user.upload"
QUEUE_FILES = ("qlog.zst", "qlog", "qcamera.ts")  # what comma connect uploads routinely (low-res)
CONNECTED_WITHIN_NS = 180 * 10**9


def is_uploaded(path: str) -> bool:
  try:
    return os.getxattr(path, UPLOAD_ATTR) == b"1"
  except OSError:
    return False


def pending(log_root: str, segments: list[seg_index.Segment]) -> tuple[int, int]:
  files = size = 0
  for s in segments:
    if s.locked:
      continue
    for f in s.files:
      if f["name"] in QUEUE_FILES and f["size"] > 0 and not is_uploaded(os.path.join(log_root, s.dir, f["name"])):
        files += 1
        size += f["size"]
  return files, size


def status(registered: bool, last_ping_ns: int | None, now_ns: int, network: dict, wifi_only: bool,
           queue: tuple[int, int]) -> dict:
  connected = registered and last_ping_ns is not None and 0 <= now_ns - last_ping_ns < CONNECTED_WITHIN_NS
  on_wifi = network.get("type") in ("wifi", "ethernet") and not network.get("metered")
  if not registered:
    state, reason = "off", "not_registered"
  elif network.get("type") in (None, "none"):
    state, reason = "paused", "no_network"
  elif wifi_only and not on_wifi:
    state, reason = ("waiting", "wifi_only") if queue[0] else ("idle", None)
  elif queue[0]:
    state, reason = "uploading", None
  else:
    state, reason = "idle", None
  return {"enabled": registered, "connected": connected, "wifiOnly": wifi_only, "state": state,
          "pausedReason": reason, "queue": {"files": queue[0], "bytes": queue[1]}}
