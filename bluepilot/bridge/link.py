"""Remote link: lets Citadel reach this bridge's API when it can't call the device directly (away from home, on LTE).

The device dials out, so nothing has to be open on the truck's side. It long-polls Citadel's comma app:

  POST <BPServerUrl>/link/poll   {"api": 1, "results": [...]}  ->  {"commands": [...]}

Citadel holds the request until it has commands (or ~25 s), each command is one bridge API call
({id, method, path, body?}), and the answers go back with the next poll. Commands run against the bridge's
own HTTP server on localhost with the device token, so auth, the parked-only rule for settings and the
validation are exactly the LAN ones. Only small calls go over the link: no file downloads, no streams.
Standard library only.
"""
import base64
import http.client
import json
import re
import ssl
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlparse

from bluepilot.bridge import API_VERSION
from bluepilot.bridge.store import iso_now
from bluepilot.bridge.usage import DataUsage

POLL_TIMEOUT_S = 40.0     # Citadel holds a poll for up to ~25 s
LOCAL_TIMEOUT_S = 15.0
IDLE_S = 5.0
BACKOFF_S = (5, 10, 30, 60, 120, 300)
MAX_COMMANDS = 8
MAX_BODY = 1024 * 1024
CONNECTED_FOR_S = 90.0

# What may be called over the link: (method, path pattern). Everything else is refused before it reaches the API.
ALLOWED = (
  ("GET", re.compile(r"^/v1/(health|live|routes|params|settings|connectivity|storage|snapshot)$")),
  ("PUT", re.compile(r"^/v1/settings$")),
  ("PUT", re.compile(r"^/v1/params/[A-Za-z0-9_]+$")),
)

# (status, content type, body)
LocalCall = Callable[[str, str, bytes | None], tuple[int, str, bytes]]
# (method, url, headers, body) -> (status, body)
Transport = Callable[[str, str, dict, bytes], tuple[int, bytes]]


@dataclass(frozen=True)
class LinkSettings:
  enabled: bool
  server_url: str
  limit_bytes: int = 0
  limit_action: int = 0  # 1 = stop all uploads over the LTE limit; the link stops too


def allowed(method: str, path: str) -> bool:
  route = path.split("?", 1)[0]
  return any(method == m and p.match(route) for m, p in ALLOWED)


def link_transport(method: str, url: str, headers: dict, body: bytes) -> tuple[int, bytes]:
  u = urlparse(url)
  path = (u.path or "/") + (f"?{u.query}" if u.query else "")
  if u.scheme == "https":
    conn: http.client.HTTPConnection = http.client.HTTPSConnection(u.hostname, u.port, timeout=POLL_TIMEOUT_S,
                                                                   context=ssl.create_default_context())
  elif u.scheme == "http":
    conn = http.client.HTTPConnection(u.hostname, u.port, timeout=POLL_TIMEOUT_S)
  else:
    raise ValueError(f"unsupported URL scheme: {u.scheme}")
  try:
    conn.request(method, path, body=body, headers={**headers, "Content-Length": str(len(body))})
    resp = conn.getresponse()
    return resp.status, resp.read(MAX_BODY + 1)
  finally:
    conn.close()


def local_caller(port: int, token: Callable[[], str]) -> LocalCall:
  """Calls this bridge's own API on localhost."""
  def call(method: str, path: str, body: bytes | None) -> tuple[int, str, bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=LOCAL_TIMEOUT_S)
    try:
      headers = {"Authorization": f"Bearer {token()}"}
      if body is not None:
        headers["Content-Type"] = "application/json"
      conn.request(method, path, body=body, headers=headers)
      resp = conn.getresponse()
      return resp.status, resp.getheader("Content-Type") or "application/octet-stream", resp.read(MAX_BODY)
    finally:
      conn.close()
  return call


def run_command(cmd: dict, local: LocalCall) -> dict:
  """One command -> one result. Never raises."""
  cid = cmd.get("id") if isinstance(cmd, dict) else None
  if not isinstance(cid, str) or len(cid) > 64:
    return {"id": str(cid)[:64], "status": 400, "type": "application/json",
            "body": _b64(b'{"error":"invalid_request","message":"command id required"}')}
  method, path = cmd.get("method"), cmd.get("path")
  if not isinstance(method, str) or not isinstance(path, str) or not allowed(method, path):
    return _json_result(cid, 403, {"error": "not_allowed", "message": "Not available over the remote link."})
  body = None
  if cmd.get("body") is not None:
    try:
      body = base64.b64decode(cmd["body"], validate=True)
    except (ValueError, TypeError):
      return _json_result(cid, 400, {"error": "invalid_request", "message": "body must be base64"})
  try:
    status, ctype, data = local(method, path, body)
  except (OSError, http.client.HTTPException) as e:
    return _json_result(cid, 502, {"error": "bridge_unavailable", "message": str(e)})
  return {"id": cid, "status": status, "type": ctype, "body": _b64(data)}


def _b64(data: bytes) -> str:
  return base64.b64encode(data).decode()


def _json_result(cid: str, status: int, body: dict) -> dict:
  return {"id": cid, "status": status, "type": "application/json", "body": _b64(json.dumps(body).encode())}


class RemoteLink(threading.Thread):
  def __init__(self, settings: Callable[[], LinkSettings], token: Callable[[], str], local: LocalCall,
               network: Callable[[], dict], usage: DataUsage, transport: Transport = link_transport,
               clock: Callable[[], float] = time.monotonic):
    super().__init__(daemon=True, name="bp_bridge_link")
    self.settings, self.token, self.local, self.network, self.usage = settings, token, local, network, usage
    self.transport, self.clock = transport, clock
    self.lock = threading.Lock()
    self.stop_event = threading.Event()
    self.results: list[dict] = []
    self.failures = 0
    self.retry_at = 0.0
    self.state, self.paused_reason = "off", "disabled"
    self.last_ok: float | None = None
    self.last_ok_iso: str | None = None
    self.commands_today = {"day": "", "count": 0}

  def status(self) -> dict:
    with self.lock:
      connected = self.last_ok is not None and self.clock() - self.last_ok < CONNECTED_FOR_S
      return {"enabled": self.state != "off", "state": self.state, "pausedReason": self.paused_reason,
              "connected": connected, "lastContact": self.last_ok_iso,
              "commandsToday": self.commands_today["count"]}

  def _set(self, state: str, reason: str | None) -> None:
    with self.lock:
      self.state, self.paused_reason = state, reason

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
    if cellular and s.limit_action == 1 and s.limit_bytes > 0 and self.usage.month_bytes() >= s.limit_bytes:
      self._set("paused", "over_limit")
      return IDLE_S
    now = self.clock()
    if now < self.retry_at:
      return min(IDLE_S, self.retry_at - now)

    with self.lock:
      results, self.results = self.results, []
    body = json.dumps({"api": API_VERSION, "results": results}, separators=(",", ":")).encode()
    if self.state not in ("connected",):
      self._set("connecting", None)
    try:
      status, resp = self.transport("POST", s.server_url.rstrip("/") + "/link/poll",
                                    {"Authorization": f"Bearer {self.token()}", "Content-Type": "application/json"}, body)
    except (OSError, http.client.HTTPException, ValueError):
      status, resp = 0, b""
    self.usage.add_upload(len(body), cellular)
    if not 200 <= status < 300:
      with self.lock:
        self.results = results + self.results  # deliver with the next successful poll
      return self._fail()

    self.failures = 0
    with self.lock:
      self.last_ok, self.last_ok_iso = self.clock(), iso_now()
    self._set("connected", None)
    try:
      commands = json.loads(resp or b"{}").get("commands") or []
    except (ValueError, AttributeError):
      commands = []
    if not isinstance(commands, list):
      commands = []
    out = [run_command(c, self.local) for c in commands[:MAX_COMMANDS]]
    if out:
      day = iso_now()[:10]
      with self.lock:
        if self.commands_today["day"] != day:
          self.commands_today = {"day": day, "count": 0}
        self.commands_today["count"] += len(out)
        self.results.extend(out)
    return 0.0  # poll again at once: deliver results, or wait for the next command

  def _fail(self) -> float:
    self.failures += 1
    wait = BACKOFF_S[min(self.failures, len(BACKOFF_S)) - 1]
    self.retry_at = self.clock() + wait
    self._set("waiting", "server_error")
    return min(IDLE_S, wait)

  def run(self) -> None:
    while not self.stop_event.is_set():
      try:
        wait = self.step()
      except Exception:  # never let the link die; try again shortly
        wait = IDLE_S
      if wait > 0:
        self.stop_event.wait(wait)
