"""
Console lane-change overlay: while openpilot is changing lanes, a translucent looping cue on the
road shows where the truck is merging to.

  chevrons  four chevrons stream along an S-curve from our lane into the target lane
  lane      the target lane is tinted, a brighter band sweeps forward along it, and a thin S-arrow points in
  arrow     one wide arrow drawn on the road that grows from our lane into the target lane

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
MERGE_LEN = 18.0       # m over which the S-curve moves across
LANE_W = 3.7           # fallback lane width when the model has no neighbouring line
SAMPLES = 36
PERIOD = {"chevrons": 1.2, "lane": 1.4, "arrow": 1.6}


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

  def _head(self, r, curve, u: float, size_m: float, color: rl.Color):
    """Filled arrowhead at fraction u of the curve, in screen space so perspective does not flatten it."""
    f = self._screen_frame(r, curve, u)
    if f is None:
      return
    at, dirv, nrm, ppm = f
    w = min(size_m * ppm, 110.0)
    tip = (at.x + dirv[0] * w * 1.3, at.y + dirv[1] * w * 1.3)
    a = (at.x + nrm[0] * w, at.y + nrm[1] * w)
    c = (at.x - nrm[0] * w, at.y - nrm[1] * w)
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

  def _arrow(self, r, curve, phase, color):
    grow = min(1.0, phase / 0.6)
    grow = 1 - (1 - grow) ** 3
    fade = 1.0 if phase < 0.8 else 1.0 - (phase - 0.8) / 0.2
    n = max(2, int(grow * (len(curve) - 1)) + 1)
    c = with_alpha(color, int(150 * fade * self._alpha))
    self._ribbon(r, curve[:n], 0.75, c)
    self._head(r, curve, (n - 1) / (len(curve) - 1), 1.4, c)

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
    phase = (rl.get_time() % PERIOD[style]) / PERIOD[style]
    color = Console.ACCENT
    getattr(self, f"_{style}")(r, curve, phase, color)
