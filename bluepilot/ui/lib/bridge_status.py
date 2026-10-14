"""
Read-only view of the data-export bridge's status file (bp_bridge, Comma 3X BluePilot work).

The bridge rewrites the file every 2 s (storage every 30 s). A missing file, or one whose `t`
is older than STALE_S, means the bridge is off; callers then fall back to their own data.
Shape: /mnt/project-files/comma/ROAD-TRIP-PLAN.md, "Status fields".
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime

STATUS_FILE = os.environ.get("BP_BRIDGE_STATUS_PATH", "/dev/shm/bp_bridge_status.json")  # tmpfs: rewritten every 2 s
STALE_S = 10.0
READ_EVERY_S = 1.0

_cache: dict | None = None
_read_at = 0.0


def _age_s(t: str) -> float:
  try:
    dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
    return time.time() - dt.timestamp()  # noqa: TID251  wall clock: comparing to the bridge's wall-clock stamp
  except (ValueError, AttributeError):
    return float("inf")


def status() -> dict | None:
  """The bridge's latest status, or None when the bridge is off or stale."""
  global _cache, _read_at
  now = time.monotonic()
  if now - _read_at >= READ_EVERY_S:
    _read_at = now
    try:
      with open(STATUS_FILE) as f:
        data = json.load(f)
      _cache = data if isinstance(data, dict) else None
    except (OSError, ValueError):
      _cache = None
  if _cache is None or _age_s(str(_cache.get("t", ""))) > STALE_S:
    return None
  return _cache


def get(*path, default=None):
  node = status()
  for key in path:
    if not isinstance(node, dict):
      return default
    node = node.get(key)
  return default if node is None else node
