"""Off-device tests for the export bridge: store, segment index, live snapshot and HTTP API."""
import json
import os
import threading
import time
import urllib.error
import urllib.request
from types import SimpleNamespace

import pytest

from bluepilot.bridge.config import ALLOWED_FILES
from bluepilot.bridge.live import DriveTracker, build_snapshot
from bluepilot.bridge.notify import Notifier
from bluepilot.bridge import segments as seg_index
from bluepilot.bridge.server import BridgeContext, make_server
from bluepilot.bridge.store import EventLog, SyncedStore, load_synced

TOKEN = "test-token"


def make_segment(root, name, files=None, locked=False):
  d = os.path.join(root, name)
  os.makedirs(d, exist_ok=True)
  for fn, data in (files or {"rlog.zst": b"r" * 100, "qcamera.ts": b"q" * 50}).items():
    with open(os.path.join(d, fn), "wb") as f:
      f.write(data)
  if locked:
    open(os.path.join(d, "rlog.lock"), "w").close()
  return d


class FakeParams:
  def __init__(self):
    self.values = {"ShowBrakeStatus": False, "LC_PID_gain_UI_curv": 3.0, "IsOnroad": False}
    self.onroad = False

  def get(self, key):
    return self.values.get(key)

  def put(self, key, value):
    self.values[key] = value

  def is_onroad(self):
    return self.onroad


class FakeLive:
  def __init__(self):
    self.snap = {"onroad": False, "device": {}}
    self.thumb = None

  def latest(self):
    return self.snap

  def latest_thumbnail(self):
    return self.thumb


@pytest.fixture
def env(tmp_path):
  log_root = tmp_path / "realdata"
  state = tmp_path / "state"
  log_root.mkdir()
  events = EventLog(str(state))
  synced = SyncedStore(str(state))
  params = FakeParams()
  live = FakeLive()
  ctx = BridgeContext(token=lambda: TOKEN, events=events, synced=synced, log_root=str(log_root), live=live,
                      params=params, version="6.0.0-test", dongle_id="abc123")
  server = make_server(ctx, host="127.0.0.1", port=0)
  t = threading.Thread(target=server.serve_forever, daemon=True)
  t.start()
  base = f"http://127.0.0.1:{server.server_address[1]}"
  yield SimpleNamespace(base=base, root=str(log_root), state=str(state), events=events, synced=synced,
                        params=params, live=live, ctx=ctx)
  server.stopping = True
  server.shutdown()


def call(env, path, method="GET", body=None, token=TOKEN, headers=None):
  h = {"Authorization": f"Bearer {token}"} if token else {}
  h.update(headers or {})
  data = None
  if body is not None:
    data = json.dumps(body).encode()
    h["Content-Type"] = "application/json"
  req = urllib.request.Request(env.base + path, data=data, method=method, headers=h)
  try:
    with urllib.request.urlopen(req, timeout=5) as r:
      return r.status, dict(r.headers), r.read()
  except urllib.error.HTTPError as e:
    return e.code, dict(e.headers), e.read()


def jcall(env, *a, **kw):
  status, headers, body = call(env, *a, **kw)
  return status, json.loads(body) if body else None


# ---------------------------------------------------------------- store

def test_event_log_persists_seq(tmp_path):
  log = EventLog(str(tmp_path), max_events=3)
  for i in range(5):
    log.append("segment_closed", "r", i)
  assert [e["seq"] for e in log.since(0)] == [3, 4, 5]
  again = EventLog(str(tmp_path), max_events=3)
  assert again.next_seq == 6
  assert again.append("drive_finished", "r", 4)["seq"] == 6


def test_synced_store_never_downgrades(tmp_path):
  s = SyncedStore(str(tmp_path))
  assert s.mark(["a--0", "a--1"], "full") == 2
  assert s.mark(["a--0"], "logs") == 0
  assert load_synced(str(tmp_path)) == {"a--0": "full", "a--1": "full"}
  s.prune({"a--1"})
  assert load_synced(str(tmp_path)) == {"a--1": "full"}
  with pytest.raises(ValueError):
    s.mark(["a--2"], "everything")


def test_load_synced_tolerates_garbage(tmp_path):
  (tmp_path / "synced.json").write_text("{not json")
  assert load_synced(str(tmp_path)) == {}


# ---------------------------------------------------------------- segments

def test_scan_groups_routes(tmp_path):
  make_segment(tmp_path, "00000001--aaaa--0")
  make_segment(tmp_path, "00000001--aaaa--1", locked=True)
  make_segment(tmp_path, "00000002--bbbb--0", files={"rlog.zst": b"x", "secret.txt": b"no"})
  os.makedirs(tmp_path / "boot")
  segs = seg_index.scan(str(tmp_path), ALLOWED_FILES)
  assert [(s.route, s.n, s.locked) for s in segs] == [("00000001--aaaa", 0, False), ("00000001--aaaa", 1, True),
                                                       ("00000002--bbbb", 0, False)]
  assert [f["name"] for f in segs[2].files] == ["rlog.zst"]
  assert seg_index.split_segment_dir("2026-10-14--15-02-11--3") == ("2026-10-14--15-02-11", 3)
  assert seg_index.split_segment_dir("crash") is None


# ---------------------------------------------------------------- live

def gps(**kw):
  base = dict(latitude=49.28, longitude=-123.12, altitude=54.1, speed=12.3, bearingDeg=181.0, horizontalAccuracy=3.0,
              hasFix=True, unixTimestampMillis=1791990000000)
  base.update(kw)
  return SimpleNamespace(**base)


class View(dict):
  def __init__(self, data):
    super().__init__(data)
    self.seen = set(data)


def onroad_view():
  return View({
    "deviceState": SimpleNamespace(maxTempC=61.04, freeSpacePercent=22.5, memoryUsagePercent=48, networkType="wifi", started=True),
    "gpsLocationExternal": gps(),
    "carState": SimpleNamespace(vEgo=12.1, aEgo=0.2, gearShifter="drive", steeringAngleDeg=-3.5, brakePressed=False,
                                gasPressed=False, leftBlinker=False, rightBlinker=True, standstill=False,
                                cruiseState=SimpleNamespace(enabled=True, speed=27.8)),
    "carStateBP": SimpleNamespace(hybridBattery=SimpleNamespace(dataAvailable=True, socActual=81.5, voltActual=384.0, ampsActual=-31.5)),
    "selfdriveState": SimpleNamespace(enabled=True, experimentalMode=False),
    "carControl": SimpleNamespace(latActive=True),
  })


def test_snapshot_onroad():
  snap = build_snapshot(onroad_view(), "gpsLocationExternal", True, "00000001--aaaa", 3)
  assert snap["gps"]["lat"] == 49.28 and snap["gps"]["fix"] is True
  assert snap["gps"]["t"].startswith("2026-")
  assert snap["car"]["gear"] == "drive" and snap["car"]["rightBlinker"] is True
  assert snap["ev"] == {"available": True, "socPct": 81.5, "packV": 384.0, "packA": -31.5, "powerKw": -12.1}
  assert snap["engaged"] is True and snap["latActive"] is True
  assert snap["device"]["network"] == "wifi" and snap["device"]["cpuTempC"] == 61.0
  assert snap["route"] == "00000001--aaaa" and snap["segment"] == 3


def test_snapshot_offroad_hides_car_data():
  snap = build_snapshot(onroad_view(), "gpsLocationExternal", False, "x", 1)
  assert snap["onroad"] is False and snap["gps"] is None and snap["car"] is None and snap["route"] is None
  assert snap["device"]["freeSpacePct"] == 22.5


def test_snapshot_ev_unavailable_and_nan():
  v = onroad_view()
  v["carStateBP"] = SimpleNamespace(hybridBattery=SimpleNamespace(dataAvailable=False, socActual=0.0, voltActual=0.0, ampsActual=0.0))
  v["gpsLocationExternal"] = gps(altitude=float("nan"))
  snap = build_snapshot(v, "gpsLocationExternal", True, None, None)
  assert snap["ev"] == {"available": False, "socPct": None, "packV": None, "packA": None, "powerKw": None}
  assert snap["gps"]["alt"] is None


def test_snapshot_prefers_ev_battery():
  v = onroad_view()
  v["carStateBP"].evBattery = SimpleNamespace(dataAvailable=True, socPercent=64.2, packVoltage=380.0, packCurrent=52.0,
                                              powerKw=19.8, rangeKm=301.0, packTempC=24.5, coolantTempC=21.0)
  snap = build_snapshot(v, "gpsLocationExternal", True, None, None)
  assert snap["ev"] == {"available": True, "socPct": 64.2, "packV": 380.0, "packA": 52.0, "powerKw": 19.8,
                        "rangeKm": 301.0, "packTempC": 24.5, "coolantTempC": 21.0}


def test_drive_tracker_events(tmp_path):
  log = EventLog(str(tmp_path / "s"))
  tr = DriveTracker(log)
  root = tmp_path / "rd"
  make_segment(root, "00000009--cccc--0", locked=True)
  tr.update_segments(seg_index.scan(str(root), ALLOWED_FILES))
  tr.update_onroad(True)
  os.remove(root / "00000009--cccc--0" / "rlog.lock")
  make_segment(root, "00000009--cccc--1", locked=True)
  tr.update_segments(seg_index.scan(str(root), ALLOWED_FILES))
  tr.bookmark()
  tr.update_onroad(False)
  kinds = [(e["kind"], e["segment"]) for e in log.since(0)]
  assert kinds == [("drive_started", 0), ("segment_closed", 0), ("bookmark", 1), ("drive_finished", 1)]
  assert all(e["route"] == "00000009--cccc" for e in log.since(0))


# ---------------------------------------------------------------- HTTP API

def test_ping_without_token_and_auth_required(env):
  status, body = jcall(env, "/v1/ping", token=None)
  assert status == 200 and body == {"ok": True, "api": 1}
  assert jcall(env, "/v1/health", token=None)[0] == 401
  assert jcall(env, "/v1/health", token="wrong")[0] == 401


def test_health(env):
  make_segment(env.root, "00000001--aaaa--0")
  make_segment(env.root, "00000001--aaaa--1", locked=True)
  status, body = jcall(env, "/v1/health")
  assert status == 200 and body["dongleId"] == "abc123" and body["unsyncedSegments"] == 1 and body["onroad"] is False


def test_routes_and_synced_filter(env):
  make_segment(env.root, "00000001--aaaa--0")
  make_segment(env.root, "00000001--aaaa--1")
  make_segment(env.root, "00000002--bbbb--0")
  status, body = jcall(env, "/v1/synced", "POST", {"segments": ["00000001--aaaa--0", "00000001--aaaa--1"], "level": "full"})
  assert status == 200 and body == {"marked": 2}
  _, body = jcall(env, "/v1/routes?synced=false")
  assert [r["route"] for r in body["routes"]] == ["00000002--bbbb"]
  _, body = jcall(env, "/v1/routes?synced=true")
  assert [r["route"] for r in body["routes"]] == ["00000001--aaaa"]
  assert body["routes"][0]["segments"][0]["syncLevel"] == "full"
  assert jcall(env, "/v1/synced", "POST", {"segments": ["../etc"]})[0] == 400


def test_file_download_and_ranges(env):
  make_segment(env.root, "00000001--aaaa--0", files={"rlog.zst": bytes(range(256)) * 4})
  status, headers, body = call(env, "/v1/files/00000001--aaaa--0/rlog.zst")
  assert status == 200 and len(body) == 1024 and headers["Accept-Ranges"] == "bytes"
  status, headers, body = call(env, "/v1/files/00000001--aaaa--0/rlog.zst", headers={"Range": "bytes=1000-"})
  assert status == 206 and body == (bytes(range(256)) * 4)[1000:] and headers["Content-Range"] == "bytes 1000-1023/1024"
  status, _, body = call(env, "/v1/files/00000001--aaaa--0/rlog.zst", headers={"Range": "bytes=-4"})
  assert status == 206 and body == bytes([252, 253, 254, 255])
  assert call(env, "/v1/files/00000001--aaaa--0/rlog.zst", headers={"Range": "bytes=5000-"})[0] == 416
  assert call(env, "/v1/files/00000001--aaaa--0/secret.txt")[0] == 400
  assert call(env, "/v1/files/..%2F..%2Fetc/passwd")[0] == 400
  assert call(env, "/v1/files/00000001--aaaa--0/qcamera.ts")[0] == 404


def test_locked_segment_refused(env):
  make_segment(env.root, "00000001--aaaa--5", locked=True)
  assert call(env, "/v1/files/00000001--aaaa--5/rlog.zst")[0] == 409
  assert call(env, "/v1/files/00000001--aaaa--5/rlog.zst?allowLocked=1")[0] == 200


def test_events_paging(env):
  for i in range(3):
    env.events.append("segment_closed", "r", i)
  _, body = jcall(env, "/v1/events?since=2&limit=1")
  assert [e["seq"] for e in body["events"]] == [2] and body["next"] == 3
  _, body = jcall(env, "/v1/events?since=10")
  assert body["events"] == [] and body["next"] == 10


def test_params_read_write_interlock(env):
  _, body = jcall(env, "/v1/params?keys=ShowBrakeStatus,LC_PID_gain_UI_curv")
  assert body["params"] == {"ShowBrakeStatus": False, "LC_PID_gain_UI_curv": 3.0}
  assert jcall(env, "/v1/params?keys=GithubSshKeys")[0] == 400
  assert jcall(env, "/v1/params/AlphaLongitudinalEnabled", "PUT", {"value": True})[0] == 403
  status, body = jcall(env, "/v1/params/ShowBrakeStatus", "PUT", {"value": True})
  assert status == 200 and env.params.values["ShowBrakeStatus"] is True
  env.params.onroad = True
  status, body = jcall(env, "/v1/params/ShowBrakeStatus", "PUT", {"value": False})
  assert status == 409 and body["error"] == "onroad" and env.params.values["ShowBrakeStatus"] is True


def test_snapshot_route(env):
  assert call(env, "/v1/snapshot")[0] == 404
  env.live.thumb = b"\xff\xd8jpeg"
  status, headers, body = call(env, "/v1/snapshot?camera=road")
  assert status == 200 and headers["Content-Type"] == "image/jpeg" and body == b"\xff\xd8jpeg"


def test_live_stream_sse(env):
  env.live.snap = {"onroad": True, "device": {}}
  env.events.append("drive_finished", "r", 2)
  req = urllib.request.Request(env.base + "/v1/live/stream?hz=5&maxS=0.5", headers={"Authorization": f"Bearer {TOKEN}"})
  # since= starts at the current end, so only new events are streamed; append one after connecting
  def later():
    time.sleep(0.2)
    env.events.append("bookmark", "r", 3)
  threading.Thread(target=later).start()
  with urllib.request.urlopen(req, timeout=5) as r:
    text = r.read().decode()
  assert "event: live" in text and '"onroad":true' in text
  assert '"kind":"bookmark"' in text and '"kind":"drive_finished"' not in text


def test_notifier_posts_drive_finished(tmp_path):
  from http.server import BaseHTTPRequestHandler, HTTPServer
  got = []

  class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
      pass

    def do_POST(self):
      got.append((self.headers["Authorization"], json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
      self.send_response(204)
      self.end_headers()

  srv = HTTPServer(("127.0.0.1", 0), H)
  threading.Thread(target=srv.serve_forever, daemon=True).start()
  log = EventLog(str(tmp_path))
  n = Notifier(log, lambda: f"http://127.0.0.1:{srv.server_address[1]}/device/v1/notify", lambda: TOKEN)
  n.start()
  log.append("segment_closed", "r", 0)
  log.append("drive_finished", "r", 0)
  deadline = time.monotonic() + 5
  while not got and time.monotonic() < deadline:
    time.sleep(0.05)
  srv.shutdown()
  assert got and got[0][0] == f"Bearer {TOKEN}" and got[0][1]["event"]["kind"] == "drive_finished"
  assert len(got) == 1


# ---------------------------------------------------------------- settings (remote control)

def test_schema_matches_allowlist():
  from bluepilot.bridge.params_allowlist import WRITABLE
  from bluepilot.bridge.settings_schema import BY_KEY
  assert set(BY_KEY) <= WRITABLE
  assert WRITABLE - set(BY_KEY) == {"BPBridgeNotifyUrl", "BPServerUrl"}


def test_settings_get_and_batch_put(env):
  env.params.values.update({"LongitudinalPersonality": 1, "custom_path_offset_curv": 0.0, "FordPrefGaugeStyle": 0})
  status, body = jcall(env, "/v1/settings")
  assert status == 200 and body["editable"] is True
  driving = next(g for g in body["groups"] if g["id"] == "driving")
  personality = next(s for s in driving["settings"] if s["key"] == "LongitudinalPersonality")
  assert personality["value"] == 1 and personality["options"][2] == {"value": 2, "label": "Relaxed"}

  status, body = jcall(env, "/v1/settings", "PUT", {"values": {"LongitudinalPersonality": "2", "custom_path_offset_curv": 0.25,
                                                               "FordPrefGaugeStyle": "1", "ShowBrakeStatus": "true"}})
  assert status == 200
  assert env.params.values["LongitudinalPersonality"] == 2 and env.params.values["custom_path_offset_curv"] == 0.25
  assert env.params.values["FordPrefGaugeStyle"] == 1 and env.params.values["ShowBrakeStatus"] is True


def test_settings_put_validates_all_before_writing(env):
  env.params.values["custom_path_offset_curv"] = 0.0
  status, body = jcall(env, "/v1/settings", "PUT", {"values": {"ShowBrakeStatus": True, "custom_path_offset_curv": 0.9}})
  assert status == 400 and "between" in body["message"]
  assert env.params.values["ShowBrakeStatus"] is False  # nothing written
  assert jcall(env, "/v1/settings", "PUT", {"values": {"AlphaLongitudinalEnabled": True}})[0] == 403
  assert jcall(env, "/v1/params/SpeedLimitMode", "PUT", {"value": 7})[0] == 400


def test_settings_refused_onroad(env):
  env.params.onroad = True
  _, body = jcall(env, "/v1/settings")
  assert body["editable"] is False
  status, body = jcall(env, "/v1/settings", "PUT", {"values": {"ShowBrakeStatus": True}})
  assert status == 409 and body["error"] == "onroad"


def _ev(**kw):
  base = dict(dataAvailable=True, socPercent=55.0, packVoltage=390.0, packCurrent=-30.0, powerKw=-11.5, rangeKm=250.0,
              packTempC=22.0, coolantTempC=20.0)
  base.update(kw)
  return SimpleNamespace(**base)


def _charging(**kw):
  base = dict(charging=True, chargeType="dc", state="charging", powerKw=150.0, powerAvailable=True,
              timeToFullHours=0.5, timeToFullAvailable=True)
  base.update(kw)
  return SimpleNamespace(**base)


DS_PARKED = SimpleNamespace(maxTempC=40.0, freeSpacePercent=50.0, memoryUsagePercent=30, networkType="wifi")


def test_offroad_charging_reports_battery():
  v = View({"deviceState": DS_PARKED,
            "chargingStateBP": SimpleNamespace(evBattery=_ev(), charging=_charging(), sleepInSeconds=1200)})
  snap = build_snapshot(v, "gpsLocationExternal", False, None, None)
  assert snap["onroad"] is False and snap["car"] is None
  ev = snap["ev"]
  assert ev["socPct"] == 55.0 and ev["charging"] is True and ev["chargeMode"] == "dc"
  assert ev["chargePowerKw"] == 150.0 and ev["chargeState"] == "charging" and ev["timeToFullH"] == 0.5 and ev["sleepInS"] == 1200


def test_charging_power_gated_and_older_schema():
  v = View({"deviceState": DS_PARKED,
            "carStateBP": SimpleNamespace(evBattery=_ev(), charging=_charging(chargeType="none", powerAvailable=False))})
  ev = build_snapshot(v, "gpsLocationExternal", False, None, None)["ev"]
  assert ev["chargeMode"] is None and ev["chargePowerKw"] is None and "sleepInS" not in ev
  v = View({"deviceState": DS_PARKED, "carStateBP": SimpleNamespace(evBattery=_ev())})  # no charging struct yet
  ev = build_snapshot(v, "gpsLocationExternal", False, None, None)["ev"]
  assert ev["socPct"] == 55.0 and "charging" not in ev


def test_writable_keys_exist_on_this_build():
  """Custom: every remotely writable key is a real param on this build (7.0 renamed the lateral tuning keys)."""
  import re
  from openpilot.common.basedir import BASEDIR
  from bluepilot.bridge.params_allowlist import READABLE
  with open(os.path.join(BASEDIR, "common", "params_keys.h")) as f:
    keys = set(re.findall(r'\{"([A-Za-z0-9_]+)"', f.read()))
  assert sorted(READABLE - keys) == []
