import pyray as rl
import numpy as np
import time
import threading
from collections.abc import Callable
from enum import Enum
from cereal import messaging, car, log
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.params import Params
from openpilot.common.realtime import drop_realtime
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.ui.lib.prime_state import PrimeState
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.hardware import HARDWARE, PC

from openpilot.common.bluepilot import is_bluepilot
from openpilot.selfdrive.ui.sunnypilot.ui_state import UIStateSP, DeviceSP
from bluepilot.ui.lib.theme import set_accent as set_console_accent, set_mode as set_console_mode, freeze_derived  # Custom: Console theme
from bluepilot.ui.lib.ev_data import EvDataSource, ChargeSession  # Custom: EV panel and charging screen
from bluepilot.ui.lib.charge_screen import ChargePolicy, DIM, DIM_BRIGHTNESS, OFF, ON  # Custom: charging screen timeouts
from bluepilot.ui.lib.ev_history import EvHistory  # Custom: Statistics page and Home chart history
from cereal.services import SERVICE_LIST  # Custom: offroad charging reader (Lightning stream, PR #2)
CHARGING_SERVICES = ["chargingStateBP"] if "chargingStateBP" in SERVICE_LIST else []  # Custom

BACKLIGHT_OFFROAD = 65 if HARDWARE.get_device_type() == "mici" else 50
PARAM_UPDATE_TIME = 1 / 5.0


class UIStatus(Enum):
  DISENGAGED = "disengaged"
  ENGAGED = "engaged"
  OVERRIDE = "override"
  LAT_ONLY = "lat_only"
  LONG_ONLY = "long_only"


class UIState(UIStateSP):
  _instance: 'UIState | None' = None

  def __new__(cls):
    if cls._instance is None:
      cls._instance = super().__new__(cls)
      cls._instance._initialize()
    return cls._instance

  def _initialize(self):
    UIStateSP.__init__(self)
    self.params = Params()
    self.sm = messaging.SubMaster(
      [
        "modelV2",
        "controlsState",
        "onroadEvents",
        "liveCalibration",
        "radarState",
        "deviceState",
        "pandaStates",
        "carParams",
        "driverMonitoringState",
        "carState",
        "driverStateV2",
        "roadCameraState",
        "wideRoadCameraState",
        "managerState",
        "selfdriveState",
        "longitudinalPlan",
        "gpsLocationExternal",
        "carOutput",
        "carControl",
        "liveParameters",
        "testJoystick",
        "rawAudioData",
        "peripheralState",  # Custom: 12 V reading for the Console EV HUD
      ] + CHARGING_SERVICES + self.sm_services_ext
      + (["carStateBP"] if is_bluepilot() else [])  # BluePilot: hybrid battery and drive data
    )

    self.prime_state = PrimeState()

    # UI Status tracking
    self.status: UIStatus = UIStatus.DISENGAGED
    self.started_frame: int = 0
    self.started_time: float = 0.0
    self._engaged_prev: bool = False
    self._started_prev: bool = False

    # Core state variables
    self.is_metric: bool = self.params.get_bool("IsMetric")
    self.is_release = False  # self.params.get_bool("IsReleaseBranch")
    self.always_on_dm: bool = self.params.get_bool("AlwaysOnDM")
    self.experimental_mode: bool = self.params.get_bool("ExperimentalMode")
    self.usbgpu: bool = self.params.get_bool("UsbGpuPresent")
    self.usbgpu_compiled: bool = self.params.get_bool("UsbGpuCompiled")
    self.started: bool = False
    self.ignition: bool = False
    self.recording_audio: bool = False
    self.panda_type: log.PandaState.PandaType = log.PandaState.PandaType.unknown
    self.personality: log.LongitudinalPersonality = log.LongitudinalPersonality.standard
    self.has_longitudinal_control: bool = False
    self.is_body: bool | None = None
    self.CP: car.CarParams | None = None
    self.light_sensor: float = -1.0

    self._params_thread: threading.Thread | None = None

    # Callbacks
    self._offroad_transition_callbacks: list[Callable[[], None]] = []
    self._engaged_transition_callbacks: list[Callable[[], None]] = []
    self._on_body_changed_callbacks: list[Callable[[], None]] = []

  def add_offroad_transition_callback(self, callback: Callable[[], None]):
    self._offroad_transition_callbacks.append(callback)

  def add_engaged_transition_callback(self, callback: Callable[[], None]):
    self._engaged_transition_callbacks.append(callback)

  def add_on_body_changed_callbacks(self, callback: Callable[[], None]):
    self._on_body_changed_callbacks.append(callback)

  @property
  def engaged(self) -> bool:
    return self.started and (self.sm["selfdriveState"].enabled or self.sm["selfdriveStateSP"].mads.enabled)

  def is_onroad(self) -> bool:
    return self.started

  def is_offroad(self) -> bool:
    return not self.started

  def update(self) -> None:
    self.prime_state.start()  # start thread after manager forks ui
    if self._params_thread is None:
      self._params_thread = threading.Thread(target=self._params_refresh_worker, daemon=True)
      self._params_thread.start()

    self.sm.update(0)
    self._update_state()
    self._update_status()
    device.update()
    UIStateSP.update(self)
    self._update_ev()
    self._update_console_mode()

  # Custom: Console day/night. Auto follows the road camera's light level while driving
  # (with hysteresis so tunnels and overpasses do not flip it) and the clock when parked.
  DAY_LIGHT_ON, DAY_LIGHT_OFF, MODE_HOLD_S = 70.0, 45.0, 10.0

  def _update_console_mode(self) -> None:
    freeze_derived()
    set_console_accent(getattr(self, "console_accent", "blue"))
    pref = getattr(self, "console_mode_pref", "auto")
    cur = getattr(self, "console_mode", None)
    if pref in ("day", "night"):
      target = "light" if pref == "day" else "dark"
      hold = 0.0
    else:
      target = cur or "dark"
      if self.started and self.light_sensor >= 0:
        if self.light_sensor > self.DAY_LIGHT_ON:
          target = "light"
        elif self.light_sensor < self.DAY_LIGHT_OFF:
          target = "dark"
      else:
        target = "light" if 7 <= time.localtime().tm_hour < 19 else "dark"
      hold = 0.0 if cur is None else self.MODE_HOLD_S

    now = time.monotonic()
    if target == cur:
      self._mode_pending_since = None
      return
    since = getattr(self, "_mode_pending_since", None)
    if since is None:
      self._mode_pending_since = since = now
    if now - since >= hold:
      self.console_mode = target
      self._mode_pending_since = None
      set_console_mode(target)
  # Custom: end

  # Custom: EV data shared by the EV panel and the charging screen
  def _update_ev(self) -> None:
    if not hasattr(self, "ev_source"):
      self.ev_source = EvDataSource()
      self.charge_session = ChargeSession()
      self.ev_history = EvHistory()
    self.ev = self.ev_source.update(self.sm, self.started_frame)
    self.ev_history.update(self.sm, self.ev)
    try:
      v_ego = float(self.sm["carState"].vEgo) if self.started else 0.0
    except (KeyError, AttributeError, TypeError, ValueError):
      v_ego = 0.0
    show = self.charge_session.update(self.ev, v_ego)
    self.charging_screen = show and (getattr(self, "charging_screen_enabled", True) or self.charge_session.reopened)
  # Custom: end

  def _params_refresh_worker(self):
    drop_realtime()
    while True:
      self.update_params()
      time.sleep(PARAM_UPDATE_TIME)

  def _update_state(self) -> None:
    # Handle panda states updates
    if self.sm.updated["pandaStates"]:
      panda_states = self.sm["pandaStates"]

      if len(panda_states) > 0:
        # Get panda type from first panda
        self.panda_type = panda_states[0].pandaType
        # Check ignition status across all pandas
        if self.panda_type != log.PandaState.PandaType.unknown:
          self.ignition = any(state.ignitionLine or state.ignitionCan for state in panda_states)
    elif self.sm.frame - self.sm.recv_frame["pandaStates"] > 5 * rl.get_fps():
      self.panda_type = log.PandaState.PandaType.unknown

    # Handle wide road camera state updates
    if self.sm.updated["wideRoadCameraState"]:
      cam_state = self.sm["wideRoadCameraState"]
      self.light_sensor = max(100.0 - cam_state.exposureValPercent, 0.0)
    elif not self.sm.alive["wideRoadCameraState"] or not self.sm.valid["wideRoadCameraState"]:
      self.light_sensor = -1

    # Update started state
    self.started = self.sm["deviceState"].started and self.ignition

    # Update body state
    if self.CP is not None and self.is_body != self.CP.notCar:
      self.is_body = self.CP.notCar
      for callback in self._on_body_changed_callbacks:
        callback()

  def _update_status(self) -> None:
    if self.started and self.sm.updated["selfdriveState"]:
      ss = self.sm["selfdriveState"]
      state = ss.state

      if state in (log.SelfdriveState.OpenpilotState.preEnabled, log.SelfdriveState.OpenpilotState.overriding):
        self.status = UIStatus.OVERRIDE
      else:
        self.status = UIStatus.ENGAGED if ss.enabled else UIStatus.DISENGAGED

      self.status = UIStatus(UIStateSP.update_status(ss, self.sm["selfdriveStateSP"], self.sm["onroadEvents"]))

    # Check for engagement state changes
    if self.engaged != self._engaged_prev:
      for callback in self._engaged_transition_callbacks:
        callback()
      self._engaged_prev = self.engaged

    # Handle onroad/offroad transition
    if self.started != self._started_prev or self.sm.frame == 1:
      if self.started:
        self.status = UIStatus.DISENGAGED
        self.started_frame = self.sm.frame
        self.started_time = time.monotonic()

      for callback in self._offroad_transition_callbacks:
        callback()

      self._started_prev = self.started

  def update_params(self) -> None:
    # For slower operations
    # Update longitudinal control state
    CP_bytes = self.params.get("CarParamsPersistent")
    if CP_bytes is not None:
      self.CP = messaging.log_from_bytes(CP_bytes, car.CarParams)
      if self.CP.alphaLongitudinalAvailable:
        self.has_longitudinal_control = self.params.get_bool("AlphaLongitudinalEnabled")
      else:
        self.has_longitudinal_control = self.CP.openpilotLongitudinalControl

    self.recording_audio = self.params.get_bool("RecordAudio") and self.started
    self.is_metric = self.params.get_bool("IsMetric")
    self.always_on_dm = self.params.get_bool("AlwaysOnDM")
    self.experimental_mode = self.params.get_bool("ExperimentalMode")
    self.usbgpu = self.params.get_bool("UsbGpuPresent")
    self.usbgpu_compiled = self.params.get_bool("UsbGpuCompiled")

    UIStateSP.update_params(self)
    # Custom: Console theme params (accent, layout preset, EV HUD). 7.0 refreshes params on a
    # background thread, so the accent is only stored here and applied on the UI thread in
    # _update_console_mode (theme tokens are rewritten in place).
    accent = self.params.get("BPConsoleAccent", return_default=True) or "blue"
    if isinstance(accent, bytes):
      accent = accent.decode("utf-8", errors="ignore")
    self.console_accent = str(accent)
    mode_pref = self.params.get("BPConsoleMode", return_default=True) or "auto"
    if isinstance(mode_pref, bytes):
      mode_pref = mode_pref.decode("utf-8", errors="ignore")
    self.console_mode_pref = str(mode_pref).strip().lower()
    try:
      preset = self.params.get("BPLayoutPreset", return_default=True)  # 0 (Minimal) is a valid value
      self.layout_preset = int(preset) if preset is not None else 1
    except (TypeError, ValueError):
      self.layout_preset = 1
    self.ev_hud = bool(self.params.get("BPEvHud", return_default=True))
    self.charging_screen_enabled = bool(self.params.get("BPChargingScreen", return_default=True))
    try:
      self.charge_sleep_min = int(self.params.get("BPChargeSleepMin", return_default=True) or 0)
    except (TypeError, ValueError):
      self.charge_sleep_min = 30
    self.charge_policy = ChargePolicy.from_params(self.params)
    # Custom: end


class Device(DeviceSP):
  def __init__(self):
    DeviceSP.__init__(self)
    self._ignition = False
    self._interaction_time: float = -1
    self._override_interactive_timeout: int | None = None
    self._interactive_timeout_callbacks: list[Callable] = []
    self._prev_timed_out = False
    self._awake: bool = True

    self._offroad_brightness: int = BACKLIGHT_OFFROAD
    self._last_brightness: int = 0
    self._brightness_filter = FirstOrderFilter(BACKLIGHT_OFFROAD, 10.00, 1 / gui_app.target_fps)
    self._brightness_thread: threading.Thread | None = None
    self._brightness_event = threading.Event()
    self._brightness_target: int = 0

  @property
  def awake(self) -> bool:
    return self._awake

  def set_override_interactive_timeout(self, timeout: int | None) -> None:
    # Override the interactive timeout duration temporarily
    self._override_interactive_timeout = timeout
    self._reset_interactive_timeout()

  @property
  def interactive_timeout(self) -> int:
    if self._override_interactive_timeout is not None:
      return self._override_interactive_timeout

    if gui_app.sunnypilot_ui() and ui_state.custom_interactive_timeout != 0:
      return ui_state.custom_interactive_timeout

    ignition_timeout = 10 if gui_app.big_ui() else 5
    return ignition_timeout if ui_state.ignition else 30

  def _reset_interactive_timeout(self) -> None:
    self._interaction_time = time.monotonic() + self.interactive_timeout

  def add_interactive_timeout_callback(self, callback: Callable):
    self._interactive_timeout_callbacks.append(callback)

  def update(self):
    self._start_brightness_thread()  # start thread after manager forks ui

    # do initial reset
    if self._interaction_time <= 0:
      self._reset_interactive_timeout()

    self._update_brightness()
    self._update_wakefulness()

  def _start_brightness_thread(self):
    if self._brightness_thread is None or not self._brightness_thread.is_alive():
      self._brightness_thread = threading.Thread(target=self._brightness_worker, daemon=True)
      self._brightness_thread.start()

  def _brightness_worker(self):
    drop_realtime()
    while True:
      self._brightness_event.wait()
      self._brightness_event.clear()
      HARDWARE.set_screen_brightness(self._brightness_target)

  def set_offroad_brightness(self, brightness: int | None):
    if brightness is None:
      brightness = BACKLIGHT_OFFROAD
    self._offroad_brightness = min(max(brightness, 0), 100)

  def _update_brightness(self):
    clipped_brightness = self._offroad_brightness

    if ui_state.started and ui_state.light_sensor >= 0:
      clipped_brightness = ui_state.light_sensor

      # CIE 1931 - https://www.photonstophotos.net/GeneralTopics/Exposure/Psychometric_Lightness_and_Gamma.htm
      if clipped_brightness <= 8:
        clipped_brightness = clipped_brightness / 903.3
      else:
        clipped_brightness = ((clipped_brightness + 16.0) / 116.0) ** 3.0

      min_brightness = 30
      if gui_app.sunnypilot_ui():
        min_brightness = DeviceSP.set_min_onroad_brightness(ui_state, min_brightness)

      clipped_brightness = float(np.interp(clipped_brightness, [0, 1], [min_brightness, 100]))

    brightness = round(self._brightness_filter.update(clipped_brightness))

    if gui_app.sunnypilot_ui():
      brightness = DeviceSP.set_onroad_brightness(ui_state, self._awake, brightness)

    if not self._awake:
      brightness = 0
    elif getattr(ui_state, "charge_screen_mode", ON) == DIM:  # Custom: charging screen dimmed after its window
      brightness = min(brightness, DIM_BRIGHTNESS)

    if brightness != self._last_brightness:
      self._brightness_target = brightness
      self._brightness_event.set()
      self._last_brightness = brightness

  def _update_wakefulness(self):
    # Handle interactive timeout
    ignition_just_turned_off = not ui_state.ignition and self._ignition
    self._ignition = ui_state.ignition

    touched = any(ev.left_down for ev in gui_app.mouse_events)
    if touched:
      self._last_touch_t = time.monotonic()  # Custom: restarts the charging screen's window
    if ignition_just_turned_off or touched:
      if gui_app.sunnypilot_ui():
        DeviceSP.wake_from_dimmed_onroad_brightness(ui_state, gui_app.mouse_events)

      self._reset_interactive_timeout()

    interaction_timeout = time.monotonic() > self._interaction_time
    if interaction_timeout and not self._prev_timed_out:
      for callback in self._interactive_timeout_callbacks:
        callback()
    self._prev_timed_out = interaction_timeout

    # Custom: the charging screen's window (Energy > Charging settings): full brightness for its minutes from
    # plug-in or the last tap, then dimmed or off. Truck off: stays awake through the window, unlike offroad.
    # Truck on: may turn the display off, but only while the charging screen is up, i.e. plugged in and stopped.
    charging_awake, charge_off = False, False
    mode = ON
    session = getattr(ui_state, "charge_session", None)
    if getattr(ui_state, "charging_screen", False) and session is not None and session.active:
      policy = getattr(ui_state, "charge_policy", None) or ChargePolicy()
      since = max(getattr(session, "window_t", 0.0), getattr(self, "_last_touch_t", 0.0))
      mode = policy.mode(ui_state.ignition, getattr(ui_state.ev, "charge_type", 0) == 2, time.monotonic() - since)
      if mode != ON and touched:
        gui_app.mouse_events.clear()  # the tap that wakes the screen does not also minimize it
        self._last_touch_t = time.monotonic()
        mode = ON
      charging_awake = not ui_state.ignition and mode != OFF
      charge_off = ui_state.ignition and mode == OFF
    ui_state.charge_screen_mode = mode
    # Custom: end
    self._set_awake((ui_state.ignition and not charge_off) or not interaction_timeout or PC or charging_awake)

  def _set_awake(self, on: bool):
    if on != self._awake:
      DeviceSP._set_awake(on, ui_state)
      self._awake = on
      cloudlog.debug(f"setting display power {int(on)}")
      HARDWARE.set_display_power(on)
      gui_app.set_should_render(on)


# Global instance
ui_state = UIState()
device = Device()
