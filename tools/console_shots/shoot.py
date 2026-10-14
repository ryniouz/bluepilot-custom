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
  "standby": "Parked standby splash (offroad idle)",
  "home": "Offroad Home dashboard in the Console shell",
  "home_alerts": "Offroad home with offroad alerts + update available",
  "home_charging": "Home after the charging page was minimized (Charging card reopens it)",
  "drives": "Drives > Previous drives (fake log root, some synced)",
  "drives_offload": "Drives > Offloading (comma connect queue + Citadel sync)",
  "drives_storage": "Drives > Storage",
  "connectivity": "Connect > Status (Wi-Fi, LTE, server and sync, home location)",
  "updates": "System > Updates with an update available from Lucas's repo",
  "calibration": "System > Calibration with a saved calibration and steering lag half learned",
  "onboarding_welcome": "Console onboarding, welcome step",
  "onboarding_safety": "Console onboarding, safety notice",
  "onboarding_terms": "Console onboarding, terms step",
  "onboarding_sunnylink": "Console onboarding, sunnylink consent",
  "cellular": "Connect > Cellular on LTE (Rogers, band 4), modem details faked",
  "bluetooth": "Connect > Bluetooth as the PC really is: no adapter",
  "bluetooth_obd": "Connect > Bluetooth, OBD wizard connect step (Wi-Fi adapter), no Bluetooth as on a real comma",
  "bluetooth_obd_bt": "Connect > Bluetooth, OBD wizard with Bluetooth chosen on a comma without Bluetooth",
  "bluetooth_obd_live": "Connect > Bluetooth, OBD wizard live data from a faked obdStateBP (design preview)",
  "bluetooth_phone": "Connect > Bluetooth, phone tab with a faked adapter (design preview)",
  "onboarding_guide": "Console onboarding, driving guide (calibration step)",
  "home_guest": "Home with Guest Mode armed (banner + toggle), keys faked when the branch lacks them",
  "settings": "Settings open on the Device panel",
  "theme": "Screen > Theme and layout (theme, UI size, accent, layout)",
  "home_large": "Home at UI size Large",
  "home_small": "Home at UI size Small",
  "cellular_large": "Connect > Cellular at UI size Large",
  "theme_large": "Screen > Theme and layout at UI size Large",
  "automations": "Connect > Home automations: at home on a home network, after joining it",
  "automations_large": "Connect > Home automations at UI size Large",
  "upload_settings": "Drives > Upload settings: comma connect, Citadel uploads, LTE data limit",
  "vehicle": "System > Vehicle: the Lightning, platform lock, Driving tab",
  "vehicle_alerts": "System > Vehicle: Alerts tab (battery %, tire PSI, 12 V)",
  "vehicle_guest": "System > Vehicle: Guest Mode tab",
  "vehicle_power": "System > Vehicle: Power tab",
  "vehicle_mismatch": "System > Vehicle: the comma refused another car",
  "steering": "Drive > Steering: torque and NNLC rows hidden",
  "boot_spinner": "Start-up spinner (system/ui/spinner.py) with a status line",
  "boot_progress": "Start-up spinner with a progress number",
  "boot_error": "Error window (system/ui/text.py) with a build log",
  "tap_large": "UI size Large: a tap on the rail's Connect item (screen px) must open Connect",
  "settings_panels": "Every settings panel, one PNG each (settings_<panel>.png), incl. BluePilot",
  "sidebar": "Onroad engaged with the quick-controls sheet open",
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
  "charging_dc_obd": "Charging screen, DC fast charge with an OBD adapter connected (extra row)",
  "truck_data": "Energy > Truck data: OBD adapter connected (faked obdStateBP)",
  "truck_data_off": "Energy > Truck data: no OBD adapter set up",
  "truck_data_asleep": "Energy > Truck data: adapter set up, truck asleep",
  # Stream C: Energy pages
  "energy_charging": "Energy > Charging in the shell while plugged in (charging screen minimized)",
  "energy_idle": "Energy > Charging when not plugged in, with the last session",
  "stats": "Energy > Statistics with an hour of seeded history and three signals graphed",
}
ALIASES = {
  "alert_full": ["alert_full_prompt", "alert_full_critical"],
  "alerts": ["alert_small", "alert_mid", "alert_full_prompt", "alert_full_critical"],
  "onroad": ["onroad_engaged", "onroad_disengaged", "onroad_override", "onroad_experimental"],
  "charging": ["charging_dc", "charging_ac"],
  "energy": ["charging_dc", "charging_ac", "energy_charging", "energy_idle", "stats"],
}

# --- Stream B (driving screen) scenes ------------------------------------------------------
SCENES.update({
  "drive_minimal": "Driving screen, Minimal layout preset (speed card, alerts, cues only)",
  "drive_dense": "Driving screen, Dense layout preset (dock + details card), regen",
  "drive_notify": "Driving screen with an informational notification and turn signal",
  "drive_signals": "Left signal on; right signal into a car in the blind spot (tile + edge bar)",
  "drive_prompt": "Mid userPrompt alert (Pay Attention) as a Console card",
  "drive_critical": "Mid critical alert as a Console card",
  "drive_popup": "SP green-light pop-up as a notification card, with smart-cruise chips",
  "drive_lead": "Closing on a lead: bracket marker and lead card with every row on",
  "drive_road_settings": "Quick controls on the Road view page (what the road view shows)",
  "drive_steer_only": "Steering only (MADS lateral without cruise): blue state band",
  "drive_off": "Disengaged: neutral state band",
  "drive_lead_bracket": "Lead speed beside the car (Speed at car on, lead card off), bracket marker",
  "drive_lead_floor": "Lead speed beside the car, floor-pad marker candidate",
  "drive_lead_corners": "Lead speed beside the car, corner-frame marker candidate",
  "drive_lead_chevron": "Lead speed beside the car, roof-chevron marker candidate",
  "drive_plugged": "Ignition on while DC charging, charging screen minimized: power tile reads Charging",
  "drive_obd": "Dense layout with the OBD adapter connected: OBD rows in the details card",
  "drive_qc_handle": "Minimal layout with the collapsed Quick controls bar at the bottom",
  "drive_qc_drag": "Minimal layout, Quick controls sheet half way up (mid swipe)",
  "drive_guest": "Guest Mode drive: factory assist banner, no path, no engage prompts",
})
ALIASES["drive"] = ["onroad_ev", "drive_minimal", "drive_dense", "drive_notify", "drive_signals", "drive_prompt",
                    "drive_critical", "drive_popup", "drive_lead", "drive_road_settings", "drive_steer_only", "drive_off",
                    "drive_guest", "drive_qc_handle", "drive_qc_drag", "drive_lead_bracket", "drive_lead_floor",
                    "drive_lead_corners", "drive_lead_chevron", "drive_plugged", "drive_obd",
                    "onroad_override", "sidebar", "alert_full_prompt", "alert_full_critical"]
# --- end stream B --------------------------------------------------------------------------

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
      base = n[:-6] if n.endswith("_large") else n[:-6] if n.endswith("_small") else n
      if n not in SCENES and base in SCENES:  # any scene at UI size Large or Small
        SCENES[n] = SCENES[base] + " (UI size " + n[-5:] + ")"
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
        if args.sim_scale != 1.0:  # render the way the PC simulator window does
          env["SCALE"] = str(args.sim_scale)
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
    ds.deviceState.networkStrength = log.DeviceState.NetworkStrength.good
    ds.deviceState.deviceType = log.InitData.DeviceType.tici
    ds.deviceState.freeSpacePercent = 72.0
    ds.deviceState.memoryUsagePercent = 41
    ds.deviceState.maxTempC = 52.0
    ds.deviceState.thermalStatus = log.DeviceState.ThermalStatus.green
    if getattr(self, "cell", False):  # Console Cellular scene: on LTE with a Canadian carrier
      ds.deviceState.networkType = log.DeviceState.NetworkType.cell4G
      ds.deviceState.networkStrength = log.DeviceState.NetworkStrength.moderate
      ds.deviceState.networkInfo.technology = "FDD LTE"
      ds.deviceState.networkInfo.operator = "Rogers"
      ds.deviceState.networkInfo.band = "LTE BAND 4"
      ds.deviceState.networkInfo.channel = 2175
      ds.deviceState.networkInfo.state = "CONNECTED"
      ds.deviceState.networkStats.wwanTx = 18_000_000
      ds.deviceState.networkStats.wwanRx = 43_000_000
      ds.deviceState.modemTempC = [41.0, 39.0]
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
      if d.get("mads"):  # stream B: (available, enabled) for steering-only scenes
        sp.selfdriveStateSP.mads.available, sp.selfdriveStateSP.mads.enabled = d["mads"]
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
    app = self.gui_app
    if getattr(app, "_scale", 1.0) != 1.0:
      # Composite into a window-sized target exactly as GuiApplication does for the window
      ssaa = getattr(app, "_ssaa", 1)
      out = rl.load_render_texture(app._scaled_width, app._scaled_height)
      rl.begin_texture_mode(out)
      rl.draw_texture_pro(app._render_texture.texture, rl.Rectangle(0, 0, app.width * ssaa, -app.height * ssaa),
                          rl.Rectangle(0, 0, app._scaled_width, app._scaled_height), rl.Vector2(0, 0), 0.0, rl.WHITE)
      rl.end_texture_mode()
      img = rl.load_image_from_texture(out.texture)
      rl.unload_render_texture(out)
    else:
      img = rl.load_image_from_texture(app._render_texture.texture)
    rl.image_flip_vertical(img)
    rl.export_image(img, path)
    rl.unload_image(img)

  # --- helpers for layouts -------------------------------------------------------------------
  @property
  def MainState(self):
    return self.main_mod.MainState

  def settings_layout(self):
    if hasattr(self.main, "_settings"):  # Console shell hosts the settings panels
      return self.main._settings
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
  base.update(drive_scene_params(name))  # stream B
  if name in ("onroad_ev", "onroad_ev_powerflow"):
    base.update({"FordPrefHybridBatteryStatus": True})
  if name == "onroad_ev_powerflow":
    base.update({"FordPrefHybridPowerFlow": True, "FordPrefHybridGaugeStyle": "flat", "FordPrefHybridDriveGaugeSize": 2})
  if name == "onroad_experimental":
    base.update({"ExperimentalMode": True, "ExperimentalModeConfirmed": True})
  if name == "onroad_all":
    base.update(ONROAD_ALL_PARAMS)
  return base


# --- Stream B (driving screen) scene setup ------------------------------------------------
DRIVE_SCENES = ("drive_minimal", "drive_dense", "drive_notify", "drive_signals", "drive_prompt", "drive_critical", "drive_popup",
                "drive_lead", "drive_road_settings", "drive_steer_only", "drive_off",
                "drive_guest", "drive_qc_handle", "drive_qc_drag", "drive_lead_bracket", "drive_lead_floor",
                "drive_lead_corners", "drive_lead_chevron", "drive_plugged", "drive_obd")


def drive_scene_params(name: str) -> dict:
  if not name.startswith("drive_"):
    return {}
  p = {"IsMetric": True, "SpeedLimitMode": 2}  # the truck runs Canadian units
  if name in ("drive_minimal", "drive_qc_handle", "drive_qc_drag"):
    p["BPLayoutPreset"] = 0
  if name in ("drive_dense", "drive_obd"):
    p["BPLayoutPreset"] = 2
  if name == "drive_signals":
    p.update({"ShowTurnSignals": True, "BlindSpot": True, "ShowBlindspotOverlay": True})
  if name == "drive_popup":
    p.update({"StandstillTimer": True})
  if name == "drive_lead":
    p.update({"BPRoadView": 0x17F})  # every row on
  if name.startswith("drive_lead_"):
    from openpilot.selfdrive.ui.bp.onroad.road_view import LEAD_STYLES, MARKER_SHIFT
    # default with the speed tag on, the lead card off and this marker style
    p.update({"BPRoadView": 0xF7 | (LEAD_STYLES.index(name.split("_")[-1]) << MARKER_SHIFT)})
  return p


def setup_drive_scene(name: str, d: dict):
  d.update(battery=dict(soc=78.0, volts=372.5, amps=-46.0))
  if name == "drive_obd":
    _fake_obd()
  if name in ("drive_dense", "drive_obd"):
    d.update(battery=dict(soc=64.0, volts=380.0, amps=110.0), a_ego=-0.8)
    _inject_ev(dict(pack_temp_c=27.0, coolant_temp_c=24.0, tire_kpa=[285.0, 287.0, 281.0, 284.0], lv_volts=14.1,
                    outside_temp_c=4.0, trip_km=18.4, trip_used_kwh=6.2, trip_regen_kwh=1.1, wh_per_km=297.0))
  elif name == "drive_notify":
    d.update(alert=("small", "normal", "Changing Lanes", ""), left_blinker=True)
  elif name == "drive_signals":
    d.update(left_blinker=True, right_blinker=True, right_blindspot=True, speed_limit_mph=62.14,
             alert=("small", "normal", "Lane Change Blocked", "Car Detected in Blindspot"))
  elif name == "drive_prompt":
    d.update(alert=("mid", "userPrompt", "Pay Attention", "Touch Steering Wheel"))
  elif name == "drive_critical":
    d.update(alert=("mid", "critical", "TAKE CONTROL", "Steering Temporarily Unavailable"))
  elif name == "drive_popup":
    d.update(v_ego=0.0, lead_d=12.0)
    _inject_popup()
  elif name == "drive_lead":
    d.update(lead_d=24.0, lead_v_rel=-4.2)
  elif name == "drive_plugged":
    d.update(battery=dict(soc=62.0, volts=388.0, amps=-746.0), v_ego=0.0, enabled=False, state="disabled", lead=False)
    _inject_charge("charging_dc")
  elif name.startswith("drive_lead_"):
    d.update(lead_d=24.0, lead_v_rel=-4.2)
  elif name == "drive_steer_only":
    d.update(enabled=False, state="disabled", mads=(True, True))
  elif name == "drive_off":
    d.update(enabled=False, state="disabled")
  elif name == "drive_guest":
    d.update(enabled=False, state="disabled", alert=("small", "normal", "openpilot Unavailable", "Dashcam Mode"))
    from openpilot.selfdrive.ui.bp.onroad.augmented_road_view_bp import AugmentedRoadViewBP
    AugmentedRoadViewBP._read_guest = lambda self: True


def _inject_ev(fields: dict):
  from bluepilot.ui.lib import ev_data
  orig = ev_data.EvDataSource.update

  def update(self, sm, started_frame, now=None):
    snap = orig(self, sm, started_frame, now)
    for k, v in fields.items():
      setattr(snap, k, v)
    return snap

  ev_data.EvDataSource.update = update
def _inject_popup():
  """Force SP's green-light alert and both smart-cruise states on, as if the planner sent them."""
  from openpilot.selfdrive.ui.sunnypilot.onroad import circular_alerts, smart_cruise_control
  ca_update = circular_alerts.CircularAlertsRenderer.update

  def update(self):
    ca_update(self)
    self._allow_e2e_alerts = True
    self._green_light_alert = True
    self._e2e_alert_display_timer = 60

  circular_alerts.CircularAlertsRenderer.update = update
  scc_update = smart_cruise_control.SmartCruiseControlRenderer.update

  def scc(self):
    scc_update(self)
    self.vision_enabled = self.vision_active = True
    self.map_enabled = True

  smart_cruise_control.SmartCruiseControlRenderer.update = scc
# --- end stream B --------------------------------------------------------------------------


def fake_obd(link_state: str):
  """Fake obdStateBP for the OBD scenes: catalog short names (selfdrive/car/obd/catalog.py), metric units."""
  from bluepilot.ui.lib import obd_link as ol
  link = ol.obd_link()
  link.available = lambda: True
  def V(short, value, unit, age):
    return ol.ObdValue(short, value, unit, age, LABELS.get(short, short))
  LABELS = {"HvbSocD": "HV battery SOC displayed", "HvbSoc": "HV battery state of charge", "HvbEte": "HV battery energy to empty",
            "HvbT": "HV battery temperature", "HvbCit": "HV battery coolant inlet temperature", "LvV": "12 V battery voltage",
            "TireLF": "Tire pressure left front", "TireRF": "Tire pressure right front"}
  values = [V("HvbSocD", 62.0, "percent", 2.0), V("HvbSoc", 64.3, "percent", 1.0), V("HvbEte", 78.6, "kWh", 3.0),
            V("HvbT", 24.0, "degC", 4.0), V("HvbCit", 21.0, "degC", 4.0), V("HvbAvgModV", 3.912, "V", 4.0),
            V("HvbMinModV", 3.897, "V", 4.0), V("HvbAge", 29.0, "months", 90.0), V("HvbV", 391.4, "V", 1.0),
            V("HvbA", -238.0, "A", 1.0), V("ChgOV", 392.0, "V", 2.0), V("ChgSt", 3.0, "", 2.0), V("Evse", 4.0, "", 2.0),
            V("LvV", 13.8, "V", 5.0), V("LvSoc", 86.0, "percent", 12.0), V("TireLF", 248.0, "kPa", 20.0),
            V("TireRF", 251.0, "kPa", 20.0), V("TireLR", 262.0, "kPa", 20.0), V("TireRR", 259.0, "kPa", 20.0),
            V("HvbSoh", 97.0, "percent", 300.0 / 10), V("HvbCapAh", 306.2, "Ah", 30.0), V("HvbCHP", 2.7, "kW", 2.0),
            V("ChgInPwr", 151.0, "kW", 2.0), V("ChgMaxP", 155.0, "kW", 10.0), V("ChgACT", 29.0, "degC", 5.0),
            V("ACInV", 240.0, "V", 2.0), V("ACInA", 47.0, "A", 2.0), V("ACInF", 60.0, "Hz", 5.0), V("PilotDC", 80.0, "percent", 5.0)]
  if link_state == "setup":
    link.available = lambda: False
  snap = ol.ObdSnapshot(received=link_state != "setup", enabled=True, transport="wifi", link=link_state, adapter="ELM327 v1.5",
                        protocol="ISO 15765-4 (CAN 11/500)", polling=link_state == "connected",
                        values=values if link_state == "connected" else [])
  link.snapshot = lambda: snap


def run_scene(sc: Scene):
  name = sc.name
  if name == "charging_dc_obd":
    fake_obd("connected")
    name = "charging_dc"
  for suffix, idx in (("_large", 2), ("_small", 0)):  # UI size variants of another scene
    if name.endswith(suffix):
      from bluepilot.ui.lib import ui_scale
      sc.put("BPConsoleScale", idx)
      ui_scale.set_scale_index(idx)
      name = name[:-len(suffix)]
  d = default_drive()
  if name in ("standby", "home", "home_alerts", "home_charging", "settings", "settings_panels",
              "drives", "drives_offload", "drives_storage", "connectivity", "updates", "home_guest",
              "calibration", "onboarding_terms", "onboarding_guide", "onboarding_welcome",
              "onboarding_safety", "onboarding_sunnylink", "cellular", "bluetooth", "bluetooth_obd", "bluetooth_phone",
              "bluetooth_obd_bt", "bluetooth_obd_live", "theme", "tap", "automations", "upload_settings",
              "vehicle", "vehicle_alerts", "vehicle_guest", "vehicle_power", "vehicle_mismatch", "steering", "boot_spinner",
              "truck_data", "truck_data_off", "truck_data_asleep", "boot_progress", "boot_error"):
    sc.drive = None
  else:
    sc.drive = d

  if name in ("standby", "home", "home_alerts", "home_charging", "home_guest"):
    _inject_last_known()

  if name == "standby":
    sc.settle()
    sc.shot()
  elif name in ("home", "home_guest"):
    _seed_drives(sc)
    if name == "home_guest":
      _fake_guest_mode()
    sc.main._home.wifi_ssid = lambda: "Garage-5G"
    if hasattr(sc.main, "_open_shell"):
      sc.main._open_shell()
    sc.settle()
    sc.shot()
  elif name == "connectivity":
    import json
    from bluepilot.ui.lib.home_location import home_location
    from bluepilot.ui.lib.net_usage import usage
    _seed_drives(sc)
    sc.main._shell.connectivity._connected_ssid = lambda: "Garage-5G"
    sc.put("BPHomeWifi", json.dumps(["Garage-5G"]))
    sc.put("WifiFavoriteSSID", "Garage-5G")
    h = home_location()
    h.last = {"lat": 49.2488, "lon": -122.9805, "t": "2026-10-14T07:52:10"}
    h.home = {"lat": 49.2489, "lon": -122.9807}
    usage().month_bytes, usage().boot_bytes = 2_480_000_000, 61_000_000
    sc.main._open_shell()
    sc.main._shell.open_panel("connectivity")
    sc.settle()
    sc.shot()
  elif name == "calibration":
    import math
    from cereal import messaging as cmsg
    ev = cmsg.new_message("liveCalibration")
    ev.liveCalibration.calStatus = 1
    ev.liveCalibration.calPerc = 100
    ev.liveCalibration.rpyCalib = [0.0, math.radians(2.3), math.radians(-0.8)]
    sc.put("CalibrationParams", ev.to_bytes())
    lag = cmsg.new_message("liveDelay")
    lag.liveDelay.calPerc = 55
    sc.put("LiveDelay", lag.to_bytes())
    sc.main._open_shell()
    sc.main._shell.open_panel("calibration")
    sc.settle()
    sc.shot()
  elif name.startswith("onboarding_"):
    from bluepilot.ui.console.onboarding import ConsoleOnboarding, _State
    ob = ConsoleOnboarding()
    ob._state = {"onboarding_welcome": _State.WELCOME, "onboarding_safety": _State.SAFETY, "onboarding_terms": _State.TERMS,
                 "onboarding_sunnylink": _State.SUNNYLINK, "onboarding_guide": _State.GUIDE}[name]
    ob._guide._i = 4
    sc.main._open_shell()
    sc.settle()
    from openpilot.system.ui.lib.application import gui_app
    gui_app.push_widget(ob)
    sc.settle()
    sc.shot()
  elif name == "cellular":
    import time as _t
    from bluepilot.ui.lib import modem_info as mi
    sc.cell = True
    _seed_drives(sc)
    sc.put("GsmApn", "ltemobile.apn")
    snap = mi.ModemSnapshot(sim_present=True, sim_id="89302720412345678901", mcc_mnc="302720", data_connected=True,
                            imei="861234056789012", modem_version="EG25GGBR07A08M2G", read_at=_t.monotonic() + 3600)
    mi.modem_info()._snap = snap
    mi.modem_info().request = lambda force=False: None
    from bluepilot.ui.lib.net_usage import usage
    sc.main._open_shell()
    sc.main._shell.open_panel("cellular")
    sc.settle()
    usage().month_bytes = 2_480_000_000
    sc.settle()
    sc.shot()
  elif name == "bluetooth_obd_live":
    fake_obd("connected")
    sc.main._open_shell()
    sc.main._shell.open_obd()
    page = sc.main._shell.current_page().widget
    page._obd_step = 3
    sc.settle()
    sc.shot()
  elif name in ("bluetooth", "bluetooth_obd", "bluetooth_phone", "bluetooth_obd_bt", "bluetooth_obd_live"):
    from bluepilot.ui.lib import bluetooth as bt
    from bluepilot.ui.lib import obd_link as ol
    if name.startswith("bluetooth_obd"):
      link = ol.obd_link()
      link.available = lambda: True
      if name == "bluetooth_obd_live":
        V = ol.ObdValue
        link.snapshot = lambda: ol.ObdSnapshot(
          received=True, enabled=True, transport="wifi", link="connected", adapter="ELM327 v1.5",
          protocol="ISO 15765-4 (CAN 11/500)", polling=True, values=[
            V("HV battery charge", 78.4, "percent", 1.0), V("Energy to empty", 96.2, "kWh", 1.0),
            V("Pack temperature", 21.5, "degC", 1.0), V("Coolant temperature", 19.0, "degC", 2.0),
            V("12 V battery", 13.6, "V", 1.0), V("Front left tire", 248.0, "kPa", 4.0),
            V("Front right tire", 251.0, "kPa", 4.0), V("Rear left tire", 262.0, "kPa", 4.0)])
      else:
        link.snapshot = lambda: ol.ObdSnapshot()
    if name == "bluetooth_phone":
      b = bt.bluetooth()
      b.refresh = lambda: None
      devs = [bt.BtDevice("00:1D:A5:68:98:8B", "Vgate iCar Pro", paired=True), bt.BtDevice("66:1E:21:00:4F:10", "OBDII"),
              bt.BtDevice("A4:C1:38:5D:22:9E", "Pixel 8 Pro"), bt.BtDevice("F0:99:B6:12:33:01", "JBL Flip 6")]
      b._state = bt.BtState(adapter=True, tool=True, powered=True, devices=devs, checked_at=1.0)
    sc.main._open_shell()
    sc.main._shell.open_panel("bluetooth")
    page = sc.main._shell.current_page().widget
    page._tab = 1 if name.startswith("bluetooth_obd") else (2 if name == "bluetooth_phone" else 0)
    if name.startswith("bluetooth_obd"):
      page._obd_step = 3 if name == "bluetooth_obd_live" else 1
      page._obd_kind = 2 if name == "bluetooth_obd_bt" else 0
    sc.settle()
    sc.shot()
  elif name == "tap":
    from openpilot.system.ui.lib.application import MouseEvent, MousePos, gui_app
    sc.main._open_shell()
    sc.settle()
    x, y = 87.0, 756.0   # the Connect rail item as drawn at Large, in screen pixels
    queue = [[MouseEvent(MousePos(x, y), 0, True, False, True, 0.0)], [MouseEvent(MousePos(x, y), 0, False, True, False, 0.1)]]
    orig = gui_app._mouse.get_events
    gui_app._mouse.get_events = lambda: queue.pop(0) if queue else orig()
    sc.step(4)
    sc.settle()
    sc.shot()
  elif name == "automations":
    import json
    from bluepilot.ui.lib.automations import automations
    sc.put("BPHomeWifi", json.dumps(["Garage-5G", "Home-2G"]))
    sc.put("BPHomeLocation", json.dumps({"lat": 45.4215, "lon": -75.6972}))
    a = automations()
    a.tick = lambda onroad: None
    a.at_home, a.reason, a.last_action, a.last_action_at = True, "home Wi-Fi", "Joined Garage-5G", "18:02"
    sc.main._open_shell()
    sc.main._shell.open_panel("automations")
    sc.settle()
    sc.shot()
  elif name == "upload_settings":
    sc.put("BPServerUrl", "https://citadel.example.lan")
    sc.put("BPRoadTripMode", True)
    sc.put("BPCellLimitMB", 5000)
    sc.main._open_shell()
    sc.main._shell.open_panel("upload_settings")
    sc.settle()
    sc.shot()
  elif name.startswith("vehicle"):
    sc.put("BPPlatformMismatch", "FORD_BRONCO_SPORT_MK1" if name == "vehicle_mismatch" else "")
    sc.main._open_shell()
    sc.main._shell.open_panel("vehicle")
    page = sc.main._shell.current_page().widget
    page._tab = {"vehicle_alerts": 1, "vehicle_guest": 2, "vehicle_power": 3}.get(name, 0)
    sc.settle()
    sc.shot()
  elif name.startswith("truck_data"):
    fake_obd({"truck_data": "connected", "truck_data_asleep": "carAsleep"}.get(name, "setup"))
    sc.main._open_shell()
    sc.main._shell.open_panel("truck_data")
    sc.settle()
    sc.shot()
  elif name == "steering":
    sc.main._open_shell()
    from openpilot.selfdrive.ui.layouts.settings.settings import PanelType
    sc.main._shell.open_panel(PanelType.STEERING)
    sc.settle()
    sc.shot()
  elif name.startswith("boot_"):
    from openpilot.system.ui.lib.application import gui_app
    from bluepilot.ui.console import boot
    if name == "boot_error":
      log = "\n".join(f"[{i:4d}/1873] Compiling selfdrive/modeld/models/commonmodel.cc" for i in range(1840, 1872))
      log += "\nselfdrive/ui/qt/offroad/settings.cc:412:7: error: use of undeclared identifier 'params'\nscons: *** [selfdrive/ui/ui] Error 1"
      w = boot.ConsoleTextWindow("openpilot failed to build\n\n" + log)
    else:
      w = boot.ConsoleSpinner()
      w.set_text("47" if name == "boot_progress" else "Installing the update. This takes a few minutes.")
    gui_app.push_widget(w)
    sc.settle()
    sc.shot()
  elif name == "theme":
    sc.main._open_shell()
    sc.main._shell.open_panel("theme")
    sc.settle()
    sc.shot()
  elif name == "updates":
    sc.put("UpdaterFetchAvailable", True)
    sc.put("UpdaterCurrentDescription", "6.0.0 / console-ui / a58335b / Oct 14")
    sc.put("UpdaterNewDescription", "6.0.1 / console-ui / 4c1d9e2 / Oct 14")
    sc.put("UpdaterAvailableBranches", "lightning-console,console-ui,console-driving,console-energy")
    sc.put("BPUpdateBranch", "console-ui")
    sc.main._open_shell()
    sc.main._shell.open_panel("updates")
    sc.settle()
    sc.shot()
  elif name in ("drives", "drives_offload", "drives_storage"):
    _seed_drives(sc)
    sc.main._open_shell()
    sc.main._shell.open_panel(name)
    sc.settle()
    sc.shot()
  elif name == "home_charging":
    _inject_charge("charging_dc")
    sc.settle()
    if hasattr(sc.main, "_on_charging_clicked"):
      sc.main._on_charging_clicked()
    sc.settle()
    sc.shot()
  elif name == "home_alerts":
    from openpilot.selfdrive.selfdrived.alertmanager import set_offroad_alert
    set_offroad_alert("Offroad_TemperatureTooHigh", True, extra_text="99C")
    set_offroad_alert("Offroad_IsTakingSnapshot", True)
    sc.put("UpdateAvailable", True)
    sc.put("UpdaterNewDescription", "6.0.1 / bp-6.0 / 0a1b2c3 / Oct 20")
    if hasattr(sc.main, "_open_shell"):
      sc.main._open_shell()
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
    elif name in ("charging_dc", "charging_ac", "energy_charging"):
      d.update(battery=dict(soc=41.0 if name == "charging_ac" else 62.0, volts=388.0, amps=-746.0),
               v_ego=0.0, enabled=False, state="disabled", lead=False)
      _inject_charge("charging_dc" if name == "energy_charging" else name)
      if name == "energy_charging":
        sc.settle()
        sc.main._on_charging_clicked()       # minimize the full screen
        sc.main._open_shell()
        sc.main._shell.open_panel("charging_page")
    elif name == "energy_idle":
      sc.drive = None
      _inject_last_known()
      _inject_last_session()
      sc.main._open_shell()
      sc.main._shell.open_panel("charging_page")
    elif name == "stats":
      d.update(battery=dict(soc=62.0, volts=388.0, amps=-120.0), v_ego=0.0)
      _seed_history()
      sc.settle()
      if hasattr(sc.main, "_stats_page"):
        sc.main._stats_page.picks = ["ev.soc", "ev.power_kw", "ev.pack_temp_c"]
        sc.main._stats_page.window_i = 3
      sc.main._open_shell()
      sc.main._shell.open_panel("statistics")
    elif name in DRIVE_SCENES:  # stream B
      setup_drive_scene(name, d)
    elif name == "onroad_all":
      d.update(battery=dict(soc=78.0, volts=372.5, amps=-46.0),
               drive=dict(throttle=34.0, threshold=70.0, mode="EV Drive", mode_value=1),
               left_blinker=True, right_blindspot=True, brake_lights=False,
               road_name="Interstate 94", speed_limit_mph=65, steer_torque=0.45)
    sc.settle()
    if name == "sidebar":
      if hasattr(sc.main, "_quick"):
        sc.main._quick.open()
      else:
        sc.main._sidebar.set_visible(True)
      sc.step(max(20, sc.frames // 4))
    if name == "drive_road_settings":  # stream B
      sc.main._quick.open()
      sc.main._quick._page = "road"
      sc.step(max(20, sc.frames // 4))
    if name == "drive_plugged":  # stream B: minimize the charging screen back to the drive view
      sc.main._on_charging_clicked()
      sc.step(max(20, sc.frames // 4))
    if name == "drive_qc_drag":  # stream B: hold the sheet where a finger would leave it
      q = sc.main._quick
      q._p = q._target = 0.55
      q._touched_t = time.monotonic()
      sc.step(4)
    if name == "onroad_debug_panel":
      sc.main._debug_panel.toggle_visibility()
      sc.step(max(30, sc.frames // 3))
    sc.shot()


def _fake_obd():
  """A connected Wi-Fi adapter reading the built-in Lightning DIDs (obdStateBP is on the Lightning branch)."""
  from bluepilot.ui.lib import obd_link as ol
  vals = [("HvbEte", 71.4, "kWh"), ("HvbAvgModV", 3.912, "V"), ("HvbMinModV", 3.894, "V"), ("LvSoc", 82.0, "percent"),
          ("HvbSoc", 61.8, "percent"), ("HvbSoh", 96.0, "percent"), ("HvbCHP", 3.2, "kW")]
  snap = ol.ObdSnapshot(received=True, enabled=True, transport="wifi", link="connected", adapter="ELM327 v1.5",
                        values=[ol.ObdValue(n, v, u, 1.0) for n, v, u in vals])
  ol.ObdLink.snapshot = lambda self: snap


def _fake_guest_mode():
  """Guest Mode keys live on the Lightning control branch; answer for them here when this build lacks them."""
  from bluepilot.ui.console import home
  fake = {"BPGuestMode": True, "BPGuestModeOneTrip": True, "BPGuestModeActive": False}
  has, get = home.has_param, home._param
  home.has_param = lambda params, key: key in fake or has(params, key)
  home._param = lambda params, key, default=None: fake[key] if key in fake else get(params, key, default)


def _seed_drives(sc):
  """A fake log root: eight drives over three days, five synced by Citadel, one bookmarked, one recording."""
  import json
  import os
  import tempfile
  import time
  from bluepilot.ui.lib import drive_index

  root = tempfile.mkdtemp(prefix="console-drives-")
  state = tempfile.mkdtemp(prefix="console-bridge-")
  drive_index.BRIDGE_SYNCED = os.path.join(state, "synced.json")
  drive_index.PORTAL_METRICS = os.path.join(state, "metrics")
  os.makedirs(drive_index.PORTAL_METRICS)
  now = time.mktime(time.localtime())
  drives = [(0.4, 12, False, False, True), (3.0, 31, False, False, False), (5.5, 18, True, False, False),
            (26.0, 44, True, True, False), (29.0, 9, True, False, False), (50.0, 62, True, False, False),
            (53.0, 25, True, False, False), (75.0, 7, False, False, False)]
  places = [("Home", "Costco Burnaby"), ("Costco Burnaby", "Home"), ("Home", "Work")]
  synced = {}
  for i, (hours_ago, segs, is_synced, bookmarked, recording) in enumerate(drives):
    route = f"{i + 120:08x}--{i:010x}"
    start = now - hours_ago * 3600
    for n in range(segs):
      d = os.path.join(root, f"{route}--{n}")
      os.makedirs(d)
      for fn, size in (("rlog.zst", 9_000_000), ("qlog.zst", 600_000), ("qcamera.ts", 3_000_000), ("fcamera.hevc", 55_000_000)):
        with open(os.path.join(d, fn), "wb") as f:
          f.truncate(size)
      if recording and n == segs - 1:
        open(os.path.join(d, "rlog.lock"), "w").close()
      if bookmarked and n == segs - 1:
        try:
          os.setxattr(d, "user.preserve", b"1")
        except OSError:
          pass
      os.utime(d, (start + n * 60, start + n * 60))
      if is_synced:
        synced[f"{route}--{n}"] = "logs"
    if i < 7:
      a, b = places[i % 3]
      with open(os.path.join(drive_index.PORTAL_METRICS, f"{route}.json"), "w") as f:
        json.dump({"total_distance_meters": segs * 1150.0, "has_gps_data": True, "start_location": a, "end_location": b}, f)
  with open(drive_index.BRIDGE_SYNCED, "w") as f:
    json.dump(synced, f)
  drive_index._indexer = drive_index.DriveIndexer(root)
  sc.put("BPBridgeEnabled", True) if hasattr(sc, "put") else None


def _inject_last_known():
  """Parked screens show the last truck data seen; seed one as if the truck had just been driven."""
  from bluepilot.ui.lib import ev_data
  snap = ev_data.EvSnapshot(available=True, soc=74.0, range_km=74.0 / 100 * 131000 / 300.0, pack_temp_c=22.0,
                            tire_kpa=[262.0, 262.0, 255.0, 258.0], lv_volts=12.6)
  orig = ev_data.EvDataSource.__init__

  def init(self, *a, **kw):
    orig(self, *a, **kw)
    self.last_good = snap

  ev_data.EvDataSource.__init__ = init


def _inject_charge(name: str):
  """Fill the charge fields the Lightning CAN stream will publish, so the screen can be rendered now."""
  import math
  import time
  from bluepilot.ui.lib import ev_data

  dc = name == "charging_dc"
  fields = dict(charging=True, charge_type=2 if dc else 1, charge_status="chargingDc" if dc else "chargingAc",
                charge_power_kw=148.0 if dc else 9.4, charge_time_to_full_min=21.0 if dc else math.nan,
                charge_inhibit_thermal=not dc, thermal_mode="cooling" if dc else "heating", heater_on=not dc,
                pack_temp_c=31.0 if dc else -4.0, coolant_temp_c=24.0 if dc else 2.0,
                range_km=(62.0 if dc else 41.0) / 100 * 131000 / 300.0)
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
    self.start_range_km = self.start_soc / 100 * 131000 / 300.0
    self.energy_kwh = 41.3 if dc else 13.6
    self.peak_kw = 152.0 if dc else 9.6

  ev_data.ChargeSession._begin = begin


def _inject_last_session():
  """A finished charge for the Energy > Charging idle state."""
  import math
  from bluepilot.ui.lib import ev_data
  orig = ev_data.ChargeSession.__init__

  def init(self, *a, **kw):
    orig(self, *a, **kw)
    self.last = {"ended": "6:42 am", "minutes": 312.0, "energy_kwh": 58.4, "peak_kw": 9.6, "start_soc": 28.0, "end_soc": 74.0}
    _ = math

  ev_data.ChargeSession.__init__ = init


def _seed_history():
  """An hour of plausible drive-then-charge history so the Statistics graph has something to show."""
  import math
  import time
  from bluepilot.ui.lib import ev_history
  orig = ev_history.EvHistory.__init__

  def init(self, *a, **kw):
    orig(self, *a, **kw)
    now = time.monotonic()
    n = int(3600 * ev_history.FINE_HZ)
    for i in range(n):
      t = now - 3600 + i / ev_history.FINE_HZ
      m = i / n
      driving = m < 0.55
      soc = 48 - 18 * m / 0.55 if driving else 30 + 32 * (m - 0.55) / 0.45
      power = (35 + 25 * math.sin(i / 37.0) + 12 * math.sin(i / 7.0)) if driving else -(148 - 40 * (m - 0.55))
      vals = {"ev.soc": soc, "ev.power_kw": power, "ev.pack_temp_c": 24 + 9 * m, "ev.voltage": 372 + soc * 0.3,
              "ev.current_a": power * 1000 / 380, "ev.coolant_temp_c": 22 + 4 * m, "ev.range_km": soc / 100 * 131000 / 300,
              "ev.lv_volts": 12.6 + (0.9 if not driving else 1.6), "ev.outside_temp_c": 14.0, "ev.charging": 0.0 if driving else 1.0,
              "ev.charge_power_kw": math.nan if driving else -power, "ev.motor_torque_nm": 180 + 140 * math.sin(i / 23.0) if driving else 0.0,
              "ev.tire_kpa.0": 38.0, "ev.tire_kpa.1": 38.0, "ev.tire_kpa.2": 37.0, "ev.tire_kpa.3": 37.5}
      self.push(vals, t)
    self._next_fine = 0.0

  ev_history.EvHistory.__init__ = init


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
  ap.add_argument("--sim-scale", type=float, default=1.0,
                  help="capture what a PC simulator window at this SCALE shows (e.g. 0.84 on a 1080p laptop)")
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
