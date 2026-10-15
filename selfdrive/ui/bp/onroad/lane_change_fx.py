"""
Console lane-change overlay (Pointer, Lucas's pick 2026-10-15): while openpilot changes lanes, a blue
truck-sized box sits in the target lane and a thin path-style line runs from the truck into it.

The box follows the vehicle's real progress instead of a looping animation:
- It is locked to the target lane itself, tracked frame to frame by lateral position. The model renumbers
  its lane lines once the truck crosses the line (the old "left lane" becomes the next lane over), so
  picking lines by index would jump the box one lane further out; tracking the nearest lane centre to
  where the target was last frame keeps it on the same physical lane.
- Progress is how much of the starting lateral gap to the target lane centre has closed. As it grows the
  box slides closer to the truck and fills a little, the connecting line straightens, and near the end
  both fade so the box is gone once the truck is centred in its new lane.

Shown only in laneChangeStarting / laneChangeFinishing (openpilot has committed to the change), so a
blocked change (blind spot) never shows it. On/off lives in BPRoadView bits 11-12 (road_view.LC_STYLES).
Drawing only; no control logic.
"""

from __future__ import annotations

import numpy as np
import pyray as rl
from cereal import log

from openpilot.system.ui.lib.shader_polygon import Gradient, draw_polygon
from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus
from bluepilot.ui.lib.theme import Console, Onroad, with_alpha

LaneChangeState = log.LaneChangeState
LaneChangeDirection = log.LaneChangeDirection

X_LINE = 3.0           # m ahead where the connecting line starts (just past the bonnet)
X_END = 40.0           # m, far end of the sampled lanes
X_TRACK = 9.0          # m ahead where the target lane's lateral position is tracked
BOX_FAR = 26.0         # box centre ahead when the change starts, m
BOX_NEAR = 15.0        # and when the truck has arrived
LANE_W = 3.7           # fallback lane width when the model has no neighbouring line
SAMPLES = 40
SPOT_LEN = 5.9         # F-150 Lightning length, m
SPOT_HALF_W = 1.05     # half its width, m
LINE_HALF_W = 0.22     # connecting line half width, m (the driving path is 0.9)
MIN_LINE_PROB = 0.2    # outer lane lines below this are ignored, the lane width is used instead
FADE_FROM = 0.75       # progress where the box and line start fading out


def _smoothstep(u):
  u = np.clip(u, 0.0, 1.0)
  return u * u * (3 - 2 * u)


def _fill(rect, poly: np.ndarray, color: rl.Color | None = None, gradient: Gradient | None = None):
  """draw_polygon with the winding the stock ribbons use; raylib culls back faces, so flip it if needed."""
  x, y = poly[:, 0], poly[:, 1]
  if float(np.dot(x, np.roll(y, -1)) - np.dot(np.roll(x, -1), y)) < 0:
    poly = poly[::-1]
  draw_polygon(rect, np.ascontiguousarray(poly, dtype=np.float32), color=color, gradient=gradient)


class LaneChangeFx:
  def __init__(self):
    self._alpha = 0.0
    self._dir = LaneChangeDirection.none
    self._tracking = False
    self._target = 0.0      # target lane centre at X_TRACK, car frame (model y, + is right)
    self._start_gap = LANE_W
    self.progress = 0.0     # 0 = change just started, 1 = truck centred in the target lane
    self._xs = np.linspace(X_LINE, X_END, SAMPLES)

  # -- lanes -----------------------------------------------------------------------------------

  def _lanes(self, r) -> tuple[list[np.ndarray], float, np.ndarray | None]:
    """Lane centre curves (SAMPLES, 3) the target could be on, the lane width, and our own lane's centre."""
    xs = self._xs
    probs = list(getattr(r, "_lane_line_probs", [])) or [1.0] * 4
    lines = []
    for i, ll in enumerate(r._lane_lines[:4]):
      pts = ll.raw_points
      ok = pts.size and pts.shape[0] >= 2 and (i in (1, 2) or (i < len(probs) and probs[i] >= MIN_LINE_PROB))
      lines.append(np.column_stack([xs, np.interp(xs, pts[:, 0], pts[:, 1]), np.interp(xs, pts[:, 0], pts[:, 2])])
                   if ok else None)
    lines += [None] * (4 - len(lines))
    if lines[1] is not None and lines[2] is not None:
      ego = (lines[1] + lines[2]) / 2
      k = int(np.searchsorted(xs, X_TRACK))
      width = float(np.clip(lines[2][k, 1] - lines[1][k, 1], 2.6, 4.6))
    else:
      path = r._path.raw_points
      if path.size == 0 or path.shape[0] < 2:
        return [], LANE_W, None
      ego = np.column_stack([xs, np.interp(xs, path[:, 0], path[:, 1]),
                             np.interp(xs, path[:, 0], path[:, 2]) + getattr(r, "_path_offset_z", 0.0)])
      width = LANE_W
    cands = [ego]
    for a, b in ((0, 1), (2, 3)):
      if lines[a] is not None and lines[b] is not None:
        cands.append((lines[a] + lines[b]) / 2)
    # the lanes either side of ours by width, for when the model has no outer line
    for s in (-2, -1, 1, 2):
      cands.append(ego + np.array([0.0, s * width, 0.0]))
    return cands, width, ego

  def _track(self, r, starting: bool) -> np.ndarray | None:
    """The target lane's centre curve, following the same physical lane through the change."""
    cands, width, ego = self._lanes(r)
    if ego is None:
      return None
    k = int(np.searchsorted(self._xs, X_TRACK))
    if starting or not self._tracking:
      side = -1.0 if self._dir == LaneChangeDirection.left else 1.0
      want = float(ego[k, 1]) + side * width
      self._target = want
      self._start_gap = max(abs(want), width * 0.5)
      self._tracking = True
      self.progress = 0.0
    # the candidate closest to where the target lane was last frame; real candidates beat the
    # width-shifted ones when they are about as close, since they carry the lane's own curve
    best, best_d = None, 1e9
    for i, c in enumerate(cands):
      d = abs(float(c[k, 1]) - self._target) + (0.0 if i < len(cands) - 4 else 0.25)
      if d < best_d:
        best, best_d = c, d
    if best is None or best_d > 0.6 * width:
      best = ego + np.array([0.0, self._target - float(ego[k, 1]), 0.0])
    self._target += (float(best[k, 1]) - self._target) * 0.5
    curve = best + np.array([0.0, self._target - float(best[k, 1]), 0.0])
    raw = float(np.clip(1.0 - abs(self._target) / self._start_gap, 0.0, 1.0))
    self.progress += (raw - self.progress) * 0.25
    return curve

  # -- drawing ---------------------------------------------------------------------------------

  @staticmethod
  def _proj(r, p):
    s = r._map_to_screen(float(p[0]), float(p[1]), float(p[2]))
    return None if s is None else (float(s[0]), float(s[1]))

  def _box(self, r, curve: np.ndarray, xc: float):
    y = float(np.interp(xc, curve[:, 0], curve[:, 1]))
    z = float(np.interp(xc, curve[:, 0], curve[:, 2]))
    hl = SPOT_LEN / 2
    scr = [self._proj(r, (xc + a, y + b, z)) for a, b in ((-hl, -SPOT_HALF_W), (hl, -SPOT_HALF_W),
                                                          (hl, SPOT_HALF_W), (-hl, SPOT_HALF_W))]
    return None if None in scr else scr

  def _line(self, r, curve: np.ndarray, x_back: float, color: rl.Color, vis: float):
    """A thin ribbon in the driving path's style, from the truck into the back of the box."""
    path = r._path.raw_points
    if path.size == 0 or x_back <= X_LINE + 1.0:
      return
    xs = np.linspace(X_LINE, x_back, 24)
    # follow the truck's own planned path near the truck, then ease into the target lane's centre so the
    # line ends in the box; the plan already bends that way, so the two read as one route
    py = np.interp(xs, path[:, 0], path[:, 1])
    ty, tz = np.interp(xs, curve[:, 0], curve[:, 1]), np.interp(xs, curve[:, 0], curve[:, 2])
    blend = _smoothstep((xs - X_LINE) / (x_back - X_LINE))
    pz = np.interp(xs, path[:, 0], path[:, 2]) + getattr(r, "_path_offset_z", 0.0)
    pts = np.column_stack([xs, py * (1 - blend) + ty * blend, pz * (1 - blend) + tz * blend]).astype(np.float32)
    poly = r._map_line_to_polygon(pts, LINE_HALF_W, 0.0, len(pts) - 1, float(pts[-1][0]), allow_invert=False)
    if poly.size < 8:
      return
    lo, hi = poly.min(axis=0), poly.max(axis=0)
    box = rl.Rectangle(float(lo[0]), float(lo[1]), float(max(hi[0] - lo[0], 1.0)), float(max(hi[1] - lo[1], 1.0)))
    # like the driving path: strongest at the truck, fading toward the box
    grad = Gradient(start=(0.0, 1.0), end=(0.0, 0.0), stops=[0.0, 0.6, 1.0],
                    colors=[with_alpha(color, int(100 * vis)), with_alpha(color, int(65 * vis)),
                            with_alpha(color, int(30 * vis))])
    _fill(box, poly, gradient=grad)

  def _draw(self, r, curve: np.ndarray):
    ease = float(_smoothstep(self.progress))
    xc = BOX_FAR + (BOX_NEAR - BOX_FAR) * ease
    vis = self._alpha * (1.0 - float(_smoothstep((self.progress - FADE_FROM) / (1.0 - FADE_FROM))))
    if vis < 0.02:
      return
    status = ui_state.status
    line_c = Onroad.ENGAGED if status == UIStatus.ENGAGED else Onroad.LAT_ONLY if status == UIStatus.LAT_ONLY else \
      rl.Color(255, 255, 255, 255)
    self._line(r, curve, xc - SPOT_LEN / 2, line_c, vis)
    scr = self._box(r, curve, xc)
    if scr is None:
      return
    accent = Console.ACCENT
    # the box fills a little as the truck closes in on it
    _fill(r._rect, np.array(scr, dtype=np.float32), color=with_alpha(accent, int((38 + 34 * ease) * vis)))
    edge = with_alpha(accent, int(175 * vis))
    vs = [rl.Vector2(x, y) for x, y in scr]
    for a, b in zip(vs, vs[1:] + vs[:1], strict=True):
      rl.draw_line_ex(a, b, 3.5, edge)
    for v in vs:
      rl.draw_circle_v(v, 1.75, edge)

  # -- entry -----------------------------------------------------------------------------------

  def render(self, r, sm, style: str):
    meta = sm['modelV2'].meta
    active = meta.laneChangeState in (LaneChangeState.laneChangeStarting, LaneChangeState.laneChangeFinishing) and \
      meta.laneChangeDirection != LaneChangeDirection.none
    starting = False
    if active:
      starting = not self._tracking or meta.laneChangeDirection != self._dir
      self._dir = meta.laneChangeDirection
    self._alpha += ((1.0 if active else 0.0) - self._alpha) * 0.15
    if not active and self._alpha < 0.02:
      self._tracking = False
      self._alpha = 0.0
      return
    if style == "off" or self._dir == LaneChangeDirection.none:
      return
    curve = self._track(r, starting)
    if curve is not None:
      self._draw(r, curve)
