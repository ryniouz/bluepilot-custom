"""HTTP API for the bridge (DEVICE-API.md v1). Standard library only."""
import hmac
import json
import os
import re
import time
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Protocol
from collections.abc import Callable
from urllib.parse import parse_qs, urlparse

from bluepilot.bridge import API_VERSION
from bluepilot.bridge import segments as seg_index
from bluepilot.bridge.config import ALLOWED_FILES, LIVE_HZ_MAX, LIVE_HZ_MIN, SSE_PING_S
from bluepilot.bridge.params_allowlist import READABLE, WRITABLE
from bluepilot.bridge.settings_schema import BY_KEY, GROUPS, validate_value
from bluepilot.bridge.store import EventLog, SyncedStore, iso_now

CHUNK = 256 * 1024
SEGMENT_DIR_RE = re.compile(r"^[0-9A-Za-z_-]+--\d+$")
RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


class ParamsAdapter(Protocol):
  def get(self, key: str) -> Any: ...
  def put(self, key: str, value: Any) -> None: ...
  def is_onroad(self) -> bool: ...


class LiveSource(Protocol):
  def latest(self) -> dict: ...
  def latest_thumbnail(self) -> bytes | None: ...


@dataclass
class BridgeContext:
  token: Callable[[], str]
  events: EventLog
  synced: SyncedStore
  log_root: str
  live: LiveSource
  params: ParamsAdapter
  version: str
  dongle_id: str | None
  started_at: float = field(default_factory=time.monotonic)
  free_space_pct: Callable[[], float | None] = lambda: None
  keep_until_synced: Callable[[], bool] = lambda: False
  on_notify_needed: Callable[[], None] = lambda: None
  connectivity: Callable[[], dict] | None = None
  storage: Callable[[], dict] | None = None


class BridgeHandler(BaseHTTPRequestHandler):
  server_version = "bp_bridge/1"
  protocol_version = "HTTP/1.1"
  ctx: BridgeContext  # set by make_server

  def log_message(self, fmt, *args):  # quiet; the manager captures stderr
    pass

  # ---- helpers
  def _send_json(self, status: int, body: Any, extra_headers: dict | None = None) -> None:
    data = json.dumps(body, separators=(",", ":")).encode()
    self.send_response(status)
    self.send_header("Content-Type", "application/json")
    self.send_header("Content-Length", str(len(data)))
    self.send_header("Cache-Control", "no-store")
    for k, v in (extra_headers or {}).items():
      self.send_header(k, v)
    self.end_headers()
    if self.command != "HEAD":
      self.wfile.write(data)

  def _error(self, status: int, code: str, message: str | None = None) -> None:
    self._send_json(status, {"error": code, "message": message or code})

  def _authorized(self) -> bool:
    expected = self.ctx.token()
    given = self.headers.get("Authorization", "")
    if not expected or not given.startswith("Bearer "):
      return False
    return hmac.compare_digest(given[7:].strip().encode(), expected.encode())

  def _read_json(self) -> Any:
    length = int(self.headers.get("Content-Length") or 0)
    if length <= 0 or length > 1024 * 1024:
      raise ValueError("body required (max 1 MiB)")
    return json.loads(self.rfile.read(length))

  # ---- dispatch
  def do_GET(self):
    self._dispatch("GET")

  def do_HEAD(self):
    self._dispatch("HEAD")

  def do_POST(self):
    self._dispatch("POST")

  def do_PUT(self):
    self._dispatch("PUT")

  def _dispatch(self, method: str) -> None:
    url = urlparse(self.path)
    path, query = url.path.rstrip("/") or "/", parse_qs(url.query)
    try:
      if method in ("GET", "HEAD") and path == "/v1/ping":
        return self._send_json(200, {"ok": True, "api": API_VERSION})
      if not self._authorized():
        return self._error(401, "unauthorized", "Bearer token required.")
      if method in ("GET", "HEAD"):
        if path == "/v1/health":
          return self._health()
        if path == "/v1/live":
          return self._send_json(200, self.ctx.live.latest())
        if path == "/v1/live/stream":
          return self._live_stream(query)
        if path == "/v1/events":
          return self._events(query)
        if path == "/v1/routes":
          return self._routes(query)
        if path.startswith("/v1/files/"):
          return self._file(path[len("/v1/files/"):], query)
        if path == "/v1/snapshot":
          return self._snapshot(query)
        if path == "/v1/params":
          return self._params_get(query)
        if path == "/v1/settings":
          return self._settings_get()
        if path == "/v1/connectivity" and self.ctx.connectivity is not None:
          return self._send_json(200, self.ctx.connectivity())
        if path == "/v1/storage" and self.ctx.storage is not None:
          return self._send_json(200, self.ctx.storage())
      elif method == "POST" and path == "/v1/synced":
        return self._synced()
      elif method == "PUT" and path == "/v1/settings":
        return self._settings_put()
      elif method == "PUT" and path.startswith("/v1/params/"):
        return self._params_put(path[len("/v1/params/"):])
      return self._error(404, "not_found")
    except (BrokenPipeError, ConnectionResetError):
      return
    except (ValueError, TypeError) as e:
      return self._error(400, "invalid_request", str(e))

  # ---- routes
  def _health(self) -> None:
    segs = seg_index.scan(self.ctx.log_root, ALLOWED_FILES)
    unsynced = sum(1 for s in segs if not s.locked and self.ctx.synced.level(s.dir) is None)
    self._send_json(200, {
      "ok": True, "api": API_VERSION, "version": self.ctx.version, "dongleId": self.ctx.dongle_id,
      "onroad": self.ctx.params.is_onroad(), "uptimeS": int(time.monotonic() - self.ctx.started_at),
      "freeSpacePct": self.ctx.free_space_pct(), "keepUntilSynced": self.ctx.keep_until_synced(),
      "unsyncedSegments": unsynced, "now": iso_now(),
    })

  def _events(self, query: dict) -> None:
    since = int(query.get("since", ["0"])[0] or 0)
    limit = max(1, min(500, int(query.get("limit", ["100"])[0] or 100)))
    events = self.ctx.events.since(since, limit)
    nxt = (events[-1]["seq"] + 1) if events else max(since, self.ctx.events.next_seq)
    self._send_json(200, {"events": events, "next": nxt})

  def _routes(self, query: dict) -> None:
    flt = query.get("synced", [None])[0]
    synced_filter = None if flt is None else flt.lower() in ("1", "true", "yes")
    segs = seg_index.scan(self.ctx.log_root, ALLOWED_FILES)
    self.ctx.synced.prune({s.dir for s in segs})
    self._send_json(200, {"routes": seg_index.routes_payload(segs, self.ctx.synced, synced_filter)})

  def _file(self, rest: str, query: dict) -> None:
    parts = rest.split("/")
    if len(parts) != 2 or not SEGMENT_DIR_RE.match(parts[0]) or parts[1] not in ALLOWED_FILES:
      return self._error(400, "invalid_path")
    seg_dir = os.path.join(self.ctx.log_root, parts[0])
    path = os.path.join(seg_dir, parts[1])
    if not os.path.isfile(path):
      return self._error(404, "not_found")
    locked = any(fn.endswith(".lock") for fn in os.listdir(seg_dir))
    if locked and query.get("allowLocked", ["0"])[0] != "1":
      return self._error(409, "segment_locked", "Segment is still being recorded.")
    st = os.stat(path)
    size = st.st_size
    etag = f'"{size}-{int(st.st_mtime)}"'
    start, end = 0, size - 1
    status = 200
    rng = self.headers.get("Range")
    if rng and size > 0:
      m = RANGE_RE.match(rng.strip())
      if not m or (not m.group(1) and not m.group(2)):
        return self._send_json(416, {"error": "bad_range"}, {"Content-Range": f"bytes */{size}"})
      if m.group(1):
        start = int(m.group(1))
        end = min(int(m.group(2)), size - 1) if m.group(2) else size - 1
      else:
        start = max(0, size - int(m.group(2)))
      if start > end or start >= size:
        return self._send_json(416, {"error": "bad_range"}, {"Content-Range": f"bytes */{size}"})
      status = 206
    length = end - start + 1 if size > 0 else 0
    self.send_response(status)
    self.send_header("Content-Type", "application/octet-stream")
    self.send_header("Content-Length", str(length))
    self.send_header("Accept-Ranges", "bytes")
    self.send_header("ETag", etag)
    if status == 206:
      self.send_header("Content-Range", f"bytes {start}-{end}/{size}")
    self.end_headers()
    if self.command == "HEAD" or length == 0:
      return
    with open(path, "rb") as f:
      f.seek(start)
      remaining = length
      while remaining > 0:
        chunk = f.read(min(CHUNK, remaining))
        if not chunk:
          break
        self.wfile.write(chunk)
        remaining -= len(chunk)

  def _synced(self) -> None:
    body = self._read_json()
    segs = body.get("segments") if isinstance(body, dict) else None
    level = body.get("level", "logs") if isinstance(body, dict) else None
    if not isinstance(segs, list) or not all(isinstance(s, str) and SEGMENT_DIR_RE.match(s) for s in segs):
      raise ValueError("segments must be a list of segment dir names")
    n = self.ctx.synced.mark(segs, level)
    self._send_json(200, {"marked": n})

  def _snapshot(self, query: dict) -> None:
    if query.get("camera", ["road"])[0] != "road":
      return self._error(400, "invalid_request", "Only camera=road is available.")
    jpeg = self.ctx.live.latest_thumbnail()
    if not jpeg:
      return self._error(404, "not_found", "No snapshot yet.")
    self.send_response(200)
    self.send_header("Content-Type", "image/jpeg")
    self.send_header("Content-Length", str(len(jpeg)))
    self.send_header("Cache-Control", "no-store")
    self.end_headers()
    if self.command != "HEAD":
      self.wfile.write(jpeg)

  def _params_get(self, query: dict) -> None:
    keys = [k for k in ",".join(query.get("keys", [""])).split(",") if k]
    if not keys:
      keys = sorted(READABLE)
    bad = [k for k in keys if k not in READABLE]
    if bad:
      return self._error(400, "not_allowed", f"Not readable: {', '.join(bad)}")
    self._send_json(200, {"params": {k: self.ctx.params.get(k) for k in keys}, "writable": sorted(WRITABLE)})

  def _params_put(self, key: str) -> None:
    if key not in WRITABLE:
      return self._error(403, "not_allowed", f"{key} cannot be changed remotely.")
    if self.ctx.params.is_onroad():
      return self._error(409, "onroad", "Settings can only be changed while the truck is parked.")
    body = self._read_json()
    if not isinstance(body, dict) or "value" not in body:
      raise ValueError("body must be {value}")
    value = body["value"]
    if value is None or isinstance(value, (dict, list)):
      raise ValueError("value must be a string, number or boolean")
    if key in BY_KEY:
      value = validate_value(BY_KEY[key], value)
    self.ctx.params.put(key, value)
    self._send_json(200, {"key": key, "value": self.ctx.params.get(key)})

  def _settings_get(self) -> None:
    onroad = self.ctx.params.is_onroad()
    groups = [{"id": g["id"], "title": g["title"],
               "settings": [{**m, "value": self.ctx.params.get(m["key"])} for m in g["settings"]]} for g in GROUPS]
    self._send_json(200, {"onroad": onroad, "editable": not onroad, "groups": groups})

  def _settings_put(self) -> None:
    """Apply several settings at once; all are validated before any is written."""
    if self.ctx.params.is_onroad():
      return self._error(409, "onroad", "Settings can only be changed while the truck is parked.")
    body = self._read_json()
    values = body.get("values") if isinstance(body, dict) else None
    if not isinstance(values, dict) or not values:
      raise ValueError("body must be {values: {key: value}}")
    unknown = [k for k in values if k not in BY_KEY]
    if unknown:
      return self._error(403, "not_allowed", f"Cannot be changed remotely: {', '.join(unknown)}")
    normalized = {k: validate_value(BY_KEY[k], v) for k, v in values.items()}
    for k, v in normalized.items():
      self.ctx.params.put(k, v)
    self._send_json(200, {"applied": {k: self.ctx.params.get(k) for k in normalized}})

  def _live_stream(self, query: dict) -> None:
    try:
      hz = float(query.get("hz", ["1"])[0])
    except ValueError:
      hz = 1.0
    hz = max(LIVE_HZ_MIN, min(LIVE_HZ_MAX, hz))
    period = 1.0 / hz
    self.send_response(200)
    self.send_header("Content-Type", "text/event-stream")
    self.send_header("Cache-Control", "no-store")
    self.send_header("Connection", "close")
    self.end_headers()
    self.close_connection = True
    next_seq = self.ctx.events.next_seq
    last_ping = time.monotonic()
    deadline = time.monotonic() + float(query.get("maxS", ["3600"])[0])
    while not getattr(self.server, "stopping", False) and time.monotonic() < deadline:
      self._sse("live", self.ctx.live.latest())
      for e in self.ctx.events.since(next_seq, 100):
        self._sse("drive", e)
        next_seq = e["seq"] + 1
      if time.monotonic() - last_ping > SSE_PING_S:
        self.wfile.write(b": ping\n\n")
        last_ping = time.monotonic()
      self.wfile.flush()
      time.sleep(period)

  def _sse(self, event: str, data: Any) -> None:
    self.wfile.write(f"event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n".encode())


def make_server(ctx: BridgeContext, host: str = "0.0.0.0", port: int = 8090) -> ThreadingHTTPServer:
  handler = type("BoundBridgeHandler", (BridgeHandler,), {"ctx": ctx})
  server = ThreadingHTTPServer((host, port), handler)
  server.daemon_threads = True
  return server
