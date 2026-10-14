import time
import pyray as rl
from opendbc.car.structs import ControllerStateBP
from openpilot.common.params import Params
from openpilot.selfdrive.ui.onroad.hud_renderer import UI_CONFIG, CRUISE_DISABLED_CHAR
from openpilot.selfdrive.ui.onroad.exp_button import FACE_SIZE
from openpilot.selfdrive.ui.sunnypilot.onroad.hud_renderer import HudRendererSP
from openpilot.selfdrive.ui.bp.onroad.exp_button_bp import ExpButtonBP
from openpilot.selfdrive.ui.bp.onroad.road_view import road_prefs
from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus
from openpilot.sunnypilot.selfdrive.controls.lib.speed_limit.common import Mode as SpeedLimitMode
from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.console import draw as D
from bluepilot.ui.lib.theme import is_day, Console, Onroad, Radius, draw_panel, roundness
from bluepilot.ui.lib.layout_presets import LayoutPreset, current_preset
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.selfdrive.ui.bp.lib.ui_debug_logger import bp_ui_log
from openpilot.selfdrive.ui.bp.onroad.console_cues import (SIGN_H, SIGN_W, CanadianSpeedLimit, SignalTiles, TILE, cruise_chips, e2e_notice,
                                                          notice, notice_size)

# BluePilot: Y center for speed display (matching upstream hardcoded values)
SPEED_CENTER_Y = 180  # stock values, kept for importers
SPEED_UNIT_CENTER_Y = 290

# Console speed card (top-left of the driving screen)
SET_SPEED_STATE_BAR_H = 10
CLUSTER_MARGIN = 24          # from the inner edge of the status frame
CLUSTER_PAD = 28
CLUSTER_H = 252
CLUSTER_MIN_W = 300
CLUSTER_RADIUS = 24         # kit PANEL_R
CLUSTER_GAP = 16             # between top-row items
CLUSTER_LABEL = 30           # state word, MAX caption (kit CAP)
CLUSTER_SPEED = 140          # current speed numeral
CLUSTER_SPEED_BIG = 230      # ... with Road view's Large speed
CLUSTER_UNIT_BIG = 44
CLUSTER_H_BIG = 352
SIGN_IN_MAX_H = 200          # the speed limit sign inside the card
CLUSTER_UNIT = 36
CLUSTER_SET = 72             # set speed numeral
STATE_BAND_H = 58         # engagement band across the top of the speed card
CLUSTER_SET_W = 108
NOTICE_TOP = 24              # notification cards sit level with the speed card

LateralMode = ControllerStateBP.LateralMode


class HudRendererBP(HudRendererSP):
  """BluePilot HudRenderer with brake status display.

  Note: Torque bar is rendered by TorqueBarRendererBP in AugmentedRoadViewBP,
  not here. This keeps the torque bar above gauges in draw order and allows
  repositioning above the battery/power flow gauges.
  """

  def __init__(self):
    super().__init__()
    # BluePilot: Restore the animated C3X wheel without modifying the upstream ExpButton.
    self._exp_button = ExpButtonBP(UI_CONFIG.button_size, UI_CONFIG.wheel_icon_size)
    self._bp_params = Params()
    self._brakes_on = False
    self.speed_right = 0
    self._gradient_rect = None  # BluePilot: Full-width rect for header gradient

    # BluePilot: Cache params to avoid per-frame disk I/O (refresh every ~60 frames)
    self._param_counter = 0
    self._show_brake_status = self._bp_params.get_bool("ShowBrakeStatus")
    self._hide_v_ego_ui = self._bp_params.get_bool("HideVEgoUI")
    self._show_lateral_control = self._bp_params.get_bool("BpShowLateralControl")
    # BluePilot: actual mode from controllerStateBP (None = not published, e.g. non-Ford)
    self._lateral_mode = None
    self.cluster_rect = rl.Rectangle(0, 0, 0, 0)  # Custom: Console speed card, for neighbours to avoid
    # Custom: Console cues replace SP's sign art, turn-signal icons and circular pop-ups
    self.speed_limit_renderer = CanadianSpeedLimit()
    self._signals = SignalTiles()
    self._signals_shown = False
    self.guest = False             # set by the road view each frame (Guest Mode drive)
    self.attention = ""            # AttentionBar state, set by the road view each frame

  def set_gradient_rect(self, rect: rl.Rectangle):
    """Set full-width rect for header gradient (when HUD renders offset for confidence ball)."""
    self._gradient_rect = rect

  def get_speed_right(self) -> int:
    return self.speed_right

  def _update_state(self) -> None:
    super()._update_state()

    # BluePilot: Refresh cached params periodically (~1s at 20fps)
    self._param_counter += 1
    if self._param_counter >= 60:
      self._param_counter = 0
      self._show_brake_status = self._bp_params.get_bool("ShowBrakeStatus")
      self._hide_v_ego_ui = self._bp_params.get_bool("HideVEgoUI")
      self._show_lateral_control = self._bp_params.get_bool("BpShowLateralControl")

    if self._show_lateral_control:
      sm = ui_state.sm
      self._lateral_mode = sm['controllerStateBP'].activeLateralMode if sm.alive['controllerStateBP'] else None

    # Check brake status if enabled
    if self._show_brake_status:
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

  # ---------------------------------------------------------------------------------------
  # Custom: Console driving screen. One speed card top-left (state, speed, set speed), the
  # speed-limit sign beside it, the experimental button top-right. No header fade: every
  # element carries its own ground, so the camera stays clear in the middle.
  # ---------------------------------------------------------------------------------------

  def _render(self, rect: rl.Rectangle) -> None:
    preset = current_preset()

    self.cluster_rect = self._draw_cluster(rect)

    # Custom: Guest Mode drive (BPGuestModeActive): the truck's factory assist drives and the
    # comma only records, so nothing that suggests openpilot can engage is drawn
    if self.guest:
      self.speed_limit_renderer.render(self._speed_limit_anchor(rect))
      self._signals_shown = self._signals.render_center(rect.x + rect.width / 2, rect.y + NOTICE_TOP)
      title, sub = tr("Factory driver assist"), tr("comma recording only")
      band_l, band_r = self.notify_band(rect)
      w, h = notice_size(title, sub, band_r - band_l)
      notice(rl.Rectangle(band_l + (band_r - band_l - w) / 2, self.notify_top(rect), w, h), title, sub, Console.DANGER, "rec")
      return

    button_x = rect.x + rect.width - UI_CONFIG.border_size - UI_CONFIG.button_size
    button_y = rect.y + UI_CONFIG.border_size
    self._exp_button.render(rl.Rectangle(button_x, button_y, UI_CONFIG.button_size, UI_CONFIG.button_size))
    self._draw_lateral_control_overlay(button_x + UI_CONFIG.button_size / 2, button_y + UI_CONFIG.button_size / 2)

    # SP additions. Console layout presets decide which of the optional ones draw:
    # Minimal keeps speed limit and turn signals (driving cues) and drops the rest.
    if preset != LayoutPreset.MINIMAL:
      self.developer_ui.render(rect)
      self.road_name_renderer.render(rect)
    self.speed_limit_renderer.render(self._speed_limit_anchor(rect))

    # Custom: turn signals and blind spot as two tiles at the top centre
    self._signals_shown = self._signals.render_center(rect.x + rect.width / 2, rect.y + NOTICE_TOP)

    if preset != LayoutPreset.MINIMAL:
      scc = self.smart_cruise_control_renderer
      if scc.vision_enabled or scc.map_enabled:
        chips_x = self.cluster_rect.x
        cruise_chips(scc, chips_x, self.cluster_rect.y + self.cluster_rect.height + 16)
      # SP green light / lead departing / stopped timer, as a notification card
      pop = e2e_notice(self.circular_alerts_renderer)
      if pop is not None:
        title, sub, bar, icon = pop
        band_l, band_r = self.notify_band(rect)
        w, h = notice_size(title, sub, band_r - band_l)
        notice(rl.Rectangle(band_l + (band_r - band_l - w) / 2, self.notify_top(rect), w, h), title, sub, bar, icon)
      self.rocket_fuel.render(rect, ui_state.sm)

  def _draw_lateral_control_overlay(self, center_x: float, center_y: float) -> None:
    """BluePilot (7.0): active lateral mode (A / C / OP) on the experimental button. Custom:
    Console chip in the face's bottom-right corner instead of the gradient disc over the wheel."""
    if not self._show_lateral_control or self._lateral_mode is None:
      return
    # Custom: a small glass badge on the round face's lower-right rim with a drawn glyph (angle: two
    # rays and an arc; curvature: a curved path; openpilot: a ring) instead of an A / C / OP letter
    if self._lateral_mode == LateralMode.angle:
      kind, color = "angle", Console.INFO
    elif self._lateral_mode == LateralMode.curvature:
      kind, color = "curve", Console.WARNING
    else:
      kind, color = "op", Console.TEXT_SECONDARY
    br = 30.0
    off = FACE_SIZE / 2 * 0.74
    bx, by = center_x + off, center_y + off
    c = rl.Vector2(bx, by)
    rl.draw_circle_v(c, br + 4, rl.Color(0, 0, 0, 0x30))
    rl.draw_circle_v(c, br, Onroad.PANEL_SOLID)
    rl.draw_ring(c, br - 3, br, 0, 360, 48, color)
    w = 3.5
    if kind == "angle":
      v = rl.Vector2(bx - 12, by + 9)
      rl.draw_line_ex(v, rl.Vector2(bx + 13, by + 9), w, color)
      rl.draw_line_ex(v, rl.Vector2(bx + 7, by - 12), w, color)
      rl.draw_ring(v, 11, 11 + w * 0.8, 300, 360, 12, color)
    elif kind == "curve":
      pts = []
      # a road bend: straight up from the bottom-left, sweeping right along a quadratic
      p0, p1, p2 = (bx - 10, by + 13), (bx - 10, by - 11), (bx + 13, by - 11)
      for i in range(17):
        t = i / 16
        u = 1 - t
        pts.append(rl.Vector2(u * u * p0[0] + 2 * u * t * p1[0] + t * t * p2[0],
                              u * u * p0[1] + 2 * u * t * p1[1] + t * t * p2[1]))
      for a, b in zip(pts, pts[1:], strict=False):
        rl.draw_line_ex(a, b, w, color)
      rl.draw_circle_v(pts[0], w / 2, color)
      rl.draw_circle_v(pts[-1], w / 2 + 1.5, color)
    else:
      rl.draw_ring(c, 8, 8 + w, 0, 360, 32, color)

  def lead_card_pos(self, rect: rl.Rectangle, width: float) -> tuple[float, float]:
    """Top-left of the lead card: under the experimental button, right edges aligned."""
    inset = (UI_CONFIG.button_size - FACE_SIZE) / 2
    right = rect.x + rect.width - UI_CONFIG.border_size - inset
    return right - width, rect.y + UI_CONFIG.border_size + UI_CONFIG.button_size + 8

  def notify_band(self, rect: rl.Rectangle) -> tuple[float, float]:
    """Notification cards centre on the screen: the widest band symmetric about the centre that
    clears the speed card and the experimental button."""
    cx = rect.x + rect.width / 2
    left = self.cluster_rect.x + self.cluster_rect.width + CLUSTER_GAP
    right = rect.x + rect.width - UI_CONFIG.border_size - UI_CONFIG.button_size - CLUSTER_GAP
    half = max(0.0, min(cx - left, right - cx))
    return cx - half, cx + half

  def notify_top(self, rect: rl.Rectangle) -> float:
    """Top of the notification card: the top row, or under the signal tiles when they show."""
    return rect.y + NOTICE_TOP + ((TILE + 16) if self._signals_shown else 0)

  def _speed_limit_anchor(self, rect: rl.Rectangle) -> rl.Rectangle:
    """SpeedLimitRenderer places its sign rect at (rect.x + 84, rect.y + 39); the Canadian sign
    is SIGN_W wide in the middle of it. Shift rect so the sign sits under the speed card,
    left edges aligned."""
    width = UI_CONFIG.set_speed_width_metric if ui_state.is_metric else UI_CONFIG.set_speed_width_imperial
    c = self.cluster_rect
    x = c.x - (width - SIGN_W) / 2 - (60 + width + 30 - 6)
    y = c.y + c.height + CLUSTER_GAP - (45 - 6)
    return rl.Rectangle(x, y, rect.width, rect.height)

  def _status(self) -> tuple[str, rl.Color]:
    if self.guest:
      return tr("Guest mode"), Console.TEXT_GHOST
    if not self.is_cruise_available:
      return tr("Unavailable"), Console.TEXT_GHOST
    if self.attention == "blocked":
      return tr("Steering blocked"), Console.DANGER
    if self.attention == "override":
      return tr("Steering override"), Console.DANGER
    status = ui_state.status
    if status == UIStatus.ENGAGED:
      return tr("Engaged"), Onroad.ENGAGED
    if status == UIStatus.OVERRIDE:
      return tr("Override"), Onroad.OVERRIDE
    if status == UIStatus.LAT_ONLY:
      return tr("Steering only"), Onroad.LAT_ONLY
    if status == UIStatus.LONG_ONLY:
      return tr("Speed only"), Onroad.LONG_ONLY
    return (tr("Ready") if self.is_cruise_set else tr("Off")), Onroad.DISENGAGED

  def _draw_cluster(self, rect: rl.Rectangle) -> rl.Rectangle:
    """Speed card: state word with dot, current speed with unit, set speed in its own column."""
    long_plan_sp = ui_state.sm['longitudinalPlanSP']
    long_override = ui_state.sm['carControl'].cruiseControl.override
    sla_active = long_plan_sp.speedLimit.assist.active
    self._get_icbm_status()

    hide_speed = self._hide_v_ego_ui
    # Road view "Large speed": a much bigger own speed (the card grows with it)
    big = road_prefs.big_speed and not hide_speed
    sp_size, unit_size = (CLUSTER_SPEED_BIG, CLUSTER_UNIT_BIG) if big else (CLUSTER_SPEED, CLUSTER_UNIT)
    card_h = CLUSTER_H_BIG if big else CLUSTER_H
    speed_text = str(round(self.speed))
    unit_text = tr("km/h") if ui_state.is_metric else tr("mph")
    speed_w = 0.0 if hide_speed else max(measure_text_cached(self._font_bold, "88", sp_size).x,
                                         measure_text_cached(self._font_bold, speed_text, sp_size).x)
    unit_w = 0.0 if hide_speed else measure_text_cached(self._font_medium, unit_text, unit_size).x
    speed_col = 0.0 if hide_speed else speed_w + 14 + unit_w

    show_set = self.is_cruise_available and not self.guest
    set_col = CLUSTER_SET_W if show_set else 0.0
    inner_w = speed_col + (CLUSTER_PAD + 2 + CLUSTER_PAD if (speed_col and set_col) else 0) + set_col
    # Custom: the speed limit sign sits in the same card, after the set speed (Lucas 22:42)
    sl = self.speed_limit_renderer
    show_sign = ui_state.speed_limit_mode != SpeedLimitMode.off and sl.has_limit
    sign_h = min(SIGN_IN_MAX_H, card_h - STATE_BAND_H - 6 - CLUSTER_PAD - 16)
    sign_w = sign_h * SIGN_W / SIGN_H
    base_w = inner_w
    if show_sign:
      inner_w += (CLUSTER_PAD + 2 + CLUSTER_PAD if inner_w else 0) + sign_w
    w = max(CLUSTER_MIN_W, inner_w + 2 * CLUSTER_PAD)
    x, y = rect.x + CLUSTER_MARGIN, rect.y + CLUSTER_MARGIN
    card = rl.Rectangle(x, y, w, card_h)
    draw_panel(card, Onroad.PANEL, CLUSTER_RADIUS)

    # State band: the top of the card fills with the engagement colour and names the state, so
    # the state reads at a glance without a full-screen border (Off / Ready / Unavailable stay
    # neutral)
    word, color = self._status()
    if sla_active and self.is_cruise_set:
      word, color = tr("Limit assist"), (Console.WARNING if long_override else Console.INFO)
    active = not self.guest and (ui_state.status != UIStatus.DISENGAGED or (sla_active and self.is_cruise_set))
    band = rl.Rectangle(x, y, w, STATE_BAND_H)
    rl.draw_rectangle_rounded(band, roundness(band, CLUSTER_RADIUS), 10, color if active else Console.BG_RAISED)
    rl.draw_rectangle_rec(rl.Rectangle(x, y + STATE_BAND_H - CLUSTER_RADIUS, w, CLUSTER_RADIUS), color if active else Console.BG_RAISED)
    # day status hues are light, so the band takes dark ink there
    ink = (Console.FRAME_INK if is_day() else Console.ON_ACCENT) if active else Console.TEXT_SECONDARY
    icon = "gauge" if ui_state.status == UIStatus.LONG_ONLY else "wheel"
    D.icon(icon, x + CLUSTER_PAD - 2, y + (STATE_BAND_H - 32) / 2, 32, ink)
    rl.draw_text_ex(self._font_semi_bold, word, rl.Vector2(x + CLUSTER_PAD + 42, y + (STATE_BAND_H - CLUSTER_LABEL) / 2 - 1),
                    CLUSTER_LABEL, 0, ink)

    body_y = y + STATE_BAND_H + 6
    cx = x + CLUSTER_PAD
    if not hide_speed:
      # BluePilot: speed turns red while the brake lights are on (ShowBrakeStatus)
      speed_color = Console.DANGER if self._brakes_on else Console.TEXT_PRIMARY
      sw = measure_text_cached(self._font_bold, speed_text, sp_size).x
      rl.draw_text_ex(self._font_bold, speed_text, rl.Vector2(cx + speed_w - sw, body_y), sp_size, 0, speed_color)
      rl.draw_text_ex(self._font_medium, unit_text, rl.Vector2(cx + speed_w + 14, body_y + sp_size * 0.80 - unit_size * 0.80),
                      unit_size, 0, Console.TEXT_MUTED)
      self.speed_right = cx + speed_col
      cx += speed_col + CLUSTER_PAD
      if show_set:
        rl.draw_rectangle(int(cx), int(body_y + 18), 2, int(card_h - (body_y - y) - CLUSTER_PAD - 18), Console.BORDER_DEFAULT)
        cx += 2 + CLUSTER_PAD
    else:
      self.speed_right = 0

    if show_set:
      if self.show_icbm_status:
        label, label_color = str(round(self.speed_cluster)), Console.ACCENT_TEXT
      elif self._auto_set_on():
        label, label_color = tr("AUTO"), Console.ACCENT_TEXT  # Resume/Set uses the driver's speed for the limit
      else:
        label, label_color = tr("MAX"), Console.TEXT_MUTED
      sy = body_y + (card_h - CLUSTER_H) / 2  # the set speed sits mid-card next to a large speed
      rl.draw_text_ex(self._font_semi_bold, label, rl.Vector2(cx, sy + 14), CLUSTER_LABEL, 0, label_color)
      set_text = CRUISE_DISABLED_CHAR if not self.is_cruise_set else str(round(self.set_speed))
      set_color = Console.TEXT_PRIMARY if self.is_cruise_set else Console.TEXT_GHOST
      rl.draw_text_ex(self._font_bold, set_text, rl.Vector2(cx, sy + 14 + CLUSTER_LABEL + 4), CLUSTER_SET, 0, set_color)
      # Squared state bar under the set speed, in the engagement colour
      bar = rl.Rectangle(cx, y + card_h - CLUSTER_PAD - SET_SPEED_STATE_BAR_H, CLUSTER_SET_W, SET_SPEED_STATE_BAR_H)
      rl.draw_rectangle_rounded(bar, roundness(bar, Radius.XS), 4, self._set_speed_state_color(long_override, sla_active))

    sign_y = body_y + 4 + (card_h - STATE_BAND_H - 6 - CLUSTER_PAD - 4 - sign_h) / 2
    if show_sign:
      sx = x + w - CLUSTER_PAD - sign_w
      if base_w:
        rl.draw_rectangle(int(sx - CLUSTER_PAD - 2), int(body_y + 18), 2, int(card_h - (body_y - y) - CLUSTER_PAD - 18),
                          Console.BORDER_DEFAULT)
      sl.target = rl.Rectangle(sx, sign_y, sign_w, sign_h)
    else:
      sl.target = rl.Rectangle(x + w - CLUSTER_PAD, sign_y, 0, sign_h)  # nothing drawn; the ahead chip still aligns
    sl.chip_y = y + card_h + 16
    return card

  def _auto_set_on(self) -> bool:
    """BPAutoSetSpeed, read about once a second."""
    now = time.monotonic()
    if now - getattr(self, "_auto_set_t", 0.0) > 1.0:
      self._auto_set_t = now
      try:
        self._auto_set = bool(ui_state.params.get_bool("BPAutoSetSpeed"))
      except Exception:
        self._auto_set = False
    return getattr(self, "_auto_set", False)

  def _set_speed_state_color(self, long_override: bool, sla_active: bool) -> rl.Color:
    if not self.is_cruise_set:
      return Console.BG_TRACK
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

  # The stock pieces are drawn by _draw_cluster; keep the hooks inert for callers of the base API
  def _draw_set_speed(self, rect: rl.Rectangle) -> None:
    pass

  def _draw_current_speed(self, rect: rl.Rectangle) -> None:
    pass
