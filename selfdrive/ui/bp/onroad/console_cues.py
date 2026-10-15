"""
Console driving cues: one visual language for everything that pops up on the driving screen.

  notice()            the notification card (informational alerts, lane changes, green light,
                      lead departing, stopped timer); a tinted icon tile and two lines
  SignalTiles         turn signals as two tiles at the top centre; a signal into an occupied lane
                      turns its tile red
  BlindSpotMarkers    a car in the blind spot: a glass disc at that screen edge, amber, red when
                      you signal into it
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

from cereal import log

from openpilot.selfdrive.ui.bp.mici.onroad.confidence_ball_bp import ConfidenceBallTiciBP
from openpilot.selfdrive.ui.sunnypilot.onroad.speed_limit import SpeedLimitRenderer, SpeedLimitSource
from openpilot.sunnypilot.selfdrive.controls.lib.speed_limit.common import Mode as SpeedLimitMode
from openpilot.selfdrive.ui.ui_state import ui_state, UIStatus
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached
from bluepilot.ui.console import draw as D
from bluepilot.ui.lib.theme import Console, Onroad, roundness, with_alpha

# -- notification card --------------------------------------------------------------------

NOTICE_R = 24
NOTICE_PAD_X = 52          # room for the accent line on the left
NOTICE_LINE = 6
NOTICE_PAD_Y = 22
NOTICE_ICON = 88         # free-standing icon (smaller on a one-line card)
NOTICE_TITLE = 46
NOTICE_SUB = 36
NOTICE_H1 = 104          # one line
NOTICE_H2 = 150          # two lines
NOTICE_MIN_W = 520


def _fonts():
  return gui_app.font(FontWeight.SEMI_BOLD), gui_app.font(FontWeight.NORMAL)


NOTICE_CHROME = NOTICE_PAD_X * 2 + NOTICE_ICON + 28


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


_NOTICE_SEEN: dict[str, tuple[float, float]] = {}
NOTICE_IN_S = 0.24        # slide-in time
NOTICE_DROP = 28          # px it drops in from
GO_PULSE_S = 1.6          # "go" notices (green light, lead moving) ring outward for this long


def _since_shown(key: str) -> float:
  """Seconds since this notice appeared; a notice gone for half a second counts as new next time."""
  now = time.monotonic()
  first, last = _NOTICE_SEEN.get(key, (now, now))
  if now - last > 0.5:
    first = now
  _NOTICE_SEEN[key] = (first, now)
  return now - first


def notice(rect: rl.Rectangle, title: str, sub: str = "", bar: rl.Color | None = None, icon: str = "bell", go: bool = False,
           boxed: bool = False):
  """Notification card (Console, Lucas 2026-10-15): a translucent glass card with a lit top edge, a squared accent
  line down its left side in the level colour, the icon free-standing in that colour, then title over subtitle.
  It drops in from just above. A "go" notice (green light, lead moving) takes a faint green wash and one soft
  sweep of light when it appears instead of rings; a boxed notice (a warning that goes with the red edge bar)
  gets the red outline too."""
  semi, body = _fonts()
  bar = bar if bar is not None else Console.ACCENT
  age = _since_shown(title)
  e = 1 - (1 - min(1.0, age / NOTICE_IN_S)) ** 3
  rect = rl.Rectangle(rect.x, rect.y - NOTICE_DROP * (1 - e), rect.width, rect.height)
  r = roundness(rect, NOTICE_R)
  rl.draw_rectangle_rounded(rl.Rectangle(rect.x, rect.y + 6, rect.width, rect.height), r, 10, rl.Color(0, 0, 0, 0x26))
  rl.draw_rectangle_rounded(rect, r, 10, Onroad.PANEL)
  if go or boxed:
    rl.draw_rectangle_rounded(rect, r, 10, with_alpha(bar, 0x1A))
  if go and age < GO_PULSE_S:
    # one sweep of light across the card
    u = age / GO_PULSE_S
    sx = rect.x - 160 + (rect.width + 320) * u
    rl.begin_scissor_mode(int(rect.x), int(rect.y), int(rect.width), int(rect.height))
    rl.draw_rectangle_gradient_h(int(sx - 160), int(rect.y), 160, int(rect.height), with_alpha(bar, 0), with_alpha(bar, 0x40))
    rl.draw_rectangle_gradient_h(int(sx), int(rect.y), 160, int(rect.height), with_alpha(bar, 0x40), with_alpha(bar, 0))
    rl.end_scissor_mode()
  # glass: a light top edge and a thin rim
  rl.draw_rectangle_gradient_v(int(rect.x + NOTICE_R), int(rect.y + 1), int(rect.width - 2 * NOTICE_R), 2, rl.Color(255, 255, 255, 0x40),
                               rl.Color(255, 255, 255, 0))
  rim = with_alpha(bar, 0xE0) if boxed else (with_alpha(bar, 0x90) if go else Console.BORDER_DEFAULT)
  rl.draw_rectangle_rounded_lines_ex(rect, r, 10, 3 if boxed else 2, rim)
  line = rl.Rectangle(rect.x + 20, rect.y + 20, NOTICE_LINE, rect.height - 40)
  rl.draw_rectangle_rounded(line, 1.0, 6, bar)
  isz = min(NOTICE_ICON, rect.height - 2 * NOTICE_PAD_Y)
  ix = rect.x + NOTICE_PAD_X
  cue_icon(icon, ix, rect.y + (rect.height - isz) / 2, isz, bar)
  tx = ix + isz + 28
  max_w = rect.x + rect.width - NOTICE_PAD_X - tx
  ts, ss, tl, sl, _, _ = _notice_layout(title, sub, rect.width)
  tlh, slh = (ts * 1.15 if len(tl) > 1 else ts), (ss * 1.25 if len(sl) > 1 else ss)
  total = len(tl) * tlh + len(sl) * slh + (8 if tl and sl else 0) - (tlh - ts if len(tl) > 1 and not sl else 0)
  y = rect.y + (rect.height - total) / 2 - 2
  for ln in tl:
    rl.draw_text_ex(semi, D.fit(ln, ts, max_w, semi=True), rl.Vector2(tx, y), ts, 0, Console.TEXT_PRIMARY)
    y += tlh
  if tl and sl:
    y += 8
  for ln in sl:
    rl.draw_text_ex(body, D.fit(ln, ss, max_w), rl.Vector2(tx, y), ss, 0, Console.TEXT_MUTED if tl else Console.TEXT_PRIMARY)
    y += slh


# -- icons not in the shell kit (24-unit grid, 2-unit stroke, like draw.icon) -------------

def _seg(pts, x, y, s, w, color):
  for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
    rl.draw_line_ex(rl.Vector2(x + x0 * s, y + y0 * s), rl.Vector2(x + x1 * s, y + y1 * s), w, color)
  for px, py in pts:
    rl.draw_circle_v(rl.Vector2(x + px * s, y + py * s), w / 2, color)


# Driving cue names that draw a pack icon (Lucas 2026-10-15): other vehicles are Phosphor's front-facing car, turn signals
# Tabler's indicator arrows, lane changes Tabler's ramps; warning, alert, bell, eye, timer, rec, light, hands, collision
# and car (the pickup) are pack icons under their own names.
CUE_PACK = {"car_rear": "car_front", "car_left": "car_front", "car_right": "car_front",
            "arrow_left": "signal_left", "arrow_right": "signal_right"}


def cue_icon(name: str, x: float, y: float, size: float, color: rl.Color):
  if name == "lead_go":
    # the car ahead pulling away: Phosphor's car under a rising arrow
    D.icon("car_front", x + size * 0.12, y + size * 0.3, size * 0.76, color)
    s = size / 24.0
    w = max(2.0, D.ICON_STROKE * s)
    _seg([(12, 6.5), (12, 1.2)], x, y, s, w, color)
    _seg([(9.2, 4), (12, 1.2), (14.8, 4)], x, y, s, w, color)
    return
  if D.pack_icon(CUE_PACK.get(name, name), x, y, size, color):
    return
  s = size / 24.0
  w = max(2.0, D.ICON_STROKE * s)
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
  elif name in ("blindspot_left", "blindspot_right"):
    # Blind spot (candidate B1, Lucas 22:42): a top-down car with two sensor arcs on the side being
    # watched; mirrored for the right
    fx = (lambda v: v) if name == "blindspot_left" else (lambda v: 24 - v)
    car = rl.Rectangle(x + min(fx(10), fx(19)) * s, y + 3.5 * s, 9 * s, 17 * s)
    rl.draw_rectangle_rounded_lines_ex(car, 0.66, 10, w, color)
    for yy in (8.5, 16):
      _seg([(fx(11.5), yy), (fx(17.5), yy)], x, y, s, w, color)
    for rad, cx in ((5.0, 11.5), (9.0, 12.0)):
      sweep = [math.radians(a) for a in range(135, 226, 9)]
      pts = [(fx(cx + rad * math.cos(t)), 12 + rad * math.sin(t)) for t in sweep]
      _seg(pts, x, y, s, w, color)
  elif name == "light_go":
    # traffic light gone green: housing, the two upper lamps as thin rings, the bottom lamp lit and larger
    rl.draw_rectangle_rounded_lines_ex(rl.Rectangle(x + 6.5 * s, y + 1 * s, 11 * s, 22 * s), 0.45, 8, w, color)
    for cy in (5.6, 11.0):
      rl.draw_ring(rl.Vector2(x + 12 * s, y + cy * s), 1.9 * s, 1.9 * s + w * 0.55, 0, 360, 24, with_alpha(color, 0x80))
    rl.draw_circle_v(rl.Vector2(x + 12 * s, y + 17.3 * s), 3.2 * s, color)
  elif name == "lead_go":
    # the car ahead pulling away: a rear-view car with an arrow rising above it
    _seg([(12, 8), (12, 1.5)], x, y, s, w, color)
    _seg([(8.8, 4.6), (12, 1.4), (15.2, 4.6)], x, y, s, w, color)
    _seg([(6.2, 14), (7.8, 10.5), (16.2, 10.5), (17.8, 14)], x, y, s, w, color)
    rl.draw_rectangle_rounded_lines_ex(rl.Rectangle(x + 3.5 * s, y + 14 * s, 17 * s, 5.5 * s), 0.4, 8, w, color)
    for lx in (7, 17):
      rl.draw_circle_v(rl.Vector2(x + lx * s, y + 16.75 * s), 1.2 * s, color)
    for wx in (5, 16):
      rl.draw_rectangle_rounded(rl.Rectangle(x + wx * s, y + 19.5 * s, 3 * s, 3 * s), 0.4, 4, color)
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

TILE_W = 232               # turn signal tiles (Lucas 2026-10-15: more room, easier to see)
TILE = 148                 # tile height; notifications drop below it
TILE_R = 32
TILE_ICON = 104
BLINK_S = 0.4             # half period, matches the stock indicator cadence
TILE_GAP = 64             # between the two tiles at the centre


class SignalTiles:
  """Two wide glass tiles side by side at the top centre, like a cluster's indicators.

  Blinker                 lit phase: solid green arrow on a green-washed tile with a soft glow; dark phase: the
                          arrow's outline on plain glass, so the tile never vanishes mid-blink
  Blinker into a car      red tile, white arrow (the red edge bar and a warning card say why)
  """

  def __init__(self):
    self._t0 = time.monotonic()

  @staticmethod
  def _state(blinker: bool, blindspot: bool) -> str | None:
    if blinker and blindspot and ui_state.blindspot:
      return "danger"
    if blinker and ui_state.turn_signals:
      return "signal"
    return None

  def render_center(self, cx: float, y: float) -> bool:
    """Draw the tiles side by side around cx; a side with nothing to show leaves its slot empty so the other tile
    never moves. Returns True when any tile drew."""
    if not (ui_state.turn_signals or ui_state.blindspot):
      return False
    cs = ui_state.sm['carState']
    now = time.monotonic() - self._t0
    on = (now % (2 * BLINK_S)) < BLINK_S
    shown = False
    for side, x, blinker, bs in (("left", cx - TILE_GAP / 2 - TILE_W, cs.leftBlinker, cs.leftBlindspot),
                                 ("right", cx + TILE_GAP / 2, cs.rightBlinker, cs.rightBlindspot)):
      st = self._state(blinker, bs)
      if st is None:
        continue
      shown = True
      r = rl.Rectangle(x, y, TILE_W, TILE)
      rr = roundness(r, TILE_R)
      ix, iy = r.x + (TILE_W - TILE_ICON) / 2, r.y + (TILE - TILE_ICON) / 2
      rl.draw_rectangle_rounded(rl.Rectangle(r.x, r.y + 6, r.width, r.height), rr, 10, rl.Color(0, 0, 0, 0x26))
      if st == "danger":
        rl.draw_rectangle_rounded(r, rr, 10, with_alpha(Console.DANGER_FILL, 0xF0 if on else 0xC0))
        rl.draw_rectangle_rounded_lines_ex(r, rr, 10, 3, with_alpha(Console.ON_ACCENT, 0x60))
        D.pack_icon(f"signal_{side}_on", ix, iy, TILE_ICON, Console.ON_ACCENT if on else with_alpha(Console.ON_ACCENT, 0x90))
        continue
      if on:
        for k, a in ((14, 0x18), (7, 0x30)):
          g = rl.Rectangle(r.x - k, r.y - k, r.width + 2 * k, r.height + 2 * k)
          rl.draw_rectangle_rounded(g, roundness(g, TILE_R + k), 10, with_alpha(Console.SUCCESS, a))
      rl.draw_rectangle_rounded(r, rr, 10, Onroad.PANEL)
      if on:
        rl.draw_rectangle_rounded(r, rr, 10, with_alpha(Console.SUCCESS, 0x2C))
      rl.draw_rectangle_gradient_v(int(r.x + TILE_R), int(r.y + 1), int(r.width - 2 * TILE_R), 2, rl.Color(255, 255, 255, 0x40),
                                   rl.Color(255, 255, 255, 0))
      rl.draw_rectangle_rounded_lines_ex(r, rr, 10, 2, with_alpha(Console.SUCCESS, 0xC0) if on else Console.BORDER_DEFAULT)
      D.pack_icon(f"signal_{side}_on" if on else f"signal_{side}", ix, iy, TILE_ICON,
                  Console.SUCCESS if on else with_alpha(Console.SUCCESS, 0x90))
    return shown


BS_FACE = 184             # glass disc for a car in the blind spot (Lucas 22:42: larger, recognisable)
BS_ICON = 124
BS_EDGE = 44              # from the screen edge
BS_Y = 0.64               # disc centre, as a share of the screen height: beside the road, under the lead card
BS_SLIDE = 36


class BlindSpotMarkers:
  """A car in the blind spot shows where it is: a round glass disc at that edge of the screen, level
  with the road, like the indicator in a side mirror.

  Car beside you           amber icon and rim on the glass (caution: look before you move over)
  Signalling into it       solid red disc with a pulsing halo, white icon and a "Blocked" chip; the
                           top arrow tile turns red too
  It slides in from the edge and fades, so it never pops. Needs ui_state.blindspot (BlindSpot)."""

  def __init__(self):
    self._a = {"left": 0.0, "right": 0.0}
    self._t0 = time.monotonic()

  def render(self, rect: rl.Rectangle):
    if not ui_state.blindspot:
      return
    try:
      cs = ui_state.sm['carState']
      sides = (("left", cs.leftBlindspot, cs.leftBlinker), ("right", cs.rightBlindspot, cs.rightBlinker))
    except Exception:
      return
    for side, bs, blinker in sides:
      self._a[side] += ((1.0 if bs else 0.0) - self._a[side]) * 0.25
      a = self._a[side]
      if a < 0.02:
        continue
      blocked = bs and blinker
      ease = 1 - (1 - a) ** 3
      off = BS_SLIDE * (1 - ease)
      r = BS_FACE / 2
      cx = rect.x + BS_EDGE + r - off if side == "left" else rect.x + rect.width - BS_EDGE - r + off
      cy = rect.y + rect.height * BS_Y
      c = rl.Vector2(cx, cy)
      rl.draw_ring(c, r, r + 6, 0, 360, 72, rl.Color(0, 0, 0, int(0x30 * a)))
      if blocked:
        # Signalling into it: the disc turns red (no chip, no halo; Lucas 2026-10-15), the red accent bar runs
        # down that edge and a boxed warning card says why (hud_renderer_bp)
        side_bar(rl.Rectangle(0, 0, gui_app.width, gui_app.height), side, a)  # on the screen edge, like AttentionBar
        rl.draw_circle_v(c, r, with_alpha(Console.DANGER_FILL, int(0xE6 * a)))
        ink = with_alpha(Console.ON_ACCENT, int(255 * a))
        rim = with_alpha(Console.ON_ACCENT, int(0x50 * a))
      else:
        rl.draw_circle_v(c, r, with_alpha(Console.BG_PANEL, int(0xC0 * a)))
        rl.draw_circle_v(c, r - 4, with_alpha(Console.WARNING, int(0x22 * a)))
        ink = with_alpha(Console.WARNING, int(255 * a))
        rim = with_alpha(Console.WARNING, int(0xD0 * a))
      rl.draw_circle_gradient(rl.Vector2(cx, cy - r * 0.38), r * 0.6, rl.Color(255, 255, 255, int(0x1C * a)), rl.Color(255, 255, 255, 0))
      rl.draw_ring(c, r - 5, r, 0, 360, 72, rim)
      cue_icon(f"blindspot_{side}", cx - BS_ICON / 2, cy - BS_ICON / 2, BS_ICON, ink)

  @staticmethod
  def blocked_side() -> str | None:
    """"left" / "right" while the driver signals into an occupied lane."""
    if not ui_state.blindspot:
      return None
    try:
      cs = ui_state.sm['carState']
    except Exception:
      return None
    if cs.leftBlindspot and cs.leftBlinker:
      return "left"
    if cs.rightBlindspot and cs.rightBlinker:
      return "right"
    return None


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
    if a <= 0.01 or blocked:
      continue  # signalling into it: BlindSpotMarkers draws the red accent bar on that edge instead
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


# -- attention bar ------------------------------------------------------------------------

ATTN_W = 14               # left-edge accent bar for steering override / blocked steering
ATTN_GLOW = 90
ATTN_INSET = 18
STEER_BLOCKED_EVENTS = ("steerTempUnavailable", "steerUnavailable", "steerSaturated", "steerTimeLimit", "lkasDisabled")


def side_bar(rect: rl.Rectangle, side: str, a: float = 1.0, pulse: bool = True):
  """The red accent bar along one screen edge, with its soft inward glow (same look as AttentionBar)."""
  if pulse:
    a *= 0.7 + 0.3 * (0.5 + 0.5 * math.sin(time.monotonic() * 2 * math.pi / 0.9))
  c = Console.DANGER_FILL
  y, h = rect.y + 60, rect.height - 120
  if side == "left":
    bar = rl.Rectangle(rect.x + ATTN_INSET, y, ATTN_W, h)
    rl.draw_rectangle_gradient_h(int(bar.x + ATTN_W), int(y), ATTN_GLOW, int(h), with_alpha(c, int(70 * a)), with_alpha(c, 0))
  else:
    bar = rl.Rectangle(rect.x + rect.width - ATTN_INSET - ATTN_W, y, ATTN_W, h)
    rl.draw_rectangle_gradient_h(int(bar.x - ATTN_GLOW), int(y), ATTN_GLOW, int(h), with_alpha(c, 0), with_alpha(c, int(70 * a)))
  rl.draw_rectangle_rounded(bar, 1.0, 8, with_alpha(c, int(255 * a)))
  core = rl.Rectangle(bar.x + 4 if side == "left" else bar.x + ATTN_W - 7, y + 10, 3, h - 20)
  rl.draw_rectangle_rounded(core, 1.0, 4, rl.Color(255, 255, 255, int(70 * a)))


class AttentionBar:
  """A red accent bar along the left edge for conditions the driver must notice: steering blocked
  or faulted, a critical alert, or the driver overriding the steering. It replaces the old
  full-screen coloured border for these cases; the speed card's status band names the state."""

  def __init__(self):
    self._a = 0.0
    self.state = ""         # "blocked" | "critical" | "override" | ""

  def update(self) -> str:
    sm = ui_state.sm
    state = ""
    try:
      cs = sm['carState']
      ss = sm['selfdriveState']
      alert_type = str(ss.alertType or "")
      active = ui_state.status in (UIStatus.ENGAGED, UIStatus.OVERRIDE, UIStatus.LAT_ONLY)
      if cs.steerFaultTemporary or cs.steerFaultPermanent or any(e in alert_type for e in STEER_BLOCKED_EVENTS):
        state = "blocked"
      elif ss.alertStatus == log.SelfdriveState.AlertStatus.critical:
        state = "critical"
      elif active and cs.steeringPressed:
        state = "override"
    except Exception:
      state = ""
    self.state = state
    self._a += ((1.0 if state else 0.0) - self._a) * 0.25
    return state

  def render(self, rect: rl.Rectangle):
    if self._a <= 0.02:
      return
    side_bar(rect, "left", self._a, pulse=self.state in ("blocked", "critical"))


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


SIGN_H = 216               # its height there (set_speed_height + 2 x 6)
SIGN_IN_W = 124            # the sign inside the speed card, beside the set speed


class CanadianSpeedLimit(SpeedLimitRenderer):
  """SP speed-limit logic with the Canadian regulatory sign: MAXIMUM, the value, km/h.
  Custom: when the speed card sets `target`, the sign draws inside the card at that rect (scaled), and the
  limit-ahead info becomes a Console chip under the card."""

  def __init__(self):
    super().__init__()
    self.target: rl.Rectangle | None = None   # set by the speed card each frame
    self.chip_y: float = 0.0                   # under the speed card

  @property
  def has_limit(self) -> bool:
    return bool(self.speed_limit_valid or self.speed_limit_last_valid)

  def _render(self, rect: rl.Rectangle):
    if self.target is None:
      super()._render(rect)
      return
    # Custom: inside the speed tile the sign shows whenever a limit is known (Lucas 2026-10-15 wanted it back),
    # whatever the speed limit assist mode; the tile's text carries the limit ahead
    self._draw_sign_main(self.target, self._pre_active_fade.alpha if ui_state.speed_limit_mode != SpeedLimitMode.off else 1.0)

  def detail_text(self) -> str:
    """Second line beside the sign in the speed tile: the next limit ahead, else where the limit comes from."""
    if (self.speed_limit_source == SpeedLimitSource.map and self.speed_limit_ahead_valid and self.speed_limit_ahead > 0
        and round(self.speed_limit_ahead) != round(self.speed_limit_last)):
      return f"{round(self.speed_limit_ahead)} {tr('ahead')} · {self._format_dist(self.speed_limit_ahead_dist)}"
    if self.speed_limit_source == SpeedLimitSource.map:
      return tr("From the map")
    if self.speed_limit_source == SpeedLimitSource.car:
      return tr("From the truck")
    return ""

  def _render_vienna(self, rect, val, sub, color, has_limit, alpha=1.0):
    self._render_canada(rect, val, sub, color, has_limit, alpha)

  def _render_mutcd(self, rect, val, sub, color, has_limit, alpha=1.0):
    self._render_canada(rect, val, sub, color, has_limit, alpha)

  def _render_canada(self, rect, val, sub, color, has_limit, alpha=1.0):
    # No known limit: no sign (an empty "MAXIMUM ---" sign reads as a broken one)
    if not has_limit:
      return
    if self.target is None:
      # Canadian regulatory signs are portrait: draw a narrower sign centred in SP's rect
      rect = rl.Rectangle(rect.x + (rect.width - SIGN_W) / 2, rect.y, SIGN_W, rect.height)
    k = rect.height / SIGN_H
    white = rl.color_alpha(rl.WHITE, alpha)
    black = rl.color_alpha(rl.BLACK, alpha)
    text_color = rl.color_alpha(color, alpha)
    rl.draw_rectangle_rounded(rect, roundness(rect, 18 * k), 10, white)
    inner = rl.Rectangle(rect.x + 9 * k, rect.y + 9 * k, rect.width - 18 * k, rect.height - 18 * k)
    rl.draw_rectangle_rounded_lines_ex(inner, roundness(inner, 12 * k), 10, max(3.0, 5 * k), black)
    cx = rect.x + rect.width / 2
    self._draw_text_centered(self.font_demi, "MAXIMUM", 22 * k, rl.Vector2(cx, rect.y + 42 * k), black)
    self._draw_text_centered(self.font_bold, val, (88 if len(val) < 3 else 66) * k, rl.Vector2(cx, rect.y + rect.height / 2 + 10 * k),
                             text_color)
    self._draw_text_centered(self.font_demi, "km/h" if ui_state.is_metric else "mph", 30 * k,
                             rl.Vector2(cx, rect.y + rect.height - 44 * k), black)
    if sub and has_limit:
      box = 64 * k
      s_rect = rl.Rectangle(rect.x + rect.width - box * 0.6, rect.y - box * 0.4, box, box)
      rl.draw_rectangle_rounded(s_rect, roundness(s_rect, 14 * k), 10, Console.BG_PANEL)
      rl.draw_rectangle_rounded_lines_ex(s_rect, roundness(s_rect, 14 * k), 10, 2, Console.BORDER_DEFAULT)
      self._draw_text_centered(self.font_bold, sub, 30 * k, rl.Vector2(s_rect.x + box / 2, s_rect.y + box / 2), Console.TEXT_PRIMARY)

  def _draw_ahead_info(self, sign_rect):
    if self.target is None:
      super()._draw_ahead_info(sign_rect)
      return
    if self.speed_limit_source != SpeedLimitSource.map:
      return
    if not (self.speed_limit_ahead_valid and self.speed_limit_ahead > 0 and self.speed_limit_ahead != self.speed_limit):
      return
    # A chip under the speed card, right edge under the sign: "80 ahead · 400 m"
    text = f"{round(self.speed_limit_ahead)} {tr('ahead')}"
    dist = self._format_dist(self.speed_limit_ahead_dist)
    tw, dw = D.text_w(text, D.LABEL, semi=True), D.text_w(dist, D.LABEL)
    w = 24 + tw + 16 + dw + 24
    r = rl.Rectangle(sign_rect.x + sign_rect.width - w, self.chip_y, w, 52)
    rl.draw_rectangle_rounded(r, 1.0, 12, Onroad.PANEL)
    D.text(text, r.x + 24, r.y + (52 - D.LABEL) / 2 - 2, D.LABEL, Console.TEXT_PRIMARY, semi=True)
    D.text(dist, r.x + 24 + tw + 16, r.y + (52 - D.LABEL) / 2 - 2, D.LABEL, Console.TEXT_MUTED)


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

def e2e_notice(ca) -> tuple[str, str, rl.Color, str, bool] | None:
  """Read SP CircularAlertsRenderer state and return (title, sub, bar, icon, go) to show, if any.
  Green light and the lead moving off are "go" notices (green, they ring to catch the eye at a stop);
  the stopped timer is quiet information (muted, no motion)."""
  if not ca._allow_e2e_alerts:
    return None
  if ca._e2e_alert_display_timer > 0:
    if ca._green_light_alert:
      return tr("Green light"), tr("Time to go"), Console.SUCCESS, "light_go", True
    if ca._lead_depart_alert:
      return tr("Lead is moving"), tr("The car ahead pulled away"), Console.SUCCESS, "lead_go", True
    return None
  if ui_state.standstill_timer and ca._is_standstill:
    return f"{tr('Stopped')} {ca._alert_text}", "", Console.TEXT_SECONDARY, "timer", False
  return None
