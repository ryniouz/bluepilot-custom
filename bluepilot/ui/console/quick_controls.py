"""
Console quick-controls sheet for the driving view.

The expanded form of the bottom dock: a sheet with four big cards (experimental mode, following
distance, screen layout, road view) and two actions in its header (mark this moment,
diagnostics). The road view card opens a second page of switches for what the road view and the
lead card show.

Opening: drag the dock (or, in Minimal mode where there is no dock, the small handle bar at the
bottom) upward and the dock itself grows into the sheet, following the finger; let go past a third of the way and it settles
open, otherwise it drops back. A tap on the handle or the dock opens it too; a tap anywhere else on the road does not. Dragging
the sheet down (from anywhere on it) closes it, as do a tap outside it, its close button, or a few seconds
without a touch, so the road stays clear.
"""

from __future__ import annotations

import time
from collections.abc import Callable

import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.console import draw as D
from bluepilot.ui.console.home import PERSONALITY_LABELS, PERSONALITY_VALUES
from bluepilot.ui.lib.layout_presets import PRESET_LABELS
from bluepilot.ui.lib.theme import Console, Onroad, roundness, with_alpha
from openpilot.selfdrive.ui.bp.onroad.road_view import (LC_STYLE_LABELS, LEAD_STYLE_LABELS, OPTIONS as ROAD_OPTIONS, PRESET_ORDER,
                                                        PRESETS, road_prefs)

AUTO_CLOSE_S = 8.0

SHEET_MARGIN = 40        # from the screen edges
SHEET_H = 400
ROAD_ROWS = 3             # Custom's switch grid
ROAD_EXTRA_H = 128        # the Road view page is one card row taller ...
PRESET_ROW_H = 96         # ... plus the preset picker on top
SHEET_RADIUS = 32
SHEET_PAD = 36
HEADER_H = 88            # title row; the action buttons are this tall
ACTION_W = 330           # header action button (icon + word)
CARD_GAP = 24
CARD_RADIUS = 24         # kit PANEL_R
CARD_PAD = 28
SPRING = 14.0            # 1/s, how fast the sheet settles toward open or closed
DRAG_SLOP = 14           # px of travel before a press counts as a drag
OPEN_AT = 0.3            # released past this fraction (from closed) settles open
CLOSE_AT = 0.7           # released below this fraction (from open) settles closed
HANDLE_W = 260           # Minimal mode's collapsed bar
HANDLE_H = 56
HANDLE_BOTTOM = 28
DOCK_RADIUS = 24         # ev_hud's dock corner, where the sheet grows from
REVEAL_AT = 0.55         # sheet contents fade in from this much open ...
REVEAL_FULL = 0.95       # ... to fully shown here


def _lerp(a: float, b: float, t: float) -> float:
  return a + (b - a) * t


def _lerp_rect(a: rl.Rectangle, b: rl.Rectangle, t: float) -> rl.Rectangle:
  return rl.Rectangle(_lerp(a.x, b.x, t), _lerp(a.y, b.y, t), _lerp(a.width, b.width, t), _lerp(a.height, b.height, t))


def _card_fill() -> rl.Color:  # read at draw time so day/night switches follow
  return with_alpha(Console.BG_RAISED, 0xE0)


def _chevron_up(cx: float, cy: float, half: float, color: rl.Color):
  w = 4.0
  pts = [(cx - half, cy + half * 0.5), (cx, cy - half * 0.5), (cx + half, cy + half * 0.5)]
  for (x0, y0), (x1, y1) in zip(pts, pts[1:], strict=False):
    rl.draw_line_ex(rl.Vector2(x0, y0), rl.Vector2(x1, y1), w, color)
  rl.draw_circle_v(rl.Vector2(cx, cy - half * 0.5), w / 2, color)


class QuickControls:
  def __init__(self):
    self._params = Params()
    self._p = 0.0            # 0 collapsed .. 1 open
    self._target = 0.0
    self._drag: list | None = None   # [start y, start progress, moved]
    self._was_down = False
    self._touched_t = 0.0
    self._sheet: rl.Rectangle | None = None
    self._origin: rl.Rectangle | None = None   # the dock (or handle) the sheet grows out of
    self._page = "main"      # or "road"
    self._last_rect: rl.Rectangle | None = None
    self._hits: list[tuple[rl.Rectangle, Callable[[], None]]] = []
    self.on_bookmark: Callable[[], None] | None = None
    self.on_diagnostics: Callable[[], None] | None = None

  @property
  def visible(self) -> bool:
    return self._p > 0.001 or self._target > 0.0 or self.in_gesture

  @property
  def in_gesture(self) -> bool:
    """True while (and on the frame) a drag is being released, so the release is not also a tap."""
    return self._drag is not None and self._drag[2]

  def open(self):
    self._target = 1.0
    self._touched_t = time.monotonic()

  def close(self):
    self._target = 0.0

  def toggle(self):
    self.close() if self.visible else self.open()

  def _get_int(self, key, default):
    try:
      return int(self._params.get(key, return_default=True))
    except Exception:
      return default

  def _pressed(self, r: rl.Rectangle) -> bool:
    return rl.is_mouse_button_down(rl.MouseButton.MOUSE_BUTTON_LEFT) and rl.check_collision_point_rec(rl.get_mouse_position(), r)

  # -- collapsed bar and drag ------------------------------------------------------------

  def _sheet_h(self) -> float:
    if self._page != "road":
      return SHEET_H
    return SHEET_H + PRESET_ROW_H + (ROAD_EXTRA_H if road_prefs.preset == 0 else -ROAD_EXTRA_H // 2)

  def _travel(self) -> float:
    return self._sheet_h() + SHEET_MARGIN

  def _handle_rect(self, rect: rl.Rectangle) -> rl.Rectangle | None:
    """Minimal mode's handle bar, or None when the dock (which is itself the handle) shows or an
    alert owns the bottom of the screen."""
    if getattr(ui_state, "qc_blocked", False) or getattr(ui_state, "qc_dock", None) is not None:
      return None
    # Something else may own the bottom centre (a theme's gauge cluster): sit above it
    inset = float(getattr(ui_state, "qc_bottom_inset", 0.0) or 0.0)
    return rl.Rectangle(rect.x + (rect.width - HANDLE_W) / 2, rect.y + rect.height - inset - HANDLE_BOTTOM - HANDLE_H, HANDLE_W, HANDLE_H)

  def _drag_zone(self, rect: rl.Rectangle) -> rl.Rectangle | None:
    if self._p > 0.5:
      return self._sheet  # a downward drag anywhere on the sheet closes it; taps still reach the cards
    dock = getattr(ui_state, "qc_dock", None)
    if dock is not None and not getattr(ui_state, "qc_blocked", False):
      return dock
    h = self._handle_rect(rect)
    return rl.Rectangle(h.x - 40, h.y - 40, h.width + 80, h.height + 40 + HANDLE_BOTTOM) if h is not None else None

  def _update_drag(self, rect: rl.Rectangle, now: float):
    down = rl.is_mouse_button_down(rl.MouseButton.MOUSE_BUTTON_LEFT)
    pos = rl.get_mouse_position()
    if self._drag is not None and self._drag[2] and not self._was_down:
      self._drag = None  # the release frame of a drag has passed
    if down and not self._was_down:
      zone = self._drag_zone(rect)
      if zone is not None and rl.check_collision_point_rec(pos, zone):
        self._drag = [pos.y, self._p, False]
    elif down and self._drag is not None:
      dy = self._drag[0] - pos.y
      if abs(dy) > DRAG_SLOP:
        self._drag[2] = True
      if self._drag[2]:
        self._p = min(1.0, max(0.0, self._drag[1] + dy / self._travel()))
        self._touched_t = now
    elif not down and self._drag is not None:
      if self._drag[2]:
        from_open = self._drag[1] > 0.5
        self._target = 1.0 if self._p > (CLOSE_AT if from_open else OPEN_AT) else 0.0
        self._touched_t = now
        self._was_down = down
        return  # keep the drag record this frame so in_gesture swallows the release tap
      self._drag = None
    self._was_down = down

  def _render_handle(self, rect: rl.Rectangle):
    h = self._handle_rect(rect)
    if h is None:
      return
    a = max(0.0, 1.0 - self._p * 2.5)
    if a <= 0.01:
      return
    pressed = self._drag is not None and self._p < 0.5
    rl.draw_rectangle_rounded(h, 1.0, 16, with_alpha(Console.BG_HIGH if pressed else Onroad.PANEL, int(0xD9 * a)))
    rl.draw_rectangle_rounded_lines_ex(h, 1.0, 16, 2, with_alpha(Console.BORDER_DEFAULT, int(255 * a)))
    label = tr("Controls")
    lw = D.text_w(label, D.LABEL, semi=True)
    x = h.x + (h.width - lw - 34) / 2
    ink = with_alpha(Console.TEXT_SECONDARY, int(255 * a))
    _chevron_up(x + 11, h.y + HANDLE_H / 2, 11, ink)
    D.text(label, x + 34, h.y + (HANDLE_H - D.LABEL) / 2 - 2, D.LABEL, ink, semi=True)

  def render(self, rect: rl.Rectangle):
    self._last_rect = rect
    now = time.monotonic()
    self._update_drag(rect, now)
    if self._drag is None or not self._drag[2]:
      if self._target > 0.0 and now - self._touched_t > AUTO_CLOSE_S:
        self._target = 0.0
      dt = min(0.05, rl.get_frame_time())
      self._p += (self._target - self._p) * min(1.0, dt * SPRING)
      if abs(self._target - self._p) < 0.002:
        self._p = self._target
    if self._p <= 0.0 and self._target <= 0.0:
      self._page = "main"
    # The dock hides while it is grown into the sheet (ev_hud reads this)
    ui_state.qc_open = self._p
    if self._p <= 0.0:
      dock = getattr(ui_state, "qc_dock", None)
      self._origin = dock if dock is not None else self._handle_rect(rect)
    self._render_handle(rect)
    self._hits = []
    if self._p <= 0.0:
      self._sheet = None
      return

    # The dock itself grows into the sheet (and shrinks back into it), following the finger while dragged. Without
    # a dock or handle to grow from, the sheet rises from the bottom edge as before.
    sheet_h = self._sheet_h()
    y_open = rect.y + rect.height - sheet_h - SHEET_MARGIN
    sheet = rl.Rectangle(rect.x + SHEET_MARGIN, y_open, rect.width - 2 * SHEET_MARGIN, sheet_h)
    e = self._p
    if self._origin is not None:
      frame = _lerp_rect(self._origin, sheet, e)
      radius = _lerp(DOCK_RADIUS, SHEET_RADIUS, e)
    else:
      frame = rl.Rectangle(sheet.x, sheet.y + (1 - e) * self._travel(), sheet.width, sheet.height)
      sheet = frame
      radius = SHEET_RADIUS
    self._sheet = frame
    # translucent like the dock it came from, so the road stays readable behind it
    rl.draw_rectangle_rounded(frame, roundness(frame, radius), 12, Onroad.PANEL)
    rl.draw_rectangle_rounded_lines_ex(frame, roundness(frame, radius), 12, 2, with_alpha(Console.BORDER_DEFAULT, 0xB0))
    grab = rl.Rectangle(frame.x + frame.width / 2 - 36, frame.y + 9 + 3 * e, 72, 6)
    rl.draw_rectangle_rounded(grab, 1.0, 6, Console.BORDER_STRONG)

    reveal = max(0.0, min(1.0, (e - REVEAL_AT) / (REVEAL_FULL - REVEAL_AT)))
    if reveal <= 0.0:
      return
    # contents keep their open layout and ride the centre of the growing panel, so they arrive in place
    cx = frame.x + frame.width / 2 - sheet.width / 2
    cy = frame.y + frame.height / 2 - sheet.height / 2
    rl.begin_scissor_mode(int(frame.x), int(frame.y), int(frame.width), int(frame.height))
    self._render_contents(rl.Rectangle(cx, cy, sheet.width, sheet.height))
    rl.end_scissor_mode()
    if reveal < 1.0:
      # contents fade in over the growing panel
      rl.draw_rectangle_rounded(frame, roundness(frame, radius), 12, with_alpha(Console.BG_PANEL, int(0xD9 * (1 - reveal))))
      self._hits = []

  def _render_contents(self, sheet: rl.Rectangle):
    # Header: title on the left; actions and close on the right
    hx, hy = sheet.x + SHEET_PAD, sheet.y + SHEET_PAD - 4
    road = self._page == "road"
    D.text(tr("Road view") if road else tr("Quick controls"), hx, hy + (HEADER_H - D.H1) / 2 - 2, D.H1, semi=True)
    right = sheet.x + sheet.width - SHEET_PAD
    close = rl.Rectangle(right - HEADER_H, hy, HEADER_H, HEADER_H)
    rl.draw_rectangle_rounded(close, roundness(close, 16), 8, Console.BG_HIGH if self._pressed(close) else Console.BG_RAISED)
    D.icon("close", close.x + (HEADER_H - 40) / 2, close.y + (HEADER_H - 40) / 2, 40, Console.TEXT_SECONDARY)
    self._hits.append((close, self.close))
    body_top = hy + HEADER_H + CARD_GAP
    body = rl.Rectangle(sheet.x + SHEET_PAD, body_top, sheet.width - 2 * SHEET_PAD, sheet.y + sheet.height - SHEET_PAD - body_top)
    if road:
      back = rl.Rectangle(close.x - CARD_GAP / 2 - ACTION_W, hy, ACTION_W, HEADER_H)
      rl.draw_rectangle_rounded(back, roundness(back, 16), 8, Console.BG_HIGH if self._pressed(back) else Console.BG_RAISED)
      D.text_center(tr("Done"), back.x + back.width / 2, back.y + (HEADER_H - D.BODY) / 2 - 2, D.BODY, semi=True)
      self._hits.append((back, lambda: setattr(self, "_page", "main")))
      self._render_road_page(body)
      return
    ax = close.x - CARD_GAP / 2
    for ic, label, fn in (("pulse", tr("Diagnostics"), self.on_diagnostics), ("bookmark", tr("Mark"), self.on_bookmark)):
      ax -= ACTION_W + CARD_GAP / 2
      a = rl.Rectangle(ax, hy, ACTION_W, HEADER_H)
      rl.draw_rectangle_rounded(a, roundness(a, 16), 8, Console.BG_HIGH if self._pressed(a) else Console.BG_RAISED)
      D.icon(ic, a.x + 28, a.y + (HEADER_H - 40) / 2, 40, Console.TEXT_PRIMARY)
      D.text(D.fit(label, D.BODY, ACTION_W - 108, semi=True), a.x + 84, a.y + (HEADER_H - D.BODY) / 2 - 2, D.BODY, semi=True)
      self._hits.append((a, (lambda f=fn: (f and f(), self.close()))))

    # Cards
    weights = [1.0, 1.0, 1.0, 1.0]
    unit = (body.width - CARD_GAP * (len(weights) - 1)) / sum(weights)
    x = body.x
    cards = []
    for wgt in weights:
      cards.append(rl.Rectangle(x, body.y, unit * wgt, body.height))
      x += unit * wgt + CARD_GAP
    for c in cards:
      rl.draw_rectangle_rounded(c, roundness(c, CARD_RADIUS), 8, _card_fill())

    # Experimental mode: title + state word, toggle on the right
    c = cards[0]
    exp = bool(self._params.get_bool("ExperimentalMode"))
    confirmed = bool(self._params.get_bool("ExperimentalModeConfirmed"))
    D.text(tr("Experimental mode"), c.x + CARD_PAD, c.y + CARD_PAD, D.BODY, semi=True)
    if not confirmed:
      state, color = tr("Enable in settings"), Console.TEXT_GHOST
    else:
      state, color = tr("End-to-end speed control"), (Console.ACCENT_TEXT if exp else Console.TEXT_MUTED)
    D.text(D.fit(state, D.LABEL, c.width - 2 * CARD_PAD - 112), c.x + CARD_PAD, c.y + c.height - CARD_PAD - D.LABEL - 14, D.LABEL, color)
    D.toggle(c.x + c.width - CARD_PAD - 104, c.y + c.height - CARD_PAD - 60, exp, enabled=confirmed)
    if confirmed:
      self._hits.append((rl.Rectangle(c.x, c.y, c.width, c.height), lambda: self._params.put_bool("ExperimentalMode", not exp)))

    # Following distance
    c = cards[1]
    D.text(tr("Following distance"), c.x + CARD_PAD, c.y + CARD_PAD, D.BODY, semi=True)
    pers = self._get_int("LongitudinalPersonality", 1)
    sel = PERSONALITY_VALUES.index(pers) if pers in PERSONALITY_VALUES else 1
    seg = rl.Rectangle(c.x + CARD_PAD - 8, c.y + c.height - CARD_PAD - D.CONTROL_H + 8, c.width - 2 * CARD_PAD + 16, D.CONTROL_H)
    for i, sr in enumerate(D.segmented(seg, [tr(s) for s in PERSONALITY_LABELS], sel, track=Console.BG_HIGH)):
      self._hits.append((sr, lambda v=PERSONALITY_VALUES[i]: self._params.put("LongitudinalPersonality", v)))

    # Screen layout
    c = cards[2]
    D.text(tr("Screen layout"), c.x + CARD_PAD, c.y + CARD_PAD, D.BODY, semi=True)
    preset = int(getattr(ui_state, "layout_preset", 1))
    seg = rl.Rectangle(c.x + CARD_PAD - 8, c.y + c.height - CARD_PAD - D.CONTROL_H + 8, c.width - 2 * CARD_PAD + 16, D.CONTROL_H)
    for i, sr in enumerate(D.segmented(seg, [tr(s) for s in PRESET_LABELS], preset, track=Console.BG_HIGH)):
      self._hits.append((sr, lambda v=i: self._set_preset(v)))

    # Road view: opens the second page
    c = cards[3]
    D.text(tr("Road view"), c.x + CARD_PAD, c.y + CARD_PAD, D.BODY, semi=True)
    D.text(tr(PRESETS[road_prefs.preset][1]), c.x + CARD_PAD, c.y + c.height - CARD_PAD - D.LABEL - 14, D.LABEL, Console.ACCENT_TEXT,
           semi=True)
    D.icon("sliders", c.x + c.width - CARD_PAD - 52, c.y + c.height - CARD_PAD - 60, 52, Console.ACCENT_TEXT)
    if self._pressed(c):
      rl.draw_rectangle_rounded_lines_ex(c, roundness(c, CARD_RADIUS), 8, 2, Console.BORDER_STRONG)
    self._hits.append((c, lambda: setattr(self, "_page", "road")))

  def _render_road_page(self, body: rl.Rectangle):
    """What the road view shows: a preset picker, then for Custom a grid of switches; the marker and lane change
    style cells always (they are the driver's own in every preset)."""
    order = list(PRESET_ORDER)
    seg = rl.Rectangle(body.x, body.y, body.width, D.CONTROL_H)
    picks = D.segmented(seg, [tr(PRESETS[i][1]) for i in order], order.index(road_prefs.preset), size=D.BODY, track=_card_fill())
    for sr, i in zip(picks, order, strict=False):
      self._hits.append((sr, lambda v=i: road_prefs.set_preset(v)))
    body = rl.Rectangle(body.x, body.y + PRESET_ROW_H, body.width, body.height - PRESET_ROW_H)
    if road_prefs.preset != 0:
      self._render_preset_summary(body)
      return
    rows = ROAD_ROWS
    cols = (len(ROAD_OPTIONS) + 2 + rows - 1) // rows  # + the marker and lane change cells
    w = (body.width - CARD_GAP * (cols - 1)) / cols
    h = (body.height - CARD_GAP * (rows - 1)) / rows
    for i, (bit, label) in enumerate(ROAD_OPTIONS):
      c = rl.Rectangle(body.x + (i % cols) * (w + CARD_GAP), body.y + (i // cols) * (h + CARD_GAP), w, h)
      rl.draw_rectangle_rounded(c, roundness(c, CARD_RADIUS), 8, _card_fill())
      on = road_prefs.on(bit)
      D.text(D.fit(tr(label), D.BODY, w - 2 * CARD_PAD - 120, semi=True), c.x + CARD_PAD, c.y + (h - D.BODY) / 2 - 2, D.BODY,
             Console.TEXT_PRIMARY if on else Console.TEXT_MUTED, semi=True)
      D.toggle(c.x + w - CARD_PAD - 104, c.y + (h - 60) / 2, on)
      self._hits.append((c, lambda b=bit: road_prefs.toggle(b)))

    steps = (("Marker", LEAD_STYLE_LABELS[road_prefs.marker], road_prefs.next_marker),
             ("Lane change", LC_STYLE_LABELS[road_prefs.lane_change], road_prefs.next_lane_change))
    for k, (label, value, step) in enumerate(steps):
      i = len(ROAD_OPTIONS) + k
      self._style_cell(rl.Rectangle(body.x + (i % cols) * (w + CARD_GAP), body.y + (i // cols) * (h + CARD_GAP), w, h),
                       label, value, step)

  def _render_preset_summary(self, body: rl.Rectangle):
    """A preset: what it shows (tap to start Custom from it), then the two style cells."""
    w = (body.width - CARD_GAP * 3) / 4
    c = rl.Rectangle(body.x, body.y, 2 * w + CARD_GAP, body.height)
    rl.draw_rectangle_rounded(c, roundness(c, CARD_RADIUS), 8, Console.BG_HIGH if self._pressed(c) else _card_fill())
    D.text(D.fit(tr(PRESETS[road_prefs.preset][2]), D.BODY, c.width - 2 * CARD_PAD), c.x + CARD_PAD, c.y + CARD_PAD, D.BODY)
    D.text(tr("Tap to adjust it in Custom"), c.x + CARD_PAD, c.y + c.height - CARD_PAD - D.LABEL - 4, D.LABEL, Console.TEXT_MUTED)
    self._hits.append((c, road_prefs.customise))
    steps = (("Marker", LEAD_STYLE_LABELS[road_prefs.marker], road_prefs.next_marker),
             ("Lane change", LC_STYLE_LABELS[road_prefs.lane_change], road_prefs.next_lane_change))
    for k, (label, value, step) in enumerate(steps):
      self._style_cell(rl.Rectangle(c.x + c.width + CARD_GAP + k * (w + CARD_GAP), body.y, w, body.height), label, value, step)

  def _style_cell(self, c: rl.Rectangle, label: str, value: str, step):
    """Tap to step through the choices."""
    rl.draw_rectangle_rounded(c, roundness(c, CARD_RADIUS), 8, Console.BG_HIGH if self._pressed(c) else _card_fill())
    ty = c.y + (c.height - D.BODY) / 2 - 2
    D.text(tr(label), c.x + CARD_PAD, ty, D.BODY, semi=True)
    D.icon("chevron", c.x + c.width - CARD_PAD - 32, c.y + (c.height - 32) / 2, 32, Console.TEXT_MUTED)
    D.text_right(tr(value), c.x + c.width - CARD_PAD - 44, ty, D.BODY, Console.ACCENT_TEXT, semi=True)
    self._hits.append((c, step))

  def _set_preset(self, v: int):
    try:
      self._params.put("BPLayoutPreset", int(v))
    except Exception:
      pass
    ui_state.layout_preset = int(v)

  def opens_from(self, pos) -> bool:
    """Only the power dock (or Minimal mode's handle bar) opens the panel (Lucas 2026-10-15): a tap anywhere else
    on the driving screen leaves it closed."""
    if getattr(ui_state, "qc_blocked", False):
      return False
    dock = getattr(ui_state, "qc_dock", None)
    if dock is not None:
      return D.hit(dock, pos)
    h = self._handle_rect(rl.Rectangle(0, 0, rl.get_screen_width(), rl.get_screen_height())) if self._last_rect is None else \
      self._handle_rect(self._last_rect)
    return h is not None and D.hit(rl.Rectangle(h.x - 40, h.y - 40, h.width + 80, h.height + 40 + HANDLE_BOTTOM), pos)

  def handle_tap(self, pos) -> bool:
    """Returns True when the tap was consumed by the sheet (including closing it)."""
    if not self.visible:
      return False
    for r, fn in self._hits:
      if D.hit(r, pos):
        fn()
        self._touched_t = time.monotonic()
        return True
    if self._sheet is not None and D.hit(self._sheet, pos):
      self._touched_t = time.monotonic()
      return True
    self.close()
    return True
