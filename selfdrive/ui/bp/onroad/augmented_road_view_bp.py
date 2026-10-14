import numpy as np
import time
import pyray as rl
from cereal import log, messaging
from openpilot.common.params import Params
from openpilot.common.params_pyx import UnknownKeyName
from openpilot.selfdrive.ui import UI_BORDER_SIZE
from openpilot.selfdrive.ui.onroad.augmented_road_view import AugmentedRoadView
from openpilot.selfdrive.ui.onroad.cameraview import CameraView
from openpilot.selfdrive.ui.bp.onroad.blindspot_renderer import BlindspotRendererMixin
from openpilot.selfdrive.ui.bp.onroad.hud_renderer_bp import HudRendererBP
from openpilot.selfdrive.ui.bp.onroad.alert_renderer_bp import AlertRendererBP
from openpilot.selfdrive.ui.bp.onroad.model_renderer_bp import ModelRendererBP
from openpilot.selfdrive.ui.bp.onroad.driver_monitor_bp import DriverMonitorBP
from openpilot.selfdrive.ui.bp.onroad.road_view import CARD_W as LEAD_CARD_W, SHOW_LEAD_CARD, draw_lead_card, road_prefs
from openpilot.selfdrive.ui.bp.onroad.torque_bar_renderer_bp import TorqueBarRendererBP
from openpilot.selfdrive.ui.bp.onroad.ev_hud import EvHudRenderer
from openpilot.selfdrive.ui.bp.onroad.console_cues import ConsoleConfidence, draw_blindspot_edge
from openpilot.selfdrive.ui.sunnypilot.onroad.developer_ui import DeveloperUiState, get_bottom_dev_ui_offset
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.bp.lib.ui_debug_logger import bp_ui_log
from openpilot.selfdrive.ui.onroad.colors import BORDER_COLORS
from openpilot.selfdrive.ui.ui_state import UIStatus
from openpilot.selfdrive.ui.onroad.augmented_road_view import DEFAULT_DEVICE_CAMERA, INF_POINT, WIDE_CAM
from bluepilot.ui.lib.theme import Console
from bluepilot.ui.lib.layout_presets import LayoutPreset, current_preset



class AugmentedRoadViewBP(AugmentedRoadView, BlindspotRendererMixin):
  """BluePilot AugmentedRoadView with blindspot indicators, gauges, and BP renderers."""

  BLIND_SPOT_WIDTH = 250  # Wider for TICI's larger screen

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._init_blindspot()
    self._bp_params = Params()

    # BluePilot: Replace renderers with BP versions
    self.model_renderer = ModelRendererBP()
    # Custom: Console driver-monitoring tile
    self.driver_state_renderer = DriverMonitorBP()
    self._hud_renderer = HudRendererBP()
    self.alert_renderer = AlertRendererBP()
    # BluePilot: Torque bar renderer. Custom: a strip along the top of the Console dock, or the
    # stock arc when the dock is hidden.
    self._torque_bar = TorqueBarRendererBP(scale=3.0)

    # Custom: Console EV HUD. The bottom dock (charge, power, range) replaces BluePilot's hybrid
    # battery and power-flow gauges; a details card on the right carries the rest.
    self._ev_hud = EvHudRenderer()

    # BluePilot: Add confidence ball on left side (MADS beam + enhanced coloring)
    # Custom: Console confidence bar (same signal and zones as the ball)
    self._confidence_ball = ConsoleConfidence()
    self._show_confidence_ball = self._bp_params.get_bool("BPShowConfidenceBall")
    self._param_counter = 0
    self._guest = self._read_guest()

  def update_fade_out_bottom_overlay(self, _content_rect):
    """BluePilot: Skip MICI fade overlay on TICI — causes unwanted black gradient at bottom."""

  def _render(self, rect):
    """Override render to add blindspot, gauges, confidence ball on left."""
    start_draw = time.monotonic()
    bp_ui_log.tick()
    if not ui_state.started:
      return

    # Refresh param periodically (~1s at 60fps)
    self._param_counter += 1
    if self._param_counter >= 60:
      self._param_counter = 0
      self._guest = self._read_guest()
      self._show_confidence_ball = self._bp_params.get_bool("BPShowConfidenceBall")

    self._switch_stream_if_needed(ui_state.sm)
    self._update_calibration()

    # Custom: Console layout preset filters optional overlays for this frame
    preset = current_preset()
    show_ball = self._show_confidence_ball and preset != LayoutPreset.MINIMAL and not self._guest
    self._hud_renderer.guest = self.alert_renderer.guest = self._guest

    # Custom: the camera fills the whole screen (no border frame); the UI keeps its inset
    self._content_rect = rl.Rectangle(rect.x, rect.y, rect.width, rect.height)
    inset = rl.Rectangle(rect.x + UI_BORDER_SIZE, rect.y + UI_BORDER_SIZE,
                         rect.width - 2 * UI_BORDER_SIZE, rect.height - 2 * UI_BORDER_SIZE)

    # Custom: confidence lives in the driver-monitor chip, so the UI no longer shifts right for it
    ui_rect = inset
    self.driver_state_renderer.confidence = self._confidence_ball.level if show_ball else None

    bp_ui_log.scissor("AugRoadView", "begin",
                       x=int(self._content_rect.x), y=int(self._content_rect.y),
                       w=int(self._content_rect.width), h=int(self._content_rect.height))
    rl.begin_scissor_mode(
      int(self._content_rect.x),
      int(self._content_rect.y),
      int(self._content_rect.width),
      int(self._content_rect.height)
    )

    # Render the base camera view
    CameraView._render(self, rect)

    # Render model (uses full content rect for camera-space overlays)
    # Custom: no path or lead marker on a Guest Mode drive (openpilot is not driving)
    if not self._guest:
      self.model_renderer.render(self._content_rect)

    # SP fade overlay
    self.update_fade_out_bottom_overlay(self._content_rect)

    # Custom: a prompt or critical alert owns the bottom of the screen, so the dock steps aside
    alert = self.alert_renderer.get_alert(ui_state.sm)
    alert_blocks_dock = alert is not None and not (alert.status == log.SelfdriveState.AlertStatus.normal and
                                                   alert.size != log.SelfdriveState.AlertSize.full)

    # BluePilot: Update torque bar filter state (once per frame, before the dock or arc uses it)
    self._torque_bar.update()

    # Custom: Console dock and details card, drawn under the blindspot edges so the red warning
    # is never covered
    dock = None if alert_blocks_dock else self._ev_hud.render_dock(self._content_rect, preset, self._torque_bar)
    self._ev_hud.render(self._content_rect, preset, bottom=dock.y if dock is not None else None)

    # BluePilot: Draw blindspot screen edge indicators ON TOP of confidence ball backdrop
    # so the red safety warning is never obscured
    self._draw_blindspot_screen_edges(self._content_rect, self.BLIND_SPOT_WIDTH)

    self._hud_renderer.render(ui_rect)

    # Custom: lead vehicle card under the experimental button (Road view settings choose its rows)
    lead = None if self._guest else self.model_renderer.lead_info
    if lead is not None and preset != LayoutPreset.MINIMAL and road_prefs.on(SHOW_LEAD_CARD):
      details = self._ev_hud.last_rect
      if details is not None:  # Dense: the details card owns the right edge; sit to its left
        x, y = details.x - 24 - LEAD_CARD_W, details.y
      else:
        x, y = self._hud_renderer.lead_card_pos(ui_rect, LEAD_CARD_W)
      draw_lead_card(x, y, lead, road_prefs.value, ui_state.is_metric, self.model_renderer.lead_alpha)

    bp_ui_log.scissor("AugRoadView", "reset (defensive)")
    # Defensive: re-establish scissor before drawing driver state. Some HUD widgets (e.g. speed
    # limit, brake status) can leave raylib state in a bad way on device, causing the bottom-left
    # widgets to be clipped or not drawn.
    rl.end_scissor_mode()
    rl.begin_scissor_mode(
      int(self._content_rect.x),
      int(self._content_rect.y),
      int(self._content_rect.width),
      int(self._content_rect.height)
    )
    # Custom: a prompt or critical card at the bottom covers the tile's corner; the card shows the ask
    if not alert_blocks_dock and not self._guest:
      self.driver_state_renderer.render(ui_rect)

    # BluePilot: stock arc torque bar when the dock (which carries the strip) is hidden.
    # Custom: the Minimal preset hides it.
    if dock is None and preset != LayoutPreset.MINIMAL and not self._guest:
      torque_rect = ui_rect
      if ui_state.developer_ui in (DeveloperUiState.BOTTOM, DeveloperUiState.BOTH):
        torque_rect = rl.Rectangle(ui_rect.x, ui_rect.y, ui_rect.width, ui_rect.height - get_bottom_dev_ui_offset())
      self._torque_bar.render(torque_rect, gauge_height_offset=0.0)

    # Alerts last so they are never covered by gauges or other overlays.
    # BluePilot: Full-screen alerts (e.g. reverse gear) must use content_rect so they cover
    # the confidence ball strip; otherwise the camera shows through where the ball was.
    alert_rect = self._content_rect if (alert and alert.size == log.SelfdriveState.AlertSize.full) else ui_rect
    self.alert_renderer.notify_band = self._hud_renderer.notify_band(ui_rect)
    self.alert_renderer.notify_top = self._hud_renderer.notify_top(ui_rect)
    self.alert_renderer.render(alert_rect)

    bp_ui_log.scissor("AugRoadView", "end")
    rl.end_scissor_mode()

    # Custom: no border or edge glow (Lucas 2026-10-14); the speed card's status band carries the
    # engagement state. Quick controls read where the dock is so a swipe up from it opens them.
    ui_state.qc_dock = dock
    ui_state.qc_blocked = alert_blocks_dock or self._guest
    ui_state.qc_bottom_inset = 0.0  # px a theme's bottom cluster reserves above the screen edge

    # Publish uiDebug
    msg = messaging.new_message('uiDebug')
    msg.uiDebug.drawTimeMillis = (time.monotonic() - start_draw) * 1000
    self._pm.send('uiDebug', msg)

  def _draw_blindspot_screen_edges(self, rect: rl.Rectangle, blind_spot_width: int = 250):
    """Custom: Console blind-spot edges, squared danger bars instead of a red gradient.
    Same toggle (ShowBlindspotOverlay) and fade as BluePilot's."""
    try:
      if not self._blindspot_params.get_bool("ShowBlindspotOverlay"):
        return
    except UnknownKeyName:
      return
    sm = ui_state.sm
    if not sm.valid['carState']:
      return
    cs = sm['carState']
    self._blindspot_left_alpha_filter.update(1.0 if cs.leftBlindspot else 0.0)
    self._blindspot_right_alpha_filter.update(1.0 if cs.rightBlindspot else 0.0)
    draw_blindspot_edge(rect, self._blindspot_left_alpha_filter.x, self._blindspot_right_alpha_filter.x,
                        cs.leftBlindspot and cs.leftBlinker, cs.rightBlindspot and cs.rightBlinker)

  def _read_guest(self) -> bool:
    """Guest Mode drive: BPGuestModeActive is set by the Lightning control stream for the whole
    drive (card passive, panda noOutput, factory ACC and lane keeping). False on builds that do
    not have the key yet."""
    try:
      return self._bp_params.get_bool("BPGuestModeActive")
    except UnknownKeyName:
      return False

  def _calc_frame_matrix(self, rect: rl.Rectangle) -> np.ndarray:
    """Custom: stock framing, but the zoom never drops below what covers the whole content rect,
    so the full-screen camera has no bars at the edges (the road camera's 1.1x falls a few
    pixels short of the panel's width otherwise)."""
    cache_key = (ui_state.sm.recv_frame['liveCalibration'], self._content_rect.width, self._content_rect.height, self.stream_type)
    if cache_key == self._matrix_cache_key and self._cached_matrix is not None:
      return self._cached_matrix

    device_camera = self.device_camera or DEFAULT_DEVICE_CAMERA
    is_wide_camera = self.stream_type == WIDE_CAM
    intrinsic = device_camera.ecam.intrinsics if is_wide_camera else device_camera.fcam.intrinsics
    calibration = self.view_from_wide_calib if is_wide_camera else self.view_from_calib

    x, y = self._content_rect.x, self._content_rect.y
    w, h = self._content_rect.width, self._content_rect.height
    cx, cy = intrinsic[0, 2], intrinsic[1, 2]
    margin = 5
    zoom = max(2.0 if is_wide_camera else 1.1, (w / 2 + margin + 1) / cx, (h / 2 + margin + 1) / cy)

    calib_transform = intrinsic @ calibration
    kep = calib_transform @ INF_POINT
    max_x_offset = cx * zoom - w / 2 - margin
    max_y_offset = cy * zoom - h / 2 - margin
    try:
      if abs(kep[2]) > 1e-6:
        x_offset = np.clip((kep[0] / kep[2] - cx) * zoom, -max_x_offset, max_x_offset)
        y_offset = np.clip((kep[1] / kep[2] - cy) * zoom, -max_y_offset, max_y_offset)
      else:
        x_offset, y_offset = 0, 0
    except (ZeroDivisionError, OverflowError):
      x_offset, y_offset = 0, 0

    self._matrix_cache_key = cache_key
    self._cached_matrix = np.array([
      [zoom * 2 * cx / w, 0, -x_offset / w * 2],
      [0, zoom * 2 * cy / h, -y_offset / h * 2],
      [0, 0, 1.0]
    ])
    video_transform = np.array([
      [zoom, 0.0, (w / 2 + x - x_offset) - (cx * zoom)],
      [0.0, zoom, (h / 2 + y - y_offset) - (cy * zoom)],
      [0.0, 0.0, 1.0]
    ])
    self.model_renderer.set_transform(video_transform @ calib_transform)
    return self._cached_matrix

  def _draw_border(self, rect: rl.Rectangle):
    """Console: page-ground outer frame, status-coloured inner frame."""
    rl.draw_rectangle_lines_ex(rect, UI_BORDER_SIZE, Console.BG_PAGE)
    border_color = BORDER_COLORS.get(ui_state.status, BORDER_COLORS[UIStatus.DISENGAGED])
    border_rect = rl.Rectangle(rect.x + UI_BORDER_SIZE, rect.y + UI_BORDER_SIZE,
                               rect.width - 2 * UI_BORDER_SIZE, rect.height - 2 * UI_BORDER_SIZE)
    rl.draw_rectangle_rounded_lines_ex(border_rect, 0.12, 10, UI_BORDER_SIZE, border_color)
