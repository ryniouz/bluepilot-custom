import time

import numpy as np
import pyray as rl
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.params import Params
from openpilot.selfdrive.ui.onroad.model_renderer import ModelRenderer, LeadVehicle, CLIP_MARGIN, MIN_DRAW_DISTANCE, MAX_DRAW_DISTANCE
from openpilot.selfdrive.ui.bp.onroad.chevron_metrics_bp import ChevronMetricsBP
from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.shader_polygon import draw_polygon, Gradient
# BluePilot: Rainbow shader moved to BP module after upstream removal
from openpilot.bluepilot.ui.lib.bp_shaders import draw_rainbow_polygon
from openpilot.selfdrive.ui.bp.lib.ui_debug_logger import bp_ui_log
# BluePilot: seasonal theme packs (colors.json overrides for road colors)
from openpilot.selfdrive.ui.bp.lib import theme_pack
# Custom: Console road view (lead marker, lead speed tag, lead card data, road-view preferences)
from openpilot.selfdrive.ui.bp.onroad.road_view import (LeadInfo, SHOW_EDGES, SHOW_LANES, SHOW_NEIGHBOURS, SHOW_SPEED_TAG,
                                                       draw_lead_marker, draw_speed_tag, lead_level, road_prefs)
from bluepilot.ui.lib.theme import Console, Onroad, mix, with_alpha  # Custom: Console theme
from openpilot.selfdrive.ui.bp.onroad.lane_change_fx import LaneChangeFx

# BluePilot: Lane line colors by status (upstream removed LANE_LINE_COLORS dict)
# Custom: Console status hues; disengaged lines go ghost grey instead of black
LANE_LINE_COLORS_BP = {
  UIStatus.DISENGAGED: Console.TEXT_GHOST,
  UIStatus.ENGAGED: Onroad.ENGAGED,
  UIStatus.OVERRIDE: Onroad.OVERRIDE,
  UIStatus.LAT_ONLY: Onroad.LAT_ONLY,
  UIStatus.LONG_ONLY: Onroad.LONG_ONLY,
}

# BluePilot: Radar/vision lead indicator colors
# Custom: Console - radar lead is info, vision lead is warning (outer mark full, inner deepened)
LEAD_RADAR_GLOW = Onroad.LEAD_RADAR
LEAD_RADAR_CHEVRON_BASE = mix(Onroad.LEAD_RADAR, Console.BG_PAGE, 0.35)
LEAD_VISION_GLOW = Onroad.LEAD_VISION
LEAD_VISION_CHEVRON_BASE = mix(Onroad.LEAD_VISION, Console.BG_PAGE, 0.35)

ROAD_EDGE_COLOR = Console.DANGER

# Custom: road markings stay white over the camera in day and night
ROAD_WHITE = rl.Color(255, 255, 255, 255)
ROAD_WHITE_DIM = rl.Color(170, 174, 180, 255)

# Custom: blind-spot lane tint
BLINDSPOT_LANE_M = 35.0
BLINDSPOT_HALF_W = 1.6
# Custom: end

# BluePilot: Overlay size scale factors (Small=0, Medium=1, Large=2)
OVERLAY_SCALE_FACTORS = {0: 0.6, 1: 1.0, 2: 1.5}
LANE_LINE_WIDTH = 0.05
MINIMAL_VIEW_LANE_LINE_WIDTH = 0.075
MINIMAL_VIEW_OUTER_LANE_LINE_WIDTH = 0.09
ROAD_EDGE_WIDTH = 0.05
MINIMAL_VIEW_ROAD_EDGE_WIDTH = 0.075
MINIMAL_VIEW_NEUTRAL_LANE_COLOR = rl.Color(185, 205, 225, 255)

# BluePilot: Rad Racer 8-bit theme road styling
# BluePilot: Rad Racer road constants + drawing methods moved to rad_racer_road.py so the
# comma four (MICI) renderer can share them; values unchanged.
from openpilot.selfdrive.ui.bp.onroad.rad_racer_road import (  # noqa: E402
  RadRacerRoadMixin, RAD_RACER_ROAD_EDGE_WIDTH, RAD_RACER_DASH_LEN_M, RAD_RACER_GAP_LEN_M,
)

CAR_HALF_W = 0.95          # m, half a typical car width  (Custom: Console lead marker sizing)


class ModelRendererBP(RadRacerRoadMixin, ModelRenderer):
  """BluePilot ModelRenderer with enhanced lane lines, path smoothing, and radar overlay."""

  def __init__(self):
    super().__init__()
    self._lc_fx = LaneChangeFx()
    self.avoid_rect: rl.Rectangle | None = None  # Custom: the speed card, set by the road view; road tints stay below it
    self._bp_params = Params()
    self._rainbow_v = 1.0

    # BluePilot: Replace SP chevron metrics with BP version (horizontal boxed layout)
    self.chevron_metrics = ChevronMetricsBP()

    # Path smoothing: store previous smoothed path for temporal damping
    self._previous_path_projected_points = np.empty((0, 2), dtype=np.float32)
    self._path_smoothing_damping = 0.3

    # BluePilot: Track whether each lead is radar-sourced
    self._lead_is_radar = [False, False]

    # BluePilot: Overlay size scale factor (read from param periodically)
    self._overlay_scale = 1.0

    # BluePilot: Cache params to avoid per-frame disk I/O (refreshed in existing 60-frame block)
    self.ford_overlay_enabled = self._bp_params.get_bool("FordPrefShowRadarLeadOverlay")
    self._disable_lane_line_status_color = self._bp_params.get_bool("BPDisableLaneLineStatusColor")
    self._hide_camera_view = self._bp_params.get_bool("BPHideCameraView")
    self._rainbow_lane_lines = self._bp_params.get_bool("BPRainbowLines")
    # BluePilot: Rad Racer 8-bit theme (green game road, dash scroll animation state)
    self._rad_racer = theme_pack.rad_racer_active(self._bp_params)
    self._dash_phase = 0.0
    self._transform_dirty = True
    # BluePilot: seasonal theme pack (None when disabled)
    self._theme_pack = theme_pack.get_active_pack(force=True)

    # BluePilot: Lead position smoothing filters to reduce radar jitter
    dt = 1 / gui_app.target_fps
    self._lead_d_filters = [FirstOrderFilter(0, 0.4, dt, initialized=False),
                            FirstOrderFilter(0, 0.4, dt, initialized=False)]
    self._lead_y_filters = [FirstOrderFilter(0, 0.5, dt, initialized=False),
                            FirstOrderFilter(0, 0.5, dt, initialized=False)]
    self._lead_v_filters = [FirstOrderFilter(0, 0.3, dt, initialized=False),
                            FirstOrderFilter(0, 0.3, dt, initialized=False)]
    self._lead_was_active = [False, False]
    self._marking = 0

    # Custom: Console lead marker geometry per lead (x, y, width) and the card's lead state
    self._lead_marks: list[tuple[float, float, float] | None] = [None, None]
    self._lead_d_smooth = [0.0, 0.0]
    self._lead_v_smooth = [0.0, 0.0]
    self.lead_info: LeadInfo | None = None
    self.lead_alpha = 0.0
    # Custom: end

  def prepare_projection(self, rect: rl.Rectangle) -> None:
    """Set clip region so _map_to_screen works before render().

    Rad Racer draws skyline/signs behind the road and calls _map_to_screen during
    that background pass, before model_renderer.render() initializes the clip rect.
    """
    self._clip_region = rl.Rectangle(
      rect.x - CLIP_MARGIN, rect.y - CLIP_MARGIN, rect.width + 2 * CLIP_MARGIN, rect.height + 2 * CLIP_MARGIN
    )

  def _refresh_bp_params(self) -> None:
    """Refresh cached BluePilot params and invalidate model geometry when visual widths change."""
    hide_camera_view = self._bp_params.get_bool("BPHideCameraView")
    if hide_camera_view != self._hide_camera_view:
      self._transform_dirty = True
    self._hide_camera_view = hide_camera_view

    rad_racer = theme_pack.rad_racer_active(self._bp_params)
    if rad_racer != self._rad_racer:
      self._transform_dirty = True
    self._rad_racer = rad_racer

    self.ford_overlay_enabled = self._bp_params.get_bool("FordPrefShowRadarLeadOverlay")
    self._disable_lane_line_status_color = self._bp_params.get_bool("BPDisableLaneLineStatusColor")
    self._rainbow_lane_lines = self._bp_params.get_bool("BPRainbowLines")
    new_pack = theme_pack.get_active_pack()
    if (new_pack is None) != (self._theme_pack is None):
      self._transform_dirty = True  # themed lane widths differ; re-project on toggle
    self._theme_pack = new_pack

  def _render(self, rect: rl.Rectangle):
    sm = ui_state.sm

    if ui_state.rainbow_path or self._rainbow_lane_lines:
      self._rainbow_v = np.clip(sm['carState'].vEgo, 2.5, 35) / 30

    if (sm.recv_frame["liveCalibration"] < ui_state.started_frame or
        sm.recv_frame["modelV2"] < ui_state.started_frame):
      bp_ui_log.visibility("ModelRenderer", False, reason=f"stale calib={sm.recv_frame['liveCalibration']} model={sm.recv_frame['modelV2']} started={ui_state.started_frame}")
      return

    bp_ui_log.state("ModelRenderer", "render_active", True)

    self._clip_region = rl.Rectangle(
      rect.x - CLIP_MARGIN, rect.y - CLIP_MARGIN, rect.width + 2 * CLIP_MARGIN, rect.height + 2 * CLIP_MARGIN
    )

    self._experimental_mode = sm['selfdriveState'].experimentalMode

    live_calib = sm['liveCalibration']
    from openpilot.selfdrive.locationd.calibrationd import HEIGHT_INIT
    self._path_offset_z = live_calib.height[0] if live_calib.height else HEIGHT_INIT[0]

    if self._counter % 60 == 0:
      self._camera_offset = ui_state.params.get("CameraOffset", return_default=True) if ui_state.active_bundle else 0.0
      try:
        size_val = int(self._bp_params.get("FordPrefRadarOverlaySize", return_default=True))
      except (TypeError, ValueError):
        size_val = 1
      self._overlay_scale = OVERLAY_SCALE_FACTORS.get(size_val, 1.0)
      # BluePilot: Refresh cached params (avoids per-frame disk I/O)
      self._refresh_bp_params()
    self._counter += 1

    if sm.updated['carParams']:
      self._longitudinal_control = sm['carParams'].openpilotLongitudinalControl

    model = sm['modelV2']
    radar_state = sm['radarState'] if sm.valid['radarState'] else None
    lead_one = radar_state.leadOne if radar_state else None

    # BluePilot: Ford radar overlay feature - show leads even without longitudinal control
    render_lead_indicator = (self._longitudinal_control or self.ford_overlay_enabled) and radar_state is not None
    bp_ui_log.state("ModelRenderer", "render_lead", render_lead_indicator)

    model_updated = sm.updated['modelV2']
    if model_updated or sm.updated['radarState'] or self._transform_dirty:
      if model_updated:
        self._update_raw_points(model)

      path_x_array = self._path.raw_points[:, 0]
      if path_x_array.size == 0:
        return

      self._update_model(lead_one, path_x_array)
      if render_lead_indicator:
        self._update_leads(radar_state, path_x_array)
        # BluePilot: Track radar vs vision status for lead coloring
        self._update_lead_radar_status(radar_state)

      self._transform_dirty = False

    # BluePilot: Advance dash scroll animation for the Rad Racer road
    if self._rad_racer:
      v_ego = sm['carState'].vEgo if sm.valid['carState'] else 0.0
      period = RAD_RACER_DASH_LEN_M + RAD_RACER_GAP_LEN_M
      self._dash_phase = (self._dash_phase + max(0.0, v_ego) / gui_app.target_fps) % period

    self._draw_lane_lines()
    if not self._rad_racer:
      self._draw_blindspot_lanes(sm)  # Custom: Console blind-spot lane tint
    self._draw_path(sm)
    # Custom: looping lane change cue toward the target lane
    self._lc_fx.render(self, sm, road_prefs.lane_change)

    # Custom: Console lead marker; the numbers go to the lead card (drawn by the road view)
    has_lead = bool(render_lead_indicator and radar_state and radar_state.leadOne.status and not self._rad_racer)
    self.lead_alpha += ((1.0 if has_lead else 0.0) - self.lead_alpha) * 0.25
    if has_lead:
      lo = radar_state.leadOne
      v_ego = sm['carState'].vEgo
      self.lead_info = LeadInfo(d_rel=self._lead_d_smooth[0], v_rel=self._lead_v_smooth[0],
                                v_lead=max(0.0, v_ego + self._lead_v_smooth[0]), v_ego=v_ego, radar=bool(getattr(lo, 'radar', False)))
    elif self.lead_alpha < 0.02:
      self.lead_info = None
    # Custom: end

    # BluePilot: In Rad Racer theme, leads are drawn as sprites by RadRacerTheme
    if render_lead_indicator and radar_state and not self._rad_racer:
      self._draw_lead_indicator()

  def _update_lead_radar_status(self, radar_state):
    """Track whether each lead is radar-sourced for coloring."""
    leads = [radar_state.leadOne, radar_state.leadTwo]
    for i, lead_data in enumerate(leads):
      if lead_data and lead_data.status:
        self._lead_is_radar[i] = getattr(lead_data, 'radar', False)
      else:
        self._lead_is_radar[i] = False

  def _update_leads(self, radar_state, path_x_array):
    """Update lead positions with temporal smoothing to reduce radar jitter."""
    self._lead_vehicles = [LeadVehicle(), LeadVehicle()]
    self._lead_marks = [None, None]  # Custom
    leads = [radar_state.leadOne, radar_state.leadTwo]

    dt = 1 / gui_app.target_fps
    for i, lead_data in enumerate(leads):
      if lead_data and lead_data.status:
        # Reset filters when a lead first appears so we don't lerp from stale data
        if not self._lead_was_active[i]:
          self._lead_d_filters[i] = FirstOrderFilter(lead_data.dRel, 0.4, dt)
          self._lead_y_filters[i] = FirstOrderFilter(lead_data.yRel, 0.5, dt)
          self._lead_v_filters[i] = FirstOrderFilter(lead_data.vRel, 0.3, dt)

        # Smooth the raw radar values
        d_rel = self._lead_d_filters[i].update(lead_data.dRel)
        y_rel = self._lead_y_filters[i].update(lead_data.yRel)
        v_rel = self._lead_v_filters[i].update(lead_data.vRel)
        self._lead_d_smooth[i], self._lead_v_smooth[i] = d_rel, v_rel  # Custom

        idx = self._get_path_length_idx(path_x_array, d_rel)
        z = self._path.raw_points[idx, 2] if idx < len(self._path.raw_points) else 0.0
        point = self._map_to_screen(d_rel, -y_rel + self._camera_offset, z + self._path_offset_z)
        # Custom: the car's real width on screen (a typical 1.9 m), so markers and the speed tag fit it
        pl = self._map_to_screen(d_rel, -y_rel + self._camera_offset - CAR_HALF_W, z + self._path_offset_z)
        pr = self._map_to_screen(d_rel, -y_rel + self._camera_offset + CAR_HALF_W, z + self._path_offset_z)
        self._lead_px_w = abs(pr[0] - pl[0]) if (pl is not None and pr is not None) else None
        if point:
          self._marking = i  # Custom
          self._lead_vehicles[i] = self._update_lead_vehicle(d_rel, v_rel, point, self._rect)

        self._lead_was_active[i] = True
      else:
        self._lead_was_active[i] = False
        self._lead_marks[i] = None  # Custom

  def _update_lead_vehicle(self, d_rel, v_rel, point, rect):
    """Override to apply overlay size scale factor to chevron geometry."""
    speed_buff, lead_buff = 10.0, 40.0

    fill_alpha = 0
    if d_rel < lead_buff:
      fill_alpha = 255 * (1.0 - (d_rel / lead_buff))
      if v_rel < 0:
        fill_alpha += 255 * (-1 * (v_rel / speed_buff))
      fill_alpha = min(fill_alpha, 255)

    # Apply overlay scale factor to chevron size
    sz = np.clip((25 * 30) / (d_rel / 3 + 30), 15.0, 30.0) * 2.35 * self._overlay_scale
    x = np.clip(point[0], 0.0, rect.width - sz / 2)
    y = min(point[1], rect.height - sz * 0.6)

    g_xo = sz / 5
    g_yo = sz / 10

    # Custom: the Console bracket spans roughly a car's width at that distance
    w = self._lead_px_w if getattr(self, "_lead_px_w", None) else sz * 3.4
    self._lead_marks[self._marking] = (float(x), float(min(point[1], rect.height - 24)), float(w))

    glow = [(x + (sz * 1.35) + g_xo, y + sz + g_yo), (x, y - g_yo), (x - (sz * 1.35) - g_xo, y + sz + g_yo)]
    chevron = [(x + (sz * 1.25), y + sz), (x, y), (x - (sz * 1.25), y + sz)]

    return LeadVehicle(glow=glow, chevron=chevron, fill_alpha=int(fill_alpha))

  def _update_model(self, lead, path_x_array):
    """Update model with doubled lane line width and path smoothing."""
    super()._update_model(lead, path_x_array)

    # BluePilot: Redo lane lines and road edges with enhanced widths.
    max_distance = np.clip(path_x_array[-1], MIN_DRAW_DISTANCE, MAX_DRAW_DISTANCE)
    max_idx = self._get_path_length_idx(self._lane_lines[0].raw_points[:, 0], max_distance)

    for i, lane_line in enumerate(self._lane_lines):
      is_current_lane = (i == 1 or i == 2)
      lane_line_width = LANE_LINE_WIDTH
      if self._hide_camera_view or self._rad_racer or self._theme_pack is not None:
        lane_line_width = MINIMAL_VIEW_LANE_LINE_WIDTH if is_current_lane else MINIMAL_VIEW_OUTER_LANE_LINE_WIDTH
      lane_line.projected_points = self._map_line_to_polygon(
        lane_line.raw_points, lane_line_width * self._lane_line_probs[i], 0.0, max_idx, max_distance
      )

    # BluePilot: Rad Racer solid outer lines are thicker than minimal view
    if self._rad_racer:
      road_edge_width = RAD_RACER_ROAD_EDGE_WIDTH
    elif self._hide_camera_view or self._theme_pack is not None:
      road_edge_width = MINIMAL_VIEW_ROAD_EDGE_WIDTH
    else:
      road_edge_width = ROAD_EDGE_WIDTH
    for road_edge in self._road_edges:
      road_edge.projected_points = self._map_line_to_polygon(road_edge.raw_points, road_edge_width, 0.0, max_idx, max_distance)

    self._apply_smooth_path()

  # Pre-computed Gaussian kernel weights for spatial smoothing (exp(-0.5 * j^2) for j=-2..2)
  _GAUSS_KERNEL = np.array([np.exp(-0.5 * j * j) for j in range(-2, 3)], dtype=np.float32)

  def _apply_smooth_path(self):
    """Apply Gaussian-weighted spatial smoothing with temporal damping to reduce path sway."""
    if self._path.projected_points.size == 0:
      return

    n = len(self._path.projected_points)
    if n < 4:
      self._previous_path_projected_points = self._path.projected_points.copy()
      return

    smoothed = self._path.projected_points.copy()

    # Vectorized Gaussian smoothing of y-coordinates for interior points
    y = self._path.projected_points[:, 1]
    kernel = self._GAUSS_KERNEL
    # np.convolve with 'same' mode applies the kernel across all points; we only use interior results
    conv = np.convolve(y, kernel, mode='same')
    # Weight sums vary at edges; compute them the same way
    ones = np.ones(n, dtype=np.float32)
    weight_sums = np.convolve(ones, kernel, mode='same')
    # Apply only to interior points (indices 2..n-2)
    smoothed[2:n-1, 1] = conv[2:n-1] / weight_sums[2:n-1]

    # Vectorized temporal damping
    if (self._previous_path_projected_points.size > 0 and
        len(self._previous_path_projected_points) == n):
      damping = self._path_smoothing_damping
      smoothed[:, 1] = self._previous_path_projected_points[:, 1] + \
        (smoothed[:, 1] - self._previous_path_projected_points[:, 1]) * (1.0 - damping)

    self._previous_path_projected_points = smoothed.copy()
    self._path.projected_points = smoothed

  def _draw_lane_lines(self):
    """Draw lane lines with enhanced rendering and glow effects."""
    # BluePilot: Rad Racer theme replaces all road rendering with green game lines
    if self._rad_racer:
      self._draw_rad_racer_road()
      return
    self._draw_enhanced_lane_lines()

  # BluePilot: _rad_racer_road_color / _draw_rad_racer_road / _draw_curbed_line /
  # _draw_road_ribbon_quad / _draw_dashed_line moved verbatim to RadRacerRoadMixin
  # (rad_racer_road.py) so the comma four renderer can share them.

  def _draw_blindspot_lanes(self, sm):
    """Custom: a car in the blind spot tints the neighbouring lane red for the first 35 m;
    signalling into it makes the tint stronger and pulse."""
    if not ui_state.blindspot:
      return
    cs = sm['carState']
    lines = self._lane_lines
    if len(lines) < 4:
      return
    pulse = 0.5 + 0.5 * np.sin(time.monotonic() * 2 * np.pi / 0.8)
    for bs, blinker, (a, b) in ((cs.leftBlindspot, cs.leftBlinker, (0, 1)), (cs.rightBlindspot, cs.rightBlinker, (2, 3))):
      if not bs or lines[a].raw_points.size == 0 or lines[b].raw_points.size == 0:
        continue
      mid = (lines[a].raw_points + lines[b].raw_points) / 2
      max_idx = self._get_path_length_idx(mid[:, 0], BLINDSPOT_LANE_M)
      poly = self._map_line_to_polygon(mid, BLINDSPOT_HALF_W, 0.0, max_idx, BLINDSPOT_LANE_M)
      if poly.size == 0:
        continue
      alpha = (0.35 + 0.25 * pulse) if blinker else 0.28
      gradient = Gradient(start=(0.0, 1.0), end=(0.0, 0.0), stops=[0.0, 0.7, 1.0],
                          colors=[with_alpha(Console.DANGER_FILL, int(255 * alpha)), with_alpha(Console.DANGER_FILL, int(200 * alpha)),
                                  with_alpha(Console.DANGER_FILL, 0)])
      # fade over the tint's own length (the gradient shader is in gl_FragCoord, bottom-left origin, so the
      # box is given flipped), and stop it under the speed card so it never shows through the translucent tile
      lo, hi = poly.min(axis=0), poly.max(axis=0)
      box = rl.Rectangle(float(lo[0]), float(gui_app.height - hi[1]), float(max(hi[0] - lo[0], 1.0)),
                         float(max(hi[1] - lo[1], 1.0)))
      card = self.avoid_rect
      top = int(card.y + card.height) if card is not None and card.width > 0 else 0
      rl.begin_scissor_mode(0, top, int(gui_app.width), int(gui_app.height) - top)
      draw_polygon(box, poly, gradient=gradient)
      rl.end_scissor_mode()

  def _get_ll_color(self, prob: float, is_current_lane: bool) -> rl.Color:
    """Get lane line color based on UI status with confidence-based brightness.

    Current lanes use status color (green when engaged, gray on override, black when disengaged).
    Outer lanes use white. All lanes go black when disengaged.
    When BPDisableLaneLineStatusColor is enabled, current lanes use white instead of status color.
    """
    if self._hide_camera_view and ui_state.status != UIStatus.ENGAGED:
      return MINIMAL_VIEW_NEUTRAL_LANE_COLOR

    # Custom: Console lane lines are white (dim when disengaged); the engagement colour lives in
    # the path, so lines and path no longer compete. White in both themes: they sit on the camera.
    if ui_state.status == UIStatus.DISENGAGED:
      return ROAD_WHITE_DIM

    # BluePilot: theme pack lane color replaces the Console white
    if self._theme_pack is not None:
      pack_color = self._theme_pack.rl_colors().get("LaneLines")
      if pack_color is not None:
        return pack_color

    return ROAD_WHITE
    # Custom: end

  def _draw_enhanced_lane_lines(self):
    """Draw enhanced lane lines with glow effects and confidence-based brightness."""
    # Custom: Console - our lane's two lines solid by confidence, neighbouring lines faint, road
    # edges red; each group can be hidden from the Road view settings. No glow, except under a
    # theme pack whose colours are meant to read as glow.
    show_lanes = road_prefs.on(SHOW_LANES)
    show_next = road_prefs.on(SHOW_NEIGHBOURS)
    rainbow_lane_lines_active = self._rainbow_lane_lines_active(ui_state.sm)
    for i, lane_line in enumerate(self._lane_lines):
      if lane_line.projected_points.size == 0 or self._lane_line_probs[i] < 0.4:
        continue
      is_current_lane = (i == 1 or i == 2)
      if not (show_lanes if is_current_lane else (show_lanes and show_next)):
        continue

      alpha = float(np.clip(self._lane_line_probs[i], 0.4, 1.0)) * (0.9 if is_current_lane else 0.35)
      if rainbow_lane_lines_active and is_current_lane:
        draw_rainbow_polygon(self._rect, lane_line.projected_points, rainbow_v=self._rainbow_v, alpha=alpha * 0.75)
      else:
        color = self._get_ll_color(float(self._lane_line_probs[i]), is_current_lane)
        draw_polygon(self._rect, lane_line.projected_points, with_alpha(color, int(alpha * 255)))

    if self._theme_pack is not None and show_lanes:
      self._draw_lane_glow_effects()

    if road_prefs.on(SHOW_EDGES):
      for i, road_edge in enumerate(self._road_edges):
        if road_edge.projected_points.size == 0:
          continue
        edge_alpha = np.clip(1.0 - self._road_edge_stds[i], 0.0, 1.0) * 0.6
        draw_polygon(self._rect, road_edge.projected_points, with_alpha(self._road_edge_base_color(), int(edge_alpha * 255)))
      if self._theme_pack is not None:
        self._draw_road_edge_glow_effects()
    # Custom: end

  def _draw_lane_glow_effects(self):
    """Draw single glow layer around lane lines with confidence-based brightness.

    Reduced from 3 layers to 1 for performance (saves ~8 draw_polygon + _expand_polygon calls/frame).
    """
    rainbow_lane_lines_active = self._rainbow_lane_lines_active(ui_state.sm)
    for i, lane_line in enumerate(self._lane_lines):
      if lane_line.projected_points.size == 0 or self._lane_line_probs[i] < 0.4:
        continue
      base_alpha = np.clip(self._lane_line_probs[i] * 0.8, 0.3, 0.8)
      is_current_lane = (i == 1 or i == 2)
      if rainbow_lane_lines_active and is_current_lane:
        continue
      if not is_current_lane:
        base_alpha *= 0.4
      base_color = self._get_ll_color(float(self._lane_line_probs[i]), is_current_lane)
      expanded_points = self._expand_polygon(lane_line.projected_points, 12.0)
      if expanded_points.size > 0:
        # Themed lanes get a stronger halo so the pack color reads as glow, not just a line
        glow_mult = 0.22 if self._theme_pack is not None else 0.12
        alpha = int(base_alpha * glow_mult * 255)
        color = rl.Color(base_color.r, base_color.g, base_color.b, alpha)
        draw_polygon(self._rect, expanded_points, color)

  def _road_edge_base_color(self) -> rl.Color:
    """Road edge color: theme pack RoadEdges when set, stock red otherwise."""
    if self._theme_pack is not None:
      pack_color = self._theme_pack.rl_colors().get("RoadEdges")
      if pack_color is not None:
        return pack_color
    return ROAD_EDGE_COLOR  # Custom: Console danger red

  def _rainbow_lane_lines_active(self, sm) -> bool:
    """Return true when inner lane lines should use the rainbow shader."""
    if not self._rainbow_lane_lines or self._disable_lane_line_status_color:
      return False

    if sm.valid.get('carControl', False) and sm['carControl'].longActive:
      return True

    return ui_state.status in (UIStatus.ENGAGED, UIStatus.LONG_ONLY)

  def _draw_road_edge_glow_effects(self):
    """Draw single glow layer around road edges.

    Reduced from 3 layers to 1 for performance (saves ~4 draw_polygon + _expand_polygon calls/frame).
    """
    for i, road_edge in enumerate(self._road_edges):
      if road_edge.projected_points.size == 0:
        continue
      edge_alpha = np.clip(1.0 - self._road_edge_stds[i], 0.0, 1.0)
      if edge_alpha < 0.3:
        continue
      expanded_points = self._expand_polygon(road_edge.projected_points, 18.0)
      if expanded_points.size > 0:
        glow_mult = 0.16 if self._theme_pack is not None else 0.08
        alpha = int(edge_alpha * glow_mult * 255)
        edge_base = self._road_edge_base_color()
        color = rl.Color(edge_base.r, edge_base.g, edge_base.b, alpha)
        draw_polygon(self._rect, expanded_points, color)

  def _expand_polygon(self, points: np.ndarray, width: float) -> np.ndarray:
    """Expand ribbon polygon outward for glow effect, tapering at ends.

    The polygon is a ribbon in [L0..Lk-1, Rk-1..R0] order. The expansion
    width is scaled proportionally to the local ribbon width so the glow
    tapers naturally where the line narrows (near the horizon and at the
    bottom of screen) instead of creating blobs at the ends.
    """
    if points.size == 0 or len(points) < 4:
      return np.empty((0, 2), dtype=np.float32)

    n = len(points)
    half = n // 2

    # Vectorized local ribbon widths
    left = points[:half]
    right = points[n - 1:n - 1 - half:-1]  # reversed right side
    local_widths = np.linalg.norm(right - left, axis=1)

    max_width = np.max(local_widths)
    if max_width < 1e-6:
      return np.empty((0, 2), dtype=np.float32)

    # Per-vertex scale: proportional to local ribbon width
    scales = np.empty(n, dtype=np.float32)
    s = local_widths / max_width
    scales[:half] = s
    scales[n - 1:n - 1 - half:-1] = s

    # Vectorized edge and normal computation
    prev_idx = np.arange(n) - 1
    prev_idx[0] = n - 1
    next_idx = np.arange(n) + 1
    next_idx[-1] = 0

    edge1 = points - points[prev_idx]  # (n, 2)
    edge2 = points[next_idx] - points  # (n, 2)

    len1 = np.linalg.norm(edge1, axis=1, keepdims=True)
    len2 = np.linalg.norm(edge2, axis=1, keepdims=True)
    len1 = np.where(len1 < 1e-6, 1.0, len1)
    len2 = np.where(len2 < 1e-6, 1.0, len2)
    edge1 = edge1 / len1
    edge2 = edge2 / len2

    # Normals: rotate edges 90 degrees ([-y, x])
    normal1 = np.stack([-edge1[:, 1], edge1[:, 0]], axis=1)
    normal2 = np.stack([-edge2[:, 1], edge2[:, 0]], axis=1)
    normal = (normal1 + normal2) * 0.5
    normal_len = np.linalg.norm(normal, axis=1, keepdims=True)
    normal_len = np.where(normal_len < 1e-6, 1.0, normal_len)
    normal = normal / normal_len

    return (points + normal * (width * scales)[:, None]).astype(np.float32)

  def _draw_path(self, sm):
    """Draw path with status-colored edges."""
    # BluePilot: Rad Racer theme draws the path as a dashed center line in _draw_rad_racer_road
    if self._rad_racer:
      return

    if not self._path.projected_points.size:
      return

    if ui_state.rainbow_path:
      draw_rainbow_polygon(self._rect, self._path.projected_points, rainbow_v=self._rainbow_v)
    elif (themed_gradient := self._themed_path_gradient()) is not None:
      # BluePilot: theme pack path colors replace the throttle/no-throttle gradient
      draw_polygon(self._rect, self._path.projected_points, gradient=themed_gradient)
      self._draw_path_edges()
    elif self._experimental_mode:
      super()._draw_path(sm)
    else:
      # Custom: Console path - a soft ribbon in the engagement colour fading toward the horizon,
      # neutral while the plan is not asking for throttle. No status-coloured edges.
      allow_throttle = sm['longitudinalPlan'].allowThrottle or not self._longitudinal_control
      self._blend_filter.update(int(allow_throttle))
      t = round(self._blend_filter.x * 100) / 100
      status = LANE_LINE_COLORS_BP.get(ui_state.status, LANE_LINE_COLORS_BP[UIStatus.DISENGAGED])
      if ui_state.status == UIStatus.DISENGAGED:
        status = ROAD_WHITE
      base = mix(ROAD_WHITE, status, t)
      gradient = Gradient(start=(0.0, 1.0), end=(0.0, 0.0),
                          colors=[with_alpha(base, 120), with_alpha(base, 80), with_alpha(base, 0)], stops=[0.0, 0.55, 1.0])
      draw_polygon(self._rect, self._path.projected_points, gradient=gradient)
      # Custom: end

  def _themed_path_gradient(self) -> Gradient | None:
    """Bottom-to-top path gradient from the active theme pack, or None.

    PathEdge tints the near end, Path carries the ribbon and fades out at the horizon —
    same alpha profile as the stock throttle gradient so depth perception is unchanged.
    """
    if self._theme_pack is None:
      return None
    colors = self._theme_pack.rl_colors()
    path = colors.get("Path")
    if path is None:
      return None
    edge = colors.get("PathEdge", path)
    return Gradient(
      start=(0.0, 1.0),
      end=(0.0, 0.0),
      colors=[rl.Color(edge.r, edge.g, edge.b, 190), rl.Color(path.r, path.g, path.b, 150), rl.Color(path.r, path.g, path.b, 30)],
      stops=[0.0, 0.5, 1.0],
    )

  def _draw_path_edges(self):
    """Draw path edges (left, right, and front) with status-based colors.

    Uses rl.draw_line_strip for batched line rendering instead of individual draw_line_ex calls.
    """
    if not self._path.projected_points.size:
      return

    points = self._path.projected_points
    num_points = len(points)
    mid_point = num_points // 2
    if mid_point < 2:
      return

    left_edge = points[:mid_point]
    right_edge = points[mid_point:][::-1]

    pack_edge = self._theme_pack.rl_colors().get("PathEdge") if self._theme_pack is not None else None
    if pack_edge is not None and ui_state.status != UIStatus.DISENGAGED:
      # BluePilot: theme pack path edge color (disengaged keeps the status blackout)
      edge_color = pack_edge
    elif self._disable_lane_line_status_color and ui_state.status != UIStatus.DISENGAGED:
      edge_color = rl.Color(255, 255, 255, 255)
    else:
      edge_color = LANE_LINE_COLORS_BP.get(ui_state.status, LANE_LINE_COLORS_BP[UIStatus.DISENGAGED])

    # Convert each polyline edge into a thin ribbon polygon (2 draw_polygon calls vs ~65 draw_line_ex).
    # This preserves the ~4px visual thickness while batching into 2 GPU calls.
    half_w = 2.0  # Half of the 4px line thickness
    for edge_pts in (left_edge, right_edge):
      if len(edge_pts) < 2:
        continue
      # Offset each point perpendicular to its segment to form a ribbon
      ribbon = self._line_to_ribbon(edge_pts, half_w)
      if ribbon.size > 0:
        draw_polygon(self._rect, ribbon, edge_color)

    # Front connecting line (single call)
    if len(left_edge) > 0 and len(right_edge) > 0:
      rl.draw_line_ex(
        rl.Vector2(float(left_edge[-1][0]), float(left_edge[-1][1])),
        rl.Vector2(float(right_edge[-1][0]), float(right_edge[-1][1])),
        4.0, edge_color
      )

  @staticmethod
  def _line_to_ribbon(pts: np.ndarray, half_w: float) -> np.ndarray:
    """Convert a polyline into a ribbon polygon of given half-width.

    Returns points in [L0..Ln, Rn..R0] order suitable for draw_polygon.
    """
    n = len(pts)
    if n < 2:
      return np.empty((0, 2), dtype=np.float32)
    # Compute segment directions
    diffs = np.diff(pts, axis=0)  # (n-1, 2)
    lengths = np.linalg.norm(diffs, axis=1, keepdims=True)
    lengths = np.where(lengths < 1e-6, 1.0, lengths)
    dirs = diffs / lengths
    # Per-vertex normals: average of adjacent segment normals
    normals = np.empty((n, 2), dtype=np.float32)
    seg_normals = np.stack([-dirs[:, 1], dirs[:, 0]], axis=1)  # rotate 90°
    normals[0] = seg_normals[0]
    normals[-1] = seg_normals[-1]
    normals[1:-1] = (seg_normals[:-1] + seg_normals[1:]) * 0.5
    nlen = np.linalg.norm(normals, axis=1, keepdims=True)
    nlen = np.where(nlen < 1e-6, 1.0, nlen)
    normals = normals / nlen
    # Build ribbon: left side then right side reversed
    left = pts + normals * half_w
    right = pts - normals * half_w
    return np.vstack([left, right[::-1]]).astype(np.float32)

  def _draw_lead_indicator(self):
    """Custom: Console - a squared bracket under each lead, coloured by time to the lead. Radar
    leads get a closed base; camera-only leads an open one. (Replaces the radar/vision chevrons;
    the numbers that the Ford radar overlay drew beside the chevron now live in the lead card.)"""
    for i, mark in enumerate(self._lead_marks):
      if mark is None:
        continue
      if i == 1 and self._lead_marks[0] is not None and abs(self._lead_d_smooth[0] - self._lead_d_smooth[1]) < 3.0:
        continue
      x, y, w = mark
      v_ego = ui_state.sm['carState'].vEgo
      info = LeadInfo(d_rel=self._lead_d_smooth[i], v_rel=self._lead_v_smooth[i], v_ego=v_ego)
      alpha = self.lead_alpha if i == 0 else 0.6
      draw_lead_marker(x, y, w, lead_level(info), alpha, vision=not self._lead_is_radar[i])
      if i == 0 and road_prefs.on(SHOW_SPEED_TAG):
        info.v_lead = max(0.0, v_ego + info.v_rel)
        draw_speed_tag(x, y, w, info, ui_state.is_metric, alpha, self._rect)

