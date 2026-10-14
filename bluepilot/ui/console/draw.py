"""
Drawing kit for the Console shell on the comma 3X (2160x1080).

Text, Console line icons, toggles, segmented controls, chips and cards, sized for a screen
read at arm's length. Everything colours from bluepilot.ui.lib.theme tokens, so day/night
and accent changes apply without re-creating anything.
"""

from __future__ import annotations

import math

import pyray as rl

from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from bluepilot.ui.lib.theme import Console, Radius, roundness

# Type scale (device px)
H1 = 52        # page title
H2 = 38        # card title
BODY = 34
LABEL = 28
CAPTION = 24

CARD_PAD = 32
ROW_H = 112
CONTROL_H = 76


def font(semi: bool = False, light: bool = False):
  # 7.0 dropped FontWeight.LIGHT; Console type is two weights (400/600), so light uses 400
  if light:
    return gui_app.font(FontWeight.NORMAL)
  return gui_app.font(FontWeight.SEMI_BOLD if semi else FontWeight.NORMAL)


def text_w(s: str, size: float, semi: bool = False, light: bool = False) -> float:
  return measure_text_cached(font(semi, light), s, int(size)).x


def text(s: str, x: float, y: float, size: float, color: rl.Color | None = None, semi: bool = False, light: bool = False) -> float:
  """Draw text with its top-left at (x, y); returns the width."""
  f = font(semi, light)
  rl.draw_text_ex(f, s, rl.Vector2(x, y), size, 0, color if color is not None else Console.TEXT_PRIMARY)
  return measure_text_cached(f, s, int(size)).x


def text_right(s: str, right: float, y: float, size: float, color: rl.Color | None = None, semi: bool = False) -> float:
  w = text_w(s, size, semi)
  text(s, right - w, y, size, color, semi)
  return w


def text_center(s: str, cx: float, y: float, size: float, color: rl.Color | None = None, semi: bool = False, light: bool = False):
  w = text_w(s, size, semi, light)
  text(s, cx - w / 2, y, size, color, semi, light)


def value_unit(value: str, unit: str, x: float, y: float, size: float, unit_size: float,
               color: rl.Color | None = None, light: bool = False) -> float:
  """A numeral with its muted unit, baseline-aligned. Returns total width."""
  w = text(value, x, y, size, color, semi=not light, light=light)
  if unit:
    uy = y + size * 0.86 - unit_size * 0.86
    w += 10 + text(unit, x + w + 10, uy, unit_size, Console.TEXT_MUTED)
  return w


def fit(s: str, size: float, max_w: float, semi: bool = False) -> str:
  if text_w(s, size, semi) <= max_w:
    return s
  while s and text_w(s + "…", size, semi) > max_w:
    s = s[:-1]
  return s + "…"


def wrap(s: str, size: float, max_w: float, max_lines: int = 2, semi: bool = False) -> list[str]:
  lines: list[str] = []
  cur = ""
  for word in s.split():
    nxt = f"{cur} {word}".strip()
    if cur and text_w(nxt, size, semi) > max_w:
      lines.append(cur)
      cur = word
    else:
      cur = nxt
  if cur:
    lines.append(cur)
  if len(lines) > max_lines:
    lines = lines[:max_lines]
    lines[-1] = fit(lines[-1] + " …", size, max_w, semi) if not lines[-1].endswith("…") else lines[-1]
  return [fit(ln, size, max_w, semi) for ln in lines]


# ---------------------------------------------------------------------------
# Surfaces
# ---------------------------------------------------------------------------

def card(rect: rl.Rectangle, color: rl.Color | None = None, radius: float = Radius.MD * 2):
  rl.draw_rectangle_rounded(rect, roundness(rect, radius), 10, color if color is not None else Console.BG_PANEL)
  from bluepilot.ui.lib.theme import is_day
  if is_day():  # light theme: cards carry a hairline instead of tone
    rl.draw_rectangle_rounded_lines_ex(rect, roundness(rect, radius), 10, 2, Console.BORDER_DEFAULT)


def dot(cx: float, cy: float, r: float, color: rl.Color):
  rl.draw_circle(int(cx), int(cy), r, color)


def chip(x: float, y: float, label: str, dot_color: rl.Color | None = None, h: float = 60,
         size: float = LABEL, bg: rl.Color | None = None, fg: rl.Color | None = None) -> rl.Rectangle:
  pad = 24
  dw = 28 if dot_color is not None else 0
  w = pad * 2 + dw + text_w(label, size, semi=True)
  r = rl.Rectangle(x, y, w, h)
  rl.draw_rectangle_rounded(r, roundness(r, Radius.SM * 2), 8, bg if bg is not None else Console.BG_RAISED)
  if dot_color is not None:
    dot(x + pad + 8, y + h / 2, 9, dot_color)
  text(label, x + pad + dw, y + (h - size) / 2 - 2, size, fg if fg is not None else Console.TEXT_SECONDARY, semi=True)
  return r


def bar(rect: rl.Rectangle, frac: float, fill: rl.Color, track: rl.Color | None = None):
  frac = max(0.0, min(1.0, frac))
  rl.draw_rectangle_rounded(rect, roundness(rect, 4), 4, track if track is not None else Console.BG_TRACK)
  if frac > 0:
    f = rl.Rectangle(rect.x, rect.y, max(2.0, rect.width * frac), rect.height)
    rl.draw_rectangle_rounded(f, roundness(f, 4), 4, fill)


# ---------------------------------------------------------------------------
# Controls (drawn; the owner does hit testing with the returned rects)
# ---------------------------------------------------------------------------

def toggle(x: float, y: float, on: bool, enabled: bool = True) -> rl.Rectangle:
  w, h = 104, 60
  r = rl.Rectangle(x, y, w, h)
  track = (Console.ACCENT_FILL if on else Console.TOGGLE_OFF) if enabled else Console.BG_HIGH
  rl.draw_rectangle_rounded(r, 1.0, 16, track)
  kx = x + (w - h / 2 - 2) if on else x + h / 2 + 2
  rl.draw_circle(int(kx), int(y + h / 2), h / 2 - 8, Console.TOGGLE_KNOB if enabled else Console.TEXT_GHOST)
  return r


def segmented(rect: rl.Rectangle, labels: list[str], selected: int, size: float = LABEL,
              track: rl.Color | None = None) -> list[rl.Rectangle]:
  rl.draw_rectangle_rounded(rect, roundness(rect, 12), 8, track if track is not None else Console.BG_RAISED)
  n = max(1, len(labels))
  pad = 6
  seg_w = (rect.width - pad * 2) / n
  rects = []
  for i, label in enumerate(labels):
    sr = rl.Rectangle(rect.x + pad + i * seg_w, rect.y + pad, seg_w, rect.height - pad * 2)
    rects.append(sr)
    if i == selected:
      rl.draw_rectangle_rounded(sr, roundness(sr, 8), 8, Console.ACCENT_FILL)
    color = Console.ON_ACCENT if i == selected else Console.TEXT_SECONDARY
    s = fit(label, size, sr.width - 16, semi=True)
    text_center(s, sr.x + sr.width / 2, sr.y + (sr.height - size) / 2 - 2, size, color, semi=True)
  return rects


def button(rect: rl.Rectangle, label: str, primary: bool = True, pressed: bool = False, size: float = BODY - 2):
  if primary:
    bg = Console.ACCENT_FILL_HOVER if pressed else Console.ACCENT_FILL
    fg = Console.ON_ACCENT
  else:
    bg = Console.BG_HIGH if pressed else Console.BG_RAISED
    fg = Console.TEXT_PRIMARY
  rl.draw_rectangle_rounded(rect, roundness(rect, 8), 8, bg)
  if not primary:
    rl.draw_rectangle_rounded_lines_ex(rect, roundness(rect, 8), 8, 2, Console.BORDER_DEFAULT)
  text_center(label, rect.x + rect.width / 2, rect.y + (rect.height - size) / 2 - 2, size, fg, semi=True)


def hit(rect: rl.Rectangle | None, pos) -> bool:
  return rect is not None and rl.check_collision_point_rec(pos, rect)


# ---------------------------------------------------------------------------
# Icons: Console line set, 24-unit grid, 2-unit stroke, drawn at any size
# ---------------------------------------------------------------------------

def _line(pts, ox, oy, s, w, color):
  for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
    rl.draw_line_ex(rl.Vector2(ox + x0 * s, oy + y0 * s), rl.Vector2(ox + x1 * s, oy + y1 * s), w, color)
  for x, y in pts:
    rl.draw_circle_v(rl.Vector2(ox + x * s, oy + y * s), w / 2, color)


def _ring(cx, cy, r, ox, oy, s, w, color):
  rl.draw_ring(rl.Vector2(ox + cx * s, oy + cy * s), r * s - w / 2, r * s + w / 2, 0, 360, 48, color)


def _arc(cx, cy, r, a0, a1, ox, oy, s, w, color):
  rl.draw_ring(rl.Vector2(ox + cx * s, oy + cy * s), r * s - w / 2, r * s + w / 2, a0, a1, 32, color)


def icon(name: str, x: float, y: float, size: float, color: rl.Color):
  """Draw a Console line icon with its 24-unit box at (x, y) scaled to size px."""
  s = size / 24.0
  w = max(2.0, 2.0 * s)
  if name == "home":
    _line([(3, 10.5), (12, 3), (21, 10.5), (21, 21), (3, 21), (3, 10.5)], x, y, s, w, color)
    _line([(9, 21), (9, 15), (15, 15), (15, 21)], x, y, s, w, color)
  elif name == "wheel":
    _ring(12, 12, 9, x, y, s, w, color)
    _ring(12, 12, 2.5, x, y, s, w, color)
    _line([(3.5, 10), (9.5, 10)], x, y, s, w, color)
    _line([(14.5, 10), (20.5, 10)], x, y, s, w, color)
    _line([(12, 14.5), (12, 21)], x, y, s, w, color)
  elif name == "calibrate":  # mount and camera calibration: a target with crosshair ticks
    _ring(12, 12, 7, x, y, s, w, color)
    _ring(12, 12, 1.5, x, y, s, w, color)
    for a, b in (((12, 1.5), (12, 5)), ((12, 19), (12, 22.5)), ((1.5, 12), (5, 12)), ((19, 12), (22.5, 12))):
      _line([a, b], x, y, s, w, color)
  elif name == "flask":  # Experimental Mode
    _line([(9, 3), (15, 3)], x, y, s, w, color)
    _line([(10, 3), (10, 9.5), (4.5, 19), (5.5, 21), (18.5, 21), (19.5, 19), (14, 9.5), (14, 3)], x, y, s, w, color)
    _line([(7, 15), (17, 15)], x, y, s, w, color)
  elif name == "bolt":
    _line([(13, 2), (4, 14), (11, 14), (10, 22), (19, 10), (12, 10), (13, 2)], x, y, s, w, color)
  elif name == "screen":
    rl.draw_rectangle_rounded_lines_ex(rl.Rectangle(x + 3 * s, y + 4 * s, 18 * s, 13 * s), 0.2, 8, w, color)
    _line([(8, 21), (16, 21)], x, y, s, w, color)
    _line([(12, 17), (12, 21)], x, y, s, w, color)
  elif name == "wifi":
    _arc(12, 20, 15, 210, 330, x, y, s, w, color)
    _arc(12, 20, 10, 215, 325, x, y, s, w, color)
    _arc(12, 20, 5, 225, 315, x, y, s, w, color)
    rl.draw_circle_v(rl.Vector2(x + 12 * s, y + 20 * s), w, color)
  elif name == "sliders":
    _line([(4, 6), (14, 6)], x, y, s, w, color)
    _line([(18, 6), (20, 6)], x, y, s, w, color)
    _line([(4, 12), (8, 12)], x, y, s, w, color)
    _line([(12, 12), (20, 12)], x, y, s, w, color)
    _line([(4, 18), (16, 18)], x, y, s, w, color)
    _ring(16, 6, 2, x, y, s, w, color)
    _ring(10, 12, 2, x, y, s, w, color)
    _ring(18, 18, 2, x, y, s, w, color)
  elif name == "bookmark":
    _line([(6, 3), (18, 3), (18, 21), (12, 17), (6, 21), (6, 3)], x, y, s, w, color)
  elif name == "pulse":
    _line([(3, 12), (7, 12), (10, 4), (14, 20), (17, 12), (21, 12)], x, y, s, w, color)
  elif name == "person":
    _ring(12, 9, 4.5, x, y, s, w, color)
    _arc(12, 24, 9, 200, 340, x, y, s, w, color)
  elif name == "chevron":
    _line([(9, 5), (16, 12), (9, 19)], x, y, s, w, color)
  elif name == "cell":  # cellular: four rising bars
    for i, h in enumerate((5, 9, 13, 17)):
      bx = 4.5 + i * 4.5
      _line([(bx, 21), (bx, 21 - h)], x, y, s, w, color)
  elif name == "bluetooth":
    _line([(6.5, 7.5), (17, 16.5), (12, 21), (12, 3), (17, 7.5), (6.5, 16.5)], x, y, s, w, color)
  elif name == "warning":
    _line([(12, 3), (22, 20.5), (2, 20.5), (12, 3)], x, y, s, w, color)
    _line([(12, 9.5), (12, 14)], x, y, s, w, color)
    rl.draw_circle_v(rl.Vector2(x + 12 * s, y + 17.3 * s), w * 0.75, color)
  elif name == "check":
    _line([(4.5, 12.5), (9.5, 17.5), (19.5, 6.5)], x, y, s, w, color)
  elif name == "close":
    _line([(6, 6), (18, 18)], x, y, s, w, color)
    _line([(18, 6), (6, 18)], x, y, s, w, color)
  elif name == "search":
    _ring(11, 11, 7, x, y, s, w, color)
    _line([(16, 16), (20, 20)], x, y, s, w, color)
  elif name == "grid":
    for gx, gy in ((3, 3), (14, 3), (3, 14), (14, 14)):
      rl.draw_rectangle_rounded_lines_ex(rl.Rectangle(x + gx * s, y + gy * s, 7 * s, 7 * s), 0.25, 6, w, color)
  elif name == "route":
    _ring(6, 19, 2, x, y, s, w, color)
    _ring(18, 5, 2, x, y, s, w, color)
    _line([(8, 19), (16.5, 19)], x, y, s, w, color)
    _arc(16.5, 15.5, 3.5, -90, 90, x, y, s, w, color)
    _line([(16.5, 12), (7.5, 12)], x, y, s, w, color)
    _arc(7.5, 8.5, 3.5, 90, 270, x, y, s, w, color)
    _line([(7.5, 5), (16, 5)], x, y, s, w, color)
  elif name == "bell":
    _arc(12, 9, 6, 180, 360, x, y, s, w, color)
    _line([(6, 9), (6, 13), (3.5, 17), (20.5, 17), (18, 13), (18, 9)], x, y, s, w, color)
    _line([(10.3, 20.5), (13.7, 20.5)], x, y, s, w, color)
  elif name == "plug":
    _line([(9, 2), (9, 8)], x, y, s, w, color)
    _line([(15, 2), (15, 8)], x, y, s, w, color)
    _line([(6, 8), (18, 8), (18, 12)], x, y, s, w, color)
    _line([(6, 8), (6, 12)], x, y, s, w, color)
    _arc(12, 12, 6, 0, 180, x, y, s, w, color)
    _line([(12, 18), (12, 22)], x, y, s, w, color)
  elif name == "list":
    for ly in (6, 12, 18):
      _line([(8, ly), (21, ly)], x, y, s, w, color)
      rl.draw_circle_v(rl.Vector2(x + 3.5 * s, y + ly * s), w * 0.75, color)
  elif name == "thermo":
    _line([(10, 15), (10, 4)], x, y, s, w, color)
    _line([(14, 15), (14, 4)], x, y, s, w, color)
    _arc(12, 4, 2, 180, 360, x, y, s, w, color)
    _ring(12, 17.5, 3.5, x, y, s, w, color)
  elif name == "steer":
    _line([(4, 19), (12, 4), (20, 19)], x, y, s, w, color)
    _line([(8, 12.5), (16, 12.5)], x, y, s, w, color)
  elif name == "gauge":
    _arc(12, 14, 9, 150, 390, x, y, s, w, color)
    _line([(12, 14), (16, 10)], x, y, s, w, color)
  elif name == "cpu":
    rl.draw_rectangle_rounded_lines_ex(rl.Rectangle(x + 5 * s, y + 5 * s, 14 * s, 14 * s), 0.2, 6, w, color)
    rl.draw_rectangle_lines_ex(rl.Rectangle(x + 9 * s, y + 9 * s, 6 * s, 6 * s), w, color)
    for p in (9, 15):
      _line([(p, 2), (p, 5)], x, y, s, w, color)
      _line([(p, 19), (p, 22)], x, y, s, w, color)
      _line([(2, p), (5, p)], x, y, s, w, color)
      _line([(19, p), (22, p)], x, y, s, w, color)
  elif name == "tune":
    _ring(12, 12, 6, x, y, s, w, color)
    for a, b in (((12, 2), (12, 6)), ((12, 18), (12, 22)), ((2, 12), (6, 12)), ((18, 12), (22, 12))):
      _line([a, b], x, y, s, w, color)
  elif name == "palette":
    _ring(12, 12, 9, x, y, s, w, color)
    for px, py in ((8, 10), (12, 7), (16, 10)):
      rl.draw_circle_v(rl.Vector2(x + px * s, y + py * s), w, color)
  elif name == "eye":
    _arc(12, 20, 11, 215, 325, x, y, s, w, color)
    _arc(12, 4, 11, 35, 145, x, y, s, w, color)
    _ring(12, 12, 3, x, y, s, w, color)
  elif name == "cloud":
    _arc(9, 13, 5, 120, 280, x, y, s, w, color)
    _arc(15, 11, 5.5, 200, 380, x, y, s, w, color)
    _line([(6.5, 17.5), (17.5, 17.5)], x, y, s, w, color)
  elif name == "flame":
    _line([(12, 3), (17, 10), (18, 15)], x, y, s, w, color)
    _line([(12, 3), (7, 10), (6, 15)], x, y, s, w, color)
    _arc(12, 15, 6, 0, 180, x, y, s, w, color)
  elif name == "export":
    _line([(12, 3), (12, 15)], x, y, s, w, color)
    _line([(7, 8), (12, 3), (17, 8)], x, y, s, w, color)
    _line([(4, 14), (4, 21), (20, 21), (20, 14)], x, y, s, w, color)
  elif name == "phone":
    rl.draw_rectangle_rounded_lines_ex(rl.Rectangle(x + 6 * s, y + 2 * s, 12 * s, 20 * s), 0.25, 6, w, color)
    _line([(11, 18), (13, 18)], x, y, s, w, color)
  elif name == "car":
    _line([(3, 16), (3, 12), (6, 6), (18, 6), (21, 12), (21, 16), (3, 16)], x, y, s, w, color)
    _ring(7.5, 17, 2, x, y, s, w, color)
    _ring(16.5, 17, 2, x, y, s, w, color)
  elif name == "download":
    _line([(12, 3), (12, 15)], x, y, s, w, color)
    _line([(7, 10), (12, 15), (17, 10)], x, y, s, w, color)
    _line([(4, 21), (20, 21)], x, y, s, w, color)
  elif name == "map":
    _line([(3, 6), (9, 3), (15, 6), (21, 3), (21, 18), (15, 21), (9, 18), (3, 21), (3, 6)], x, y, s, w, color)
    _line([(9, 3), (9, 18)], x, y, s, w, color)
    _line([(15, 6), (15, 21)], x, y, s, w, color)
  elif name == "code":
    _line([(8, 7), (3, 12), (8, 17)], x, y, s, w, color)
    _line([(16, 7), (21, 12), (16, 17)], x, y, s, w, color)
  elif name == "layout":
    rl.draw_rectangle_rounded_lines_ex(rl.Rectangle(x + 3 * s, y + 3 * s, 18 * s, 18 * s), 0.12, 6, w, color)
    _line([(3, 9), (21, 9)], x, y, s, w, color)
    _line([(9, 9), (9, 21)], x, y, s, w, color)
  elif name == "battery":
    rl.draw_rectangle_rounded_lines_ex(rl.Rectangle(x + 2 * s, y + 7 * s, 17 * s, 10 * s), 0.25, 6, w, color)
    _line([(21.5, 10.5), (21.5, 13.5)], x, y, s, w, color)
  elif name == "sun":  # screen brightness: a disc with eight rays
    _ring(12, 12, 4, x, y, s, w, color)
    for a, b in (((12, 2), (12, 4.5)), ((12, 19.5), (12, 22)), ((2, 12), (4.5, 12)), ((19.5, 12), (22, 12)),
                 ((4.9, 4.9), (6.7, 6.7)), ((17.3, 17.3), (19.1, 19.1)), ((4.9, 19.1), (6.7, 17.3)), ((17.3, 6.7), (19.1, 4.9))):
      _line([a, b], x, y, s, w, color)
  elif name == "clock":  # timers and delays: a dial with two hands
    _ring(12, 12, 9, x, y, s, w, color)
    _line([(12, 7), (12, 12), (15.5, 14)], x, y, s, w, color)
  else:
    _ring(12, 12, 9, x, y, s, w, color)


def ring_gauge(cx: float, cy: float, r: float, width: float, frac: float, fill: rl.Color,
               track: rl.Color | None = None, marker: float | None = None):
  """Ring that fills clockwise from 12 o'clock."""
  rl.draw_ring(rl.Vector2(cx, cy), r - width / 2, r + width / 2, 0, 360, 96, track if track is not None else Console.BG_TRACK)
  frac = max(0.0, min(1.0, frac))
  if frac > 0:
    rl.draw_ring(rl.Vector2(cx, cy), r - width / 2, r + width / 2, -90, -90 + 360 * frac, 96, fill)
  if marker is not None and 0 < marker <= 1:
    a = math.radians(-90 + 360 * marker)
    p0 = rl.Vector2(cx + math.cos(a) * (r - width / 2 - 14), cy + math.sin(a) * (r - width / 2 - 14))
    p1 = rl.Vector2(cx + math.cos(a) * (r + width / 2 + 14), cy + math.sin(a) * (r + width / 2 + 14))
    rl.draw_line_ex(p0, p1, 6, Console.TEXT_PRIMARY)
