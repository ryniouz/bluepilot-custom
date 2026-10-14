"""Persistent bridge state: the event log and the synced-segment set."""
import json
import os
import threading
import time
from datetime import datetime, UTC

from bluepilot.bridge import config
from bluepilot.bridge.config import EVENTS_FILE, MAX_EVENTS, SYNC_LEVELS, SYNCED_FILE, STATE_DIR


def iso_now(ts: float | None = None) -> str:
  dt = datetime.fromtimestamp(time.time() if ts is None else ts, tz=UTC)  # noqa: TID251  wall clock is the point
  return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _atomic_write(path: str, data: str) -> None:
  os.makedirs(os.path.dirname(path), exist_ok=True)
  tmp = f"{path}.tmp"
  with open(tmp, "w") as f:
    f.write(data)
    f.flush()
    os.fsync(f.fileno())
  os.replace(tmp, path)


class EventLog:
  """Ring buffer of drive events; seq keeps increasing across restarts."""

  def __init__(self, state_dir: str = STATE_DIR, max_events: int = MAX_EVENTS):
    self.path = os.path.join(state_dir, EVENTS_FILE)
    self.max_events = max_events
    self.lock = threading.Lock()
    self.cond = threading.Condition(self.lock)
    self.events: list[dict] = []
    self._load()

  def _load(self) -> None:
    try:
      with open(self.path) as f:
        for line in f:
          line = line.strip()
          if line:
            try:
              self.events.append(json.loads(line))
            except ValueError:
              continue
    except FileNotFoundError:
      pass
    self.events = self.events[-self.max_events:]

  @property
  def next_seq(self) -> int:
    return (self.events[-1]["seq"] + 1) if self.events else 1

  def append(self, kind: str, route: str | None = None, segment: int | None = None, t: str | None = None) -> dict:
    with self.cond:
      event = {"seq": self.next_seq, "t": t or iso_now(), "kind": kind, "route": route, "segment": segment}
      self.events.append(event)
      if len(self.events) > self.max_events:
        self.events = self.events[-self.max_events:]
        _atomic_write(self.path, "".join(json.dumps(e) + "\n" for e in self.events))
      else:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with open(self.path, "a") as f:
          f.write(json.dumps(event) + "\n")
      self.cond.notify_all()
      return event

  def since(self, seq: int, limit: int = 100) -> list[dict]:
    with self.lock:
      return [e for e in self.events if e["seq"] >= seq][:limit]

  def wait_for(self, seq: int, timeout: float) -> list[dict]:
    """Block until an event with seq >= seq exists or timeout."""
    with self.cond:
      if not any(e["seq"] >= seq for e in self.events):
        self.cond.wait(timeout)
      return [e for e in self.events if e["seq"] >= seq]


class SyncedStore:
  """Segment dir -> sync level ("logs" or "full"), shared with the deleter."""

  def __init__(self, state_dir: str = STATE_DIR):
    self.path = os.path.join(state_dir, SYNCED_FILE)
    self.lock = threading.Lock()
    self.levels: dict[str, str] = load_synced(state_dir)

  def mark(self, segments: list[str], level: str) -> int:
    if level not in SYNC_LEVELS:
      raise ValueError(f"level must be one of {SYNC_LEVELS}")
    with self.lock:
      n = 0
      for seg in segments:
        # never downgrade full -> logs
        if self.levels.get(seg) == "full" and level == "logs":
          continue
        self.levels[seg] = level
        n += 1
      _atomic_write(self.path, json.dumps(self.levels, sort_keys=True))
      return n

  def level(self, segment_dir: str) -> str | None:
    with self.lock:
      return self.levels.get(segment_dir)

  def prune(self, existing: set[str]) -> None:
    """Forget segments that no longer exist on disk."""
    with self.lock:
      gone = [k for k in self.levels if k not in existing]
      if gone:
        for k in gone:
          del self.levels[k]
        _atomic_write(self.path, json.dumps(self.levels, sort_keys=True))


def load_synced(state_dir: str | None = None) -> dict[str, str]:
  """Read-only view used by the deleter; never raises."""
  try:
    with open(os.path.join(state_dir or config.STATE_DIR, SYNCED_FILE)) as f:
      data = json.load(f)
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
  except (OSError, ValueError):
    return {}
