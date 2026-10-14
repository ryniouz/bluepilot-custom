"""Index of recorded segments in the log root, grouped into routes."""
import os
from dataclasses import dataclass, field

from bluepilot.bridge.store import SyncedStore, iso_now


@dataclass
class Segment:
  dir: str
  route: str
  n: int
  locked: bool
  mtime: float
  files: list[dict] = field(default_factory=list)


def split_segment_dir(name: str) -> tuple[str, int] | None:
  """'00000123--a1b2c3d4e5--7' -> ('00000123--a1b2c3d4e5', 7); None for non-segment dirs."""
  route, sep, n = name.rpartition("--")
  if not sep or not route or not n.isdigit():
    return None
  return route, int(n)


def scan(log_root: str, allowed_files: frozenset[str]) -> list[Segment]:
  segments: list[Segment] = []
  try:
    names = os.listdir(log_root)
  except OSError:
    return segments
  for name in names:
    parsed = split_segment_dir(name)
    path = os.path.join(log_root, name)
    if parsed is None or not os.path.isdir(path):
      continue
    try:
      entries = os.listdir(path)
      mtime = os.path.getmtime(path)
    except OSError:
      continue
    files = []
    for fn in sorted(entries):
      if fn in allowed_files:
        try:
          files.append({"name": fn, "size": os.path.getsize(os.path.join(path, fn))})
        except OSError:
          continue
    locked = any(fn.endswith(".lock") for fn in entries)
    segments.append(Segment(dir=name, route=parsed[0], n=parsed[1], locked=locked, mtime=mtime, files=files))
  segments.sort(key=lambda s: (s.route, s.n))
  return segments


def routes_payload(segments: list[Segment], synced: SyncedStore, synced_filter: bool | None = None) -> list[dict]:
  by_route: dict[str, list[Segment]] = {}
  for s in segments:
    by_route.setdefault(s.route, []).append(s)
  out = []
  for route, segs in by_route.items():
    seg_json = [{
      "n": s.n, "dir": s.dir, "locked": s.locked, "mtime": iso_now(s.mtime),
      "synced": synced.level(s.dir) is not None, "syncLevel": synced.level(s.dir), "files": s.files,
    } for s in segs]
    if synced_filter is False and all(x["synced"] for x in seg_json):
      continue
    if synced_filter is True and not all(x["synced"] for x in seg_json):
      continue
    first = min(segs, key=lambda s: s.n)
    out.append({"route": route, "firstSegmentAt": iso_now(first.mtime) if first.n == 0 else None, "segments": seg_json})
  # newest first by latest mtime
  out.sort(key=lambda r: max(s["mtime"] for s in r["segments"]), reverse=True)
  return out
