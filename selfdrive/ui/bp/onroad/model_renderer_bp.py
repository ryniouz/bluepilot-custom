import time

import numpy as np
import pyray as rl
from openpilot.common.filter_simple import FirstOrderFilter
from openpilot.common.params import Params
from openpilot.selfdrive.ui.onroad.model_renderer import ModelRenderer, LeadVehicle, CLIP_MARGIN, MIN_DRAW_DISTANCE, MAX_DRAW_DISTANCE
from openpilot.selfdrive.ui.bp.onroad.chevron_metrics_bp import ChevronMetricsBP
from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.shader_polygon import draw_polygon
from openpilot.selfdrive.ui.bp.lib.ui_debug_logger import bp_ui_log
from openpilot.selfdrive.ui.bp.onroad.road_view import (LeadInfo, SHOW_EDGES, SHOW_LANES, SHOW_NEIGHBOURS, SHOW_SPEED_TAG,
                                                        draw_lead_marker, draw_speed_tag,
                                                        lead_level, road_prefs)
from openpilot.system.ui.lib.shader_polygon import Gradient
from bluepilot.ui.lib.theme import Console, Onroad, mix, with_alpha
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

# BluePilot: Overlay size scale factors (Small=0, Medium=1, Large=2)
OVERLAY_SCALE_FACTORS = {0: 0.6, 1: 1.0, 2: 1.5}


CAR_HALF_W = 0.95          # m, half a typical car width


class ModelRendererBP(ModelRenderer):
  """BluePilot ModelRenderer with enhanced lane lines, path smoothing, and radar overlay."""

  def __init__(self):
    super().__init__()
    self._lc_fx = LaneChangeFx()
    self._bp_params = Params()

    # BluePilot: Replace SP chevron metrics with BP version (horizontal boxed layout)
    self.chevron_metrics = ChevronMetricsBP()

    # Path smoothing: store previous smoothed path for temporal damping
    self._previous_path_projected_points = np.empty((0, 2), dtype=np.float32)
    self._path_smoothing_damping = 0.3

    # BluePilot: Track whether each lead is radar-sourced
    self._lead_is_radar = [False, False]

    # BluePilot: Overlay size scale factor (read from param periodically)
    self._overlay_scale = 1.0

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

  def _render(self, rect: rl.Rectangle):
    sm = ui_state.sm

    if ui_state.rainbow_path:
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
    self._counter += 1

    if sm.updated['carParams']:
      self._longitudinal_control = sm['carParams'].openpilotLongitudinalControl

    model = sm['modelV2']
    radar_state = sm['radarState'] if sm.valid['radarState'] else None
    lead_one = radar_state.leadOne if radar_state else None

    # BluePilot: Ford radar overlay feature - show leads even without longitudinal control
    self.ford_overlay_enabled = self._bp_params.get_bool("FordPrefShowRadarLeadOverlay")
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

    self._draw_lane_lines()
    self._draw_blindspot_lanes(sm)
    self._draw_path(sm)
    # Custom: looping lane change cue toward the target lane
    self._lc_fx.render(self, sm, road_prefs.lane_change)

    # Custom: Console lead marker; the numbers go to the lead card (drawn by the road view)
    has_lead = bool(render_lead_indicator and radar_state and radar_state.leadOne.status)
    self.lead_alpha += ((1.0 if has_lead else 0.0) - self.lead_alpha) * 0.25
    if has_lead:
      lo = radar_state.leadOne
      v_ego = sm['carState'].vEgo
      self.lead_info = LeadInfo(d_rel=self._lead_d_smooth[0], v_rel=self._lead_v_smooth[0],
                                v_lead=max(0.0, v_ego + self._lead_v_smooth[0]), v_ego=v_ego, radar=bool(getattr(lo, 'radar', False)))
    elif self.lead_alpha < 0.02:
      self.lead_info = None
    if render_lead_indicator and radar_state:
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
    self._lead_marks = [None, None]
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
        self._lead_d_smooth[i], self._lead_v_smooth[i] = d_rel, v_rel

        idx = self._get_path_length_idx(path_x_array, d_rel)
        z = self._path.raw_points[idx, 2] if idx < len(self._path.raw_points) else 0.0
        point = self._map_to_screen(d_rel, -y_rel + self._camera_offset, z + self._path_offset_z)
        # Custom: the car's real width on screen (a typical 1.9 m), so markers and the speed tag fit it
        pl = self._map_to_screen(d_rel, -y_rel + self._camera_offset - CAR_HALF_W, z + self._path_offset_z)
        pr = self._map_to_screen(d_rel, -y_rel + self._camera_offset + CAR_HALF_W, z + self._path_offset_z)
        self._lead_px_w = abs(pr[0] - pl[0]) if (pl is not None and pr is not None) else None
        if point:
          self._marking = i
          self._lead_vehicles[i] = self._update_lead_vehicle(d_rel, v_rel, point, self._rect)

        self._lead_was_active[i] = True
      else:
        self._lead_was_active[i] = False
        self._lead_marks[i] = None

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

    # BluePilot: Redo lane lines and road edges with doubled width (0.05 vs upstream 0.025)
    max_distance = np.clip(path_x_array[-1], MIN_DRAW_DISTANCE, MAX_DRAW_DISTANCE)
    max_idx = self._get_path_length_idx(self._lane_lines[0].raw_points[:, 0], max_distance)

    for i, lane_line in enumerate(self._lane_lines):
      lane_line.projected_points = self._map_line_to_polygon(
        lane_line.raw_points, 0.05 * self._lane_line_probs[i], 0.0, max_idx, max_distance
      )

    for road_edge in self._road_edges:
      road_edge.projected_points = self._map_line_to_polygon(road_edge.raw_points, 0.05, 0.0, max_idx, max_distance)

    self._apply_smooth_path()

  def _apply_smooth_path(self):
    """Apply Gaussian-weighted spatial smoothing with temporal damping to reduce path sway."""
    if self._path.projected_points.size == 0:
      return

    if len(self._path.projected_points) < 4:
      self._previous_path_projected_points = self._path.projected_points.copy()
      return

    n = len(self._path.projected_points)
    smoothed = np.zeros_like(self._path.projected_points)

    for i in range(n):
      pt = self._path.projected_points[i].copy()
      if 1 < i < n - 1:
        y_smooth = 0.0
        weight_sum = 0.0
        for j in range(-2, 3):
          idx = i + j
          if 0 <= idx < n:
            weight = np.exp(-0.5 * j * j)
            y_smooth += self._path.projected_points[idx][1] * weight
            weight_sum += weight
        if weight_sum > 0:
          pt[1] = y_smooth / weight_sum
      smoothed[i] = pt

    if (self._previous_path_projected_points.size > 0 and
        len(self._previous_path_projected_points) == len(smoothed)):
      damping = self._path_smoothing_damping
      for i in range(len(smoothed)):
        y_diff = smoothed[i][1] - self._previous_path_projected_points[i][1]
        smoothed[i][1] = self._previous_path_projected_points[i][1] + y_diff * (1.0 - damping)
    else:
      self._previous_path_projected_points = smoothed.copy()

    self._previous_path_projected_points = smoothed.copy()
    self._path.projected_points = smoothed

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
      draw_polygon(self._rect, poly, gradient=gradient)

  def _draw_lane_lines(self):
    """Draw lane lines with enhanced rendering and glow effects."""
    self._draw_enhanced_lane_lines()

  def _get_ll_color(self, prob: float, is_current_lane: bool) -> rl.Color:
    """Custom: Console lane lines are white (ghost grey when disengaged); the engagement colour
    lives in the path, so lines and path no longer compete. White in both themes: they sit on
    the camera, not on a Console surface."""
    if ui_state.status == UIStatus.DISENGAGED:
      return ROAD_WHITE_DIM
    return ROAD_WHITE

  def _draw_enhanced_lane_lines(self):
    """Custom: our lane's two lines solid by confidence, neighbouring lines faint, road edges red;
    each group can be hidden from the Road view settings."""
    show_lanes = road_prefs.on(SHOW_LANES)
    show_next = road_prefs.on(SHOW_NEIGHBOURS)
    for i, lane_line in enumerate(self._lane_lines):
      if lane_line.projected_points.size == 0 or self._lane_line_probs[i] < 0.4:
        continue
      is_current_lane = (i == 1 or i == 2)
      if not (show_lanes if is_current_lane else (show_lanes and show_next)):
        continue
      alpha = float(np.clip(self._lane_line_probs[i], 0.4, 1.0)) * (0.9 if is_current_lane else 0.35)
      color = self._get_ll_color(float(self._lane_line_probs[i]), is_current_lane)
      draw_polygon(self._rect, lane_line.projected_points, with_alpha(color, int(alpha * 255)))

    if road_prefs.on(SHOW_EDGES):
      for i, road_edge in enumerate(self._road_edges):
        if road_edge.projected_points.size == 0:
          continue
        edge_alpha = np.clip(1.0 - self._road_edge_stds[i], 0.0, 1.0) * 0.6
        draw_polygon(self._rect, road_edge.projected_points, with_alpha(ROAD_EDGE_COLOR, int(edge_alpha * 255)))

  def _draw_path(self, sm):
    """Custom: the path is a soft ribbon in the engagement colour fading toward the horizon, and
    turns neutral while the plan is not asking for throttle. Experimental mode and rainbow keep
    their own colouring."""
    if not self._path.projected_points.size:
      return
    if ui_state.rainbow_path:
      draw_polygon(self._rect, self._path.projected_points, rainbow=True, rainbow_v=self._rainbow_v)
      return
    if self._experimental_mode:
      super()._draw_path(sm)
      return

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

  def _draw_lead_indicator(self):
    """Custom: a squared bracket under each lead, coloured by time to the lead. Radar leads get a
    closed base; camera-only leads an open one."""
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

