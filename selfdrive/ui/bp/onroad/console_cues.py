"""
Console driving cues: one visual language for everything that pops up on the driving screen.

  notice()            the notification card (informational alerts, lane changes, green light,
                      lead departing, stopped timer); a squared status bar, an icon, two lines
  SignalTiles         turn signals and blind-spot warnings as two tiles flanking the
                      notification slot; a signal into an occupied lane turns its tile red
  draw_blindspot_edge squared danger bars on the screen edges (no gradient)
  ConsoleConfidence   the model confidence indicator as a thick squared vertical bar
  CanadianSpeedLimit  Canadian regulatory sign (MAXIMUM / value / km/h) for SP's speed limit
  CruiseChips         SP smart-cruise (vision / map curve) state as Console chips

Everything colours from bluepilot.ui.lib.theme tokens, so day/night and accent apply.
"""

from __future__ import annotations

import math
import time

import pyray as rl

from openpilot.selfdrive.ui.bp.mici.onroad.confidence_ball_bp import ConfidenceBallTiciBP
from openpilot.selfdrive.ui.sunnypilot.onroad.speed_limit import SpeedLimitRenderer
from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from bluepilot.ui.console import draw as D
from bluepilot.ui.lib.theme import Console, Onroad, Radius, roundness

# -- notification card --------------------------------------------------------------------

NOTICE_R = 24
NOTICE_PAD_X = 32
NOTICE_PAD_Y = 22
NOTICE_BAR_W = 12
NOTICE_ICON = 52
NOTICE_TITLE = 46
NOTICE_SUB = 36
NOTICE_H1 = 104          # one line
NOTICE_H2 = 150          # two lines
NOTICE_MIN_W = 520


def _fonts():
  return gui_app.font(FontWeight.SEMI_BOLD), gui_app.font(FontWeight.NORMAL)


NOTICE_CHROME = NOTICE_PAD_X * 2 + NOTICE_BAR_W + 24 + NOTICE_ICON + 24


def _notice_sizes(title: str, sub: str, max_w: float) -> tuple[int, int]:
  """Title/subtitle sizes: the standard pair, or one step smaller when the band is narrow."""
  semi, body = _fonts()
  for t, s in ((NOTICE_TITLE, NOTICE_SUB), (NOTICE_TITLE - 6, NOTICE_SUB - 4), (NOTICE_TITLE - 10, NOTICE_SUB - 6)):
    tw = measure_text_cached(semi, title, t).x if title else 0
    sw = measure_text_cached(body, sub, s).x if sub else 0
    if NOTICE_CHROME + max(tw, sw) <= max_w:
      break
  return t, s


def notice_size(title: str, sub: str, max_w: float) -> tuple[float, float]:
  semi, body = _fonts()
  t, s = _notice_sizes(title, sub, max_w)
  tw = measure_text_cached(semi, title, t).x if title else 0
  sw = measure_text_cached(body, sub, s).x if sub else 0
  w = NOTICE_CHROME + max(tw, sw)
  return min(max(w, NOTICE_MIN_W), max_w), (NOTICE_H2 if (title and sub) else NOTICE_H1)


def notice(rect: rl.Rectangle, title: str, sub: str = "", bar: rl.Color | None = None, icon: str = "bell"):
  """Notification card: panel, squared status bar, icon, title (primary) over subtitle (muted)."""
  semi, body = _fonts()
  bar = bar if bar is not None else Console.ACCENT
  r = roundness(rect, NOTICE_R)
  rl.draw_rectangle_rounded(rect, r, 10, Onroad.PANEL_SOLID)
  rl.draw_rectangle_rounded_lines_ex(rect, r, 10, 2, Console.BORDER_DEFAULT)
  b = rl.Rectangle(rect.x + NOTICE_PAD_X, rect.y + NOTICE_PAD_Y, NOTICE_BAR_W, rect.height - 2 * NOTICE_PAD_Y)
  rl.draw_rectangle_rounded(b, roundness(b, Radius.XS), 4, bar)
  ix = b.x + NOTICE_BAR_W + 24
  cue_icon(icon, ix, rect.y + (rect.height - NOTICE_ICON) / 2, NOTICE_ICON, bar)
  tx = ix + NOTICE_ICON + 24
  max_w = rect.x + rect.width - NOTICE_PAD_X - tx
  ts, ss = _notice_sizes(title, sub, rect.width)
  if title and sub:
    y = rect.y + (rect.height - ts - 8 - ss) / 2 - 2
    rl.draw_text_ex(semi, D.fit(title, ts, max_w, semi=True), rl.Vector2(tx, y), ts, 0, Console.TEXT_PRIMARY)
    rl.draw_text_ex(body, D.fit(sub, ss, max_w), rl.Vector2(tx, y + ts + 8), ss, 0, Console.TEXT_MUTED)
  else:
    text = title or sub
    rl.draw_text_ex(semi, D.fit(text, ts, max_w, semi=True), rl.Vector2(tx, rect.y + (rect.height - ts) / 2 - 2), ts, 0,
                    Console.TEXT_PRIMARY)


# -- icons not in the shell kit (24-unit grid, 2-unit stroke, like draw.icon) -------------

def _seg(pts, x, y, s, w, color):
  for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
    rl.draw_line_ex(rl.Vector2(x + x0 * s, y + y0 * s), rl.Vector2(x + x1 * s, y + y1 * s), w, color)
  for px, py in pts:
    rl.draw_circle_v(rl.Vector2(x + px * s, y + py * s), w / 2, color)


def cue_icon(name: str, x: float, y: float, size: float, color: rl.Color):
  s = size / 24.0
  w = max(2.0, 2.2 * s)
  if name == "warning":
    _seg([(12, 3), (22, 20.5), (2, 20.5), (12, 3)], x, y, s, w, color)
    _seg([(12, 9.5), (12, 14)], x, y, s, w, color)
    rl.draw_circle_v(rl.Vector2(x + 12 * s, y + 17.3 * s), w * 0.7, color)
  elif name == "arrow_left":
    _seg([(20, 12), (4, 12)], x, y, s, w * 1.4, color)
    _seg([(11, 5), (4, 12), (11, 19)], x, y, s, w * 1.4, color)
  elif name == "arrow_right":
    _seg([(4, 12), (20, 12)], x, y, s, w * 1.4, color)
    _seg([(13, 5), (20, 12), (13, 19)], x, y, s, w * 1.4, color)
  elif name == "lane_left":
    _seg([(16, 21), (16, 12), (8, 4)], x, y, s, w, color)
    _seg([(8, 9), (8, 4), (13, 4)], x, y, s, w, color)
  elif name == "lane_right":
    _seg([(8, 21), (8, 12), (16, 4)], x, y, s, w, color)
    _seg([(16, 9), (16, 4), (11, 4)], x, y, s, w, color)
  elif name == "light":
    rl.draw_rectangle_rounded_lines_ex(rl.Rectangle(x + 7 * s, y + 2 * s, 10 * s, 20 * s), 0.4, 8, w, color)
    for cy in (7, 12, 17):
      rl.draw_circle_v(rl.Vector2(x + 12 * s, y + cy * s), 2.2 * s, color)
  elif name == "timer":
    rl.draw_ring(rl.Vector2(x + 12 * s, y + 13 * s), 8.5 * s - w / 2, 8.5 * s + w / 2, 0, 360, 40, color)
    _seg([(12, 13), (12, 8.5)], x, y, s, w, color)
    _seg([(10, 2.5), (14, 2.5)], x, y, s, w, color)
  else:
    D.icon(name, x, y, size, color)


# -- turn signals and blind spot ----------------------------------------------------------

TILE = 128
TILE_R = 24
BLINK_S = 0.4             # half period, matches the stock indicator cadence


class SignalTiles:
  """Two tiles flanking the notification slot.

  Blinker only            panel tile, arrow in success, blinking
  Car in the blind spot   panel tile with a danger outline and the word "Car" (ShowBlindspot)
  Blinker into that lane  danger-filled tile, white arrow, steady (lane change unsafe)
  """

  def __init__(self):
    self._t0 = time.monotonic()

  @staticmethod
  def _state(blinker: bool, blindspot: bool) -> str | None:
    bs = blindspot and ui_state.blindspot
    if blinker and bs:
      return "danger"
    if bs:
      return "car"
    if blinker and ui_state.turn_signals:
      return "signal"
    return None

  def render(self, band_l: float, band_r: float, y: float):
    if not (ui_state.turn_signals or ui_state.blindspot):
      return
    cs = ui_state.sm['carState']
    on = ((time.monotonic() - self._t0) % (2 * BLINK_S)) < BLINK_S
    for side, x, blinker, bs in (("left", band_l, cs.leftBlinker, cs.leftBlindspot),
                                 ("right", band_r - TILE, cs.rightBlinker, cs.rightBlindspot)):
      st = self._state(blinker, bs)
      if st is None:
        continue
      r = rl.Rectangle(x, y, TILE, TILE)
      rr = roundness(r, TILE_R)
      if st == "danger":
        rl.draw_rectangle_rounded(r, rr, 10, Console.DANGER_FILL)
        fg, word = Console.ON_ACCENT, "Car"
      else:
        rl.draw_rectangle_rounded(r, rr, 10, Onroad.PANEL_SOLID)
        rl.draw_rectangle_rounded_lines_ex(r, rr, 10, 4 if st == "car" else 2,
                                           Console.DANGER if st == "car" else Console.BORDER_DEFAULT)
        fg = Console.DANGER if st == "car" else (Console.SUCCESS if on else Console.BG_HIGH)
        word = "Car" if st == "car" else ("Left" if side == "left" else "Right")
      cue_icon(f"arrow_{side}", r.x + (TILE - 60) / 2, r.y + 16, 60, fg)
      D.text_center(word, r.x + TILE / 2, r.y + TILE - 44, 28, fg if st != "signal" else Console.TEXT_SECONDARY, semi=True)


EDGE_W = 20
EDGE_INSET = 16


def draw_blindspot_edge(rect: rl.Rectangle, left_a: float, right_a: float):
  """Squared danger bars on the screen edges, alpha 0..1 from the caller's fade filters."""
  pulse = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(time.monotonic() * 2 * math.pi / 1.5))
  for a, x in ((left_a, rect.x + EDGE_INSET), (right_a, rect.x + rect.width - EDGE_INSET - EDGE_W)):
    if a <= 0.01:
      continue
    c = Console.DANGER_FILL
    bar = rl.Rectangle(x, rect.y + 120, EDGE_W, rect.height - 240)
    rl.draw_rectangle_rounded(bar, roundness(bar, 6), 4, rl.Color(c.r, c.g, c.b, int(255 * a * pulse)))


# -- model confidence ---------------------------------------------------------------------

class ConsoleConfidence(ConfidenceBallTiciBP):
  """Model confidence as a thick squared vertical bar on the left edge (fills upward).

  Same signal and zones as BluePilot's confidence ball: success above 0.5, warning above
  0.2, danger below; white while overriding; the track tints info (steering only) or purple
  (speed only) in MADS states.
  """

  BALL_WIDTH = 64           # strip reserved on the left (bar + margin)
  BAR_W = 28

  def _render(self, _):
    r = self.rect
    track = rl.Rectangle(r.x + 12, r.y + 140, self.BAR_W, r.height - 280)
    status = ui_state.status
    if status == UIStatus.LAT_ONLY:
      track_c = Onroad.LAT_ONLY
    elif status == UIStatus.LONG_ONLY:
      track_c = Onroad.LONG_ONLY
    else:
      track_c = None
    rl.draw_rectangle_rounded(track, roundness(track, 6), 4, Onroad.PANEL)
    if track_c is not None:
      rl.draw_rectangle_rounded_lines_ex(track, roundness(track, 6), 4, 4, track_c)

    x = self._confidence_filter.x
    frac = max(0.0, min(1.0, (x + 0.5) / 1.5))
    if status in (UIStatus.LAT_ONLY, UIStatus.LONG_ONLY, UIStatus.ENGAGED) or self._demo:
      fill = Console.SUCCESS if x > 0.5 else (Console.WARNING if x > 0.2 else Console.DANGER)
    elif status == UIStatus.OVERRIDE:
      fill = Console.TEXT_PRIMARY
    else:
      fill = None
    if fill is not None and frac > 0.01:
      inner = rl.Rectangle(track.x + 6, track.y + 6, track.width - 12, track.height - 12)
      h = max(6.0, inner.height * frac)
      f = rl.Rectangle(inner.x, inner.y + inner.height - h, inner.width, h)
      rl.draw_rectangle_rounded(f, roundness(f, 4), 4, fill)


# -- Canadian speed-limit sign ------------------------------------------------------------

class CanadianSpeedLimit(SpeedLimitRenderer):
  """SP speed-limit logic with the Canadian regulatory sign: MAXIMUM, the value, km/h."""

  def _render_vienna(self, rect, val, sub, color, has_limit, alpha=1.0):
    self._render_canada(rect, val, sub, color, has_limit, alpha)

  def _render_mutcd(self, rect, val, sub, color, has_limit, alpha=1.0):
    self._render_canada(rect, val, sub, color, has_limit, alpha)

  def _render_canada(self, rect, val, sub, color, has_limit, alpha=1.0):
    white = rl.color_alpha(rl.WHITE, alpha)
    black = rl.color_alpha(rl.BLACK, alpha)
    text_color = rl.color_alpha(color, alpha)
    rl.draw_rectangle_rounded(rect, roundness(rect, 18), 10, white)
    inner = rl.Rectangle(rect.x + 9, rect.y + 9, rect.width - 18, rect.height - 18)
    rl.draw_rectangle_rounded_lines_ex(inner, roundness(inner, 12), 10, 5, black)
    cx = rect.x + rect.width / 2
    self._draw_text_centered(self.font_demi, "MAXIMUM", 30, rl.Vector2(cx, rect.y + 44), black)
    self._draw_text_centered(self.font_bold, val, 96 if len(val) < 3 else 80, rl.Vector2(cx, rect.y + rect.height / 2 + 12), text_color)
    self._draw_text_centered(self.font_demi, "km/h" if ui_state.is_metric else "mph", 30,
                             rl.Vector2(cx, rect.y + rect.height - 44), black)
    if sub and has_limit:
      box = 64
      s_rect = rl.Rectangle(rect.x + rect.width - box * 0.6, rect.y - box * 0.4, box, box)
      rl.draw_rectangle_rounded(s_rect, roundness(s_rect, 14), 10, Console.BG_PANEL)
      rl.draw_rectangle_rounded_lines_ex(s_rect, roundness(s_rect, 14), 10, 2, Console.BORDER_DEFAULT)
      self._draw_text_centered(self.font_bold, sub, 30, rl.Vector2(s_rect.x + box / 2, s_rect.y + box / 2), Console.TEXT_PRIMARY)


# -- smart cruise chips -------------------------------------------------------------------

def cruise_chips(scc, x: float, y: float):
  """SP smart cruise (vision / map curve control) as chips under the speed card."""
  cx = x
  for enabled, active, label in ((scc.vision_enabled, scc.vision_active, "Curve · vision"),
                                 (scc.map_enabled, scc.map_active, "Curve · map")):
    if not enabled:
      continue
    if active:
      dot = Console.WARNING if scc.long_override else Console.SUCCESS
    else:
      dot = Console.TEXT_GHOST
    r = D.chip(cx, y, label, dot_color=dot, h=60, size=28, bg=Onroad.PANEL_SOLID)
    cx += r.width + 12


# -- e2e pop-ups (green light, lead departing, stopped timer) -----------------------------

def e2e_notice(ca) -> tuple[str, str, rl.Color, str] | None:
  """Read SP CircularAlertsRenderer state and return (title, sub, bar, icon) to show, if any."""
  if not ca._allow_e2e_alerts:
    return None
  if ca._e2e_alert_display_timer > 0:
    if ca._green_light_alert:
      return "Green light", "The light ahead changed", Console.SUCCESS, "light"
    if ca._lead_depart_alert:
      return "Lead vehicle departing", "Traffic ahead is moving", Console.SUCCESS, "car"
    return None
  if ui_state.standstill_timer and ca._is_standstill:
    return f"Stopped {ca._alert_text}", "", Console.WARNING, "timer"
  return None
