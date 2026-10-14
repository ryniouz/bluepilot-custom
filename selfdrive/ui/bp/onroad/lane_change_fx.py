"""
Console lane-change overlay: while openpilot is changing lanes, a translucent looping cue on the
road shows where the truck is merging to.

  chevrons  four chevrons stream along an S-curve from our lane into the target lane
  lane      the target lane is tinted, a brighter band sweeps forward along it, and a thin S-arrow points in
  arrow     a translucent arrow grows from our lane into the target lane and lights up a truck-sized
            box where the truck will end up (the default)

Shown only in laneChangeStarting / laneChangeFinishing (openpilot has committed to the change), so
a blocked change (blind spot) never shows it. The style is chosen in Quick controls > Road view and
stored in BPRoadView bits 11-12 (see road_view.LC_STYLES). Drawing only; no control logic.
"""

from __future__ import annotations

import math

import numpy as np
import pyray as rl
from cereal import log

from openpilot.system.ui.lib.shader_polygon import draw_polygon
from bluepilot.ui.lib.theme import Console, with_alpha

LaneChangeState = log.LaneChangeState
LaneChangeDirection = log.LaneChangeDirection

X_START = 6.0          # m ahead where the cue starts
X_END = 34.0           # m ahead where it ends in the target lane
MERGE_LEN = 15.0       # m over which the S-curve moves across
LANE_W = 3.7           # fallback lane width when the model has no neighbouring line
SAMPLES = 36
SPOT_LEN = 5.9         # F-150 Lightning length, m
SPOT_HALF_W = 1.05     # half its width, m
PERIOD = {"chevrons": 1.2, "lane": 1.4, "arrow": 1.6, "glide": 1.8, "brackets": 1.5, "pointer": 1.4}


def _smoothstep(u: np.ndarray) -> np.ndarray:
  u = np.clip(u, 0.0, 1.0)
  return u * u * (3 - 2 * u)


def _fill(r, poly: np.ndarray, color: rl.Color):
  """draw_polygon with the winding the stock ribbons use; raylib culls back faces, so flip it if needed."""
  x, y = poly[:, 0], poly[:, 1]
  if float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y)) < 0:
    poly = poly[::-1]
  draw_polygon(r._rect, np.ascontiguousarray(poly, dtype=np.float32), color=color)


class LaneChangeFx:
  def __init__(self):
    self._alpha = 0.0
    self._dir = LaneChangeDirection.none
    self._edges: tuple[np.ndarray, np.ndarray] | None = None  # target lane's two lines, (SAMPLES, 3) each
    self.phase_override: float | None = None  # tests and design previews: hold the loop at this phase

  # -- geometry --------------------------------------------------------------------------------

  @staticmethod
  def _interp(points: np.ndarray, xs: np.ndarray) -> tuple[np.ndarray, np.ndarray] | None:
    if points.size == 0 or points.shape[0] < 2:
      return None
    return np.interp(xs, points[:, 0], points[:, 1]), np.interp(xs, points[:, 0], points[:, 2])

  def _curve(self, r, left: bool) -> np.ndarray | None:
    """(SAMPLES, 3) points in car space: our lane centre bending into the target lane centre."""
    xs = np.linspace(X_START, X_END, SAMPLES)
    lines = [self._interp(ll.raw_points, xs) for ll in r._lane_lines] if len(r._lane_lines) >= 4 else []
    self._edges = None
    if len(lines) >= 4 and lines[1] is not None and lines[2] is not None:
      oy, oz = (lines[1][0] + lines[2][0]) / 2, (lines[1][1] + lines[2][1]) / 2
      a, b = (0, 1) if left else (2, 3)
      if lines[a] is not None and lines[b] is not None:
        ty, tz = (lines[a][0] + lines[b][0]) / 2, (lines[a][1] + lines[b][1]) / 2
        self._edges = (np.column_stack([xs, lines[a][0], lines[a][1]]), np.column_stack([xs, lines[b][0], lines[b][1]]))
      else:
        ty, tz = oy + (-LANE_W if left else LANE_W), oz
    else:
      path = self._interp(r._path.raw_points, xs)
      if path is None:
        return None
      oy, oz = path
      ty, tz = oy + (-LANE_W if left else LANE_W), oz
    blend = _smoothstep((xs - X_START - 1.0) / MERGE_LEN)
    return np.column_stack([xs, oy * (1 - blend) + ty * blend, oz * (1 - blend) + tz * blend])

  @staticmethod
  def _at(curve: np.ndarray, u: float) -> tuple[np.ndarray, np.ndarray]:
    """Point and unit ground-plane tangent at fraction u of the curve."""
    f = min(max(u, 0.0), 1.0) * (len(curve) - 1)
    i = min(int(f), len(curve) - 2)
    t = f - i
    p = curve[i] * (1 - t) + curve[i + 1] * t
    d = curve[i + 1] - curve[i]
    n = math.hypot(d[0], d[1]) or 1.0
    return p, np.array([d[0] / n, d[1] / n, 0.0])

  @staticmethod
  def _proj(r, p: np.ndarray):
    s = r._map_to_screen(float(p[0]), float(p[1]), float(p[2]))
    return None if s is None else rl.Vector2(float(s[0]), float(s[1]))

  # -- styles ----------------------------------------------------------------------------------

  def _screen_frame(self, r, curve, u: float):
    """Screen point, screen unit direction along the curve, its normal, and pixels per metre at u."""
    p, d = self._at(curve, u)
    side = np.array([-d[1], d[0], 0.0])
    a, b, c = self._proj(r, p), self._proj(r, p + d * 2.0), self._proj(r, p + side)
    if a is None or b is None or c is None:
      return None
    dx, dy = b.x - a.x, b.y - a.y
    n = math.hypot(dx, dy) or 1.0
    return a, (dx / n, dy / n), (-dy / n, dx / n), math.hypot(c.x - a.x, c.y - a.y)

  def _chevron_2d(self, at, dirv, nrm, half_w: float, depth: float, thick: float, color: rl.Color, r):
    """A V band in screen space pointing along dirv: arms at -depth, tip at 0, thick px deep."""
    def pt(along, across):
      return [at.x + dirv[0] * along + nrm[0] * across, at.y + dirv[1] * along + nrm[1] * across]
    front = [pt(-depth, half_w), pt(0, 0), pt(-depth, -half_w)]
    back = [pt(-depth - thick, half_w), pt(-thick, 0), pt(-depth - thick, -half_w)]
    _fill(r, np.array(front + back[::-1], dtype=np.float32), color)

  def _chevrons(self, r, curve, phase, color):
    n = 4
    for k in range(n):
      u = (k + phase) / n
      fade = math.sin(math.pi * u)  # fade in near the truck, out at the far end
      f = self._screen_frame(r, curve, u)
      if f is None:
        continue
      at, dirv, nrm, ppm = f
      w = min(1.3 * ppm, 120.0)
      self._chevron_2d(at, dirv, nrm, w, w * 0.7, w * 0.45, with_alpha(color, int(160 * fade * self._alpha)), r)

  def _ribbon(self, r, pts: np.ndarray, half_w: float, color: rl.Color):
    if len(pts) < 2:
      return
    poly = r._map_line_to_polygon(pts, half_w, 0.0, len(pts) - 1, float(pts[-1][0]))
    if poly.size:
      _fill(r, poly, color)

  def _head(self, r, curve, u: float, size_m: float, color: rl.Color, aim: np.ndarray | None = None):
    """Filled arrowhead at fraction u of the curve, in screen space so perspective does not flatten it."""
    f = self._screen_frame(r, curve, u)
    if f is None:
      return
    at, dirv, _, ppm = f
    # point at `aim` (the landing spot) when given, else along the arrow's visible sweep (a chord over
    # the last stretch): past the merge the local tangent runs at the vanishing point and looks sideways
    ref = self._proj(r, aim) if aim is not None else self._proj(r, self._at(curve, max(0.0, u - 0.3))[0])
    if ref is None:
      return
    dx, dy = (ref.x - at.x, ref.y - at.y) if aim is not None else (at.x - ref.x, at.y - ref.y)
    n = math.hypot(dx, dy) or 1.0
    dirv, nrm = (dx / n, dy / n), (-dy / n, dx / n)
    w = min(size_m * ppm, 64.0)
    tip = (at.x + dirv[0] * w * 1.9, at.y + dirv[1] * w * 1.9)
    a = (at.x + nrm[0] * w * 0.62, at.y + nrm[1] * w * 0.62)
    c = (at.x - nrm[0] * w * 0.62, at.y - nrm[1] * w * 0.62)
    _fill(r, np.array([a, tip, tip, c], dtype=np.float32), color)

  def _lane(self, r, curve, phase, color):
    if self._edges is not None:
      ea, eb = self._edges
      lo, hi = int(len(curve) * 0.35), len(curve)

      def band(i0, i1, alpha):
        pa = [self._proj(r, q) for q in ea[i0:i1]]
        pb = [self._proj(r, q) for q in eb[i0:i1]]
        pts = [v for v in pa + pb[::-1] if v is not None]
        if len(pts) >= 4 and len(pts) % 2 == 0:
          _fill(r, np.array([[v.x, v.y] for v in pts], dtype=np.float32), with_alpha(color, alpha))

      band(lo, hi, int(45 * self._alpha))
      i1 = lo + int(phase * (hi - lo + 6))
      band(max(lo, i1 - 6), min(hi, i1), int(110 * math.sin(math.pi * phase) * self._alpha))
    self._ribbon(r, curve, 0.3, with_alpha(color, int(150 * self._alpha)))
    self._head(r, curve, 1.0, 0.9, with_alpha(color, int(150 * self._alpha)))

  @staticmethod
  def _spot_x() -> tuple[float, float]:
    x0 = X_START + 1.0 + MERGE_LEN * 0.85
    return x0, x0 + SPOT_LEN

  def _spot_centre(self, curve) -> np.ndarray:
    x = sum(self._spot_x()) / 2
    return np.array([x, np.interp(x, curve[:, 0], curve[:, 1]), np.interp(x, curve[:, 0], curve[:, 2])])

  def _spot(self, r, curve, glow: float, color: rl.Color):
    """Where the truck ends up: a truck-sized footprint in the target lane, past the end of the merge."""
    x0, x1 = self._spot_x()
    i0, i1 = np.searchsorted(curve[:, 0], [x0, x1])
    seg = curve[max(0, i0 - 1):min(len(curve), i1 + 1)]
    if len(seg) < 2:
      return
    ys, zs = np.interp([x0, x1], seg[:, 0], seg[:, 1]), np.interp([x0, x1], seg[:, 0], seg[:, 2])
    pts = [np.array([x, y + side * SPOT_HALF_W, z]) for (x, y, z), side in
           (((x0, ys[0], zs[0]), -1), ((x1, ys[1], zs[1]), -1), ((x1, ys[1], zs[1]), 1), ((x0, ys[0], zs[0]), 1))]
    scr = [self._proj(r, q) for q in pts]
    if None in scr:
      return
    _fill(r, np.array([[v.x, v.y] for v in scr], dtype=np.float32), with_alpha(color, int((28 + 40 * glow) * self._alpha)))
    edge = with_alpha(color, int((90 + 110 * glow) * self._alpha))
    for a, b in zip(scr, scr[1:] + scr[:1], strict=True):
      rl.draw_line_ex(a, b, 5.0, edge)

  def _arrow(self, r, curve, phase, color):
    """Lucas's pick (2026-10-14): a translucent arrow sweeps from our lane into the landing spot, the
    spot lights up as it arrives, then both fade and the loop starts again.

    The arrow is a screen-space curve between two road points (our lane just ahead, the back of the
    spot) so it reads as an arrow at any camera height; a band painted flat on the road foreshortens
    into a sliver over the short distance a lane change covers."""
    x0, _ = self._spot_x()
    start = self._proj(r, curve[0])
    ahead = self._proj(r, self._at(curve, 0.2)[0] * np.array([1, 0, 1]) + curve[0] * np.array([0, 1, 0]))
    end_p = np.array([x0, np.interp(x0, curve[:, 0], curve[:, 1]), np.interp(x0, curve[:, 0], curve[:, 2])])
    end, fwd = self._proj(r, end_p), self._proj(r, end_p + np.array([6.0, 0, 0]))
    side = self._proj(r, curve[0] + np.array([0, 1.0, 0]))
    if None in (start, ahead, end, fwd, side):
      return
    p0, p3 = np.array([start.x, start.y]), np.array([end.x, end.y])
    span = float(np.linalg.norm(p3 - p0)) or 1.0
    t0 = np.array([ahead.x - start.x, ahead.y - start.y])
    # finish heading straight up the screen (forward, like a navigation arrow) rather than along the
    # lane's perspective line, which runs nearly sideways toward the vanishing point
    t1 = np.array([0.25 * (fwd.x - end.x) / (abs(fwd.y - end.y) or 1.0), -1.0])
    t0 /= np.linalg.norm(t0) or 1.0
    t1 /= np.linalg.norm(t1) or 1.0
    p1, p2 = p0 + t0 * span * 0.45, p3 - t1 * span * 0.35

    grow = 1 - (1 - min(1.0, phase / 0.55)) ** 3
    fade = 1.0 if phase < 0.82 else 1.0 - (phase - 0.82) / 0.18
    ts = np.linspace(0.0, grow, 28)[:, None]
    pts = (1 - ts) ** 3 * p0 + 3 * (1 - ts) ** 2 * ts * p1 + 3 * (1 - ts) * ts ** 2 * p2 + ts ** 3 * p3
    if len(pts) >= 2 and grow > 0.02:
      d = np.gradient(pts, axis=0)
      d /= np.maximum(np.linalg.norm(d, axis=1, keepdims=True), 1e-6)
      nrm = np.column_stack([-d[:, 1], d[:, 0]])
      w0 = min(0.5 * math.hypot(side.x - start.x, side.y - start.y), 56.0)
      half = (w0 + (14.0 - w0) * ts[:, 0])[:, None]  # tapers toward the spot
      band = np.vstack([pts + nrm * half, (pts - nrm * half)[::-1]]).astype(np.float32)
      _fill(r, band, with_alpha(color, int(85 * fade * self._alpha)))
      tip_at, tip_d = pts[-1], d[-1]
      tip_n = np.array([-tip_d[1], tip_d[0]])
      hw = float(half[-1, 0]) * 2.2
      head = np.array([tip_at + tip_n * hw, tip_at + tip_d * hw * 2.2, tip_at + tip_d * hw * 2.2, tip_at - tip_n * hw],
                      dtype=np.float32)
      _fill(r, head, with_alpha(color, int(115 * fade * self._alpha)))
    arrive = max(0.0, min(1.0, (phase - 0.45) / 0.15))
    self._spot(r, curve, arrive * fade, color)

  # -- box-concept options (Lucas 22:42: keep the landing box, try other treatments; he picks one) --------------

  def _box(self, r, curve, xc: float, scale: float = 1.0):
    """Screen corners of a truck-sized box centred xc m ahead, sitting on the curve's lateral position there."""
    y, z = float(np.interp(xc, curve[:, 0], curve[:, 1])), float(np.interp(xc, curve[:, 0], curve[:, 2]))
    hl, hw = SPOT_LEN / 2 * scale, SPOT_HALF_W * scale
    pts = [np.array([xc + a, y + b, z]) for a, b in ((-hl, -hw), (hl, -hw), (hl, hw), (-hl, hw))]
    scr = [self._proj(r, q) for q in pts]
    return None if None in scr else scr

  def _fill_box(self, r, scr, color: rl.Color):
    _fill(r, np.array([[v.x, v.y] for v in scr], dtype=np.float32), color)

  def _outline(self, scr, width: float, color: rl.Color):
    for a, b in zip(scr, scr[1:] + scr[:1], strict=True):
      rl.draw_line_ex(a, b, width, color)
    for v in scr:
      rl.draw_circle_v(v, width / 2, color)

  def _glide(self, r, curve, phase, color):
    """Glide: a ghost of the truck's box slides along the merge into the landing box, two fainter echoes
    behind it; the landing box fills as it arrives. No arrow, the motion itself shows the way."""
    x_land = float(self._spot_centre(curve)[0])
    x_from = X_START + (x_land - X_START) * 0.4  # starts clear of the dock, still in our lane
    move = float(_smoothstep(np.array(min(1.0, phase / 0.75))))
    fade = 1.0 if phase < 0.85 else 1.0 - (phase - 0.85) / 0.15
    land = self._box(r, curve, x_land)
    if land is not None:
      self._fill_box(r, land, with_alpha(color, int((20 + 50 * move) * fade * self._alpha)))
      self._outline(land, 3.0, with_alpha(color, int((70 + 120 * move) * fade * self._alpha)))
    for k, a in ((2, 0.25), (1, 0.5), (0, 1.0)):
      m = max(0.0, move - 0.12 * k)
      ghost = self._box(r, curve, x_from + (x_land - x_from) * m, 0.92)
      if ghost is not None and move < 0.98:
        self._fill_box(r, ghost, with_alpha(color, int(70 * a * fade * self._alpha)))
        if k == 0:
          self._outline(ghost, 3.0, with_alpha(color, int(170 * fade * self._alpha)))

  def _brackets(self, r, curve, phase, color):
    """Brackets: four corner brackets close in on the landing box like a camera focusing, and a dotted
    path of dots flows from our lane into it."""
    x_land = float(self._spot_centre(curve)[0])
    close = float(_smoothstep(np.array(min(1.0, phase / 0.7))))
    fade = 1.0 if phase < 0.85 else 1.0 - (phase - 0.85) / 0.15
    n = 9
    x_end = x_land - SPOT_LEN / 2
    for k in range(n):
      u = (k + (phase * 3) % 1.0) / n
      x = X_START + (x_end - X_START) * u
      p = np.array([x, np.interp(x, curve[:, 0], curve[:, 1]), np.interp(x, curve[:, 0], curve[:, 2])])
      v = self._proj(r, p)
      side = self._proj(r, p + np.array([0, 0.18, 0]))
      if v is None or side is None:
        continue
      rad = max(3.0, min(14.0, math.hypot(side.x - v.x, side.y - v.y)))
      rl.draw_circle_v(v, rad, with_alpha(color, int(150 * math.sin(math.pi * u) * fade * self._alpha)))
    box = self._box(r, curve, x_land, 1.8 - 0.8 * close)
    if box is None:
      return
    land = self._box(r, curve, x_land)
    if land is not None:
      self._fill_box(r, land, with_alpha(color, int(40 * close * fade * self._alpha)))
    ink = with_alpha(color, int((120 + 100 * close) * fade * self._alpha))
    for i, c in enumerate(box):
      for nb in (box[(i + 1) % 4], box[(i - 1) % 4]):
        e = rl.Vector2(c.x + (nb.x - c.x) * 0.28, c.y + (nb.y - c.y) * 0.28)
        rl.draw_line_ex(c, e, 6.0, ink)
      rl.draw_circle_v(c, 3.0, ink)

  def _pointer(self, r, curve, phase, color):
    """Pointer: the landing box glows on the road with two bold chevrons inside it sweeping toward the new
    lane, and a thin line ties it to our lane."""
    x_land = float(self._spot_centre(curve)[0])
    land = self._box(r, curve, x_land)
    if land is None:
      return
    breathe = 0.5 + 0.5 * math.sin(phase * 2 * math.pi)
    self._fill_box(r, land, with_alpha(color, int((40 + 30 * breathe) * self._alpha)))
    self._outline(land, 3.0, with_alpha(color, int(150 * self._alpha)))
    pts = [self._proj(r, q) for q in curve if q[0] <= x_land - SPOT_LEN / 2]
    pts = [v for v in pts if v is not None]
    for a, b in zip(pts, pts[1:], strict=False):
      rl.draw_line_ex(a, b, 4.0, with_alpha(color, int(110 * self._alpha)))
    # chevrons across the box, pointing to the lane change side, stepping outward
    cxp = rl.Vector2(sum(v.x for v in land) / 4, sum(v.y for v in land) / 4)
    width = max(v.x for v in land) - min(v.x for v in land)
    left = self._dir == LaneChangeDirection.left
    dirv, nrm = ((-1.0, 0.0), (0.0, 1.0)) if left else ((1.0, 0.0), (0.0, -1.0))
    for k in range(2):
      u = (phase + k * 0.5) % 1.0
      at = rl.Vector2(cxp.x + dirv[0] * width * (u - 0.4) * 0.6, cxp.y)
      a = math.sin(math.pi * u)
      h = min(width * 0.16, 46.0)
      self._chevron_2d(at, dirv, nrm, h, h * 0.8, h * 0.5, with_alpha(color, int(220 * a * self._alpha)), r)

  # -- entry -----------------------------------------------------------------------------------

  def render(self, r, sm, style: str):
    meta = sm['modelV2'].meta
    active = meta.laneChangeState in (LaneChangeState.laneChangeStarting, LaneChangeState.laneChangeFinishing) and \
      meta.laneChangeDirection != LaneChangeDirection.none
    if active:
      self._dir = meta.laneChangeDirection
    self._alpha += ((1.0 if active else 0.0) - self._alpha) * 0.2
    if style == "off" or self._alpha < 0.02 or self._dir == LaneChangeDirection.none:
      return
    curve = self._curve(r, self._dir == LaneChangeDirection.left)
    if curve is None:
      return
    phase = self.phase_override if self.phase_override is not None else (rl.get_time() % PERIOD[style]) / PERIOD[style]
    color = Console.ACCENT
    getattr(self, f"_{style}")(r, curve, phase, color)
