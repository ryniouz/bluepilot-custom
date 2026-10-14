"""
Console driving cues: one visual language for everything that pops up on the driving screen.

  notice()            the notification card (informational alerts, lane changes, green light,
                      lead departing, stopped timer); a tinted icon tile and two lines
  SignalTiles         turn signals and blind-spot warnings as two tiles flanking the
                      notification slot; a signal into an occupied lane turns its tile red
  draw_blindspot_edge squared danger bars on the screen edges (no gradient)
  ConsoleConfidence   model confidence level (drawn inside the driver-monitor chip)
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
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from bluepilot.ui.console import draw as D
from bluepilot.ui.lib.theme import Console, Onroad, roundness, with_alpha

# -- notification card --------------------------------------------------------------------

NOTICE_R = 24
NOTICE_PAD_X = 32
NOTICE_PAD_Y = 22
NOTICE_TILE = 96         # tinted icon tile (smaller on a one-line card)
NOTICE_TILE_R = 18
NOTICE_TITLE = 46
NOTICE_SUB = 36
NOTICE_H1 = 104          # one line
NOTICE_H2 = 150          # two lines
NOTICE_MIN_W = 520


def _fonts():
  return gui_app.font(FontWeight.SEMI_BOLD), gui_app.font(FontWeight.NORMAL)


NOTICE_CHROME = NOTICE_PAD_X * 2 + NOTICE_TILE + 28


def _notice_sizes(title: str, sub: str, max_w: float) -> tuple[int, int]:
  """Title/subtitle sizes: the standard pair, or one step smaller when the band is narrow."""
  semi, body = _fonts()
  for t, s in ((NOTICE_TITLE, NOTICE_SUB), (NOTICE_TITLE - 6, NOTICE_SUB - 4), (NOTICE_TITLE - 10, NOTICE_SUB - 6)):
    tw = measure_text_cached(semi, title, t).x if title else 0
    sw = measure_text_cached(body, sub, s).x if sub else 0
    if NOTICE_CHROME + max(tw, sw) <= max_w:
      return t, s
  return NOTICE_TITLE - 6, NOTICE_SUB - 4


def _notice_layout(title: str, sub: str, max_w: float) -> tuple[int, int, list[str], list[str], float, float]:
  """(title size, sub size, title lines, sub lines, width, height). Text that does not fit the band
  on one line wraps to two lines each instead of being cut off, and the card grows taller."""
  semi, body = _fonts()
  ts, ss = _notice_sizes(title, sub, max_w)
  tw = measure_text_cached(semi, title, ts).x if title else 0
  sw = measure_text_cached(body, sub, ss).x if sub else 0
  if NOTICE_CHROME + max(tw, sw) <= max_w:
    w = min(max(NOTICE_CHROME + max(tw, sw), NOTICE_MIN_W), max_w)
    return ts, ss, [title] if title else [], [sub] if sub else [], w, (NOTICE_H2 if (title and sub) else NOTICE_H1)
  text_w = max_w - NOTICE_CHROME
  tl = D.wrap(title, ts, text_w, max_lines=2, semi=True) if title else []
  sl = D.wrap(sub, ss, text_w, max_lines=2) if sub else []
  h = 2 * NOTICE_PAD_Y + 8 + len(tl) * ts * 1.15 + len(sl) * ss * 1.25 + (8 if tl and sl else 0)
  return ts, ss, tl, sl, max_w, max(h, NOTICE_H2 if (title and sub) else NOTICE_H1)


def notice_size(title: str, sub: str, max_w: float) -> tuple[float, float]:
  _, _, _, _, w, h = _notice_layout(title, sub, max_w)
  return w, h


def notice(rect: rl.Rectangle, title: str, sub: str = "", bar: rl.Color | None = None, icon: str = "bell"):
  """Notification card, same family as the prompt card: translucent panel, a tinted icon tile in
  the status colour, title (primary) over subtitle (muted)."""
  semi, body = _fonts()
  bar = bar if bar is not None else Console.ACCENT
  r = roundness(rect, NOTICE_R)
  rl.draw_rectangle_rounded(rect, r, 10, Onroad.PANEL)
  rl.draw_rectangle_rounded_lines_ex(rect, r, 10, 2, Console.BORDER_DEFAULT)
  tile = min(NOTICE_TILE, rect.height - 2 * NOTICE_PAD_Y)
  t = rl.Rectangle(rect.x + NOTICE_PAD_X, rect.y + (rect.height - tile) / 2, tile, tile)
  rl.draw_rectangle_rounded(t, roundness(t, NOTICE_TILE_R), 10, with_alpha(bar, 0x38))
  isz = tile * 0.6
  cue_icon(icon, t.x + (tile - isz) / 2, t.y + (tile - isz) / 2, isz, bar)
  tx = t.x + tile + 28
  max_w = rect.x + rect.width - NOTICE_PAD_X - tx
  ts, ss, tl, sl, _, _ = _notice_layout(title, sub, rect.width)
  tlh, slh = (ts * 1.15 if len(tl) > 1 else ts), (ss * 1.25 if len(sl) > 1 else ss)
  total = len(tl) * tlh + len(sl) * slh + (8 if tl and sl else 0) - (tlh - ts if len(tl) > 1 and not sl else 0)
  y = rect.y + (rect.height - total) / 2 - 2
  for line in tl:
    rl.draw_text_ex(semi, D.fit(line, ts, max_w, semi=True), rl.Vector2(tx, y), ts, 0, Console.TEXT_PRIMARY)
    y += tlh
  if tl and sl:
    y += 8
  for line in sl:
    rl.draw_text_ex(body, D.fit(line, ss, max_w), rl.Vector2(tx, y), ss, 0, Console.TEXT_MUTED if tl else Console.TEXT_PRIMARY)
    y += slh


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
  elif name in ("car_left", "car_right", "car_rear"):
    # rear view of a car: roof, body, lights, wheels
    _seg([(6.5, 10), (8.5, 5), (15.5, 5), (17.5, 10)], x, y, s, w, color)
    rl.draw_rectangle_rounded_lines_ex(rl.Rectangle(x + 3 * s, y + 10 * s, 18 * s, 7.5 * s), 0.35, 8, w, color)
    for lx in (6.5, 17.5):
      rl.draw_circle_v(rl.Vector2(x + lx * s, y + 13.6 * s), 1.4 * s, color)
    for wx in (4.5, 16):
      rl.draw_rectangle_rounded(rl.Rectangle(x + wx * s, y + 17.5 * s, 3.5 * s, 3.5 * s), 0.4, 4, color)
  elif name == "rec":
    # recording: a filled dot in a ring
    rl.draw_ring(rl.Vector2(x + 12 * s, y + 12 * s), 9 * s - w / 2, 9 * s + w / 2, 0, 360, 40, color)
    rl.draw_circle_v(rl.Vector2(x + 12 * s, y + 12 * s), 5 * s, color)
  elif name == "alert":
    # bold exclamation for alert tiles
    rl.draw_rectangle_rounded(rl.Rectangle(x + 10 * s, y + 3 * s, 4 * s, 12.5 * s), 0.6, 6, color)
    rl.draw_circle_v(rl.Vector2(x + 12 * s, y + 19.5 * s), 2.3 * s, color)
  elif name == "eye":
    rl.draw_ring(rl.Vector2(x + 12 * s, y + 12 * s), 3.2 * s - w / 2, 3.2 * s + w / 2, 0, 360, 32, color)
    pts_top = [(2, 12), (6, 7.5), (12, 5.8), (18, 7.5), (22, 12)]
    pts_bot = [(2, 12), (6, 16.5), (12, 18.2), (18, 16.5), (22, 12)]
    _seg(pts_top, x, y, s, w, color)
    _seg(pts_bot, x, y, s, w, color)
  elif name == "hands":
    # steering wheel held at nine and three
    rl.draw_ring(rl.Vector2(x + 12 * s, y + 12 * s), 9 * s - w / 2, 9 * s + w / 2, 0, 360, 48, color)
    _seg([(3, 12), (21, 12)], x, y, s, w, color)
    _seg([(12, 12), (12, 21)], x, y, s, w, color)
    for hx in (3, 21):
      rl.draw_rectangle_rounded(rl.Rectangle(x + (hx - 2.6) * s, y + 8.5 * s, 5.2 * s, 7 * s), 0.6, 6, color)
  else:
    D.icon(name, x, y, size, color)


# -- turn signals and blind spot ----------------------------------------------------------

TILE = 128
TILE_R = 24
BLINK_S = 0.4             # half period, matches the stock indicator cadence
TILE_GAP = 24             # between the two tiles at the centre


class SignalTiles:
  """Two tiles side by side at the top centre, like a cluster's indicators.

  Blinker only            translucent tile, arrow in success, lit while the indicator is on
  Car in the blind spot   panel tile with a thick danger outline, car mark, "Car" (ShowBlindspot)
  Blinker into that lane  red tile with a pulsing halo, car mark, "Blocked" (lane change unsafe)
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

  def render_center(self, cx: float, y: float) -> bool:
    """Draw the tiles side by side around cx (left of centre, right of centre); a side with
    nothing to show leaves its slot empty so the other tile never moves. Returns True when any
    tile drew."""
    if not (ui_state.turn_signals or ui_state.blindspot):
      return False
    cs = ui_state.sm['carState']
    now = time.monotonic() - self._t0
    on = (now % (2 * BLINK_S)) < BLINK_S
    pulse = 0.5 + 0.5 * math.sin(now * 2 * math.pi / 0.8)
    shown = False
    for side, x, blinker, bs in (("left", cx - TILE_GAP / 2 - TILE, cs.leftBlinker, cs.leftBlindspot),
                                 ("right", cx + TILE_GAP / 2, cs.rightBlinker, cs.rightBlindspot)):
      st = self._state(blinker, bs)
      if st is None:
        continue
      shown = True
      r = rl.Rectangle(x, y, TILE, TILE)
      rr = roundness(r, TILE_R)
      if st == "danger":
        # Lane change into a car: solid red tile with a pulsing halo, car mark and "Blocked"
        halo = rl.Rectangle(r.x - 8, r.y - 8, TILE + 16, TILE + 16)
        rl.draw_rectangle_rounded(halo, roundness(halo, TILE_R + 8), 10, with_alpha(Console.DANGER_FILL, int(90 + 110 * pulse)))
        rl.draw_rectangle_rounded(r, rr, 10, Console.DANGER_FILL)
        cue_icon("car_" + side, r.x + (TILE - 72) / 2, r.y + 14, 72, Console.ON_ACCENT)
        D.text_center(tr("Blocked"), r.x + TILE / 2, r.y + TILE - 42, 28, Console.ON_ACCENT, semi=True)
      elif st == "car":
        rl.draw_rectangle_rounded(r, rr, 10, Onroad.PANEL)
        rl.draw_rectangle_rounded_lines_ex(r, rr, 10, 4, Console.DANGER)
        cue_icon("car_" + side, r.x + (TILE - 72) / 2, r.y + 14, 72, Console.DANGER)
        D.text_center(tr("Car"), r.x + TILE / 2, r.y + TILE - 42, 28, Console.DANGER, semi=True)
      else:
        # Turn signal: the arrow alone, lit tile while the indicator is on (no word, like a cluster)
        rl.draw_rectangle_rounded(r, rr, 10, Onroad.PANEL)
        if on:
          rl.draw_rectangle_rounded(r, rr, 10, with_alpha(Console.SUCCESS, 0x30))
        rl.draw_rectangle_rounded_lines_ex(r, rr, 10, 2, with_alpha(Console.SUCCESS, 0x90) if on else Console.BORDER_DEFAULT)
        cue_icon(f"arrow_{side}", r.x + (TILE - 80) / 2, r.y + (TILE - 80) / 2, 80, Console.SUCCESS if on else Console.TEXT_GHOST)
    return shown


EDGE_W = 32               # car in the blind spot
EDGE_W_BLOCKED = 56       # signalling into it
GLOW_W = 140
GLOW_W_BLOCKED = 300
EDGE_INSET = 12


def draw_blindspot_edge(rect: rl.Rectangle, left_a: float, right_a: float, left_blocked: bool = False,
                        right_blocked: bool = False):
  """Red side of the screen for a car in the blind spot: a squared danger bar along the edge with
  a red wash fading inward. Signalling into that lane doubles both and makes them pulse."""
  t = time.monotonic()
  for a, side, blocked in ((left_a, "left", left_blocked), (right_a, "right", right_blocked)):
    if a <= 0.01:
      continue
    pulse = (0.6 + 0.4 * (0.5 + 0.5 * math.sin(t * 2 * math.pi / 0.8))) if blocked else 0.85
    bw, gw = (EDGE_W_BLOCKED, GLOW_W_BLOCKED) if blocked else (EDGE_W, GLOW_W)
    y, h = rect.y + 60, rect.height - 120
    c = Console.DANGER_FILL
    glow_c = with_alpha(c, int((150 if blocked else 90) * a * pulse))
    clear = with_alpha(c, 0)
    if side == "left":
      bar = rl.Rectangle(rect.x + EDGE_INSET, y, bw, h)
      rl.draw_rectangle_gradient_h(int(bar.x + bw), int(y), int(gw), int(h), glow_c, clear)
    else:
      bar = rl.Rectangle(rect.x + rect.width - EDGE_INSET - bw, y, bw, h)
      rl.draw_rectangle_gradient_h(int(bar.x - gw), int(y), int(gw), int(h), clear, glow_c)
    rl.draw_rectangle_rounded(bar, roundness(bar, 8), 4, with_alpha(c, int(255 * a * pulse)))


# -- model confidence ---------------------------------------------------------------------

class ConsoleConfidence(ConfidenceBallTiciBP):
  """Model confidence as a thick squared vertical bar on the left edge (fills upward).

  Same signal and zones as BluePilot's confidence ball: success above 0.5, warning above
  0.2, danger below; white while overriding; the track tints info (steering only) or purple
  (speed only) in MADS states.
  """

  BALL_WIDTH = 64           # strip reserved on the left (bar + margin)
  BAR_W = 28

  def level(self) -> tuple[float, rl.Color | None]:
    """Advance the filter one frame and return (fraction, zone colour or None when not engaged).
    The driver-monitor chip draws it; the standalone strip below is no longer placed."""
    self._update_state()
    x = self._confidence_filter.x
    frac = max(0.0, min(1.0, (x + 0.5) / 1.5))
    status = ui_state.status
    if status in (UIStatus.LAT_ONLY, UIStatus.LONG_ONLY, UIStatus.ENGAGED) or self._demo:
      return frac, (Console.SUCCESS if x > 0.5 else (Console.WARNING if x > 0.2 else Console.DANGER))
    if status == UIStatus.OVERRIDE:
      return frac, Console.TEXT_PRIMARY
    return frac, None

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

SIGN_W = 168               # portrait Canadian sign inside SP's 200 px sign rect


class CanadianSpeedLimit(SpeedLimitRenderer):
  """SP speed-limit logic with the Canadian regulatory sign: MAXIMUM, the value, km/h."""

  def _render_vienna(self, rect, val, sub, color, has_limit, alpha=1.0):
    self._render_canada(rect, val, sub, color, has_limit, alpha)

  def _render_mutcd(self, rect, val, sub, color, has_limit, alpha=1.0):
    self._render_canada(rect, val, sub, color, has_limit, alpha)

  def _render_canada(self, rect, val, sub, color, has_limit, alpha=1.0):
    # No known limit: no sign (an empty "MAXIMUM ---" sign reads as a broken one)
    if not has_limit:
      return
    # Canadian regulatory signs are portrait: draw a narrower sign centred in SP's rect
    rect = rl.Rectangle(rect.x + (rect.width - SIGN_W) / 2, rect.y, SIGN_W, rect.height)
    white = rl.color_alpha(rl.WHITE, alpha)
    black = rl.color_alpha(rl.BLACK, alpha)
    text_color = rl.color_alpha(color, alpha)
    rl.draw_rectangle_rounded(rect, roundness(rect, 18), 10, white)
    inner = rl.Rectangle(rect.x + 9, rect.y + 9, rect.width - 18, rect.height - 18)
    rl.draw_rectangle_rounded_lines_ex(inner, roundness(inner, 12), 10, 5, black)
    cx = rect.x + rect.width / 2
    self._draw_text_centered(self.font_demi, "MAXIMUM", 22, rl.Vector2(cx, rect.y + 42), black)
    self._draw_text_centered(self.font_bold, val, 88 if len(val) < 3 else 72, rl.Vector2(cx, rect.y + rect.height / 2 + 10), text_color)
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
