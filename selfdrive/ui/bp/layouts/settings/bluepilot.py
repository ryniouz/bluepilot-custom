import pyray as rl

from openpilot.common.params import Params
from openpilot.common.params_pyx import UnknownKeyName
from openpilot.common.swaglog import cloudlog
from openpilot.system.ui.widgets import Widget, DialogResult
from openpilot.system.ui.widgets.confirm_dialog import ConfirmDialog
from openpilot.system.ui.widgets.list_view import toggle_item, multiple_button_item, button_item, text_item, ButtonAction, ListItem
from openpilot.system.ui.widgets.scroller_tici import Scroller
from openpilot.system.ui.widgets.option_dialog import MultiOptionDialog
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.wifi_manager import WifiManager, Network
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.bp.widgets.float_control_item import float_control_item
from openpilot.selfdrive.ui.bp.widgets.section_header import SectionHeader
from bluepilot.ui.lib.theme import ACCENT_NAMES, ACCENT_LABELS, MODE_NAMES, MODE_LABELS, set_accent  # Custom: Console theme
from bluepilot.ui.lib.layout_presets import PRESET_LABELS, PRESET_DESCRIPTIONS  # Custom: Console theme
from bluepilot.ui.lib.ui_scale import LABELS as SCALE_LABELS, set_scale_index  # Custom: Console UI size


class BluePilotLayout(Widget):
  """BluePilot settings layout for TICI UI."""

  @staticmethod
  def _safe_get_bool(params: Params, key: str, default: bool = False) -> bool:
    """Get bool param; return default if key is unknown (e.g. dev environment with reduced params)."""
    try:
      return params.get_bool(key)
    except UnknownKeyName:
      return default

  @staticmethod
  def _safe_get(params: Params, key: str, default=None):
    """Get param; return default if key is unknown (e.g. dev environment with reduced params)."""
    try:
      val = params.get(key, return_default=True)
      return val if val not in (None, b"", "") else default
    except UnknownKeyName:
      return default

  def __init__(self):
    super().__init__()
    self._params = Params()

    # Create WifiManager instance for preferred network selector
    self._wifi_manager = WifiManager()
    self._wifi_manager.set_active(False)  # Don't scan unless needed
    self._saved_networks: list[Network] = []
    self._preferred_network_dialog: MultiOptionDialog | None = None

    # Register callback to update saved networks list
    self._wifi_manager.add_callbacks(networks_updated=self._on_network_updated)

    # Initialize items
    items = self._initialize_items()
    self._scroller = Scroller(items, line_separator=True, spacing=0)

    # Toggle refresh list
    self._refresh_toggles = (
      ("send_hands_free_cluster_msg", self._show_hands_free_ui),
      ("ShowBlindspotOverlay", self._show_blindspot),
      ("ShowBrakeStatus", self._show_brake_status),
      ("BPHideOnroadBorder", self._hide_onroad_border),
      ("BPShowConfidenceBall", self._show_confidence_ball),
      ("BPAnimateSteeringWheel", self._animate_steering_wheel),
      ("FordPrefShowRadarLeadOverlay", self._show_ford_radar_overlay),
      ("FordPrefHybridBatteryStatus", self._show_hybrid_battery_status),
      ("FordPrefHybridPowerFlow", self._show_hybrid_power_flow),
      ("enable_human_turn_detection", self._enable_human_turn_detection),
      ("BlinkerPauseLaneChange", self._disable_lane_change_under_speed),
      ("enable_lane_positioning", self._enable_lane_positioning),
      ("enable_lane_full_mode", self._enable_lane_full_mode),
      ("custom_profile", self._custom_profile),
      ("disable_BP_lat_UI", self._disable_BP_lat),
      ("disable_BP_long_UI", self._disable_BP_long),
      ("disable_downhill_comp_UI", self._disable_dowhill_comp),
      ("BPUIDebugLog", self._ui_debug_log),
      ("BPEvHud", self._ev_hud),
      ("BPChargingScreen", self._charging_screen),
      ("BPBridgeEnabled", self._bridge_enabled),
      ("BPKeepUntilSynced", self._keep_until_synced),
    )

    ui_state.add_offroad_transition_callback(self._update_toggles)

  def _initialize_items(self):
    """Initialize all BluePilot menu items."""

    # BlueCruise icon on dash toggle
    self._show_hands_free_ui = toggle_item(
      lambda: tr("Show BlueCruise Icon on Dash"),
      lambda: tr("Display BlueCruise icon in the gauge cluster for supported vehicles."),
      initial_state=self._safe_get_bool(self._params, "send_hands_free_cluster_msg"),
      callback=lambda state: self._toggle_callback(state, "send_hands_free_cluster_msg"),
      icon="monitoring.png"
    )

    # Blindspot overlay toggle (BluePilot red edge overlay; SunnyPilot BSM is controlled by Visuals → BlindSpot)
    self._show_blindspot = toggle_item(
      lambda: tr("Show Blindspot Overlay"),
      lambda: tr("Display red overlay when vehicle is detected in blindspot."),
      initial_state=self._safe_get_bool(self._params, "ShowBlindspotOverlay"),
      callback=lambda state: self._toggle_callback(state, "ShowBlindspotOverlay"),
      icon="warning.png"
    )

    # Brake status toggle
    self._show_brake_status = toggle_item(
      lambda: tr("Show Brake Status"),
      lambda: tr("Display speed setpoint in red when vehicle is braking."),
      initial_state=self._safe_get_bool(self._params, "ShowBrakeStatus"),
      callback=lambda state: self._toggle_callback(state, "ShowBrakeStatus"),
      icon="warning.png"
    )

    # Hide onroad border toggle
    self._hide_onroad_border = toggle_item(
      lambda: tr("Hide Onroad Border"),
      lambda: tr("Hide the colored status border around the driving view."),
      initial_state=self._safe_get_bool(self._params, "BPHideOnroadBorder"),
      callback=lambda state: self._toggle_callback(state, "BPHideOnroadBorder"),
      icon="warning.png"
    )

    # Show confidence ball toggle
    self._show_confidence_ball = toggle_item(
      lambda: tr("Show Confidence Ball"),
      lambda: tr("Display the confidence ball on the left side of the driving view."),
      initial_state=self._safe_get_bool(self._params, "BPShowConfidenceBall"),
      callback=lambda state: self._toggle_callback(state, "BPShowConfidenceBall"),
      icon="warning.png"
    )

    # Animate steering wheel toggle
    self._animate_steering_wheel = toggle_item(
      lambda: tr("Animate Steering Wheel"),
      lambda: tr("Rotate the steering wheel icon to match the current steering angle."),
      initial_state=self._safe_get_bool(self._params, "BPAnimateSteeringWheel"),
      callback=lambda state: self._toggle_callback(state, "BPAnimateSteeringWheel"),
      icon="chffr_wheel.png"
    )

    # Ford radar lead overlay toggle
    self._show_ford_radar_overlay = toggle_item(
      lambda: tr("Show Radar Lead Overlay (Ford ACC)"),
      lambda: tr("Display chevron with lead vehicle info when using Ford stock ACC."),
      initial_state=self._safe_get_bool(self._params, "FordPrefShowRadarLeadOverlay"),
      callback=lambda state: self._toggle_callback(state, "FordPrefShowRadarLeadOverlay"),
      icon="speed_limit.png"
    )

    # Ford radar overlay size selector (inline buttons like Driving Personality)
    try:
      overlay_size_idx = int(self._safe_get(self._params, "FordPrefRadarOverlaySize") or 1)
    except (TypeError, ValueError):
      overlay_size_idx = 1
    # Ensure default is persisted so consumers read the correct value on first load
    try:
      if self._safe_get(self._params, "FordPrefRadarOverlaySize") is None:
        self._params.put("FordPrefRadarOverlaySize", str(overlay_size_idx))
    except UnknownKeyName:
      pass
    self._radar_overlay_size_btn = multiple_button_item(
      lambda: tr("Radar Overlay Size"),
      lambda: tr("Set the size of the radar lead overlay chevron and info boxes."),
      buttons=[lambda: tr("Small"), lambda: tr("Medium"), lambda: tr("Large")],
      button_width=225,
      callback=self._set_overlay_size,
      selected_index=overlay_size_idx,
      icon="speed_limit.png"
    )

    # Hybrid battery status toggle
    self._show_hybrid_battery_status = toggle_item(
      lambda: tr("Battery gauge"),
      lambda: tr("Battery charge, voltage and current while driving."),
      initial_state=self._safe_get_bool(self._params, "FordPrefHybridBatteryStatus"),
      callback=lambda state: self._toggle_callback(state, "FordPrefHybridBatteryStatus"),
      icon="warning.png"
    )

    # Hybrid power flow toggle
    self._show_hybrid_power_flow = toggle_item(
      lambda: tr("Power flow gauge"),
      lambda: tr("Power to the motors and regen back to the battery."),
      initial_state=self._safe_get_bool(self._params, "FordPrefHybridPowerFlow"),
      callback=lambda state: self._toggle_callback(state, "FordPrefHybridPowerFlow"),
      icon="warning.png"
    )

    # Hybrid drive gauge size selector (inline buttons: Small=1, Large=2)
    try:
      gauge_size_idx = int(self._safe_get(self._params, "FordPrefHybridDriveGaugeSize") or 1)
    except (TypeError, ValueError):
      gauge_size_idx = 1
    # Clamp old 3-tier values to new 2-tier range
    gauge_size_idx = min(gauge_size_idx, 2)
    # Ensure default is persisted so consumers read the correct value on first load
    try:
      if self._safe_get(self._params, "FordPrefHybridDriveGaugeSize") is None:
        self._params.put("FordPrefHybridDriveGaugeSize", str(gauge_size_idx))
    except UnknownKeyName:
      pass
    # Map 1/2 to button index 0/1
    self._hybrid_gauge_size_btn = multiple_button_item(
      lambda: tr("Battery and power flow size"),
      lambda: tr("Set the size of the battery and power flow gauges."),
      buttons=[lambda: tr("Small"), lambda: tr("Large")],
      button_width=225,
      callback=self._set_hybrid_gauge_size,
      selected_index=gauge_size_idx - 1,
      icon="warning.png"
    )

    # Hybrid gauge style: Flat (horizontal bar + container) vs Arched (arch above torque bar)
    gauge_style_raw = self._safe_get(self._params, "FordPrefHybridGaugeStyle") or b"flat"
    gauge_style_str = (gauge_style_raw.decode("utf-8", errors="replace").strip("\x00").lower()
                       if isinstance(gauge_style_raw, bytes) else str(gauge_style_raw).strip().lower())
    gauge_style_idx = 1 if gauge_style_str == "arched" else 0
    try:
      if gauge_style_str not in ("flat", "arched"):
        self._params.put("FordPrefHybridGaugeStyle", "flat")
    except UnknownKeyName:
      pass
    self._hybrid_gauge_style_btn = multiple_button_item(
      lambda: tr("Battery and power flow style"),
      lambda: tr("Flat: horizontal bar in shared container. Arched: arch above torque bar (older style)."),
      buttons=[lambda: tr("Flat"), lambda: tr("Arched")],
      button_width=225,
      callback=self._set_hybrid_gauge_style,
      selected_index=gauge_style_idx,
      icon="warning.png"
    )

    # Human turn detection toggle
    self._enable_human_turn_detection = toggle_item(
      lambda: tr("Enable Human Turn Detection"),
      lambda: tr("Enable detection of human-initiated turns."),
      initial_state=self._safe_get_bool(self._params, "enable_human_turn_detection"),
      callback=lambda state: self._toggle_callback(state, "enable_human_turn_detection"),
      icon="warning.png"
    )

    # Lane change factor high (float)
    self._lane_change_factor_high = float_control_item(
      lambda: tr("Lane Change Factor High"),
      lambda: tr("Adjust the high-speed lane change factor (0.5-1.0)."),
      param="lane_change_factor_high",
      min_value=0.5,
      max_value=1.0,
      step=0.05,
      icon="speed_limit.png"
    )

    # Disable lane change under speed toggle (BlinkerPauseLaneChange)
    self._disable_lane_change_under_speed = toggle_item(
      lambda: tr("Disable Lane Change Under Speed"),
      lambda: tr("Pause lateral control when blinker is on and below minimum speed."),
      initial_state=self._safe_get_bool(self._params, "BlinkerPauseLaneChange"),
      callback=lambda state: self._toggle_callback(state, "BlinkerPauseLaneChange"),
      icon="chffr_wheel.png"
    )

    # Enable lane positioning toggle
    self._enable_lane_positioning = toggle_item(
      lambda: tr("Enable Lane Positioning"),
      lambda: tr("Enable custom lane positioning controls."),
      initial_state=self._safe_get_bool(self._params, "enable_lane_positioning"),
      callback=lambda state: self._toggle_callback(state, "enable_lane_positioning"),
      icon="chffr_wheel.png"
    )

    # Custom path offset (float, conditional on lane positioning)
    self._custom_path_offset = float_control_item(
      lambda: tr("In-Lane Offset"),
      lambda: tr("Adjust the in-lane offset (-0.5 to 0.5)."),
      param="custom_path_offset",
      min_value=-0.5,
      max_value=0.5,
      step=0.05,
      enabled=lambda: self._safe_get_bool(self._params, "enable_lane_positioning"),
      icon="chffr_wheel.png"
    )

    # Enable lanefull mode toggle (conditional on lane positioning)
    self._enable_lane_full_mode = toggle_item(
      lambda: tr("Enable Lanefull Mode"),
      lambda: tr("Enable lanefull mode for lane positioning."),
      initial_state=self._safe_get_bool(self._params, "enable_lane_full_mode"),
      callback=lambda state: self._toggle_callback(state, "enable_lane_full_mode"),
      enabled=lambda: self._safe_get_bool(self._params, "enable_lane_positioning"),
      icon="chffr_wheel.png"
    )

    # Custom profile toggle
    self._custom_profile = toggle_item(
      lambda: tr("Use Custom Tuning Profile"),
      lambda: tr("Enable custom tuning profile settings."),
      initial_state=self._safe_get_bool(self._params, "custom_profile"),
      callback=lambda state: self._toggle_callback(state, "custom_profile"),
      icon="chffr_wheel.png"
    )

    # Predicted curvature blend ratio high (float, conditional on custom profile)
    self._pc_blend_ratio_high_C = float_control_item(
      lambda: tr("Predicted Curvature Blend Ratio High"),
      lambda: tr("Adjust the high curvature blend ratio (0.0-1.0)."),
      param="pc_blend_ratio_high_C_UI",
      min_value=0.0,
      max_value=1.0,
      step=0.05,
      enabled=lambda: self._safe_get_bool(self._params, "custom_profile"),
      icon="chffr_wheel.png"
    )

    # Predicted curvature blend ratio low (float, conditional on custom profile)
    self._pc_blend_ratio_low_C = float_control_item(
      lambda: tr("Predicted Curvature Blend Ratio Low"),
      lambda: tr("Adjust the low curvature blend ratio (0.0-1.0)."),
      param="pc_blend_ratio_low_C_UI",
      min_value=0.0,
      max_value=1.0,
      step=0.05,
      enabled=lambda: self._safe_get_bool(self._params, "custom_profile"),
      icon="chffr_wheel.png"
    )

    # Low curvature PID gain (float, conditional on custom profile)
    self._lc_pid_gain = float_control_item(
      lambda: tr("Low Curvature PID Gain"),
      lambda: tr("Adjust the low curvature PID gain (0.0-5.0)."),
      param="LC_PID_gain_UI",
      min_value=0.0,
      max_value=5.0,
      step=0.1,
      enabled=lambda: self._safe_get_bool(self._params, "custom_profile"),
      icon="chffr_wheel.png"
    )

    # 12V battery limit (float)
    self._vbatt_pause_charging = float_control_item(
      lambda: tr("12V Battery Limit"),
      lambda: tr("Set the 12V battery charging pause limit (11.0-14.0V)."),
      param="vbatt_pause_charging",
      min_value=11.0,
      max_value=14.0,
      step=0.1,
      suffix="V",
      icon="warning.png"
    )

    # UI Debug Logging toggle
    self._ui_debug_log = toggle_item(
      lambda: tr("UI Debug Logging"),
      lambda: tr("Log UI state transitions for diagnosing rendering issues on device."),
      initial_state=self._safe_get_bool(self._params, "BPUIDebugLog"),
      callback=lambda state: self._toggle_callback(state, "BPUIDebugLog"),
      icon="warning.png"
    )

    # Disable BP lateral control toggle
    self._disable_BP_lat = toggle_item(
      lambda: tr("Disable BP Lateral Control"),
      lambda: tr("Disable BluePilot lateral control."),
      initial_state=self._safe_get_bool(self._params, "disable_BP_lat_UI"),
      callback=lambda state: self._toggle_callback(state, "disable_BP_lat_UI"),
      icon="chffr_wheel.png"
    )

    # Bypass BP longitudinal control toggle (use stock long logic)
    self._disable_BP_long = toggle_item(
      lambda: tr("Bypass BP Longitudinal Control"),
      lambda: tr("Use stock longitudinal logic instead of BluePilot TTC/coasting tuning."),
      initial_state=self._safe_get_bool(self._params, "disable_BP_long_UI"),
      callback=lambda state: self._toggle_callback(state, "disable_BP_long_UI"),
      icon="chffr_wheel.png"
    )

    # Disable downhill compensation toggle
    self._disable_dowhill_comp = toggle_item(
      lambda: tr("Disable Downhill Compensation"),
      lambda: tr("Disable pitch-based brake/gas compensation when going downhill."),
      initial_state=self._safe_get_bool(self._params, "disable_downhill_comp_UI"),
      callback=lambda state: self._toggle_callback(state, "disable_downhill_comp_UI"),
      icon="chffr_wheel.png"
    )

    # Preferred WiFi Network selector
    self._preferred_network_action = ButtonAction(lambda: tr("SELECT"))
    self._preferred_network_action.set_value(lambda: self._get_preferred_network_display())
    self._preferred_network_btn = ListItem(
      lambda: tr("Preferred WiFi Network"),
      description=lambda: tr("Automatically connect to this network when available"),
      action_item=self._preferred_network_action,
      callback=self._select_preferred_network
    )

    # Clear model runner cache (ModelRunnerTypeCache + ModelManager_ActiveBundle) and reboot
    self._clear_model_cache_btn = button_item(
      lambda: tr("Clear Crashed Model"),
      lambda: tr("CLEAR"),
      lambda: tr("Clear crashed model runner cache and reboot. Fixes 'Communication Issue' if modeld fails to start."),
      callback=self._clear_model_cache
    )

    # Custom: Console theme settings
    accent = str(self._safe_get(self._params, "BPConsoleAccent", "blue") or "blue")
    if isinstance(accent, bytes):
      accent = accent.decode("utf-8", errors="ignore")
    accent_idx = ACCENT_NAMES.index(accent) if accent in ACCENT_NAMES else 0
    mode = str(self._safe_get(self._params, "BPConsoleMode", "auto") or "auto")
    if isinstance(mode, bytes):
      mode = mode.decode("utf-8", errors="ignore")
    self._console_mode_btn = multiple_button_item(
      lambda: tr("Theme"),
      lambda: tr("Day uses the light Console palette, Night the dark one. Auto follows the light level while driving and the time of day when parked."),
      buttons=[lambda n=n: tr(n) for n in MODE_LABELS],
      button_width=200,
      callback=self._set_console_mode,
      selected_index=MODE_NAMES.index(mode) if mode in MODE_NAMES else 0,
      icon="settings.png"
    )
    self._console_scale_btn = multiple_button_item(
      lambda: tr("UI size"),
      lambda: tr("Size of text, icons and buttons on the settings and home screens. The driving view keeps its own layout."),
      buttons=[lambda n=n: tr(n) for n in SCALE_LABELS],
      button_width=230,
      callback=self._set_console_scale,
      selected_index=self._console_scale_idx(),
      icon="settings.png"
    )
    self._console_accent_btn = multiple_button_item(
      lambda: tr("Accent"),
      lambda: tr("Console accent colour for buttons, selections and the driving path. Status colours never change."),
      buttons=[lambda n=n: tr(n) for n in ACCENT_LABELS],
      button_width=200,
      callback=self._set_console_accent,
      selected_index=accent_idx,
      icon="settings.png"
    )
    try:
      preset_idx = int(self._safe_get(self._params, "BPLayoutPreset", 1))
    except (TypeError, ValueError):
      preset_idx = 1
    self._layout_preset_btn = multiple_button_item(
      lambda: tr("Driving layout"),
      lambda: tr(PRESET_DESCRIPTIONS[self._layout_preset_idx()]),
      buttons=[lambda n=n: tr(n) for n in PRESET_LABELS],
      button_width=225,
      callback=self._set_layout_preset,
      selected_index=max(0, min(2, preset_idx)),
      icon="monitoring.png"
    )
    self._ev_hud = toggle_item(
      lambda: tr("EV panel"),
      lambda: tr("Show battery charge, power, range and efficiency on the driving screen. Dense layout adds temperatures, limits, tires and 12 V."),
      initial_state=self._safe_get_bool(self._params, "BPEvHud", True),
      callback=lambda state: self._toggle_callback(state, "BPEvHud"),
      icon="speed_limit.png"
    )
    sleep_opts = [10, 30, 60, 0]
    try:
      sleep_min = int(self._safe_get(self._params, "BPChargeSleepMin", 30))
    except (TypeError, ValueError):
      sleep_min = 30
    self._charge_sleep_btn = multiple_button_item(
      lambda: tr("Sleep while charging"),
      lambda: tr("With the truck off and charging, keep the charging screen on this long, then turn the display off. Tap to wake it."),
      buttons=[lambda: tr("10 min"), lambda: tr("30 min"), lambda: tr("1 h"), lambda: tr("Never")],
      button_width=200,
      callback=lambda i: self._set_int_param("BPChargeSleepMin", sleep_opts[i], "charge_sleep_min"),
      selected_index=sleep_opts.index(sleep_min) if sleep_min in sleep_opts else 1,
      icon="monitoring.png"
    )
    self._charging_screen = toggle_item(
      lambda: tr("Charging screen"),
      lambda: tr("While the truck is charging and parked, show charge state, power, energy added and time to full. Tap to go back."),
      initial_state=self._safe_get_bool(self._params, "BPChargingScreen", True),
      callback=lambda state: self._toggle_callback(state, "BPChargingScreen"),
      icon="speed_limit.png"
    )

    # Custom: Data export (params from the comma-export branch; rows hide their value if the key is absent)
    self._bridge_enabled = toggle_item(
      lambda: tr("Data export for home server"),
      lambda: tr("Serve drives, GPS and a live feed to your home server over Wi-Fi. Read-only, token protected."),
      initial_state=self._safe_get_bool(self._params, "BPBridgeEnabled"),
      callback=lambda state: self._toggle_callback(state, "BPBridgeEnabled"),
      icon="network.png"
    )
    self._keep_until_synced = toggle_item(
      lambda: tr("Keep drives until synced"),
      lambda: tr("Do not let storage rotation delete drives the home server has not pulled yet."),
      initial_state=self._safe_get_bool(self._params, "BPKeepUntilSynced", True),
      callback=lambda state: self._toggle_callback(state, "BPKeepUntilSynced"),
      icon="network.png"
    )
    self._bridge_address = text_item(
      lambda: tr("Export address"),
      self._bridge_address_text,
      lambda: tr("Wi-Fi address and port the home server connects to."),
    )
    self._token_revealed = False
    self._bridge_token = button_item(
      lambda: tr("Export token"),
      self._bridge_token_text,
      lambda: tr("Tap to show or hide. Enter this token in the comma app on your home server."),
      callback=self._toggle_token,
    )

    # Build menu with sections per TICI_MENU.csv
    return [
      SectionHeader(tr("System")),
      self._preferred_network_btn,
      self._clear_model_cache_btn,
      self._ui_debug_log,
      SectionHeader(tr("Vehicle")),
      self._show_hands_free_ui,
      self._vbatt_pause_charging,
      # Custom: Console theme, charging and data export rows live on their own Console shell pages
      # (Screen > Theme and layout, Energy > Charging, Connect > Data export); see console_page_items()
      SectionHeader(tr("Visuals")),
      # Custom: no onroad border and no hybrid gauges on the Console driving view (the EV dock replaces
      # them), so their rows are left out: Hide Onroad Border, Battery/Power flow gauge, size, style
      self._show_blindspot,
      self._show_brake_status,
      self._show_confidence_ball,
      self._animate_steering_wheel,
      self._show_ford_radar_overlay,
      self._radar_overlay_size_btn,
      SectionHeader(tr("Longitudinal Tuning")),
      self._disable_BP_long,
      self._disable_dowhill_comp,
      SectionHeader(tr("Lateral Tuning")),
      self._disable_BP_lat,
      self._enable_human_turn_detection,
      self._disable_lane_change_under_speed,
      self._lane_change_factor_high,
      self._enable_lane_positioning,
      self._custom_path_offset,
      self._enable_lane_full_mode,
      self._custom_profile,
      self._pc_blend_ratio_high_C,
      self._pc_blend_ratio_low_C,
      self._lc_pid_gain,
    ]

  def _get_float_param(self, param: str, default: float) -> float:
    """Get float parameter value."""
    try:
      return float(self._params.get(param, return_default=True))
    except (TypeError, ValueError):
      return default

  def _toggle_callback(self, state: bool, param: str):
    """Handle toggle state changes."""
    try:
      self._params.put_bool(param, state)
    except UnknownKeyName:
      pass  # Param not available in dev environment
    self._update_toggles(just_toggled={param: state})

  def _update_toggles(self, just_toggled: dict | None = None):
    """Update toggle states from params. just_toggled: {param: value} for params we just wrote (avoids refresh race)."""
    ui_state.update_params()
    fresh = just_toggled or {}

    # Refresh toggles from params to mirror external changes (use fresh for params we just wrote)
    for key, item in self._refresh_toggles:
      state = fresh[key] if key in fresh else self._safe_get_bool(ui_state.params, key)
      item.action_item.set_state(state)

    # Update button enabled states
    self._radar_overlay_size_btn.action_item.set_enabled(self._safe_get_bool(ui_state.params, "FordPrefShowRadarLeadOverlay"))
    try:
      overlay_idx = int(self._safe_get(ui_state.params, "FordPrefRadarOverlaySize") or 1)
    except (TypeError, ValueError):
      overlay_idx = 1
    self._radar_overlay_size_btn.action_item.set_selected_button(overlay_idx)
    # Hybrid gauge size and style: enable only when power flow gauge is enabled (NOT battery status)
    self._hybrid_gauge_size_btn.action_item.set_enabled(
      lambda: self._safe_get_bool(ui_state.params, "FordPrefHybridPowerFlow")
    )
    self._hybrid_gauge_style_btn.action_item.set_enabled(
      lambda: self._safe_get_bool(ui_state.params, "FordPrefHybridPowerFlow")
    )
    try:
      gauge_size = int(self._safe_get(ui_state.params, "FordPrefHybridDriveGaugeSize") or 1)
    except (TypeError, ValueError):
      gauge_size = 1
    gauge_size = min(gauge_size, 2)  # Clamp old 3-tier values
    self._hybrid_gauge_size_btn.action_item.set_selected_button(gauge_size - 1)
    raw_style = self._safe_get(ui_state.params, "FordPrefHybridGaugeStyle") or b"flat"
    style_str = (raw_style.decode("utf-8", errors="replace").strip("\x00").lower()
                 if isinstance(raw_style, bytes) else str(raw_style).strip().lower())
    style_idx = 1 if style_str == "arched" else 0
    self._hybrid_gauge_style_btn.action_item.set_selected_button(style_idx)
    # Use just_toggled for params we just wrote to avoid update_params refresh race
    lane_pos = fresh.get("enable_lane_positioning") if "enable_lane_positioning" in fresh else self._safe_get_bool(ui_state.params, "enable_lane_positioning")
    custom_prof = fresh.get("custom_profile") if "custom_profile" in fresh else self._safe_get_bool(ui_state.params, "custom_profile")
    self._custom_path_offset.action_item.set_enabled(lane_pos)
    self._enable_lane_full_mode.action_item.set_enabled(lane_pos)
    self._pc_blend_ratio_high_C.action_item.set_enabled(custom_prof)
    self._pc_blend_ratio_low_C.action_item.set_enabled(custom_prof)
    self._lc_pid_gain.action_item.set_enabled(lane_pos and custom_prof)

  def show_event(self):
    super().show_event()
    self._scroller.show_event()
    self._update_toggles()
    # Enable WiFi scanning when BluePilot menu is shown
    self._wifi_manager.set_active(True)

  def hide_event(self):
    super().hide_event()
    # Disable WiFi scanning when BluePilot menu is hidden
    self._wifi_manager.set_active(False)

  def _on_network_updated(self, networks: list[Network]):
    """Update saved networks list when WiFi networks are updated"""
    self._saved_networks = [n for n in networks if self._wifi_manager.is_connection_saved(n.ssid)]
    self._preferred_network_action.set_enabled(len(self._saved_networks) > 0)

    # Check if preferred network is still saved in NetworkManager
    try:
      favorite_value = self._params.get("WifiFavoriteSSID")
      current_favorite = ""
      if favorite_value:
        if isinstance(favorite_value, bytes):
          current_favorite = favorite_value.decode('utf-8', errors='replace').strip('\x00')
        else:
          current_favorite = str(favorite_value).strip('\x00')
      if current_favorite:
        # Check NetworkManager's saved connections directly
        saved_connections = self._wifi_manager._get_connections()
        if current_favorite not in saved_connections:
          # Network is no longer saved, clear preferred setting
          self._params.put("WifiFavoriteSSID", "")
          cloudlog.info(f"Cleared preferred network '{current_favorite}' - network no longer saved in NetworkManager")
    except Exception as e:
      cloudlog.debug(f"Error checking preferred network: {e}")

  def _get_preferred_network_display(self) -> str:
    """Get the display text for preferred network"""
    try:
      favorite_value = self._params.get("WifiFavoriteSSID")
      if favorite_value:
        if isinstance(favorite_value, bytes):
          favorite_ssid = favorite_value.decode('utf-8', errors='replace').strip('\x00')
        else:
          favorite_ssid = str(favorite_value).strip('\x00')
        if favorite_ssid:
          # Truncate if too long
          if len(favorite_ssid) > 20:
            return favorite_ssid[:17] + "..."
          return favorite_ssid
    except Exception:
      pass
    return tr("None")

  def _select_preferred_network(self):
    """Open dialog to select preferred network from saved networks"""
    if len(self._saved_networks) == 0:
      return

    # Get current favorite
    current_favorite = ""
    try:
      favorite_value = self._params.get("WifiFavoriteSSID")
      if favorite_value:
        if isinstance(favorite_value, bytes):
          current_favorite = favorite_value.decode('utf-8', errors='replace').strip('\x00')
        else:
          current_favorite = str(favorite_value).strip('\x00')
    except Exception:
      pass

    # Build list of network names (add "None" option first)
    network_options = [tr("None")]
    network_options.extend([n.ssid for n in self._saved_networks])

    def handle_selection(result):
      """Handle selection from dialog"""
      if result == DialogResult.CONFIRM and self._preferred_network_dialog is not None:
        selection = self._preferred_network_dialog.selection
        # Convert "None" back to empty string
        if selection == tr("None"):
          selection = ""

        # Save the selection
        self._params.put("WifiFavoriteSSID", selection)
        if selection:
          cloudlog.info(f"Set preferred network: {selection}")
        else:
          cloudlog.info("Cleared preferred network")

        # Update button value display
        self._preferred_network_action.set_value(self._get_preferred_network_display())

      self._preferred_network_dialog = None

    # Create dialog with callback; MultiOptionDialog calls pop_widget and callback internally
    self._preferred_network_dialog = MultiOptionDialog(
      tr("Select Preferred Network"),
      network_options,
      current_favorite if current_favorite else tr("None"),
      callback=handle_selection
    )
    gui_app.push_widget(self._preferred_network_dialog)

  def _clear_model_cache(self):
    """Clear ModelRunnerTypeCache and ModelManager_ActiveBundle, then reboot."""

    def handle_confirm(result: DialogResult):
      if result == DialogResult.CONFIRM:
        try:
          self._params.remove("ModelRunnerTypeCache")
        except Exception:
          pass
        try:
          self._params.remove("ModelManager_ActiveBundle")
        except Exception:
          pass
        self._params.put_bool_nonblocking("DoReboot", True)
        cloudlog.info("BluePilot: Cleared model cache (ModelRunnerTypeCache, ModelManager_ActiveBundle), triggered reboot")

    dialog = ConfirmDialog(
      tr("Clear crashed model runner cache and reboot? This fixes 'Communication Issue' when modeld fails to start."),
      tr("Clear & Reboot"),
      callback=handle_confirm
    )
    gui_app.push_widget(dialog)

  # Custom: Console theme and data export callbacks
  def _set_console_accent(self, button_index: int):
    name = ACCENT_NAMES[max(0, min(len(ACCENT_NAMES) - 1, button_index))]
    try:
      self._params.put("BPConsoleAccent", name)
    except UnknownKeyName:
      pass
    set_accent(name)

  def _set_console_mode(self, button_index: int):
    name = MODE_NAMES[button_index] if 0 <= button_index < len(MODE_NAMES) else "auto"
    try:
      self._params.put("BPConsoleMode", name)
    except UnknownKeyName:
      pass
    ui_state.console_mode_pref = name

  def _console_scale_idx(self) -> int:
    try:
      return max(0, min(2, int(self._safe_get(self._params, "BPConsoleScale", 1))))
    except (TypeError, ValueError):
      return 1

  def _set_console_scale(self, button_index: int):
    try:
      self._params.put("BPConsoleScale", int(button_index))
    except UnknownKeyName:
      pass
    set_scale_index(button_index)

  def _layout_preset_idx(self) -> int:
    try:
      return max(0, min(2, int(self._safe_get(self._params, "BPLayoutPreset", 1))))
    except (TypeError, ValueError):
      return 1

  def _set_layout_preset(self, button_index: int):
    try:
      self._params.put("BPLayoutPreset", int(button_index))
    except UnknownKeyName:
      pass
    ui_state.layout_preset = int(button_index)

  # Custom: Quick controls also set the layout preset, so the Theme page re-reads it when shown
  def console_page_refresh(self):
    self._layout_preset_btn.action_item.set_selected_button(self._layout_preset_idx())
    self._console_scale_btn.action_item.set_selected_button(self._console_scale_idx())

  # Custom: rows the Console shell shows on its own pages
  def console_page_items(self) -> dict[str, list]:
    return {
      "theme": [self._console_mode_btn, self._console_scale_btn, self._console_accent_btn, self._layout_preset_btn, self._ev_hud],
      "charging": [self._charging_screen, self._charge_sleep_btn],
      "export": [self._bridge_enabled, self._keep_until_synced, self._bridge_address, self._bridge_token],
    }

  def _set_int_param(self, key: str, value: int, ui_attr: str | None = None):
    try:
      self._params.put(key, int(value))
    except UnknownKeyName:
      pass
    if ui_attr:
      setattr(ui_state, ui_attr, int(value))

  @staticmethod
  def _local_ip() -> str:
    import socket
    try:
      with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect(("10.255.255.255", 1))  # no packet is sent; picks the outbound interface
        return sock.getsockname()[0]
    except OSError:
      return ""

  def _bridge_address_text(self) -> str:
    port = self._safe_get(self._params, "BPBridgePort", None)
    if port is None:
      return tr("Not available")
    if isinstance(port, bytes):
      port = port.decode("utf-8", errors="ignore")
    ip = self._local_ip()
    return f"{ip}:{port}" if ip else tr("No Wi-Fi")

  def _bridge_token_text(self) -> str:
    token = self._safe_get(self._params, "BPBridgeToken", None)
    if not token:
      return tr("NONE")
    if isinstance(token, bytes):
      token = token.decode("utf-8", errors="ignore")
    if self._token_revealed:
      return token if len(token) <= 16 else f"{token[:8]}…{token[-6:]}"
    return tr("SHOW")

  def _toggle_token(self):
    self._token_revealed = not self._token_revealed
  # Custom: end

  def _set_overlay_size(self, button_index: int):
    """Handle overlay size button selection."""
    self._params.put("FordPrefRadarOverlaySize", button_index)

  def _set_hybrid_gauge_size(self, button_index: int):
    """Handle hybrid gauge size button selection. Buttons are 0/1/2, param stores 1/2/3."""
    self._params.put("FordPrefHybridDriveGaugeSize", button_index + 1)

  def _set_hybrid_gauge_style(self, button_index: int):
    """Handle hybrid gauge style: 0 = Flat, 1 = Arched."""
    self._params.put("FordPrefHybridGaugeStyle", "arched" if button_index == 1 else "flat")

  def _render(self, rect):
    # Process WiFi manager callbacks
    self._wifi_manager.process_callbacks()
    self._scroller.render(rect)
