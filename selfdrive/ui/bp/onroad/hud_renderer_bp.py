import pyray as rl
from openpilot.common.params import Params
from openpilot.selfdrive.ui.onroad.hud_renderer import UI_CONFIG, FONT_SIZES, COLORS, CRUISE_DISABLED_CHAR
from openpilot.selfdrive.ui.sunnypilot.onroad.hud_renderer import HudRendererSP
from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus
from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.lib.theme import Console, Onroad, Radius, draw_panel, roundness
from bluepilot.ui.lib.layout_presets import LayoutPreset, current_preset
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.selfdrive.ui.bp.lib.ui_debug_logger import bp_ui_log

# BluePilot: Y center for speed display (matching upstream hardcoded values)
SPEED_CENTER_Y = 180
SPEED_UNIT_CENTER_Y = 290

# Console: set-speed panel state bar
SET_SPEED_STATE_BAR_H = 8


class HudRendererBP(HudRendererSP):
  """BluePilot HudRenderer with brake status display.

  Note: Torque bar is rendered by TorqueBarRendererBP in AugmentedRoadViewBP,
  not here. This keeps the torque bar above gauges in draw order and allows
  repositioning above the battery/power flow gauges.
  """

  def __init__(self):
    super().__init__()
    self._bp_params = Params()
    self._brakes_on = False
    self.speed_right = 0
    self._gradient_rect = None  # BluePilot: Full-width rect for header gradient

  def set_gradient_rect(self, rect: rl.Rectangle):
    """Set full-width rect for header gradient (when HUD renders offset for confidence ball)."""
    self._gradient_rect = rect

  def get_speed_right(self) -> int:
    return self.speed_right

  def _update_state(self) -> None:
    super()._update_state()

    # Check brake status if enabled
    if self._bp_params.get_bool("ShowBrakeStatus"):
      sm = ui_state.sm
      if sm.valid['carStateBP']:
        try:
          car_state_bp = sm['carStateBP']
          brake_light_status = car_state_bp.brakeLightStatus
          self._brakes_on = brake_light_status.dataAvailable and brake_light_status.brakeLightsOn
        except (KeyError, AttributeError):
          self._brakes_on = False
      else:
        self._brakes_on = False
    else:
      self._brakes_on = False

    bp_ui_log.state("HudRendererBP", "brakes_on", self._brakes_on)

  def _render(self, rect: rl.Rectangle) -> None:
    preset = current_preset()

    # Console: page-ground header fade at full content width (not offset by confidence ball).
    # The one gradient Console allows: it keeps the HUD legible over a bright camera.
    gradient_rect = self._gradient_rect if self._gradient_rect else rect
    rl.draw_rectangle_gradient_v(int(gradient_rect.x), int(gradient_rect.y), int(gradient_rect.width),
                                 UI_CONFIG.header_height, COLORS.HEADER_GRADIENT_START, COLORS.HEADER_GRADIENT_END)

    # HUD elements use the (possibly offset) rect for positioning
    if self.is_cruise_available:
      self._draw_set_speed(rect)
    self._draw_current_speed(rect)

    button_x = rect.x + rect.width - UI_CONFIG.border_size - UI_CONFIG.button_size
    button_y = rect.y + UI_CONFIG.border_size
    self._exp_button.render(rl.Rectangle(button_x, button_y, UI_CONFIG.button_size, UI_CONFIG.button_size))

    # SP additions. Console layout presets decide which of the optional ones draw:
    # minimal keeps speed limit and turn signals (driving cues) and drops the rest.
    if preset != LayoutPreset.MINIMAL:
      self.developer_ui.render(rect)
      self.road_name_renderer.render(rect)
    self.speed_limit_renderer.render(rect)
    if preset != LayoutPreset.MINIMAL:
      self.smart_cruise_control_renderer.render(rect)
    self.turn_signal_controller.render(rect)
    if preset != LayoutPreset.MINIMAL:
      self.circular_alerts_renderer.render(rect)
      self.rocket_fuel.render(rect, ui_state.sm)

  def _set_speed_state_color(self, long_override: bool, sla_active: bool) -> rl.Color:
    if not self.is_cruise_set:
      return Console.BORDER_DEFAULT
    if sla_active:
      return Console.WARNING if long_override else Console.INFO
    if ui_state.status == UIStatus.ENGAGED:
      return Onroad.ENGAGED
    if ui_state.status == UIStatus.OVERRIDE:
      return Onroad.OVERRIDE
    if ui_state.status == UIStatus.LAT_ONLY:
      return Onroad.LAT_ONLY
    if ui_state.status == UIStatus.LONG_ONLY:
      return Onroad.LONG_ONLY
    return Onroad.DISENGAGED

  def _draw_set_speed(self, rect: rl.Rectangle) -> None:
    """Console set-speed panel: flat panel, squared state bar on top, caption label, 600 numeral."""
    long_plan_sp = ui_state.sm['longitudinalPlanSP']
    long_override = ui_state.sm['carControl'].cruiseControl.override
    sla_active = long_plan_sp.speedLimit.assist.active
    self._get_icbm_status()

    set_speed_width = UI_CONFIG.set_speed_width_metric if ui_state.is_metric else UI_CONFIG.set_speed_width_imperial
    x = rect.x + 60 + (UI_CONFIG.set_speed_width_imperial - set_speed_width) // 2
    y = rect.y + 45
    panel = rl.Rectangle(x, y, set_speed_width, UI_CONFIG.set_speed_height)
    draw_panel(panel, Onroad.PANEL, Radius.MD * 2)

    state_color = self._set_speed_state_color(long_override, sla_active)
    bar = rl.Rectangle(x + 20, y + 16, set_speed_width - 40, SET_SPEED_STATE_BAR_H)
    rl.draw_rectangle_rounded(bar, roundness(bar, Radius.XS), 4, state_color)

    # Label: "MAX", or the cluster speed while ICBM is adjusting
    if self.show_icbm_status:
      label, label_size, label_color = str(round(self.speed_cluster)), 52, Console.ACCENT_TEXT
    else:
      label, label_size, label_color = tr("MAX"), FONT_SIZES.max_speed, Console.TEXT_MUTED
    label_w = measure_text_cached(self._font_semi_bold, label, label_size).x
    rl.draw_text_ex(self._font_semi_bold, label, rl.Vector2(x + (set_speed_width - label_w) / 2, y + 40),
                    label_size, 0, label_color)

    set_speed_text = CRUISE_DISABLED_CHAR if not self.is_cruise_set else str(round(self.set_speed))
    value_color = Console.TEXT_PRIMARY if self.is_cruise_set else Console.TEXT_GHOST
    value_w = measure_text_cached(self._font_bold, set_speed_text, FONT_SIZES.set_speed).x
    rl.draw_text_ex(self._font_bold, set_speed_text, rl.Vector2(x + (set_speed_width - value_w) / 2, y + 92),
                    FONT_SIZES.set_speed, 0, value_color)

  def _draw_current_speed(self, rect: rl.Rectangle) -> None:
    """Override to add brake status red coloring and track speed_right."""
    # BluePilot: Respect "Speedometer: Hide from Onroad Screen" (HideVEgoUI) from Visuals.
    # Read param directly for immediate response (ui_state.hide_v_ego_ui refreshes every 5s).
    if self._bp_params.get_bool("HideVEgoUI"):
      self.speed_right = 0
      return
    speed_text = str(round(self.speed))
    speed_text_size = measure_text_cached(self._font_bold, speed_text, FONT_SIZES.current_speed)
    speed_pos = rl.Vector2(
      rect.x + rect.width / 2 - speed_text_size.x / 2,
      SPEED_CENTER_Y - speed_text_size.y / 2
    )
    self.speed_right = speed_pos.x + speed_text_size.x

    # BluePilot: Show red when braking if brake status is enabled
    speed_color = Console.DANGER if self._brakes_on else COLORS.WHITE
    rl.draw_text_ex(self._font_bold, speed_text, speed_pos, FONT_SIZES.current_speed, 0, speed_color)

    unit_text = "km/h" if ui_state.is_metric else "mph"
    unit_text_size = measure_text_cached(self._font_medium, unit_text, FONT_SIZES.speed_unit)
    unit_pos = rl.Vector2(rect.x + rect.width / 2 - unit_text_size.x / 2, SPEED_UNIT_CENTER_Y - unit_text_size.y / 2)
    # Draw drop shadow for readability over camera feed
    shadow_offset = 2
    shadow_pos = rl.Vector2(unit_pos.x + shadow_offset, unit_pos.y + shadow_offset)
    rl.draw_text_ex(self._font_medium, unit_text, shadow_pos, FONT_SIZES.speed_unit, 0, Onroad.SHADOW)
    rl.draw_text_ex(self._font_medium, unit_text, unit_pos, FONT_SIZES.speed_unit, 0, COLORS.WHITE_TRANSLUCENT)
