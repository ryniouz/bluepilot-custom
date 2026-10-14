"""Off-device tests for Road Trip Mode: data usage, upload planning, the uploader loop and status."""
import datetime as dt
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from bluepilot.bridge.config import ALLOWED_FILES
from bluepilot.bridge import segments as seg_index
from bluepilot.bridge.roadtrip import RoadTripSettings, RoadTripUploader, UploadedStore, http_transport, plan_uploads
from bluepilot.bridge import comma_connect
from bluepilot.bridge.status import StatusWriter, cellular_view, connectivity, network_view, storage_breakdown
from bluepilot.bridge.store import SyncedStore
from bluepilot.bridge.usage import DataUsage, month_start


def make_segment(root, name, files, locked=False, mtime=None):
  d = os.path.join(root, name)
  os.makedirs(d, exist_ok=True)
  for fn, data in files.items():
    with open(os.path.join(d, fn), "wb") as f:
      f.write(data)
  if locked:
    open(os.path.join(d, "rlog.lock"), "w").close()
  if mtime is not None:
    os.utime(d, (mtime, mtime))


SEG_FILES = {"rlog.zst": b"r" * 100, "qlog.zst": b"l" * 30, "qcamera.ts": b"q" * 50, "fcamera.hevc": b"f" * 400}


# ---- usage

def test_month_start_clamps_and_wraps():
  assert month_start(dt.date(2026, 10, 14), 1) == dt.date(2026, 10, 1)
  assert month_start(dt.date(2026, 10, 14), 20) == dt.date(2026, 9, 20)
  assert month_start(dt.date(2026, 2, 28), 31) == dt.date(2026, 2, 28)
  assert month_start(dt.date(2026, 1, 5), 10) == dt.date(2025, 12, 10)


def test_usage_accumulates_deltas_and_counter_resets(tmp_path):
  day = [dt.date(2026, 10, 14)]
  u = DataUsage(str(tmp_path / "usage.json"), today=lambda: day[0])
  u.observe_modem(1000, 2000)  # first sample: baseline only
  assert u.summary()["cell"]["monthBytes"] == 0
  u.observe_modem(1500, 2500)
  assert u.summary()["cell"]["todayBytes"] == 1000
  u.observe_modem(100, 50)  # modem restarted: counts from zero
  assert u.summary()["cell"]["monthBytes"] == 1150
  day[0] = dt.date(2026, 10, 15)
  s = u.summary(limit_bytes=1000)
  assert s["cell"]["todayBytes"] == 0 and s["cell"]["monthBytes"] == 1150
  assert s["overLimit"] is True and s["remainingBytes"] == 0
  day[0] = dt.date(2026, 11, 1)
  assert u.summary()["cell"]["monthBytes"] == 0 and u.summary()["cell"]["totalBytes"] == 1150


def test_usage_persists(tmp_path):
  path = str(tmp_path / "usage.json")
  u = DataUsage(path, today=lambda: dt.date(2026, 10, 14))
  u.observe_modem(0, 0)
  u.observe_modem(600_000, 600_000)  # > 1 MB: saved
  u.add_upload(5000, cellular=True)
  u.save()
  u2 = DataUsage(path, today=lambda: dt.date(2026, 10, 14))
  s = u2.summary()
  assert s["cell"]["monthBytes"] == 1_200_000 and s["uploader"]["cellBytesMonth"] == 5000
  assert s["remainingBytes"] is None and s["overLimit"] is False


# ---- planning

def test_plan_logs_first_newest_drive_first(tmp_path):
  root = str(tmp_path)
  make_segment(root, "00000001--aaaaaaaaaa--0", SEG_FILES, mtime=1000)
  make_segment(root, "00000001--aaaaaaaaaa--1", SEG_FILES, mtime=1060)
  make_segment(root, "00000002--bbbbbbbbbb--0", SEG_FILES, mtime=5000)
  make_segment(root, "00000002--bbbbbbbbbb--1", SEG_FILES, locked=True, mtime=5060)
  make_segment(root, "00000003--cccccccccc--0", SEG_FILES, mtime=900)
  synced = SyncedStore(str(tmp_path / "state"))
  synced.mark(["00000003--cccccccccc--0"], "logs")  # already home
  uploaded = UploadedStore(str(tmp_path / "state"))
  plan = plan_uploads(seg_index.scan(root, ALLOWED_FILES), uploaded, synced, video=True)
  assert [(p[0][:8], p[0][-1], p[1]) for p in plan] == [
    ("00000002", "0", "qlog.zst"), ("00000001", "0", "qlog.zst"), ("00000001", "1", "qlog.zst"),
    ("00000002", "0", "qcamera.ts"), ("00000001", "0", "qcamera.ts"), ("00000001", "1", "qcamera.ts"),
  ]
  uploaded.mark("00000002--bbbbbbbbbb--0", "qlog.zst", 30)
  plan = plan_uploads(seg_index.scan(root, ALLOWED_FILES), uploaded, synced, video=False)
  assert [p[1] for p in plan] == ["qlog.zst", "qlog.zst"]


# ---- uploader with a fake transport

class FakeTransport:
  def __init__(self, status=200):
    self.status = status
    self.calls: list[tuple[str, str, dict, bytes]] = []

  def __call__(self, method, url, headers, body):
    data = body if isinstance(body, (bytes, type(None))) else b"".join(body)
    self.calls.append((method, url, headers, data))
    return self.status


@pytest.fixture
def rt(tmp_path):
  root = str(tmp_path / "realdata")
  os.makedirs(root)
  make_segment(root, "00000001--aaaaaaaaaa--0", SEG_FILES)
  state = str(tmp_path / "state")
  settings = RoadTripSettings(enabled=True, video=True, server_url="https://citadel.example/device/v1")
  net = {"type": "cell", "metered": True, "strength": "good"}
  live = {"onroad": False}
  usage = DataUsage(os.path.join(state, "usage.json"), today=lambda: dt.date(2026, 10, 14))
  transport = FakeTransport()
  clock = [100.0]
  up = RoadTripUploader(lambda: settings, lambda: "tok", root, ALLOWED_FILES, SyncedStore(state), UploadedStore(state),
                        usage, lambda: net, lambda: live, transport=transport, clock=lambda: clock[0])
  return type("RT", (), dict(root=root, settings=settings, net=net, live=live, usage=usage, transport=transport,
                             clock=clock, up=up, state=state))


def test_uploads_qlog_then_qcamera_then_pings(rt):
  assert rt.up.step() == 0.0
  m, url, headers, body = rt.transport.calls[-1]
  assert m == "PUT" and url.endswith("/upload/00000001--aaaaaaaaaa--0/qlog.zst") and body == b"l" * 30
  assert headers["Authorization"] == "Bearer tok" and headers["Content-Length"] == "30"
  rt.up.step()
  assert rt.transport.calls[-1][1].endswith("/qcamera.ts")
  rt.up.step()
  assert rt.transport.calls[-1][0] == "GET" and rt.transport.calls[-1][1].endswith("/ping")
  st = rt.up.status()
  assert st["roadTrip"]["state"] == "idle" and st["roadTrip"]["uploadedToday"] == {"files": 2, "bytes": 80}
  assert st["server"]["reachable"] is True and st["roadTrip"]["lastUpload"]["file"] == "qcamera.ts"
  assert rt.usage.summary()["uploader"]["cellBytesMonth"] == 80
  # survives a restart: nothing left to send
  again = UploadedStore(rt.state)
  assert again.has("00000001--aaaaaaaaaa--0", "qcamera.ts", 50)


def test_live_push_only_while_driving(rt):
  rt.live["onroad"] = True
  rt.up.step()
  assert rt.transport.calls[0][0] == "POST" and rt.transport.calls[0][1].endswith("/live")
  assert json.loads(rt.transport.calls[0][3]) == {"onroad": True}
  n = len(rt.transport.calls)
  rt.up.step()  # within 10 s: no second live push
  assert sum(1 for c in rt.transport.calls[n:] if c[1].endswith("/live")) == 0


def test_pauses_and_limits(rt):
  rt.settings.server_url = ""
  rt.up.step()
  assert rt.up.status()["roadTrip"]["pausedReason"] == "no_server" and not rt.transport.calls
  rt.settings.server_url = "https://citadel.example/device/v1"
  rt.net["type"] = "none"
  rt.up.step()
  assert rt.up.status()["roadTrip"]["pausedReason"] == "no_network"
  rt.net["type"] = "cell"
  rt.settings.limit_bytes = 1
  rt.usage.observe_modem(0, 0)
  rt.usage.observe_modem(10, 10)
  rt.settings.limit_action = 1
  rt.up.step()
  assert rt.up.status()["roadTrip"]["pausedReason"] == "over_limit" and not rt.transport.calls
  rt.settings.limit_action = 0  # telemetry only: qlog yes, video no
  rt.up.step()
  rt.up.step()
  assert [c[1].rsplit("/", 1)[1] for c in rt.transport.calls] == ["qlog.zst", "ping"]
  # on unmetered Wi-Fi the cellular limit doesn't apply
  rt.net.update(type="wifi", metered=False)
  rt.up.step()
  assert rt.transport.calls[-1][1].endswith("/qcamera.ts")


def test_backoff_on_server_error(rt):
  rt.transport.status = 503
  rt.up.step()
  st = rt.up.status()["roadTrip"]
  assert st["state"] == "waiting" and st["pausedReason"] == "server_error"
  n = len(rt.transport.calls)
  rt.up.step()
  assert len(rt.transport.calls) == n  # still backing off
  rt.clock[0] += 6
  rt.transport.status = 200
  rt.up.step()
  assert len(rt.transport.calls) == n + 1 and rt.up.status()["roadTrip"]["state"] == "uploading"


def test_disabled_does_nothing(rt):
  rt.settings.enabled = False
  rt.up.step()
  assert rt.up.status()["roadTrip"]["state"] == "off" and not rt.transport.calls


# ---- real HTTP round trip

def test_http_transport_streams_body():
  got = {}

  class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
      pass

    def do_PUT(self):
      n = int(self.headers["Content-Length"])
      got["body"], got["auth"] = self.rfile.read(n), self.headers["Authorization"]
      self.send_response(201)
      self.send_header("Content-Length", "0")
      self.end_headers()

  srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
  threading.Thread(target=srv.serve_forever, daemon=True).start()
  try:
    status = http_transport("PUT", f"http://127.0.0.1:{srv.server_address[1]}/upload/x/qlog.zst",
                            {"Authorization": "Bearer t", "Content-Length": "6"}, iter([b"abc", b"def"]))
    assert status == 201 and got == {"body": b"abcdef", "auth": "Bearer t"}
  finally:
    srv.shutdown()


# ---- status

def test_storage_breakdown_and_status_file(tmp_path):
  root = str(tmp_path / "realdata")
  make_segment(root, "00000001--aaaaaaaaaa--0", SEG_FILES)
  make_segment(root, "00000001--aaaaaaaaaa--1", SEG_FILES)
  synced = SyncedStore(str(tmp_path / "state"))
  synced.mark(["00000001--aaaaaaaaaa--0"], "logs")
  st = storage_breakdown(seg_index.scan(root, ALLOWED_FILES), synced, total=10_000, free=4_000)
  assert st["categories"] == {"video": 800, "videoLowRes": 100, "logs": 260, "unsynced": 580, "system": 4840}
  assert network_view({"type": "cell4G", "metered": True, "strength": "great"}) == \
    {"type": "cell", "metered": True, "strength": "great"}
  assert network_view(None) == {"type": "none", "metered": False, "strength": "unknown"}


  path = str(tmp_path / "status.json")
  rts = {"server": {"configured": False}, "roadTrip": {"enabled": False, "video": True, "cellular": False, "state": "off",
         "pausedReason": "disabled", "queue": {"files": 0, "bytes": 0}, "current": None, "lastUpload": None,
         "uploadedToday": {"files": 0, "bytes": 0}}}
  comma = comma_connect.status(True, 0, 10, {"type": "wifi"}, True, (0, 0))
  cell = cellular_view({"technology": "LTE", "operator": "Telus", "band": "B4", "channel": 2000, "state": "connected"},
                       "good", {"sim_state": ["READY"], "mcc_mnc": "302220", "data_connected": True}, "EG25", False, "", True)
  path = str(tmp_path / "status.json")
  w = StatusWriter(path, lambda: connectivity(network_view(None), rts, {"cell": {}}, comma, True, 1, None, cell),
                   lambda: st)
  w.write_once(refresh_storage=True)
  with open(path) as f:
    doc = json.load(f)
  assert doc["storage"]["freeBytes"] == 4000 and doc["homeSync"]["unsyncedSegments"] == 1 and doc["commaConnect"] is True
  assert doc["services"]["citadel"]["cellular"] is False and doc["services"]["commaConnect"]["connected"] is True
  assert doc["cellular"]["operator"] == "Telus" and doc["cellular"]["sim"] == \
    {"present": True, "state": "ready", "mccMnc": "302220", "dataConnected": True}
  assert doc["cellular"]["settings"] == {"roaming": False, "apn": None, "metered": True}


def test_comma_connect_status(tmp_path):
  root = str(tmp_path)
  make_segment(root, "00000001--aaaaaaaaaa--0", SEG_FILES)
  make_segment(root, "00000001--aaaaaaaaaa--1", SEG_FILES, locked=True)
  segs = seg_index.scan(root, ALLOWED_FILES)
  assert comma_connect.pending(root, segs) == (2, 80)  # qlog + qcamera of the closed segment only
  try:
    os.setxattr(os.path.join(root, "00000001--aaaaaaaaaa--0", "qlog.zst"), "user.upload", b"1")
    assert comma_connect.pending(root, segs) == (1, 50)
  except OSError:
    pass  # filesystem without user xattrs
  wifi, cell = {"type": "wifi", "metered": False}, {"type": "cell", "metered": True}
  st = comma_connect.status(True, 100, 100 + 10**9, wifi, True, (2, 80))
  assert st["connected"] is True and st["state"] == "uploading"
  st = comma_connect.status(True, None, 0, cell, True, (2, 80))
  assert st["connected"] is False and (st["state"], st["pausedReason"]) == ("waiting", "wifi_only")
  assert comma_connect.status(True, None, 0, cell, False, (2, 80))["state"] == "uploading"
  assert comma_connect.status(False, None, 0, wifi, True, (0, 0))["pausedReason"] == "not_registered"
  assert comma_connect.status(True, 0, 200 * 10**9, wifi, True, (0, 0))["connected"] is False


def test_citadel_wifi_only(rt):
  rt.settings.cellular = False
  rt.up.step()
  assert rt.up.status()["roadTrip"]["pausedReason"] == "wifi_only" and not rt.transport.calls
  rt.net.update(type="wifi", metered=False)
  rt.up.step()
  assert rt.transport.calls[-1][1].endswith("/qlog.zst")


def test_categories_from_the_uploader(rt):
  rt.net.update(type="cell", metered=True)
  rt.live["onroad"] = True
  rt.up.step()   # live push, then the qlog
  rt.up.step()
  cats = rt.usage.state["categories"]
  assert cats["citadel"] == 30 + 50
  assert cats["live"] == len(b'{"onroad":true}')
