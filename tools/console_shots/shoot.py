#!/usr/bin/env python3
"""
Headless screenshot harness for the BluePilot / sunnypilot raylib UI (TICI "BIG" layout).

Each scene runs in its own fresh Python process (so UI modules are imported fresh every run
and no state leaks between scenes), inside its own OpenpilotPrefix (private params dir +
msgq namespace). Fake cereal messages are published with PubMaster every frame, and a
synthetic road image is streamed over VisionIPC as the road camera.

Usage (see README.md next to this file):
  python tools/console_shots/shoot.py --out /tmp/shots                 # all scenes
  python tools/console_shots/shoot.py --out /tmp/shots --scenes home,onroad_engaged
  python tools/console_shots/shoot.py --list
  python tools/console_shots/shoot.py --repo /path/to/other/checkout --out ...   # render another tree

If $DISPLAY is not set, the harness re-executes itself under `xvfb-run -a`.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_REPO = HERE.parents[1]

# Width/height of the TICI UI and the road camera (ar0231 on tici/tizi)
UI_W, UI_H = 2160, 1080
CAM_W, CAM_H = 1928, 1208
CAM_F = 2648.0
CAM_HEIGHT = 1.22  # metres, camera above ground

MPH = 0.44704
KPH = 1 / 3.6

# ----------------------------------------------------------------------------------------------
# Scene list. Each entry: name -> (description, shots it produces)
# Scenes producing several images list them; everything else produces <name>.png
# ----------------------------------------------------------------------------------------------
SCENES: dict[str, str] = {
  "home": "Offroad home screen (sidebar + home layout)",
  "home_alerts": "Offroad home with offroad alerts + update available",
  "settings": "Settings open on the Device panel",
  "settings_panels": "Every settings panel, one PNG each (settings_<panel>.png), incl. BluePilot",
  "sidebar": "Onroad engaged with the sidebar opened",
  "onroad_engaged": "Onroad, engaged, lead car, 65 mph, set speed 70",
  "onroad_disengaged": "Onroad, cruise available but disengaged",
  "onroad_override": "Onroad, driver overriding (gas/steer)",
  "onroad_experimental": "Onroad, engaged in experimental mode",
  "alert_small": "Small (normal) alert",
  "alert_mid": "Mid (userPrompt) alert",
  "alert_full_prompt": "Full-screen userPrompt alert",
  "alert_full_critical": "Full-screen critical alert",
  "onroad_ev": "Onroad with carStateBP.hybridBattery (EV battery gauge)",
  "onroad_ev_powerflow": "Onroad with battery + power flow gauges (flat style)",
  "onroad_all": "Onroad with as many optional elements enabled as possible",
  "onroad_debug_panel": "Onroad with the BluePilot controls debug panel open",
  "charging_dc": "Charging screen, DC fast charge (charge fields injected; CarStateBP.ev not on this branch yet)",
  "charging_ac": "Charging screen, AC charge limited by a cold battery",
}
ALIASES = {
  "alert_full": ["alert_full_prompt", "alert_full_critical"],
  "alerts": ["alert_small", "alert_mid", "alert_full_prompt", "alert_full_critical"],
  "onroad": ["onroad_engaged", "onroad_disengaged", "onroad_override", "onroad_experimental"],
  "charging": ["charging_dc", "charging_ac"],
}

SCONS_TARGETS = [
  "common/params_pyx.so",
  "msgq_repo/msgq/ipc_pyx.so",
  "msgq_repo/msgq/visionipc/visionipc_pyx.so",
  "cereal",
  "selfdrive/assets/fonts",
]


# ==============================================================================================
# Parent process
# ==============================================================================================

def resolve_scenes(spec: str | None) -> list[str]:
  if not spec or spec == "all":
    return list(SCENES)
  out: list[str] = []
  for s in (x.strip() for x in spec.split(",")):
    if not s:
      continue
    names = ALIASES.get(s, [s])
    for n in names:
      if n not in SCENES:
        raise SystemExit(f"unknown scene '{n}'. Known: {', '.join(SCENES)}; aliases: {', '.join(ALIASES)}")
      if n not in out:
        out.append(n)
  return out


def worker_env(repo: Path) -> dict[str, str]:
  env = dict(os.environ)
  env["PYTHONPATH"] = str(repo) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
  env["BIG"] = "1"
  env["SCALE"] = "1.0"
  env["OFFSCREEN"] = "1"
  env.setdefault("SUNNYPILOT_UI", "1")
  env.pop("RECORD", None)
  return env


def run_build(repo: Path) -> None:
  cmd = ["scons", f"-j{os.cpu_count() or 4}", *SCONS_TARGETS]
  print(f"[build] {' '.join(cmd)}  (cwd={repo})", flush=True)
  scons = shutil.which("scons", path=str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""))
  if scons:
    cmd[0] = scons
  subprocess.run(cmd, cwd=repo, check=True, env={**os.environ, "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", "")})


def run_parent(args) -> int:
  repo = Path(args.repo).resolve()
  if args.list:
    for k, v in SCENES.items():
      print(f"{k:22s} {v}")
    print("\naliases: " + ", ".join(f"{k}={'+'.join(v)}" for k, v in ALIASES.items()))
    return 0

  if not os.environ.get("DISPLAY") and not args.no_xvfb:
    xvfb = shutil.which("xvfb-run")
    if not xvfb:
      raise SystemExit("No $DISPLAY and xvfb-run not found; install xvfb or pass --no-xvfb with a display")
    cmd = [xvfb, "-a", "-s", f"-screen 0 {UI_W + 64}x{UI_H + 64}x24", sys.executable, str(Path(__file__).resolve()), *sys.argv[1:]]
    return subprocess.call(cmd)

  if args.build:
    run_build(repo)

  scenes = resolve_scenes(args.scenes)
  out = Path(args.out).resolve()
  out.mkdir(parents=True, exist_ok=True)
  logs = out / "logs"
  logs.mkdir(exist_ok=True)

  def one(scene: str):
    t0 = time.monotonic()
    log = logs / f"{scene}.log"
    cmd = [sys.executable, str(Path(__file__).resolve()), "--_worker", scene, "--out", str(out), "--frames", str(args.frames)]
    with open(log, "w") as f:
      try:
        env = worker_env(repo)
        env["CONSOLE_SHOTS_THEME"] = args.theme
        rc = subprocess.call(cmd, cwd=repo, env=env, stdout=f, stderr=subprocess.STDOUT, timeout=args.timeout)
      except subprocess.TimeoutExpired:
        rc = -999
    return scene, rc, time.monotonic() - t0, log

  print(f"Rendering {len(scenes)} scene(s) from {repo} -> {out}", flush=True)
  failed = []
  with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.jobs)) as ex:
    for scene, rc, dt, log in ex.map(one, scenes):
      status = "ok" if rc == 0 else ("TIMEOUT" if rc == -999 else f"FAILED rc={rc}")
      print(f"  {scene:22s} {status:12s} {dt:5.1f}s", flush=True)
      if rc != 0:
        failed.append(scene)
        tail = log.read_text(errors="replace").splitlines()[-25:]
        print("    " + "\n    ".join(tail), flush=True)
  pngs = sorted(p.name for p in out.glob("*.png"))
  print(f"{len(pngs)} PNG(s) in {out}")
  if failed:
    print(f"FAILED scenes: {', '.join(failed)} (logs in {logs})")
    return 1
  return 0


# ==============================================================================================
# Worker process (one scene)
# ==============================================================================================

def synth_road_rgb(lead_d: float | None = None, ss: int = 2):
  """Render a simple road scene as seen by the road camera (pinhole, zero calibration)."""
  import numpy as np

  W, H = CAM_W * ss, CAM_H * ss
  f = CAM_F * ss
  cx, cy = W / 2, H / 2
  v = (np.arange(H, dtype=np.float32) + 0.5)[:, None]
  u = (np.arange(W, dtype=np.float32) + 0.5)[None, :]

  img = np.zeros((H, W, 3), dtype=np.float32)

  # Sky: gradient
  t = np.clip((cy - v) / cy, 0, 1)[..., None]
  sky = (1 - t) * np.array([196, 204, 212], np.float32) + t * np.array([92, 128, 176], np.float32)
  img[:] = sky

  # Distant tree line just above the horizon
  tree_h = (8 + 6 * np.sin(u / (37.0 * ss)) + 4 * np.sin(u / (11.0 * ss))) * ss
  trees = (v < cy) & (v > cy - tree_h)
  img[np.broadcast_to(trees, (H, W))] = np.array([58, 74, 60], np.float32)

  ground = np.broadcast_to(v > cy + 0.5, (H, W))
  vv = np.maximum(v - cy, 1e-3)
  Z = np.broadcast_to(f * CAM_HEIGHT / vv, (H, W))
  X = (u - cx) * Z / f

  col = np.zeros((H, W, 3), np.float32)
  grass = np.array([78, 96, 56], np.float32)
  asphalt = np.array([66, 68, 72], np.float32)
  shoulder = np.array([92, 92, 90], np.float32)
  col[:] = grass
  road = np.abs(X) < 6.4
  col[(np.abs(X) < 7.2) & ~road] = shoulder
  col[road] = asphalt
  # subtle asphalt texture by distance bands
  band = (np.floor(Z / 4.0) % 2 == 0) & road
  col[band] = asphalt * 0.97

  def mark(xc, width, color, dashed=False):
    m = np.abs(X - xc) < width / 2
    if dashed:
      m &= (Z % 12.0) < 3.0
    col[m] = color

  white = np.array([232, 232, 228], np.float32)
  yellow = np.array([226, 184, 64], np.float32)
  mark(-5.55, 0.15, yellow)
  mark(-1.85, 0.12, white, dashed=True)
  mark(1.85, 0.12, white, dashed=True)
  mark(5.55, 0.15, white)

  # Atmospheric haze
  haze = 1 - np.exp(-Z / 260.0)
  haze_col = np.array([180, 188, 196], np.float32)
  col = col * (1 - haze[..., None]) + haze_col * haze[..., None]
  img[ground] = col[ground]

  if lead_d is not None and lead_d > 3:
    Zl = lead_d + 1.0
    def px(xm, ym):
      return cx + f * xm / Zl, cy + f * ym / Zl
    x0, yb = px(-0.98, CAM_HEIGHT)
    x1, yt = px(0.98, CAM_HEIGHT - 1.65)
    x0, x1, yt, yb = int(x0), int(x1), int(yt), int(yb)
    img[yt:yb, x0:x1] = np.array([34, 38, 46], np.float32)
    # rear window
    wx0, wy0 = px(-0.75, CAM_HEIGHT - 1.55)
    wx1, wy1 = px(0.75, CAM_HEIGHT - 1.15)
    img[int(wy0):int(wy1), int(wx0):int(wx1)] = np.array([18, 20, 26], np.float32)
    # taillights
    for sx in (-0.9, 0.62):
      tx0, ty0 = px(sx, CAM_HEIGHT - 1.0)
      tx1, ty1 = px(sx + 0.28, CAM_HEIGHT - 0.85)
      img[int(ty0):int(ty1), int(tx0):int(tx1)] = np.array([200, 30, 30], np.float32)
    # shadow under car
    sx0, sy0 = px(-1.1, CAM_HEIGHT)
    sx1, _ = px(1.1, CAM_HEIGHT)
    img[int(sy0):int(sy0) + max(2, int(0.1 * f / Zl)), int(sx0):int(sx1)] = np.array([20, 20, 22], np.float32)

  img = img.reshape(CAM_H, ss, CAM_W, ss, 3).mean(axis=(1, 3))
  return np.clip(img, 0, 255).astype(np.uint8)


def rgb_to_nv12(rgb) -> bytes:
  import numpy as np
  h, w = rgb.shape[:2]
  r = rgb[:, :, 0].astype(np.int32)
  g = rgb[:, :, 1].astype(np.int32)
  b = rgb[:, :, 2].astype(np.int32)
  y = np.clip((((b * 13 + g * 65 + r * 33) + 64) >> 7) + 16, 0, 255).astype(np.uint8)
  r_sub = (r[0::2, 0::2] + r[0::2, 1::2] + r[1::2, 0::2] + r[1::2, 1::2] + 2) >> 2
  g_sub = (g[0::2, 0::2] + g[0::2, 1::2] + g[1::2, 0::2] + g[1::2, 1::2] + 2) >> 2
  b_sub = (b[0::2, 0::2] + b[0::2, 1::2] + b[1::2, 0::2] + b[1::2, 1::2] + 2) >> 2
  uu = np.clip((b_sub * 56 - g_sub * 37 - r_sub * 19 + 0x8080) >> 8, 0, 255).astype(np.uint8)
  vv = np.clip((r_sub * 56 - g_sub * 47 - b_sub * 9 + 0x8080) >> 8, 0, 255).astype(np.uint8)
  uv = np.empty((h // 2, w), dtype=np.uint8)
  uv[:, 0::2] = uu
  uv[:, 1::2] = vv
  return np.concatenate([y.ravel(), uv.ravel()]).tobytes()


def default_drive() -> dict:
  return dict(
    started=True,
    enabled=True,
    state="enabled",
    v_ego=65 * MPH,
    v_cruise_kph=70 * MPH / KPH,
    a_ego=0.1,
    lead=True,
    lead_d=38.0,
    lead_v_rel=-0.8,
    alert=None,  # (size, status, text1, text2)
    left_blinker=False,
    right_blinker=False,
    left_blindspot=False,
    right_blindspot=False,
    steering_pressed=False,
    gas_pressed=False,
    override_long=False,
    experimental=False,
    battery=None,  # dict(soc=, volts=, amps=)
    drive=None,  # dict(throttle=, threshold=, mode=, mode_value=, reason=, reason_value=)
    brake_lights=False,
    road_name="",
    speed_limit_mph=None,
    steer_torque=0.25,
    curvature=0.0,
  )


class Scene:
  """Imperative helper wrapping the gui_app render generator."""

  def __init__(self, name: str, out: Path, frames: int):
    self.name = name
    self.out = out
    self.frames = frames
    self.drive: dict | None = None  # None -> offroad
    self.frame = 0
    self._capture_path: str | None = None
    self._captured: list[str] = []

  # --- set up -------------------------------------------------------------------------------
  def boot(self, params: dict):
    import pyray as rl
    self.rl = rl
    rl.set_config_flags(rl.ConfigFlags.FLAG_WINDOW_HIDDEN)

    from openpilot.common.params import Params
    self.params = Params()
    self._setup_base_params()
    for k, v in params.items():
      self.put(k, v)

    from cereal import messaging, log, car, custom
    self.messaging, self.log, self.car, self.custom = messaging, log, car, custom

    # Import UI fresh (this is a fresh process)
    from openpilot.selfdrive.ui.ui_state import ui_state
    from openpilot.system.ui.lib.application import gui_app
    self.ui_state, self.gui_app = ui_state, gui_app

    fps = 60
    gui_app.init_window("console shots", fps=fps)
    # Deterministic animation timing (same trick as selfdrive/ui/tests/diff/replay.py)
    rl.get_frame_time = lambda: 1.0 / fps
    rl.get_time = lambda: self.frame / fps

    if getattr(gui_app, "_render_texture", None) is None:
      gui_app._render_texture = rl.load_render_texture(gui_app.width, gui_app.height)
      rl.set_texture_filter(gui_app._render_texture.texture, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)

    orig_end_drawing = rl.end_drawing

    def end_drawing_capture():
      orig_end_drawing()
      if self._capture_path is not None:
        self._save_render_texture(self._capture_path)
        self._capture_path = None
    rl.end_drawing = end_drawing_capture

    from openpilot.selfdrive.ui.layouts import main as main_mod
    self.main_mod = main_mod
    self.main = main_mod.MainLayout()

    # Keep the device "awake" and stop the interactive timeout from closing settings / sidebar
    # (rendering on llvmpipe is slow, so wall-clock timeouts would otherwise fire mid-scene).
    try:
      from openpilot.selfdrive.ui.ui_state import device
      device.set_override_interactive_timeout(24 * 3600)
    except Exception as e:
      print("[shoot] could not override interactive timeout:", e, flush=True)

    services = ["deviceState", "pandaStates", "selfdriveState", "selfdriveStateSP", "carState", "controlsState",
                "radarState", "modelV2", "liveCalibration", "carStateBP", "carParams", "carControl", "carOutput",
                "driverMonitoringState", "driverStateV2", "roadCameraState", "longitudinalPlan", "longitudinalPlanSP",
                "liveMapDataSP", "liveParameters", "onroadEvents", "controllerStateBP", "liveTorqueParameters", "carStateSP",
                "liveDelay"]
    self.pm = messaging.PubMaster([s for s in services if s in self._known_services()])
    self.vipc = None
    self._road_nv12: dict = {}
    self._gen = gui_app.render()

  @staticmethod
  def _known_services():
    from cereal.services import SERVICE_LIST
    return SERVICE_LIST

  def put(self, key: str, value):
    """Put a param regardless of its declared type; ignore unknown keys."""
    p = self.params
    try:
      if isinstance(value, bool):
        p.put_bool(key, value)
      else:
        p.put(key, value)
      return
    except Exception:
      pass
    for cand in (str(value), int(value) if isinstance(value, (int, float)) else None, float(value) if isinstance(value, (int, float)) else None):
      if cand is None:
        continue
      try:
        p.put(key, cand)
        return
      except Exception:
        continue
    print(f"[shoot] warning: could not set param {key}={value!r}", flush=True)

  def _setup_base_params(self):
    from cereal import car
    self.put("BPConsoleMode", os.environ.get("CONSOLE_SHOTS_THEME", "night"))
    try:
      from openpilot.system.version import terms_version, training_version
      self.put("HasAcceptedTerms", terms_version)
      self.put("CompletedTrainingVersion", training_version)
    except Exception as e:
      print("[shoot] terms versions:", e)
    try:
      from openpilot.system.version import terms_version_sp, sunnylink_consent_version
      self.put("HasAcceptedTermsSP", terms_version_sp)
      self.put("CompletedSunnylinkConsentVersion", sunnylink_consent_version)
    except Exception as e:
      print("[shoot] sp terms versions:", e)
    self.put("DongleId", "c0ffee0123456789")
    self.put("UpdaterCurrentDescription", "6.0.0 / bp-6.0 / f29bcae / Oct 14")
    self.put("Version", "6.0.0")
    self.put("GitBranch", "bp-6.0")
    self.put("GitCommit", "f29bcae0ff9131237ba23a1d0fbd8edf9c80e87")
    self.put("GitCommitDate", "'1760400000 2025-10-14 00:00:00 +0000'")
    self.put("IsMetric", False)
    # Suppress BluePilot "Recent Changes" auto-popup
    try:
      bpv = (Path.cwd() / "BPVERSION").read_text().splitlines()[0].strip()
      self.put("BPLastSeenVersion", bpv)
    except Exception:
      pass
    CP = car.CarParams.new_message()
    CP.brand = "ford"
    CP.carFingerprint = "FORD_F_150_LIGHTNING_MK1"
    CP.openpilotLongitudinalControl = True
    CP.steerActuatorDelay = 0.2
    CP.longitudinalActuatorDelay = 0.5
    CP.steerControlType = car.CarParams.SteerControlType.angle
    b = CP.to_bytes()
    self.put("CarParams", b)
    self.put("CarParamsPersistent", b)
    self._cp_bytes = b

  # --- per-frame publishing -------------------------------------------------------------------
  def _ensure_vipc(self, lead_d):
    if self.vipc is None:
      from msgq.visionipc import VisionIpcServer, VisionStreamType
      self.VST = VisionStreamType
      self.vipc = VisionIpcServer("camerad")
      self.vipc.create_buffers(VisionStreamType.VISION_STREAM_ROAD, 4, CAM_W, CAM_H)
      self.vipc.start_listener()
      self._vipc_frame = 0
    key = round(lead_d, 1) if lead_d is not None else None
    if key not in self._road_nv12:
      self._road_nv12[key] = rgb_to_nv12(synth_road_rgb(lead_d))
    return self._road_nv12[key]

  def _send_camera(self, d):
    lead_d = d["lead_d"] if d["lead"] else None
    nv12 = self._ensure_vipc(lead_d)
    if self.frame % 5 == 0:
      fid = self._vipc_frame
      self.vipc.send(self.VST.VISION_STREAM_ROAD, nv12, fid, int(fid * 5e7), int(fid * 5e7))
      self._vipc_frame += 1
    msg = self.messaging.new_message("roadCameraState", valid=True)
    msg.roadCameraState.frameId = self._vipc_frame
    msg.roadCameraState.sensor = self.log.FrameData.ImageSensor.ar0231
    msg.roadCameraState.transform = [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0]
    self.pm.send("roadCameraState", msg)

  def send(self):
    m, log = self.messaging, self.log
    d = self.drive
    started = bool(d and d["started"])

    ds = m.new_message("deviceState", valid=True)
    ds.deviceState.started = started
    ds.deviceState.networkType = log.DeviceState.NetworkType.wifi
    ds.deviceState.deviceType = log.InitData.DeviceType.tici
    ds.deviceState.freeSpacePercent = 72.0
    ds.deviceState.memoryUsagePercent = 41
    ds.deviceState.maxTempC = 52.0
    ds.deviceState.thermalStatus = log.DeviceState.ThermalStatus.green
    self.pm.send("deviceState", ds)

    ps = m.new_message("pandaStates", 1, valid=True)
    ps.pandaStates[0].pandaType = log.PandaState.PandaType.tres
    ps.pandaStates[0].ignitionLine = started
    self.pm.send("pandaStates", ps)

    if not started:
      return

    self._send_camera(d)
    v = d["v_ego"]

    # selfdriveState
    ss_msg = m.new_message("selfdriveState", valid=True)
    ss = ss_msg.selfdriveState
    ss.enabled = d["enabled"]
    ss.active = d["enabled"]
    ss.engageable = True
    ss.state = getattr(log.SelfdriveState.OpenpilotState, d["state"])
    ss.experimentalMode = d["experimental"]
    ss.personality = log.LongitudinalPersonality.standard
    if d["alert"]:
      size, status, t1, t2 = d["alert"]
      ss.alertSize = getattr(log.SelfdriveState.AlertSize, size)
      ss.alertStatus = getattr(log.SelfdriveState.AlertStatus, status)
      ss.alertText1 = t1
      ss.alertText2 = t2
      ss.alertType = f"shoot/{size}/{status}"
    self.pm.send("selfdriveState", ss_msg)

    if "selfdriveStateSP" in self.pm.sock:
      sp = m.new_message("selfdriveStateSP", valid=True)
      self.pm.send("selfdriveStateSP", sp)

    # carState
    cs_msg = m.new_message("carState", valid=True)
    cs = cs_msg.carState
    cs.vEgo = v
    cs.vEgoCluster = v
    cs.vEgoRaw = v
    cs.aEgo = d["a_ego"]
    cs.standstill = v < 0.1
    cs.vCruise = d["v_cruise_kph"]
    cs.vCruiseCluster = d["v_cruise_kph"]
    cs.cruiseState.enabled = d["enabled"]
    cs.cruiseState.available = True
    cs.cruiseState.speed = d["v_cruise_kph"] * KPH
    cs.cruiseState.speedCluster = d["v_cruise_kph"] * KPH
    cs.leftBlinker = d["left_blinker"]
    cs.rightBlinker = d["right_blinker"]
    cs.leftBlindspot = d["left_blindspot"]
    cs.rightBlindspot = d["right_blindspot"]
    cs.steeringPressed = d["steering_pressed"]
    cs.gasPressed = d["gas_pressed"]
    cs.steeringAngleDeg = -1.5
    cs.steeringTorqueEps = d["steer_torque"]
    cs.gearShifter = self.car.CarState.GearShifter.drive
    self.pm.send("carState", cs_msg)

    # controlsState
    ctl = m.new_message("controlsState", valid=True)
    ctl.controlsState.vCruiseDEPRECATED = d["v_cruise_kph"]
    ctl.controlsState.curvature = d["curvature"]
    ctl.controlsState.desiredCurvature = d["curvature"]
    try:
      ctl.controlsState.lateralControlState.init("angleState")
    except Exception:
      pass
    self.pm.send("controlsState", ctl)

    # carControl / carOutput
    cc = m.new_message("carControl", valid=True)
    cc.carControl.enabled = d["enabled"]
    cc.carControl.latActive = d["enabled"]
    cc.carControl.longActive = d["enabled"]
    cc.carControl.actuators.torque = d["steer_torque"]
    cc.carControl.actuators.accel = d["a_ego"]
    cc.carControl.actuators.steeringAngleDeg = -1.4
    cc.carControl.cruiseControl.override = d["override_long"]
    self.pm.send("carControl", cc)
    co = m.new_message("carOutput", valid=True)
    co.carOutput.actuatorsOutput.torque = d["steer_torque"]
    co.carOutput.actuatorsOutput.accel = d["a_ego"]
    self.pm.send("carOutput", co)

    cp = m.new_message("carParams", valid=True)
    cp.carParams = self.messaging.log_from_bytes(self._cp_bytes, self.car.CarParams)
    self.pm.send("carParams", cp)

    # radarState
    rs = m.new_message("radarState", valid=True)
    if d["lead"]:
      lo = rs.radarState.leadOne
      lo.status = True
      lo.dRel = d["lead_d"]
      lo.yRel = 0.0
      lo.vRel = d["lead_v_rel"]
      lo.vLead = v + d["lead_v_rel"]
      lo.aLeadK = 0.0
      lo.modelProb = 0.95
      lo.radar = True
    self.pm.send("radarState", rs)

    self._send_model(v, d)

    lc = m.new_message("liveCalibration", valid=True)
    lc.liveCalibration.calStatus = log.LiveCalibrationData.Status.calibrated
    lc.liveCalibration.rpyCalib = [0.0, 0.0, 0.0]
    lc.liveCalibration.height = [CAM_HEIGHT]
    lc.liveCalibration.validBlocks = 20
    lc.liveCalibration.wideFromDeviceEuler = [0.0, 0.0, 0.0]
    self.pm.send("liveCalibration", lc)

    # Driver monitoring (face icon)
    dms = m.new_message("driverMonitoringState", valid=True)
    dms.driverMonitoringState.isActiveMode = True
    dms.driverMonitoringState.faceDetected = True
    dms.driverMonitoringState.awarenessStatus = 1.0
    self.pm.send("driverMonitoringState", dms)
    dsv = m.new_message("driverStateV2", valid=True)
    dsv.driverStateV2.wheelOnRightProb = 0.0
    dd = dsv.driverStateV2.leftDriverData
    dd.faceOrientation = [0.05, -0.1, 0.0]
    dd.faceOrientationStd = [0.1, 0.1, 0.1]
    dd.facePosition = [0.0, 0.0]
    dd.faceProb = 0.99
    self.pm.send("driverStateV2", dsv)

    lp = m.new_message("longitudinalPlan", valid=True)
    lp.longitudinalPlan.allowThrottle = True
    lp.longitudinalPlan.hasLead = d["lead"]
    self.pm.send("longitudinalPlan", lp)

    if "longitudinalPlanSP" in self.pm.sock:
      lps = m.new_message("longitudinalPlanSP", valid=True)
      if d["speed_limit_mph"]:
        r = lps.longitudinalPlanSP.speedLimit.resolver
        sl = d["speed_limit_mph"] * MPH
        r.speedLimit = sl
        r.speedLimitLast = sl
        r.speedLimitFinal = sl
        r.speedLimitFinalLast = sl
        r.speedLimitValid = True
        r.speedLimitLastValid = True
      self.pm.send("longitudinalPlanSP", lps)

    if "liveMapDataSP" in self.pm.sock:
      lmd = m.new_message("liveMapDataSP", valid=True)
      lmd.liveMapDataSP.roadName = d["road_name"]
      if d["speed_limit_mph"]:
        lmd.liveMapDataSP.speedLimitValid = True
        lmd.liveMapDataSP.speedLimit = d["speed_limit_mph"] * MPH
      self.pm.send("liveMapDataSP", lmd)

    lpm = m.new_message("liveParameters", valid=True)
    lpm.liveParameters.roll = 0.0
    lpm.liveParameters.valid = True
    self.pm.send("liveParameters", lpm)

    if "controllerStateBP" in self.pm.sock:
      csb = m.new_message("controllerStateBP", valid=True)
      try:
        csb.controllerStateBP.lateralUncertainty = 0.1
      except Exception:
        pass
      self.pm.send("controllerStateBP", csb)

    # carStateBP (EV / hybrid data + brake lights)
    bp = m.new_message("carStateBP", valid=True)
    if d["battery"]:
      hb = bp.carStateBP.hybridBattery
      hb.dataAvailable = True
      hb.socActual = d["battery"]["soc"]
      hb.socMinPerc = d["battery"].get("soc_min", 10.0)
      hb.socMaxPerc = d["battery"].get("soc_max", 95.0)
      hb.voltActual = d["battery"]["volts"]
      hb.voltHighLimit = d["battery"].get("v_high", 410.0)
      hb.voltLowLimit = d["battery"].get("v_low", 300.0)
      hb.ampsActual = d["battery"]["amps"]
    if d["drive"]:
      hd = bp.carStateBP.hybridDrive
      hd.dataAvailable = True
      hd.throttleDemandPercent = d["drive"].get("throttle", 35.0)
      hd.throttleThresholdPercent = d["drive"].get("threshold", 60.0)
      hd.powerFlowMode = d["drive"].get("mode", "EV")
      hd.powerFlowModeValue = d["drive"].get("mode_value", 1)
      hd.engineOnReason = d["drive"].get("reason", "")
      hd.engineOnReasonValue = d["drive"].get("reason_value", 0)
    bp.carStateBP.brakeLightStatus.dataAvailable = True
    bp.carStateBP.brakeLightStatus.brakeLightsOn = d["brake_lights"]
    self.pm.send("carStateBP", bp)

  def _send_model(self, v, d):
    import numpy as np
    m = self.messaging
    T = np.array([10.0 * (i / 32) ** 2 for i in range(33)], dtype=np.float32)
    x = np.maximum(v, 3.0) * T + 0.5 * T
    curv = d["curvature"]
    y_path = 0.5 * curv * x ** 2
    msg = m.new_message("modelV2", valid=True)
    mv = msg.modelV2
    mv.frameId = self.frame
    mv.position.x = x.tolist()
    mv.position.y = y_path.tolist()
    mv.position.z = np.zeros_like(x).tolist()
    mv.position.t = T.tolist()
    mv.velocity.x = np.full_like(x, v).tolist()
    mv.acceleration.x = np.full_like(x, 0.1).tolist()
    mv.orientation.z = np.zeros_like(x).tolist()
    mv.orientationRate.z = np.zeros_like(x).tolist()
    lls = mv.init("laneLines", 4)
    for i, off in enumerate((-5.55, -1.85, 1.85, 5.55)):
      lls[i].x = x.tolist()
      lls[i].y = (y_path + off).tolist()
      lls[i].z = np.full_like(x, CAM_HEIGHT).tolist()
      lls[i].t = T.tolist()
    mv.laneLineProbs = [0.75, 0.97, 0.97, 0.75]
    mv.laneLineStds = [0.3, 0.1, 0.1, 0.3]
    res = mv.init("roadEdges", 2)
    for i, off in enumerate((-6.4, 6.4)):
      res[i].x = x.tolist()
      res[i].y = (y_path + off).tolist()
      res[i].z = np.full_like(x, CAM_HEIGHT).tolist()
      res[i].t = T.tolist()
    mv.roadEdgeStds = [0.25, 0.25]
    mv.confidence = self.log.ModelDataV2.ConfidenceClass.green
    mv.meta.engagedProb = 0.99
    dp = mv.meta.disengagePredictions
    dp.t = [2.0, 4.0, 6.0, 8.0, 10.0]
    dp.brakeDisengageProbs = [0.02] * 5
    dp.gasDisengageProbs = [0.02] * 5
    dp.steerOverrideProbs = [0.03] * 5
    dp.brake3MetersPerSecondSquaredProbs = [0.01] * 5
    dp.brake4MetersPerSecondSquaredProbs = [0.01] * 5
    dp.brake5MetersPerSecondSquaredProbs = [0.01] * 5
    self.pm.send("modelV2", msg)

  # --- driving the render loop ---------------------------------------------------------------
  def step(self, n: int = 1):
    for _ in range(n):
      try:
        next(self._gen)
      except StopIteration:
        raise RuntimeError("gui_app.render() generator ended unexpectedly") from None
      self.send()
      self.ui_state.update()
      self.frame += 1

  def settle(self):
    self.step(self.frames)

  def shot(self, name: str | None = None):
    path = str(self.out / f"{name or self.name}.png")
    self._capture_path = path
    self.step(1)
    if self._capture_path is not None:  # end_drawing hook did not fire (application changed?)
      self._save_render_texture(path)
      self._capture_path = None
    self._captured.append(path)
    print(f"[shoot] saved {path}", flush=True)

  def _save_render_texture(self, path: str):
    rl = self.rl
    img = rl.load_image_from_texture(self.gui_app._render_texture.texture)
    rl.image_flip_vertical(img)
    rl.export_image(img, path)
    rl.unload_image(img)

  # --- helpers for layouts -------------------------------------------------------------------
  @property
  def MainState(self):
    return self.main_mod.MainState

  def settings_layout(self):
    return self.main._layouts[self.MainState.SETTINGS]

  def panel_types(self):
    return list(self.settings_layout()._panels.keys())


# ----------------------------------------------------------------------------------------------
# Scene definitions
# ----------------------------------------------------------------------------------------------

ONROAD_ALL_PARAMS = {
  "FordPrefHybridBatteryStatus": True,
  "FordPrefHybridPowerFlow": True,
  "FordPrefHybridGaugeStyle": "flat",
  "FordPrefHybridDriveGaugeSize": 2,
  "FordPrefShowRadarLeadOverlay": True,
  "BPShowConfidenceBall": True,
  "BPAnimateSteeringWheel": True,
  "ShowTurnSignals": True,
  "BlindSpot": True,
  "ShowBlindspotOverlay": True,
  "DevUIInfo": 3,
  "RoadNameToggle": True,
  "ChevronInfo": 4,
  "TorqueBar": True,
  "ShowBrakeStatus": True,
  "RocketFuel": True,
  "SpeedLimitMode": 2,
  "AlwaysOnDM": True,
  "StandstillTimer": True,
}


def scene_params(name: str) -> dict:
  base = {"BPShowConfidenceBall": True}
  if name in ("onroad_ev", "onroad_ev_powerflow"):
    base.update({"FordPrefHybridBatteryStatus": True})
  if name == "onroad_ev_powerflow":
    base.update({"FordPrefHybridPowerFlow": True, "FordPrefHybridGaugeStyle": "flat", "FordPrefHybridDriveGaugeSize": 2})
  if name == "onroad_experimental":
    base.update({"ExperimentalMode": True, "ExperimentalModeConfirmed": True})
  if name == "onroad_all":
    base.update(ONROAD_ALL_PARAMS)
  return base


def run_scene(sc: Scene):
  name = sc.name
  d = default_drive()
  if name in ("home", "home_alerts", "settings", "settings_panels"):
    sc.drive = None
  else:
    sc.drive = d

  if name == "home":
    sc.settle()
    sc.shot()
  elif name == "home_alerts":
    from openpilot.selfdrive.selfdrived.alertmanager import set_offroad_alert
    set_offroad_alert("Offroad_TemperatureTooHigh", True, extra_text="99C")
    set_offroad_alert("Offroad_IsTakingSnapshot", True)
    sc.put("UpdateAvailable", True)
    sc.put("UpdaterNewDescription", "6.0.1 / bp-6.0 / 0a1b2c3 / Oct 20")
    home = sc.main._layouts[sc.MainState.HOME]
    if hasattr(home, "last_refresh"):
      home.last_refresh = 0
    sc.settle()
    sc.shot()
  elif name == "settings":
    sc.step(10)
    sc.main.open_settings(sc.panel_types()[0])
    sc.settle()
    sc.shot()
  elif name == "settings_panels":
    sc.step(10)
    for pt in sc.panel_types():
      sc.main.open_settings(pt)
      sc.step(max(20, sc.frames // 4))
      sc.shot(f"settings_{pt.name.lower()}")
  else:
    if name == "onroad_disengaged":
      d.update(enabled=False, state="disabled", lead=True)
    elif name == "onroad_override":
      d.update(state="overriding", steering_pressed=True, gas_pressed=True, override_long=True, steer_torque=0.6)
    elif name == "onroad_experimental":
      d.update(experimental=True)
    elif name == "alert_small":
      d.update(alert=("small", "normal", "Lane Change Blocked", "Car Detected in Blindspot"))
    elif name == "alert_mid":
      d.update(alert=("mid", "userPrompt", "Pay Attention", "Touch Steering Wheel"))
    elif name == "alert_full_prompt":
      d.update(alert=("full", "userPrompt", "TAKE CONTROL IMMEDIATELY", "Calibration Invalid: Remount Device & Recalibrate"))
    elif name == "alert_full_critical":
      d.update(alert=("full", "critical", "DISENGAGE IMMEDIATELY", "Driver Distracted"))
    elif name in ("onroad_ev", "onroad_ev_powerflow"):
      d.update(battery=dict(soc=78.0, volts=372.5, amps=-46.0))
      if name == "onroad_ev_powerflow":
        d.update(drive=dict(throttle=34.0, threshold=70.0, mode="EV Drive", mode_value=1))
    elif name in ("charging_dc", "charging_ac"):
      d.update(battery=dict(soc=62.0 if name == "charging_dc" else 41.0, volts=388.0, amps=-746.0),
               v_ego=0.0, enabled=False, state="disabled", lead=False)
      _inject_charge(name)
    elif name == "onroad_all":
      d.update(battery=dict(soc=78.0, volts=372.5, amps=-46.0),
               drive=dict(throttle=34.0, threshold=70.0, mode="EV Drive", mode_value=1),
               left_blinker=True, right_blindspot=True, brake_lights=False,
               road_name="Interstate 94", speed_limit_mph=65, steer_torque=0.45)
    sc.settle()
    if name == "sidebar":
      sc.main._sidebar.set_visible(True)
      sc.step(max(20, sc.frames // 4))
    if name == "onroad_debug_panel":
      sc.main._debug_panel.toggle_visibility()
      sc.step(max(30, sc.frames // 3))
    sc.shot()


def _inject_charge(name: str):
  """Fill the charge fields the Lightning CAN stream will publish, so the screen can be rendered now."""
  import math
  import time
  from bluepilot.ui.lib import ev_data

  dc = name == "charging_dc"
  fields = dict(charging=True, charge_type=2 if dc else 1, charge_status="chargingDc" if dc else "chargingAc",
                charge_power_kw=148.0 if dc else 9.4, charge_time_to_full_min=21.0 if dc else 312.0,
                charge_target_soc=80.0 if dc else 90.0, charge_inhibit_thermal=not dc,
                pack_temp_c=31.0 if dc else -4.0, range_km=(62.0 if dc else 41.0) / 100 * 131000 / 300.0)
  orig = ev_data.EvDataSource.update

  def update(self, sm, started_frame, now=None):
    snap = orig(self, sm, started_frame, now)
    for k, v in fields.items():
      setattr(snap, k, v)
    return snap

  ev_data.EvDataSource.update = update
  ev_data.ChargeSession.ENTER_S = 0.0
  ev_data.ChargeSession.STANDSTILL_MS = math.inf
  orig_begin = ev_data.ChargeSession._begin

  def begin(self, snap, now):
    orig_begin(self, snap, now)
    self.start_t = time.monotonic() - (23 if dc else 95) * 60
    self.start_soc = 31.0 if dc else 28.0
    self.energy_kwh = 41.3 if dc else 13.6
    self.peak_kw = 212.0 if dc else 9.6

  ev_data.ChargeSession._begin = begin


def run_worker(args) -> int:
  scene = args._worker
  out = Path(args.out).resolve()
  out.mkdir(parents=True, exist_ok=True)
  os.environ.setdefault("BIG", "1")
  os.environ.setdefault("SCALE", "1.0")
  os.environ.setdefault("OFFSCREEN", "1")

  from openpilot.common.prefix import OpenpilotPrefix
  with OpenpilotPrefix():
    sc = Scene(scene, out, args.frames)
    sc.boot(scene_params(scene))
    run_scene(sc)
    try:
      sc.gui_app.close()
    except Exception:
      pass
  # Avoid slow/fragile interpreter teardown of threads (wifi manager, prime state, etc.)
  sys.stdout.flush()
  sys.stderr.flush()
  os._exit(0)


def main() -> int:
  ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
  ap.add_argument("--out", default=str(HERE / "out"), help="output directory for PNGs (default: tools/console_shots/out)")
  ap.add_argument("--scenes", default="all", help="comma separated scene names or aliases (default: all)")
  ap.add_argument("--list", action="store_true", help="list scenes and exit")
  ap.add_argument("--repo", default=str(DEFAULT_REPO), help="openpilot checkout to render (default: this repo)")
  ap.add_argument("--frames", type=int, default=90, help="frames to settle before each capture (default 90 = 1.5s sim time)")
  ap.add_argument("--jobs", type=int, default=min(4, os.cpu_count() or 1), help="scenes rendered in parallel")
  ap.add_argument("--timeout", type=int, default=600, help="per-scene timeout in seconds")
  ap.add_argument("--theme", choices=["night", "day", "auto"], default="night",
                  help="Console palette (BPConsoleMode) for every scene (default night)")
  ap.add_argument("--build", action="store_true", help="run the targeted scons build in --repo first")
  ap.add_argument("--no-xvfb", action="store_true", help="do not wrap in xvfb-run even if $DISPLAY is unset")
  ap.add_argument("--_worker", help=argparse.SUPPRESS)
  args = ap.parse_args()
  if args._worker:
    return run_worker(args)
  return run_parent(args)


if __name__ == "__main__":
  sys.exit(main())
