import time
import pyray as rl
from cereal import log, messaging
from openpilot.common.params import Params
from openpilot.selfdrive.ui import UI_BORDER_SIZE
from openpilot.selfdrive.ui.onroad.augmented_road_view import AugmentedRoadView
from openpilot.selfdrive.ui.onroad.cameraview import CameraView
from openpilot.selfdrive.ui.bp.onroad.blindspot_renderer import BlindspotRendererMixin
from openpilot.selfdrive.ui.bp.onroad.hud_renderer_bp import HudRendererBP
from openpilot.selfdrive.ui.bp.onroad.alert_renderer_bp import AlertRendererBP
from openpilot.selfdrive.ui.bp.onroad.model_renderer_bp import ModelRendererBP
from openpilot.selfdrive.ui.bp.onroad.torque_bar_renderer_bp import TorqueBarRendererBP
from openpilot.selfdrive.ui.bp.onroad.ev_hud import EvHudRenderer
from openpilot.selfdrive.ui.bp.mici.onroad.confidence_ball_bp import ConfidenceBallTiciBP
from openpilot.selfdrive.ui.sunnypilot.onroad.developer_ui import DeveloperUiState, get_bottom_dev_ui_offset
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.selfdrive.ui.bp.lib.ui_debug_logger import bp_ui_log
from openpilot.selfdrive.ui.onroad.colors import BORDER_COLORS
from openpilot.selfdrive.ui.ui_state import UIStatus
from bluepilot.ui.lib.theme import Console, Onroad
from bluepilot.ui.lib.layout_presets import LayoutPreset, current_preset

# BluePilot: Margin to keep confidence ball inside the colored border
BALL_BORDER_MARGIN = UI_BORDER_SIZE // 2  # 15px

class AugmentedRoadViewBP(AugmentedRoadView, BlindspotRendererMixin):
  """BluePilot AugmentedRoadView with blindspot indicators, gauges, and BP renderers."""

  BLIND_SPOT_WIDTH = 250  # Wider for TICI's larger screen

  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self._init_blindspot()
    self._bp_params = Params()

    # BluePilot: Replace renderers with BP versions
    self.model_renderer = ModelRendererBP()
    self._hud_renderer = HudRendererBP()
    self.alert_renderer = AlertRendererBP()
    # BluePilot: Torque bar renderer. Custom: a strip along the top of the Console dock, or the
    # stock arc when the dock is hidden.
    self._torque_bar = TorqueBarRendererBP(scale=3.0)

    # Custom: Console EV HUD. The bottom dock (charge, power, range) replaces BluePilot's hybrid
    # battery and power-flow gauges; a details card on the right carries the rest.
    self._ev_hud = EvHudRenderer()

    # BluePilot: Add confidence ball on left side (MADS beam + enhanced coloring)
    self._confidence_ball = ConfidenceBallTiciBP()
    self._show_confidence_ball = self._bp_params.get_bool("BPShowConfidenceBall")
    self._param_counter = 0

  def update_fade_out_bottom_overlay(self, _content_rect):
    """BluePilot: Skip MICI fade overlay on TICI — causes unwanted black gradient at bottom."""
    pass

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
      self._show_confidence_ball = self._bp_params.get_bool("BPShowConfidenceBall")

    self._switch_stream_if_needed(ui_state.sm)
    self._update_calibration()

    # Custom: Console layout preset filters optional overlays for this frame
    preset = current_preset()
    show_ball = self._show_confidence_ball and preset != LayoutPreset.MINIMAL

    # Create inner content area with border padding
    self._content_rect = rl.Rectangle(
      rect.x + UI_BORDER_SIZE,
      rect.y + UI_BORDER_SIZE,
      rect.width - 2 * UI_BORDER_SIZE,
      rect.height - 2 * UI_BORDER_SIZE,
    )

    # BluePilot: Offset rect pushes HUD/driver state/alerts right of the confidence ball
    ball_offset = (ConfidenceBallTiciBP.BALL_WIDTH + BALL_BORDER_MARGIN) if show_ball else 0
    ui_rect = rl.Rectangle(
      self._content_rect.x + ball_offset,
      self._content_rect.y,
      self._content_rect.width - ball_offset,
      self._content_rect.height,
    )

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
    self.model_renderer.render(self._content_rect)

    # SP fade overlay
    self.update_fade_out_bottom_overlay(self._content_rect)

    # BluePilot: Render confidence ball on left side (narrow rect = ball strip only, not full width)
    if show_ball:
      ball_strip_width = ConfidenceBallTiciBP.BALL_WIDTH + BALL_BORDER_MARGIN
      # Semi-transparent dark backdrop so ball is visible against bright camera feed
      rl.draw_rectangle_gradient_h(
        int(self._content_rect.x),
        int(self._content_rect.y),
        int(ball_strip_width),
        int(self._content_rect.height),
        Onroad.BAND,                # Console bg-page at the left edge
        Console.TRANSPARENT,        # fades out so the camera stays readable
      )
      ball_rect = rl.Rectangle(
        self._content_rect.x + BALL_BORDER_MARGIN,
        self._content_rect.y,
        ball_strip_width,
        self._content_rect.height,
      )
      self._confidence_ball.render(ball_rect)

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
    self.driver_state_renderer.render(ui_rect)

    # BluePilot: stock arc torque bar when the dock (which carries the strip) is hidden.
    # Custom: the Minimal preset hides it.
    if dock is None and preset != LayoutPreset.MINIMAL:
      torque_rect = ui_rect
      if ui_state.developer_ui in (DeveloperUiState.BOTTOM, DeveloperUiState.BOTH):
        torque_rect = rl.Rectangle(ui_rect.x, ui_rect.y, ui_rect.width, ui_rect.height - get_bottom_dev_ui_offset())
      self._torque_bar.render(torque_rect, gauge_height_offset=0.0)

    # Alerts last so they are never covered by gauges or other overlays.
    # BluePilot: Full-screen alerts (e.g. reverse gear) must use content_rect so they cover
    # the confidence ball strip; otherwise the camera shows through where the ball was.
    alert_rect = (
      self._content_rect
      if (alert and alert.size == log.SelfdriveState.AlertSize.full and show_ball)
      else ui_rect
    )
    self.alert_renderer.notify_band = self._hud_renderer.notify_band(ui_rect)
    self.alert_renderer.render(alert_rect)

    bp_ui_log.scissor("AugRoadView", "end")
    rl.end_scissor_mode()

    # BluePilot: Conditionally draw border
    if not self._bp_params.get_bool("BPHideOnroadBorder"):
      self._draw_border(rect)

    # Publish uiDebug
    msg = messaging.new_message('uiDebug')
    msg.uiDebug.drawTimeMillis = (time.monotonic() - start_draw) * 1000
    self._pm.send('uiDebug', msg)

  def _draw_border(self, rect: rl.Rectangle):
    """Console: page-ground outer frame, status-coloured inner frame."""
    rl.draw_rectangle_lines_ex(rect, UI_BORDER_SIZE, Console.BG_PAGE)
    border_color = BORDER_COLORS.get(ui_state.status, BORDER_COLORS[UIStatus.DISENGAGED])
    border_rect = rl.Rectangle(rect.x + UI_BORDER_SIZE, rect.y + UI_BORDER_SIZE,
                               rect.width - 2 * UI_BORDER_SIZE, rect.height - 2 * UI_BORDER_SIZE)
    rl.draw_rectangle_rounded_lines_ex(border_rect, 0.12, 10, UI_BORDER_SIZE, border_color)
