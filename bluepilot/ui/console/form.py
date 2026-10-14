"""
Console settings forms: the one component set every Citadel Auto OS settings page is built from, in place of
openpilot / sunnypilot / BluePilot list items (ListItem, toggle_item, multiple_button_item, Scroller ...).

A page subclasses FormPage and returns its sections; FormPage lays them out as cards (two columns from
1200 px of page width, one below that, e.g. at UI size Large), scrolls them, does hit testing, and reads params through a small cache.

  class SteeringPage(FormPage):
    def sections(self):
      p = self.p
      return [
        Section("Lane changes", "steer", [
          Toggle("Automatic lane change", "Starts when you signal", p.bool("AutoLaneChange"),
                 p.flip("AutoLaneChange")),
          Choice("Delay", ["None", "0.5 s", "1 s", "2 s"], p.int("LaneChangeDelay"), p.setter("LaneChangeDelay")),
        ], note="Hold the signal to change lanes."),
      ]

Rows (all heights fixed, so layout never jumps):

  Toggle    title, one-line sub, switch on the right                         ROW_SET  104
  Choice    title above a segmented control (<= 4 short options)             ROW_SEG  130
            or a radio list (more options, or labels too long to fit)        76 + 80 per option
  Stepper   title, sub, - value +                                            ROW_SET  104
  Nav       title, sub, value and a chevron; opens a sub-page or panel       ROW_SET  104
            (back=True: an accent "Back" row with the chevron pointing left)
  Action    title, sub, a button (primary, plain or danger)                  ROW_SET  104
  Info      label left, value right, optional status dot                     ROW_INFO  64
  Meter     label, value, and a thick squared bar (K.bar)                     ROW_METER 112
  Stack     one thick bar split into parts, legend below (where a total went)  64 + 56 per legend line
  Note      muted wrapped text (up to 4 lines)                               40 per line + 16
  Custom    any height; draw(rect) returns its own hit rects

Section(title, icon, rows, note="", wide=False): one card. `wide` spans both columns.
FormPage.confirm(title, body, label, fn, danger=False): a Console confirm sheet over the page.
Typography and spacing come from draw.py (H1 52, H2 38, BODY 34, LABEL 28, CAPTION 24; CARD_PAD 32, GAP 32).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import pyray as rl

from openpilot.common.params import Params
from openpilot.system.ui.lib.application import MouseEvent
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.lib.theme import Console, roundness

GAP = 32
TITLE_H = 76
ROW_SET = 104
ROW_SEG = 130
ROW_INFO = 64
ROW_METER = 112
ROW_RADIO = 80
STACK_BAR = 40
STACK_LEGEND = 56
NOTE_LINE = 40
TWO_COLS_W = 1200
DRAG_PX = 16
PARAM_TTL_S = 1.0


# -- params ---------------------------------------------------------------------------------------

class ParamCache:
  """Params read at most once a second per key (pages draw at 60 fps), written through at once."""

  def __init__(self, params: Params | None = None):
    self._params = params or Params()
    self._vals: dict[str, tuple[float, object]] = {}

  def has(self, key: str) -> bool:
    try:
      self._params.get(key, return_default=True)
      return True
    except Exception:
      return False

  def get(self, key: str, default=None):
    now = time.monotonic()
    hit = self._vals.get(key)
    if hit is not None and now - hit[0] < PARAM_TTL_S:
      return hit[1]
    try:
      v = self._params.get(key, return_default=True)
    except Exception:
      v = None
    if isinstance(v, bytes):
      v = v.decode(errors="ignore")
    v = default if v is None else v
    self._vals[key] = (now, v)
    return v

  def put(self, key: str, value) -> None:
    """7.0's Params writes in the background unless block=True; the cache keeps the written value either way,
    so a row shows what was tapped instead of the old value read back before the write lands."""
    fn = self._params.put_bool if isinstance(value, bool) else self._params.put
    try:
      fn(key, value, block=True)
    except TypeError:
      try:
        fn(key, value)
      except Exception:
        pass
    except Exception:
      pass
    self._vals[key] = (time.monotonic(), value)

  def invalidate(self) -> None:
    self._vals.clear()

  # shorthands that return the callables rows take
  def bool(self, key: str, default: bool = False) -> bool:
    v = self.get(key, default)
    return v if isinstance(v, bool) else str(v).strip().lower() in ("1", "true")

  def int(self, key: str, default: int = 0) -> int:
    try:
      return int(float(self.get(key, default)))
    except (TypeError, ValueError):
      return default

  def float(self, key: str, default: float = 0.0) -> float:
    try:
      return float(self.get(key, default))
    except (TypeError, ValueError):
      return default

  def flip(self, key: str, default: bool = False) -> Callable[[], None]:
    return lambda: self.put(key, not self.bool(key, default))

  def setter(self, key: str, values: Sequence | None = None) -> Callable[[int], None]:
    """For Choice: stores the index, or values[index] when given."""
    return lambda i: self.put(key, values[i] if values is not None else int(i))


# -- rows -----------------------------------------------------------------------------------------

@dataclass
class Toggle:
  title: str
  sub: str
  on: bool
  fn: Callable[[], None] | None
  enabled: bool = True

  def height(self, w: float) -> float:
    return ROW_SET


@dataclass
class Choice:
  title: str
  options: Sequence[str]
  selected: int
  fn: Callable[[int], None]
  enabled: bool = True
  sub: str = ""                 # radio list only: under the title
  subs: Sequence[str] = ()      # radio list only: one line under each option
  radio: bool | None = None     # force the radio list (True) or segmented (False)
  unifont: bool = False         # option labels in scripts the UI font lacks (language names)

  def is_radio(self, w: float) -> bool:
    if self.radio is not None:
      return self.radio
    if len(self.options) > 4 or self.subs:
      return True
    seg_w = (w - 12) / max(1, len(self.options))
    return any(D.text_w(o, D.LABEL, semi=True) > seg_w - 24 for o in self.options)

  def height(self, w: float) -> float:
    if self.is_radio(w):
      return 72 + (40 if self.sub else 0) + len(self.options) * (ROW_RADIO + (36 if self.subs else 0)) + 8
    return ROW_SEG


@dataclass
class Stepper:
  title: str
  value: str
  minus: Callable[[], None]
  plus: Callable[[], None]
  sub: str = ""
  enabled: bool = True

  def height(self, w: float) -> float:
    return ROW_SET


@dataclass
class Nav:
  title: str
  sub: str
  fn: Callable[[], None]
  value: str = ""
  back: bool = False            # a "Back" row: chevron on the left, pointing back

  def height(self, w: float) -> float:
    return ROW_SET


@dataclass
class Action:
  title: str
  sub: str
  label: str
  fn: Callable[[], None]
  primary: bool = False
  danger: bool = False
  enabled: bool = True

  def height(self, w: float) -> float:
    return ROW_SET


@dataclass
class Info:
  label: str
  value: str
  dot: rl.Color | None = None

  def height(self, w: float) -> float:
    return ROW_INFO


@dataclass
class Meter:
  label: str
  value: str
  frac: float
  color: rl.Color | None = None
  target: float | None = None

  def height(self, w: float) -> float:
    return ROW_METER


@dataclass
class StackPart:
  label: str
  value: str          # shown in the legend, already formatted (e.g. "412 MB")
  amount: float       # bar length, in the same unit as Stack.scale
  color: rl.Color


@dataclass
class Stack:
  """One thick squared bar split into parts with a legend underneath: where a total went (data, storage, energy).
  `scale` is what the full bar stands for (0: the sum of the parts); `marker` draws a limit line at that amount.
  Parts with no amount keep their legend entry (shown as zero) unless `hide_empty`."""
  parts: Sequence[StackPart]
  scale: float = 0.0
  marker: float | None = None
  cols: int = 0             # legend columns; 0 picks 3 on a wide card, 2 otherwise
  hide_empty: bool = False

  def _legend(self) -> list[StackPart]:
    return [p for p in self.parts if p.amount > 0 or not self.hide_empty]

  def ncols(self, w: float) -> int:
    return self.cols if self.cols > 0 else (3 if w >= 1300 else 2)

  def height(self, w: float) -> float:
    n, c = len(self._legend()), self.ncols(w)
    return 24 + STACK_BAR + 16 + STACK_LEGEND * ((n + c - 1) // c) + 8


@dataclass
class Note:
  text: str
  color: rl.Color | None = None
  lines: int = 4

  def height(self, w: float) -> float:
    return 16 + NOTE_LINE * len(D.wrap(self.text, D.LABEL, w, self.lines))


@dataclass
class Custom:
  h: float
  draw: Callable[[rl.Rectangle], list[tuple[rl.Rectangle, Callable[[], None]]] | None]

  def height(self, w: float) -> float:
    return self.h


Row = Toggle | Choice | Stepper | Nav | Action | Info | Meter | Stack | Note | Custom


@dataclass
class Section:
  title: str
  icon: str
  rows: list = field(default_factory=list)
  note: str = ""
  wide: bool = False

  def height(self, w: float) -> float:
    inner = w - 2 * D.CARD_PAD
    h = D.CARD_PAD + TITLE_H + sum(r.height(inner) for r in self.rows if r is not None)
    if self.note:
      h += Note(self.note).height(inner)
    return h + D.CARD_PAD - 8


# -- page -----------------------------------------------------------------------------------------

@dataclass
class _Confirm:
  title: str
  body: str
  label: str
  fn: Callable[[], None]
  danger: bool


class FormPage(Widget):
  """Override sections(). Optionally override header(rect) -> height used above the cards (not scrolled)."""

  def __init__(self, params: Params | None = None):
    super().__init__()
    self.p = ParamCache(params)
    self._hits: list[tuple[rl.Rectangle, Callable[[], None]]] = []
    self._offset = 0.0
    self._content_h = 0.0
    self._view = rl.Rectangle(0, 0, 0, 0)
    self._press: tuple[float, float] | None = None
    self._press_offset = 0.0
    self._dragging = False
    self._confirm: _Confirm | None = None

  # -- to override --
  def sections(self) -> list[Section]:
    return []

  def header(self, rect: rl.Rectangle) -> float:
    return 0.0

  # -- helpers --
  def confirm(self, title: str, body: str, label: str, fn: Callable[[], None], danger: bool = False) -> None:
    self._confirm = _Confirm(title, body, label, fn, danger)

  def show_event(self):
    super().show_event()
    self.p.invalidate()
    self._offset = 0.0
    self._confirm = None

  # -- layout --
  def _columns(self, rect: rl.Rectangle, sections: list[Section]) -> list[tuple[Section, rl.Rectangle]]:
    two = rect.width >= TWO_COLS_W
    cw = (rect.width - GAP) / 2 if two else rect.width
    ys = [rect.y, rect.y]
    placed = []
    for s in sections:
      if not s.rows and not s.note:
        continue
      if two and s.wide:
        y = max(ys)
        h = s.height(rect.width)
        placed.append((s, rl.Rectangle(rect.x, y, rect.width, h)))
        ys = [y + h + GAP, y + h + GAP]
        continue
      c = 0 if not two or ys[0] <= ys[1] else 1
      h = s.height(cw)
      placed.append((s, rl.Rectangle(rect.x + c * (cw + GAP), ys[c], cw, h)))
      ys[c] += h + GAP
    self._content_h = max(ys) - rect.y - GAP if placed else 0
    return placed

  def _render(self, rect: rl.Rectangle):
    self._hits = []
    top = self.header(rect)
    view = rl.Rectangle(rect.x, rect.y + top, rect.width, rect.height - top)
    self._view = view
    sections = [s for s in self.sections() if s is not None]
    placed = self._columns(rl.Rectangle(view.x, view.y, view.width - 16, view.height), sections)
    self._offset = max(0.0, min(self._offset, max(0.0, self._content_h - view.height)))
    rl.begin_scissor_mode(int(view.x), int(view.y), int(view.width), int(view.height))
    for s, r in placed:
      r = rl.Rectangle(r.x, r.y - self._offset, r.width, r.height)
      if r.y + r.height < view.y or r.y > view.y + view.height:
        continue
      self._draw_section(s, r)
    rl.end_scissor_mode()
    self._indicator(view)
    self._hits = [(h, fn) for h, fn in self._hits if rl.check_collision_recs(h, view)]
    if self._confirm is not None:
      self._draw_confirm(rect)

  def _indicator(self, view: rl.Rectangle):
    max_off = self._content_h - view.height
    if max_off <= 0:
      return
    th = max(60.0, view.height * view.height / self._content_h)
    ty = view.y + (view.height - th) * self._offset / max_off
    rl.draw_rectangle_rounded(rl.Rectangle(view.x + view.width - 8, ty, 6, th), 1.0, 6, Console.BG_TRACK)

  def _draw_section(self, s: Section, r: rl.Rectangle):
    D.card(r)
    p = D.CARD_PAD
    D.icon(s.icon, r.x + p, r.y + p - 2, 44, Console.TEXT_SECONDARY)
    D.text(D.fit(s.title, D.H2, r.width - 2 * p - 64, semi=True), r.x + p + 64, r.y + p, D.H2, semi=True)
    x, w = r.x + p, r.width - 2 * p
    y = r.y + p + TITLE_H
    first = True
    for row in s.rows:
      if row is None:
        continue
      h = row.height(w)
      if not isinstance(row, Note) and not first:
        K.hline(x, x + w, y)
      self._draw_row(row, rl.Rectangle(x, y, w, h))
      y += h
      first = False
    if s.note:
      self._draw_row(Note(s.note), rl.Rectangle(x, y, w, Note(s.note).height(w)))

  def _title_sub(self, x: float, y: float, w: float, title: str, sub: str, enabled: bool = True):
    col = Console.TEXT_PRIMARY if enabled else Console.TEXT_GHOST
    if sub:
      D.text(D.fit(title, D.BODY, w, semi=True), x, y + 14, D.BODY, col, semi=True)
      D.text(D.fit(sub, D.LABEL, w), x, y + 58, D.LABEL, Console.TEXT_MUTED)
    else:
      D.text(D.fit(title, D.BODY, w, semi=True), x, y + (ROW_SET - D.BODY) / 2 - 2, D.BODY, col, semi=True)

  def _draw_row(self, row, r: rl.Rectangle):
    x, y, w = r.x, r.y, r.width
    right = x + w
    if isinstance(row, Toggle):
      self._title_sub(x, y, w - 140, row.title, row.sub, row.enabled)
      D.toggle(right - 104, y + (ROW_SET - 60) / 2, row.on, enabled=row.enabled)
      if row.enabled and row.fn is not None:
        self._hits.append((r, row.fn))
    elif isinstance(row, Choice):
      self._draw_choice(row, r)
    elif isinstance(row, Stepper):
      val_w = max(120, D.text_w(row.value, D.H2, semi=True) + 32)
      plus = rl.Rectangle(right - 76, y + 18, 76, 68)
      minus = rl.Rectangle(plus.x - val_w - 76, y + 18, 76, 68)
      self._title_sub(x, y, minus.x - x - 16, row.title, row.sub, row.enabled)
      D.button(minus, "-", primary=False)
      D.text_center(row.value, minus.x + 76 + val_w / 2, y + 30, D.H2,
                    Console.TEXT_PRIMARY if row.enabled else Console.TEXT_GHOST, semi=True)
      D.button(plus, "+", primary=False)
      if row.enabled:
        self._hits += [(minus, row.minus), (plus, row.plus)]
    elif isinstance(row, Nav) and row.back:
      D.icon("back", x - 4, y + (ROW_SET - 36) / 2, 36, Console.ACCENT)
      D.text(row.title, x + 44, y + (ROW_SET - D.BODY) / 2 - 2, D.BODY, Console.ACCENT_TEXT, semi=True)
      self._hits.append((r, row.fn))
    elif isinstance(row, Nav):
      vw = D.text_w(row.value, D.LABEL, semi=True) + 24 if row.value else 0
      self._title_sub(x, y, w - vw - 64, row.title, row.sub)
      if row.value:
        D.text_right(row.value, right - 52, y + (ROW_SET - D.LABEL) / 2 - 2, D.LABEL, Console.TEXT_SECONDARY, semi=True)
      D.icon("chevron", right - 36, y + (ROW_SET - 36) / 2, 36, Console.TEXT_MUTED)
      self._hits.append((r, row.fn))
    elif isinstance(row, Action):
      bw = D.text_w(row.label, D.LABEL, semi=True) + 64
      b = rl.Rectangle(right - bw, y + (ROW_SET - 72) / 2, bw, 72)
      self._title_sub(x, y, b.x - x - 16, row.title, row.sub, row.enabled)
      if row.danger:
        rl.draw_rectangle_rounded(b, 0.25, 8, K.rgba(Console.DANGER, 40))
        rl.draw_rectangle_rounded_lines_ex(b, 0.25, 8, 2, Console.DANGER)
        D.text_center(row.label, b.x + bw / 2, b.y + (72 - D.LABEL) / 2 - 2, D.LABEL, Console.DANGER, semi=True)
      else:
        D.button(b, row.label, primary=row.primary and row.enabled, size=D.LABEL)
      if row.enabled:
        self._hits.append((b, row.fn))
    elif isinstance(row, Info):
      vx = right
      if row.dot is not None:
        D.dot(right - 9, y + ROW_INFO / 2, 9, row.dot)
        vx -= 32
      value = D.fit(row.value, D.LABEL, (vx - x) * 0.62, semi=True)
      vw = D.text_w(value, D.LABEL, semi=True)
      ty = y + (ROW_INFO - D.LABEL) / 2 - 2
      D.text(D.fit(row.label, D.LABEL, vx - x - vw - 32), x, ty, D.LABEL, Console.TEXT_MUTED)
      D.text_right(value, vx, ty, D.LABEL, semi=True)
    elif isinstance(row, Meter):
      D.text(D.fit(row.label, D.LABEL, w * 0.6), x, y + 16, D.LABEL, Console.TEXT_MUTED)
      D.text_right(row.value, right, y + 12, D.BODY, semi=True)
      K.bar(rl.Rectangle(x, y + 64, w, 28), row.frac, row.color or Console.ACCENT, target=row.target)
    elif isinstance(row, Stack):
      self._draw_stack(row, r)
    elif isinstance(row, Note):
      yy = y + 12
      for ln in D.wrap(row.text, D.LABEL, w, row.lines):
        D.text(ln, x, yy, D.LABEL, row.color or Console.TEXT_MUTED)
        yy += NOTE_LINE
    elif isinstance(row, Custom):
      hits = row.draw(r)
      if hits:
        self._hits += hits

  def _draw_stack(self, row: Stack, r: rl.Rectangle):
    x, w = r.x, r.width
    bar = rl.Rectangle(x, r.y + 24, w, STACK_BAR)
    total = sum(max(0.0, p.amount) for p in row.parts)
    scale = row.scale if row.scale > 0 else total
    rl.draw_rectangle_rounded(bar, roundness(bar, 6), 4, Console.BG_TRACK)
    if scale > 0 and total > 0:
      end = bar.x + w * min(1.0, total / scale)   # parts past the scale (over a limit) are cut at the bar's end
      sx = bar.x
      for p in row.parts:
        if p.amount <= 0 or sx >= end:
          continue
        pw = min(max(6.0, w * p.amount / scale), end - sx)
        rl.draw_rectangle_rec(rl.Rectangle(sx, bar.y, pw, STACK_BAR), p.color)
        sx += pw
        if sx < end - 1:  # a hairline of card between parts
          rl.draw_rectangle_rec(rl.Rectangle(sx - 2, bar.y, 3, STACK_BAR), Console.BG_PANEL)
    if row.marker is not None and scale > 0 and 0 < row.marker <= scale:
      mx = bar.x + w * row.marker / scale
      rl.draw_rectangle_rec(rl.Rectangle(mx - 3, bar.y - 12, 6, STACK_BAR + 24), Console.TEXT_PRIMARY)
    cols = row.ncols(w)
    cw = w / cols
    for i, p in enumerate(row._legend()):
      lx = x + (i % cols) * cw
      ly = bar.y + STACK_BAR + 16 + (i // cols) * STACK_LEGEND
      inner = cw - (48 if i % cols < cols - 1 else 0)
      D.dot(lx + 9, ly + STACK_LEGEND / 2, 9, p.color if p.amount > 0 else Console.BORDER_STRONG)
      vw = D.text_w(p.value, D.LABEL, semi=True)
      D.text(D.fit(p.label, D.LABEL, inner - 36 - vw - 16), lx + 32, ly + (STACK_LEGEND - D.LABEL) / 2 - 2, D.LABEL,
             Console.TEXT_SECONDARY)
      D.text_right(p.value, lx + inner, ly + (STACK_LEGEND - D.LABEL) / 2 - 2, D.LABEL,
                   Console.TEXT_PRIMARY if p.amount > 0 else Console.TEXT_GHOST, semi=True)

  def _draw_choice(self, row: Choice, r: rl.Rectangle):
    x, y, w = r.x, r.y, r.width
    col = Console.TEXT_PRIMARY if row.enabled else Console.TEXT_GHOST
    if not row.is_radio(w):
      D.text(D.fit(row.title, D.BODY, w, semi=True), x, y + 12, D.BODY, col, semi=True)
      rects = D.segmented(rl.Rectangle(x, y + 56, w, 62), list(row.options), row.selected if row.enabled else -1)
      if row.enabled:
        self._hits += [(sr, (lambda i=i: row.fn(i))) for i, sr in enumerate(rects)]
      return
    D.text(D.fit(row.title, D.BODY, w, semi=True), x, y + 14, D.BODY, col, semi=True)
    yy = y + 64
    if row.sub:
      D.text(D.fit(row.sub, D.LABEL, w), x, yy - 4, D.LABEL, Console.TEXT_MUTED)
      yy += 40
    oh = ROW_RADIO + (36 if row.subs else 0)
    for i, opt in enumerate(row.options):
      o = rl.Rectangle(x, yy + 4, w, oh - 8)
      sel = i == row.selected
      rl.draw_rectangle_rounded(o, 0.2 if row.subs else 0.3, 8, Console.BG_RAISED if not sel else K.rgba(Console.ACCENT, 36))
      if sel:
        rl.draw_rectangle_rounded_lines_ex(o, 0.2 if row.subs else 0.3, 8, 2, Console.ACCENT)
      cx, cy = o.x + 40, o.y + (ROW_RADIO - 8) / 2
      rl.draw_ring(rl.Vector2(cx, cy), 13, 17, 0, 360, 32, Console.ACCENT if sel else Console.TEXT_MUTED)
      if sel:
        rl.draw_circle(int(cx), int(cy), 8, Console.ACCENT)
      if row.unifont and any(ord(ch) > 0x04FF for ch in opt):  # Latin, Greek, Cyrillic: the UI font has them
        from openpilot.system.ui.lib.application import FontWeight, gui_app
        rl.draw_text_ex(gui_app.font(FontWeight.UNIFONT), opt, rl.Vector2(o.x + 80, cy - (D.BODY - 2) / 2 - 2), D.BODY - 2, 0, col)
      else:
        D.text(D.fit(opt, D.BODY - 2, o.width - 104, semi=True), o.x + 80, cy - (D.BODY - 2) / 2 - 2, D.BODY - 2,
               col, semi=True)
      if row.subs and i < len(row.subs) and row.subs[i]:
        D.text(D.fit(row.subs[i], D.LABEL - 2, o.width - 104), o.x + 80, cy + 22, D.LABEL - 2, Console.TEXT_MUTED)
      if row.enabled:
        self._hits.append((o, lambda i=i: row.fn(i)))
      yy += oh

  # -- confirm sheet --
  def _draw_confirm(self, rect: rl.Rectangle):
    c = self._confirm
    rl.draw_rectangle_rec(rect, K.rgba(Console.BG_PAGE, 200))
    w = min(1000, rect.width - 64)
    lines = D.wrap(c.body, D.BODY - 2, w - 2 * 48, 4)
    h = 48 + 64 + len(lines) * 48 + 48 + 96 + 48
    r = rl.Rectangle(rect.x + (rect.width - w) / 2, rect.y + (rect.height - h) / 2, w, h)
    D.card(r, Console.BG_RAISED)
    y = r.y + 48
    D.text(D.fit(c.title, D.H2, w - 96, semi=True), r.x + 48, y, D.H2, semi=True)
    y += 64
    for ln in lines:
      D.text(ln, r.x + 48, y, D.BODY - 2, Console.TEXT_SECONDARY)
      y += 48
    bw = (w - 96 - 24) / 2
    cancel = rl.Rectangle(r.x + 48, r.y + h - 48 - 96, bw, 96)
    ok = rl.Rectangle(cancel.x + bw + 24, cancel.y, bw, 96)
    D.button(cancel, tr("Cancel"), primary=False)
    if c.danger:
      rl.draw_rectangle_rounded(ok, 0.2, 8, Console.DANGER)
      D.text_center(c.label, ok.x + bw / 2, ok.y + (96 - (D.BODY - 2)) / 2 - 2, D.BODY - 2, Console.ON_ACCENT, semi=True)
    else:
      D.button(ok, c.label)

    def do_ok():
      self._confirm = None
      c.fn()
    self._hits = [(cancel, lambda: setattr(self, "_confirm", None)), (ok, do_ok)]

  # -- input --
  def _handle_mouse_event(self, ev: MouseEvent):
    if self._confirm is not None:
      return
    if ev.left_pressed and D.hit(self._view, ev.pos):
      self._press = (ev.pos.x, ev.pos.y)
      self._press_offset = self._offset
      self._dragging = False
    elif ev.left_down and self._press is not None:
      dy = ev.pos.y - self._press[1]
      if not self._dragging and abs(dy) > DRAG_PX:
        self._dragging = True
      if self._dragging:
        self._offset = max(0.0, min(self._press_offset - dy, max(0.0, self._content_h - self._view.height)))
    elif ev.left_released:
      self._press = None

  def _handle_mouse_release(self, pos) -> bool:
    if self._dragging:
      self._dragging = False
      return True
    for r, fn in self._hits:
      if D.hit(r, pos):
        fn()
        self.p.invalidate()
        return True
    if self._confirm is not None:
      self._confirm = None
      return True
    return False
