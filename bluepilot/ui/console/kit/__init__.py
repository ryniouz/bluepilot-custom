"""
Console component kit: Citadel's page patterns for the comma 3X (2160x1080).

Citadel's Console theme and icons at phone-app sizes for the small 3X screen: big type,
big touch targets, few things per screen. Stat strips, thick squared bars, key/value grids,
form rows and controls (the area chart is for the Statistics page only). Everything colours from bluepilot.ui.lib.theme tokens per
frame, so day/night and accent changes need nothing else.

Drawing only: each call returns the rects its owner hit-tests.
"""

from __future__ import annotations

import math
import time
from collections.abc import Sequence
from dataclasses import dataclass

import pyray as rl

from bluepilot.ui.console import draw as D
from bluepilot.ui.lib.theme import Console, is_day, roundness

# -- metrics (device px) ------------------------------------------------------------------
TOP_H = 96
RAIL_W = 92
PAD_L = 48
PAD_R = 44
PAD_T = 24
GAP = 24
HEADER_H = 84

TAB = 28          # top-bar tab label
TITLE = 52        # page title
SUB = 30          # page subtitle
H2 = 40           # section title
CAP = 30          # captions, notes, axis ticks
VAL = 64          # stat value
KV = 38           # key/value value, row title
DESC = 30         # row description

PANEL_R = 24      # card radius
HAIR = 2          # hairline width


def rgba(c: rl.Color, a: int) -> rl.Color:
  """A per-frame translucent copy of a token (not recorded as a derived theme colour)."""
  return rl.Color(c.r, c.g, c.b, max(0, min(255, int(a))))


# -- surfaces -----------------------------------------------------------------------------

def panel(r: rl.Rectangle, color: rl.Color | None = None):
  rl.draw_rectangle_rounded(r, roundness(r, PANEL_R), 10, color if color is not None else Console.BG_PANEL)
  if is_day():
    rl.draw_rectangle_rounded_lines_ex(r, roundness(r, PANEL_R), 10, HAIR, Console.BORDER_DEFAULT)


def vline(x: float, y0: float, y1: float, color: rl.Color | None = None):
  rl.draw_rectangle_rec(rl.Rectangle(x, y0, HAIR, y1 - y0), color if color is not None else Console.BORDER_SUBTLE)


def hline(x0: float, x1: float, y: float, color: rl.Color | None = None):
  rl.draw_rectangle_rec(rl.Rectangle(x0, y, x1 - x0, HAIR), color if color is not None else Console.BORDER_SUBTLE)


def split_cols(r: rl.Rectangle, weights: Sequence[float]) -> list[rl.Rectangle]:
  total = sum(weights)
  out, x = [], r.x
  for w in weights:
    cw = r.width * w / total
    out.append(rl.Rectangle(x, r.y, cw, r.height))
    x += cw
  return out


def split_rows(r: rl.Rectangle, weights: Sequence[float]) -> list[rl.Rectangle]:
  total = sum(weights)
  out, y = [], r.y
  for w in weights:
    rh = r.height * w / total
    out.append(rl.Rectangle(r.x, y, r.width, rh))
    y += rh
  return out


def joined(r: rl.Rectangle, sections: Sequence[rl.Rectangle]):
  """One panel holding `sections` (sub-rects of r), separated by hairlines on their shared edges."""
  panel(r)
  for s in sections:
    if s.x > r.x + 1:
      vline(s.x, s.y, s.y + s.height)
    if s.y > r.y + 1:
      hline(s.x, s.x + s.width, s.y)


def inset(r: rl.Rectangle, pad_x: float = 32, pad_y: float = 24) -> rl.Rectangle:
  return rl.Rectangle(r.x + pad_x, r.y + pad_y, r.width - 2 * pad_x, r.height - 2 * pad_y)


# -- chrome ---------------------------------------------------------------------------------

def top_bar(r: rl.Rectangle, tabs: Sequence[tuple[str, str]], active: int, status: Sequence[tuple[str, rl.Color]] = (),
            alerts: int = 0, product: str = "BLUEPILOT") -> tuple[list[rl.Rectangle], rl.Rectangle]:
  """Section tabs across the top. Returns (tab rects, bell rect)."""
  rl.draw_rectangle_rec(r, Console.BG_PAGE)
  hline(r.x, r.x + r.width, r.y + r.height - HAIR)
  x = r.x + 20
  mark = rl.Rectangle(x, r.y + (r.height - 52) / 2, 52, 52)
  rl.draw_rectangle_rounded(mark, roundness(mark, 12), 8, Console.ACCENT_FILL)
  D.text_center("BP", mark.x + 26, mark.y + 13, 22, Console.ON_ACCENT, semi=True)
  x += 52 + 16
  x += D.text(product, x, r.y + (r.height - 26) / 2 - 1, 26, semi=True) + 44

  rects = []
  for i, (label, ic) in enumerate(tabs):
    w = 26 + 32 + 14 + D.text_w(label, TAB) + 26
    tr = rl.Rectangle(x, r.y, w, r.height)
    rects.append(tr)
    on = i == active
    D.icon(ic, x + 26, r.y + (r.height - 32) / 2, 32, Console.ACCENT if on else Console.TEXT_MUTED)
    D.text(label, x + 26 + 32 + 14, r.y + (r.height - TAB) / 2 - 2, TAB, Console.TEXT_PRIMARY if on else Console.TEXT_SECONDARY)
    if on:
      rl.draw_rectangle_rec(rl.Rectangle(x, r.y + r.height - 4, w, 4), Console.ACCENT)
    x += w

  right = r.x + r.width - 32
  clock = time.strftime("%-I:%M %p")
  right -= D.text_right(clock, right, r.y + (r.height - TAB) / 2 - 2, TAB, semi=True) + 32
  bell = rl.Rectangle(right - 40, r.y + (r.height - 40) / 2, 40, 40)
  D.icon("bell", bell.x + 2, bell.y + 2, 36, Console.TEXT_MUTED)
  if alerts:
    D.dot(bell.x + 34, bell.y + 6, 8, Console.DANGER)
  right = bell.x - 28
  for label, color in status:
    w = 18 + 16 + 12 + D.text_w(label, CAP, semi=True) + 18
    c = rl.Rectangle(right - w, r.y + (r.height - 48) / 2, w, 48)
    rl.draw_rectangle_rounded(c, roundness(c, 8), 8, Console.BG_HIGH)
    D.dot(c.x + 18 + 8, c.y + 24, 8, color)
    D.text(label, c.x + 18 + 16 + 12, c.y + (48 - CAP) / 2 - 1, CAP, Console.TEXT_SECONDARY, semi=True)
    right = c.x - 16
  return rects, bell


def page_rail(r: rl.Rectangle, icons: Sequence[str], active: int) -> list[rl.Rectangle]:
  """The section's pages as an icon column. Returns item rects."""
  rl.draw_rectangle_rec(r, Console.BG_PANEL)
  vline(r.x + r.width - HAIR, r.y, r.y + r.height)
  rects = []
  y = r.y + 24
  for i, ic in enumerate(icons):
    it = rl.Rectangle(r.x + (r.width - 68) / 2, y, 68, 68)
    rects.append(rl.Rectangle(r.x, y - 6, r.width, 80))
    on = i == active
    if on:
      rl.draw_rectangle_rounded(it, roundness(it, 12), 8, Console.ACCENT_TINT)
    D.icon(ic, it.x + 15, it.y + 15, 38, Console.ACCENT if on else Console.TEXT_MUTED)
    y += 80
  return rects


def page_header(r: rl.Rectangle, ic: str, title: str, sub: str = "", sub_dot: rl.Color | None = None,
                action: str | None = None, action_primary: bool = False, chip: tuple[str, rl.Color] | None = None,
                chip_accent: bool = False) -> rl.Rectangle | None:
  """Icon, title, subtitle with a status dot, and one chip or button on the right. Returns the button rect."""
  D.icon(ic, r.x, r.y + 18, 40, Console.TEXT_MUTED)
  tx = r.x + 40 + 24
  D.text(title, tx, r.y, TITLE, semi=True)
  if sub:
    parts = sub.split("|", 1)
    x = tx
    if len(parts) == 2:
      x += D.text(parts[0].strip(), x, r.y + 48, SUB, Console.TEXT_SECONDARY) + 14
      if sub_dot is None:
        x += D.text("·", x, r.y + 48, SUB, Console.TEXT_MUTED) + 14
    if sub_dot is not None:
      D.dot(x + 8, r.y + 48 + SUB / 2 + 2, 8, sub_dot)
      x += 16 + 12
    D.text(parts[-1].strip(), x, r.y + 48, SUB, Console.TEXT_SECONDARY)
  right = r.x + r.width
  if action:
    w = D.text_w(action, KV - 2, semi=True) + 56
    b = rl.Rectangle(right - w, r.y + (r.height - 64) / 2, w, 64)
    pressed = rl.is_mouse_button_down(rl.MouseButton.MOUSE_BUTTON_LEFT) and rl.check_collision_point_rec(rl.get_mouse_position(), b)
    D.button(b, action, primary=action_primary, pressed=pressed, size=KV - 2)
    return b
  if chip:
    label, color = chip
    w = 18 + 16 + 12 + D.text_w(label, CAP, semi=True) + 18
    c = rl.Rectangle(right - w, r.y + (r.height - 48) / 2, w, 48)
    rl.draw_rectangle_rounded(c, roundness(c, 8), 8, Console.ACCENT_TINT if chip_accent else Console.BG_HIGH)
    D.dot(c.x + 26, c.y + 24, 8, color)
    D.text(label, c.x + 46, c.y + (48 - CAP) / 2 - 1, CAP, Console.ACCENT_TEXT if chip_accent else Console.TEXT_SECONDARY, semi=True)
  return None


# -- data -----------------------------------------------------------------------------------

@dataclass
class Stat:
  label: str
  value: str
  unit: str = ""
  note: str = ""
  tone: rl.Color | None = None   # status dot before the value
  value_color: rl.Color | None = None


STRIP_H = 200
BAR_H = 40        # thick squared SOC bar


def stat_strip(r: rl.Rectangle, cells: Sequence[Stat]):
  """One panel split into equal cells: caption, value with muted unit, note."""
  cols = split_cols(r, [1] * max(1, len(cells)))
  joined(r, cols)
  for c, s in zip(cols, cells, strict=False):
    x, y = c.x + 32, c.y + 24
    D.text(D.fit(s.label, CAP, c.width - 48), x, y, CAP, Console.TEXT_MUTED)
    vx = x
    if s.tone is not None:
      D.dot(vx + 10, y + 44 + VAL / 2, 10, s.tone)
      vx += 34
    D.value_unit(s.value, s.unit, vx, y + 44, VAL, CAP, s.value_color)
    if s.note:
      D.text(D.fit(s.note, CAP, c.width - 48), x, y + 44 + VAL + 12, CAP, Console.TEXT_SECONDARY)


def section_title(r: rl.Rectangle, title: str, caption: str = "", right: str = "",
                  right_color: rl.Color | None = None) -> float:
  """Title and muted caption at the top of a section. Returns the y below it."""
  w = D.text(title, r.x, r.y, H2, semi=True)
  if caption:
    D.text(D.fit(caption, CAP, r.width - w - 40 - (D.text_w(right, CAP) if right else 0)), r.x + w + 16, r.y + (H2 - CAP) - 2, CAP, Console.TEXT_MUTED)
  if right:
    D.text_right(right, r.x + r.width, r.y + (H2 - CAP) - 2, CAP, right_color if right_color is not None else Console.TEXT_MUTED)
  return r.y + H2 + 20


def kv(x: float, y: float, label: str, value: str, unit: str = "", max_w: float = 0,
       color: rl.Color | None = None):
  D.text(D.fit(label, CAP, max_w) if max_w else label, x, y, CAP, Console.TEXT_MUTED)
  if unit:
    D.value_unit(value, unit, x, y + 42, KV, CAP, color)
  else:
    D.text(D.fit(value, KV, max_w) if max_w else value, x, y + 42, KV, color)


def kv_grid(r: rl.Rectangle, items: Sequence[tuple[str, str, str]], cols: int, row_h: float = 112):
  cw = r.width / max(1, cols)
  for i, (label, value, unit) in enumerate(items):
    kv(r.x + (i % cols) * cw, r.y + (i // cols) * row_h, label, value, unit, max_w=cw - 24)


def bar(r: rl.Rectangle, frac: float, fill: rl.Color, target: float | None = None, live: bool = False):
  """A thick squared meter (BAR_H tall by default); `live` draws the striped fill for sampled readings, `target` a marker."""
  frac = max(0.0, min(1.0, frac))
  rl.draw_rectangle_rounded(r, roundness(r, 6), 4, Console.BG_TRACK)
  if frac > 0:
    w = max(4.0, r.width * frac)
    if live:
      x = r.x
      while x < r.x + w:
        rl.draw_rectangle_rec(rl.Rectangle(x, r.y, min(10, r.x + w - x), r.height), fill)
        x += 14
    else:
      f = rl.Rectangle(r.x, r.y, w, r.height)
      rl.draw_rectangle_rounded(f, roundness(f, 6), 4, fill)
  if target is not None and 0 < target <= 1:
    tx = r.x + r.width * target
    rl.draw_rectangle_rec(rl.Rectangle(tx - 3, r.y - 12, 6, r.height + 24), Console.TEXT_PRIMARY)


def gauge(cx: float, cy: float, radius: float, frac: float, fill: rl.Color, label: str, sub: str = "",
          target: float | None = None, width: float = 20):
  D.ring_gauge(cx, cy, radius, width, frac, fill, marker=target)
  D.text_center(label, cx, cy - 40, 60, semi=True)
  if sub:
    D.text_center(sub, cx, cy + 28, CAP, Console.TEXT_MUTED)


def _nice_ticks(vmin: float, vmax: float, n: int = 4) -> list[float]:
  span = max(1e-6, vmax - vmin)
  raw = span / n
  mag = 10 ** math.floor(math.log10(raw))
  step = next(m * mag for m in (1, 2, 2.5, 5, 10) if m * mag >= raw)
  lo = (vmin // step) * step
  ticks, t = [], lo
  while t <= vmax + step * 0.01:
    ticks.append(round(t, 6))
    t += step
  return ticks


def _dashed_h(x0: float, x1: float, y: float, color: rl.Color):
  x = x0
  while x < x1:
    rl.draw_rectangle_rec(rl.Rectangle(x, y, min(6, x1 - x), HAIR), color)
    x += 12


@dataclass
class Series:
  values: Sequence[float]          # evenly spaced, oldest first; NaN or None are gaps
  color: rl.Color
  area: bool = True


def area_chart(r: rl.Rectangle, series: Sequence[Series], x_labels: Sequence[str], vmin: float | None = None,
               vmax: float | None = None, unit: str = "", marker: float | None = None, fmt=None,
               empty: str = "No data yet"):
  """Citadel AreaChart: dashed gridlines, labelled ticks, 3 px line over a fading area, dot on the latest value."""
  vals = [v for s in series for v in s.values if v is not None and math.isfinite(v)]
  if len(vals) < 2:
    D.text_center(empty, r.x + r.width / 2, r.y + r.height / 2 - CAP / 2, CAP, Console.TEXT_MUTED)
    return
  lo = min(vals) if vmin is None else vmin
  hi = max(vals) if vmax is None else vmax
  if hi - lo < 1e-6:
    hi = lo + 1
  ticks = _nice_ticks(lo, hi, 3 if r.height < 220 else 4)
  lo, hi = min(lo, ticks[0]), max(hi, ticks[-1])
  fmt = fmt or (lambda v: f"{v:g}{unit}")
  label_w = max(D.text_w(fmt(t), CAP) for t in ticks) + 16
  plot = rl.Rectangle(r.x + label_w, r.y + 8, r.width - label_w - 8, r.height - 8 - CAP - 14)

  def py(v):
    return plot.y + plot.height * (1 - (v - lo) / (hi - lo))

  for t in ticks:
    y = py(t)
    if abs(t - lo) < 1e-9:
      hline(plot.x, plot.x + plot.width, y, Console.BORDER_DEFAULT)
    else:
      _dashed_h(plot.x, plot.x + plot.width, y, Console.BORDER_SUBTLE)
    D.text_right(fmt(t), plot.x - 12, y - CAP / 2 - 2, CAP, Console.TEXT_MUTED)
  n_lab = len(x_labels)
  for i, lab in enumerate(x_labels):
    x = plot.x + plot.width * (i / (n_lab - 1) if n_lab > 1 else 0)
    w = D.text_w(lab, CAP)
    lx = x if i == 0 else (x - w if i == n_lab - 1 else x - w / 2)
    D.text(lab, lx, plot.y + plot.height + 10, CAP, Console.TEXT_MUTED)
  if marker is not None:
    _dashed_h(plot.x, plot.x + plot.width, py(marker), Console.TEXT_MUTED)

  base = plot.y + plot.height
  for s in series:
    n = len(s.values)
    if n < 2:
      continue
    pts = [(plot.x + plot.width * i / (n - 1), py(v)) if v is not None and math.isfinite(v) else None
           for i, v in enumerate(s.values)]
    fill = rgba(s.color, 0x40 if not is_day() else 0x30)
    for a, b in zip(pts, pts[1:], strict=False):
      if a is None or b is None:
        continue
      if s.area:
        # quad a-b-base as two triangles (counter-clockwise for raylib)
        rl.draw_triangle(rl.Vector2(a[0], a[1]), rl.Vector2(a[0], base), rl.Vector2(b[0], base), fill)
        rl.draw_triangle(rl.Vector2(a[0], a[1]), rl.Vector2(b[0], base), rl.Vector2(b[0], b[1]), fill)
      rl.draw_line_ex(rl.Vector2(*a), rl.Vector2(*b), 3, s.color)
    last = next((p for p in reversed(pts) if p is not None), None)
    if last is not None:
      rl.draw_circle_v(rl.Vector2(*last), 7, s.color)


# -- forms ------------------------------------------------------------------------------------

FORM_ROW_H = 112


def form_row(r: rl.Rectangle, title: str, desc: str = "", first: bool = False):
  """Title and description on the left of a settings row; the caller draws the control at the right edge."""
  if not first:
    hline(r.x, r.x + r.width, r.y)
  ty = r.y + (r.height - (KV + (8 + DESC if desc else 0))) / 2
  D.text(D.fit(title, KV, r.width * 0.6), r.x, ty, KV)
  if desc:
    D.text(D.fit(desc, DESC, r.width * 0.62), r.x, ty + KV + 8, DESC, Console.TEXT_MUTED)


def toggle(right: float, cy: float, on: bool, enabled: bool = True) -> rl.Rectangle:
  w, h = 104, 60
  r = rl.Rectangle(right - w, cy - h / 2, w, h)
  track = (Console.ACCENT_FILL if on else Console.TOGGLE_OFF) if enabled else Console.BG_HIGH
  rl.draw_rectangle_rounded(r, 1.0, 16, track)
  kx = r.x + w - h / 2 if on else r.x + h / 2
  rl.draw_circle(int(kx), int(cy), h / 2 - 7, Console.TOGGLE_KNOB if enabled else Console.TEXT_GHOST)
  return r


def segmented(right: float, cy: float, labels: Sequence[str], selected: int, min_seg: float = 0) -> list[rl.Rectangle]:
  """Citadel segmented control, right-aligned at `right`. Returns segment rects."""
  pad = 6
  widths = [max(min_seg, D.text_w(lab, CAP, semi=True) + 56) for lab in labels]
  total = sum(widths) + pad * 2
  h = 80
  r = rl.Rectangle(right - total, cy - h / 2, total, h)
  rl.draw_rectangle_rounded(r, roundness(r, 12), 8, Console.BG_RAISED)
  rl.draw_rectangle_rounded_lines_ex(r, roundness(r, 12), 8, HAIR, Console.BORDER_DEFAULT)
  rects, x = [], r.x + pad
  for i, (lab, w) in enumerate(zip(labels, widths, strict=False)):
    sr = rl.Rectangle(x, r.y + pad, w, h - pad * 2)
    rects.append(sr)
    on = i == selected
    if on:
      rl.draw_rectangle_rounded(sr, roundness(sr, 10), 8, Console.ACCENT_FILL)
    D.text_center(lab, sr.x + w / 2, sr.y + (sr.height - CAP) / 2 - 2, CAP,
                  Console.ON_ACCENT if on else Console.TEXT_SECONDARY, semi=on)
    x += w
  return rects


def chip(x: float, y: float, label: str, color: rl.Color | None = None, accent: bool = False) -> rl.Rectangle:
  w = 22 + (32 if color is not None else 0) + D.text_w(label, CAP, semi=True) + 22
  c = rl.Rectangle(x, y, w, 60)
  rl.draw_rectangle_rounded(c, roundness(c, 12), 8, Console.ACCENT_TINT if accent else Console.BG_HIGH)
  tx = c.x + 22
  if color is not None:
    D.dot(tx + 9, c.y + 30, 9, color)
    tx += 32
  D.text(label, tx, c.y + (60 - CAP) / 2 - 1, CAP, Console.ACCENT_TEXT if accent else Console.TEXT_SECONDARY, semi=True)
  return c


def tag(x: float, y: float, label: str, accent: bool = False) -> rl.Rectangle:
  w = D.text_w(label, 26, semi=True) + 28
  c = rl.Rectangle(x, y, w, 44)
  rl.draw_rectangle_rounded(c, roundness(c, 8), 8, Console.ACCENT_TINT if accent else Console.BG_HIGH)
  D.text(label, c.x + 14, c.y + 8, 26, Console.ACCENT_TEXT if accent else Console.TEXT_SECONDARY, semi=True)
  return c


def signal_bars(x: float, bottom: float, h: float, level: int, color: rl.Color, n: int = 4) -> float:
  """Signal-strength bars (Wi-Fi or cellular), bottom-aligned at `bottom`. Returns the width drawn."""
  bw, gap = max(6.0, h / 4.5), max(4.0, h / 8)
  for i in range(n):
    bh = h * (i + 1) / n
    r = rl.Rectangle(x + i * (bw + gap), bottom - bh, bw, bh)
    rl.draw_rectangle_rounded(r, roundness(r, 2), 4, color if i < level else Console.BG_TRACK)
  return n * bw + (n - 1) * gap


def signal_chip(right: float, y: float, label: str, level: int | None, color: rl.Color | None = None) -> rl.Rectangle:
  """Right-aligned 60 px chip: signal bars (or a dot when there is no signal level) and a label."""
  h, pad = 60, 22
  icon_w = 4 * 7 + 3 * 4 if level is not None else 18
  w = pad + icon_w + 14 + D.text_w(label, CAP, semi=True) + pad
  c = rl.Rectangle(right - w, y, w, h)
  rl.draw_rectangle_rounded(c, roundness(c, 12), 8, Console.BG_HIGH)
  fill = color if color is not None else Console.SUCCESS
  if level is not None:
    signal_bars(c.x + pad, c.y + h / 2 + 14, 28, level, fill)
  else:
    D.dot(c.x + pad + 9, c.y + h / 2, 9, fill)
  D.text(label, c.x + pad + icon_w + 14, c.y + (h - CAP) / 2 - 1, CAP, Console.TEXT_SECONDARY, semi=True)
  return c
