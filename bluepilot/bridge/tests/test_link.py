"""Off-device tests for the remote link: the command allowlist, the long-poll loop and calls into the real API."""
import base64
import json

from bluepilot.bridge.link import LinkSettings, RemoteLink, allowed, local_caller, run_command
from bluepilot.bridge.usage import DataUsage
from bluepilot.bridge.tests.test_bridge import TOKEN, env  # noqa: F401  (pytest fixture)

ON = LinkSettings(enabled=True, server_url="https://citadel.example/device/v1")
WIFI = {"type": "wifi", "metered": False}


def b64json(obj) -> str:
  return base64.b64encode(json.dumps(obj).encode()).decode()


def body_of(result) -> dict:
  return json.loads(base64.b64decode(result["body"]))


class FakeServer:
  """Citadel's /link/poll: hands out queued command batches and records what the device posts."""

  def __init__(self, batches=(), status=200):
    self.batches, self.status, self.posts = list(batches), status, []

  def __call__(self, method, url, headers, body):
    assert method == "POST" and url == "https://citadel.example/device/v1/link/poll"
    assert headers["Authorization"] == "Bearer tok"
    self.posts.append(json.loads(body))
    if self.status != 200:
      return self.status, b""
    return 200, json.dumps({"commands": self.batches.pop(0) if self.batches else []}).encode()


def make_link(tmp_path, server, settings=ON, network=WIFI, local=None, clock=None):
  calls = []

  def fake_local(method, path, body):
    calls.append((method, path, body))
    return 200, "application/json", b'{"ok":true}'

  usage = DataUsage(str(tmp_path / "usage.json"))
  link = RemoteLink(lambda: settings, lambda: "tok", local or fake_local, lambda: network, usage,
                    transport=server, clock=clock or (lambda: 1000.0))
  return link, calls, usage


def test_allowlist():
  assert allowed("GET", "/v1/settings") and allowed("GET", "/v1/live") and allowed("GET", "/v1/routes?synced=false")
  assert allowed("PUT", "/v1/settings") and allowed("PUT", "/v1/params/BPRoadTripMode")
  assert not allowed("GET", "/v1/files/a--1/fcamera.hevc")   # downloads stay on the LAN
  assert not allowed("GET", "/v1/live/stream")               # no streams
  assert not allowed("GET", "/v1/ping") and not allowed("GET", "/v1/events")
  assert not allowed("POST", "/v1/synced")                   # only the home pull marks segments synced
  assert not allowed("DELETE", "/v1/settings") and not allowed("PUT", "/v1/params/../x")


def test_run_command_refuses_and_validates():
  def boom(*a):
    raise AssertionError("must not reach the API")
  r = run_command({"id": "1", "method": "GET", "path": "/v1/files/x--1/rlog"}, boom)
  assert r["status"] == 403 and body_of(r)["error"] == "not_allowed"
  r = run_command({"id": "2", "method": "PUT", "path": "/v1/settings", "body": "not base64!"}, boom)
  assert r["status"] == 400
  r = run_command({"method": "GET", "path": "/v1/live"}, boom)
  assert r["status"] == 400


def test_poll_runs_commands_and_delivers_results_next_poll(tmp_path):
  server = FakeServer([[{"id": "a", "method": "GET", "path": "/v1/settings"},
                        {"id": "b", "method": "PUT", "path": "/v1/settings", "body": b64json({"values": {"X": 1}})}]])
  link, calls, _ = make_link(tmp_path, server)
  assert link.step() == 0.0  # polls again at once
  assert calls == [("GET", "/v1/settings", None), ("PUT", "/v1/settings", b'{"values": {"X": 1}}')]
  assert server.posts[0]["results"] == []
  link.step()
  results = server.posts[1]["results"]
  assert [r["id"] for r in results] == ["a", "b"] and all(r["status"] == 200 for r in results)
  st = link.status()
  assert st["state"] == "connected" and st["connected"] and st["commandsToday"] == 2
  link.step()
  assert server.posts[2]["results"] == []  # each result goes once


def test_failed_poll_keeps_results_and_backs_off(tmp_path):
  now = [1000.0]
  server = FakeServer([[{"id": "a", "method": "GET", "path": "/v1/live"}]])
  link, _, _ = make_link(tmp_path, server, clock=lambda: now[0])
  link.step()
  server.status = 503
  assert link.step() == 5
  assert link.status()["state"] == "waiting" and link.status()["pausedReason"] == "server_error"
  assert link.step() > 0 and len(server.posts) == 2  # still backing off: no request
  now[0] += 6
  server.status = 200
  link.step()
  assert [r["id"] for r in server.posts[2]["results"]] == ["a"]


def test_gating(tmp_path):
  server = FakeServer()
  link, _, _ = make_link(tmp_path, server, settings=LinkSettings(enabled=False, server_url="x"))
  link.step()
  assert link.status()["state"] == "off" and not server.posts
  link, _, _ = make_link(tmp_path, server, settings=LinkSettings(enabled=True, server_url=""))
  link.step()
  assert link.status()["pausedReason"] == "no_server"
  link, _, _ = make_link(tmp_path, server, network={"type": "none"})
  link.step()
  assert link.status()["pausedReason"] == "no_network"
  over = LinkSettings(enabled=True, server_url=ON.server_url, limit_bytes=10, limit_action=1)
  link, _, usage = make_link(tmp_path, server, settings=over, network={"type": "cell", "metered": True})
  usage.observe_modem(0, 0)
  usage.observe_modem(100, 0)  # 100 bytes of LTE this month
  link.step()
  assert link.status()["pausedReason"] == "over_limit" and not server.posts
  # Telemetry-only limit action: the link keeps going (it is a few KB a minute)
  link, _, usage = make_link(tmp_path, server, settings=LinkSettings(True, ON.server_url, 10, 0),
                             network={"type": "cell", "metered": True})
  usage.observe_modem(0, 0)
  usage.observe_modem(100, 0)
  link.step()
  assert link.status()["state"] == "connected"


def test_commands_go_through_the_real_api(env, tmp_path):  # noqa: F811
  port = int(env.base.rsplit(":", 1)[1])
  local = local_caller(port, lambda: TOKEN)
  r = run_command({"id": "1", "method": "GET", "path": "/v1/settings"}, local)
  assert r["status"] == 200 and "groups" in body_of(r)
  env.params.onroad = True  # settings stay parked-only over the link too
  r = run_command({"id": "2", "method": "PUT", "path": "/v1/settings",
                   "body": b64json({"values": {"BPRoadTripMode": True}})}, local)
  assert r["status"] == 409 and body_of(r)["error"] == "onroad"
  bad = local_caller(port, lambda: "wrong")
  assert run_command({"id": "3", "method": "GET", "path": "/v1/live"}, bad)["status"] == 401
