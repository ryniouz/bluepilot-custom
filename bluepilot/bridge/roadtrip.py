"""Road Trip Mode: push finished segments (qlog, then low-res qcamera) and a live snapshot to our own server.

The server is the Citadel comma app (`BPServerUrl`, e.g. https://<host>/device/v1). Protocol:
  GET  <base>/ping                         -> 2xx when reachable
  PUT  <base>/upload/<segmentDir>/<file>   body = file bytes, Content-Length, X-Segment-Locked: 0
  POST <base>/live                         body = /v1/live JSON
all with `Authorization: Bearer <BPBridgeToken>`. Standard library only, so it is testable off-device.
"""
import http.client
import json
import os
import ssl
import threading
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import quote, urlparse

from bluepilot.bridge import segments as seg_index
from bluepilot.bridge.store import SyncedStore, _atomic_write, iso_now
from bluepilot.bridge.usage import DataUsage

UPLOADED_FILE = "uploaded.json"
LOG_FILES = ("qlog.zst", "qlog")
VIDEO_FILES = ("qcamera.ts",)
LIVE_PUSH_S = 10.0
PING_S = 60.0
IDLE_S = 5.0
BACKOFF_S = (5, 10, 30, 60, 120, 300)
CHUNK = 64 * 1024
TIMEOUT_S = 30.0
REACHABLE_FOR_S = 300.0


@dataclass
class RoadTripSettings:
  enabled: bool = False
  video: bool = True
  server_url: str = ""
  limit_bytes: int = 0
  limit_action: int = 0  # 0 = telemetry only once over the limit, 1 = stop uploading over cellular
  cellular: bool = True  # False: wait for unmetered Wi-Fi


class UploadedStore:
  """Which files of which segments have reached the server: {segmentDir: {file: size}}."""

  def __init__(self, state_dir: str):
    self.path = os.path.join(state_dir, UPLOADED_FILE)
    self.lock = threading.Lock()
    try:
      with open(self.path) as f:
        self.data: dict[str, dict[str, int]] = {k: dict(v) for k, v in json.load(f).items()}
    except (OSError, ValueError, AttributeError):
      self.data = {}

  def has(self, seg: str, name: str, size: int) -> bool:
    with self.lock:
      return self.data.get(seg, {}).get(name) == size

  def mark(self, seg: str, name: str, size: int) -> None:
    with self.lock:
      self.data.setdefault(seg, {})[name] = size
      _atomic_write(self.path, json.dumps(self.data))

  def prune(self, existing: set[str]) -> None:
    with self.lock:
      gone = [k for k in self.data if k not in existing]
      if gone:
        for k in gone:
          del self.data[k]
        _atomic_write(self.path, json.dumps(self.data))


def plan_uploads(segments: list[seg_index.Segment], uploaded: UploadedStore, synced: SyncedStore,
                 video: bool) -> list[tuple[str, str, int]]:
  """Files still to push, as (segmentDir, file, size).

  Only closed segments that have not already been pulled home. Telemetry first for every segment, then video,
  each newest drive first and in segment order within a drive, so the server always has the freshest trip.
  """
  todo = [s for s in segments if not s.locked and synced.level(s.dir) is None]
  route_latest: dict[str, float] = {}
  for s in todo:
    route_latest[s.route] = max(route_latest.get(s.route, 0.0), s.mtime)
  todo.sort(key=lambda s: (-route_latest[s.route], s.route, s.n))

  def pick(seg: seg_index.Segment, names: Iterable[str]) -> tuple[str, int] | None:
    sizes = {f["name"]: f["size"] for f in seg.files}
    for name in names:
      if name in sizes:
        return name, sizes[name]
    return None

  logs, vids = [], []
  for s in todo:
    p = pick(s, LOG_FILES)
    if p and p[1] > 0 and not uploaded.has(s.dir, *p):
      logs.append((s.dir, *p))
    if video:
      v = pick(s, VIDEO_FILES)
      if v and v[1] > 0 and not uploaded.has(s.dir, *v):
        vids.append((s.dir, *v))
  return logs + vids


# ---- transport

Transport = Callable[[str, str, dict, bytes | Iterable[bytes] | None], int]


def http_transport(method: str, url: str, headers: dict, body) -> int:
  """One HTTP request; returns the status code. `body` is bytes, an iterable of byte chunks, or None."""
  u = urlparse(url)
  path = (u.path or "/") + (f"?{u.query}" if u.query else "")
  if u.scheme == "https":
    conn: http.client.HTTPConnection = http.client.HTTPSConnection(u.hostname, u.port, timeout=TIMEOUT_S,
                                                                   context=ssl.create_default_context())
  elif u.scheme == "http":
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=TIMEOUT_S)
  else:
    raise ValueError(f"unsupported URL scheme: {u.scheme}")
  try:
    conn.putrequest(method, path)
    for k, v in headers.items():
      conn.putheader(k, v)
    if isinstance(body, (bytes, bytearray)):
      conn.putheader("Content-Length", str(len(body)))
      conn.endheaders(body)
    else:
      conn.endheaders()
      for chunk in body or ():
        conn.send(chunk)
    resp = conn.getresponse()
    resp.read()
    return resp.status
  finally:
    conn.close()


class RoadTripUploader(threading.Thread):
  def __init__(self, settings: Callable[[], RoadTripSettings], token: Callable[[], str], log_root: str,
               allowed_files: frozenset[str], synced: SyncedStore, uploaded: UploadedStore, usage: DataUsage,
               network: Callable[[], dict], live: Callable[[], dict], transport: Transport = http_transport,
               clock: Callable[[], float] = time.monotonic):
    super().__init__(daemon=True, name="bp_bridge_roadtrip")
    self.settings, self.token, self.log_root, self.allowed_files = settings, token, log_root, allowed_files
    self.synced, self.uploaded, self.usage = synced, uploaded, usage
    self.network, self.live, self.transport, self.clock = network, live, transport, clock
    self.lock = threading.Lock()
    self.stop_event = threading.Event()
    self.failures = 0
    self.retry_at = 0.0
    self.last_live = -1e9
    self.last_ping = -1e9
    self.last_ok: float | None = None
    self.last_ok_iso: str | None = None
    self.state = "off"
    self.paused_reason: str | None = "disabled"
    self.queue = (0, 0)
    self.current: dict | None = None
    self.last_upload: dict | None = None
    self.today = {"day": None, "files": 0, "bytes": 0}

  # ---- status
  def status(self) -> dict:
    s = self.settings()
    with self.lock:
      reachable = self.last_ok is not None and self.clock() - self.last_ok < REACHABLE_FOR_S
      return {
        "server": {"configured": bool(s.server_url), "reachable": reachable if s.server_url else False,
                   "lastContact": self.last_ok_iso, "url": s.server_url or None},
        "roadTrip": {"enabled": s.enabled, "video": s.video, "cellular": s.cellular, "state": self.state, "pausedReason": self.paused_reason,
                     "queue": {"files": self.queue[0], "bytes": self.queue[1]}, "current": self.current,
                     "lastUpload": self.last_upload,
                     "uploadedToday": {"files": self.today["files"], "bytes": self.today["bytes"]}},
      }

  def _set(self, state: str, reason: str | None) -> None:
    with self.lock:
      self.state, self.paused_reason = state, reason

  # ---- one pass of the loop; returns seconds to wait before the next
  def step(self) -> float:
    s = self.settings()
    if not s.enabled:
      self._set("off", "disabled")
      return IDLE_S
    if not s.server_url:
      self._set("paused", "no_server")
      return IDLE_S
    net = self.network()
    if net.get("type") in (None, "none"):
      self._set("paused", "no_network")
      return IDLE_S
    cellular = net.get("type") == "cell" or bool(net.get("metered"))
    if cellular and not s.cellular:
      self._set("paused", "wifi_only")
      return IDLE_S
    over = cellular and s.limit_bytes > 0 and self.usage.month_bytes() >= s.limit_bytes
    if over and s.limit_action == 1:
      self._set("paused", "over_limit")
      return IDLE_S
    now = self.clock()
    if now < self.retry_at:
      self._set("waiting", "server_error")
      return min(IDLE_S, self.retry_at - now)

    base = s.server_url.rstrip("/")
    snap = self.live()
    if snap.get("onroad") and now - self.last_live >= LIVE_PUSH_S:
      self.last_live = now
      body = json.dumps(snap, separators=(",", ":")).encode()
      if not self._request("POST", f"{base}/live", body, {"Content-Type": "application/json"}, cellular):
        return self._fail()

    segs = seg_index.scan(self.log_root, self.allowed_files)
    self.uploaded.prune({x.dir for x in segs})
    plan = plan_uploads(segs, self.uploaded, self.synced, video=s.video and not over)
    with self.lock:
      self.queue = (len(plan), sum(p[2] for p in plan))
    if not plan:
      self._set("idle", "over_limit" if over and s.video else None)
      if now - self.last_ping >= PING_S:
        self.last_ping = now
        if not self._request("GET", f"{base}/ping", None, {}, cellular):
          return self._fail()
      return IDLE_S

    seg, name, size = plan[0]
    self._set("uploading", None)
    if not self._upload(base, seg, name, size, cellular):
      return self._fail()
    return 0.0

  def _fail(self) -> float:
    self.failures += 1
    wait = BACKOFF_S[min(self.failures, len(BACKOFF_S)) - 1]
    self.retry_at = self.clock() + wait
    self._set("waiting", "server_error")
    return min(IDLE_S, wait)

  def _ok(self) -> None:
    self.failures = 0
    with self.lock:
      self.last_ok = self.clock()
      self.last_ok_iso = iso_now()

  def _headers(self, extra: dict) -> dict:
    return {"Authorization": f"Bearer {self.token()}", **extra}

  def _request(self, method: str, url: str, body: bytes | None, headers: dict, cellular: bool) -> bool:
    try:
      status = self.transport(method, url, self._headers(headers), body)
    except (OSError, http.client.HTTPException, ValueError):
      return False
    if body:
      self.usage.add_upload(len(body), cellular)
    if 200 <= status < 300:
      self._ok()
      return True
    return False

  def _upload(self, base: str, seg: str, name: str, size: int, cellular: bool) -> bool:
    path = os.path.join(self.log_root, seg, name)
    sent = [0]

    def chunks():
      with open(path, "rb") as f:
        while sent[0] < size:
          data = f.read(min(CHUNK, size - sent[0]))
          if not data:
            break
          sent[0] += len(data)
          with self.lock:
            self.current = {"segment": seg, "file": name, "pct": int(100 * sent[0] / size)}
          yield data

    with self.lock:
      self.current = {"segment": seg, "file": name, "pct": 0}
    url = f"{base}/upload/{quote(seg)}/{quote(name)}"
    try:
      status = self.transport("PUT", url, self._headers({"Content-Length": str(size),
                                                         "Content-Type": "application/octet-stream"}), chunks())
    except (OSError, http.client.HTTPException, ValueError):
      status = 0
    finally:
      self.usage.add_upload(sent[0], cellular)
      with self.lock:
        self.current = None
    if not (200 <= status < 300) or sent[0] != size:
      return False
    self._ok()
    self.uploaded.mark(seg, name, size)
    day = iso_now()[:10]
    with self.lock:
      if self.today["day"] != day:
        self.today = {"day": day, "files": 0, "bytes": 0}
      self.today["files"] += 1
      self.today["bytes"] += size
      self.last_upload = {"segment": seg, "file": name, "t": iso_now()}
    return True

  def run(self) -> None:
    while not self.stop_event.is_set():
      try:
        wait = self.step()
      except Exception:  # never let the uploader die; try again shortly
        wait = IDLE_S
      if wait > 0:
        self.stop_event.wait(wait)
