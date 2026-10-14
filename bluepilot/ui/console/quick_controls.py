"""
Console quick-controls sheet for the driving view.

The expanded form of the bottom dock: a sheet with four big cards (experimental mode, following
distance, screen layout, road view) and two actions in its header (mark this moment,
diagnostics). The road view card opens a second page of switches for what the road view and the
lead card show.

Opening: drag the dock (or, in Minimal mode where there is no dock, the small handle bar at the
bottom) upward and the sheet follows the finger; let go past a third of the way and it settles
open, otherwise it drops back. A tap on the handle, the dock or the camera opens it too. Dragging
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
from openpilot.selfdrive.ui.bp.onroad.road_view import LEAD_STYLE_LABELS, OPTIONS as ROAD_OPTIONS, road_prefs

AUTO_CLOSE_S = 8.0

SHEET_MARGIN = 40        # from the screen edges
SHEET_H = 400
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
    self._page = "main"      # or "road"
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

  def _travel(self) -> float:
    return SHEET_H + SHEET_MARGIN

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
    self._render_handle(rect)
    self._hits = []
    if self._p <= 0.0:
      self._sheet = None
      return

    # The sheet rises from the bottom edge, following the finger while dragged
    y_open = rect.y + rect.height - SHEET_H - SHEET_MARGIN
    sheet = rl.Rectangle(rect.x + SHEET_MARGIN, y_open + (1 - self._p) * self._travel(), rect.width - 2 * SHEET_MARGIN, SHEET_H)
    self._sheet = sheet
    rl.draw_rectangle_rounded(sheet, roundness(sheet, SHEET_RADIUS), 12, Console.BG_PANEL)
    rl.draw_rectangle_rounded_lines_ex(sheet, roundness(sheet, SHEET_RADIUS), 12, 2, Console.BORDER_DEFAULT)
    grab = rl.Rectangle(sheet.x + sheet.width / 2 - 36, sheet.y + 12, 72, 6)
    rl.draw_rectangle_rounded(grab, 1.0, 6, Console.BORDER_STRONG)

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
      rl.draw_rectangle_rounded(c, roundness(c, CARD_RADIUS), 8, Console.BG_RAISED)

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
    n_on = sum(1 for bit, _ in ROAD_OPTIONS if road_prefs.on(bit))
    D.text(tr(f"{n_on} of {len(ROAD_OPTIONS)} shown"), c.x + CARD_PAD, c.y + c.height - CARD_PAD - D.LABEL - 14, D.LABEL, Console.TEXT_MUTED)
    D.icon("sliders", c.x + c.width - CARD_PAD - 52, c.y + c.height - CARD_PAD - 60, 52, Console.ACCENT_TEXT)
    if self._pressed(c):
      rl.draw_rectangle_rounded_lines_ex(c, roundness(c, CARD_RADIUS), 8, 2, Console.BORDER_STRONG)
    self._hits.append((c, lambda: setattr(self, "_page", "road")))

  def _render_road_page(self, body: rl.Rectangle):
    """What the road view shows: a grid of switches, two rows."""
    rows = 2
    cols = (len(ROAD_OPTIONS) + 1 + rows - 1) // rows  # + the marker style cell
    w = (body.width - CARD_GAP * (cols - 1)) / cols
    h = (body.height - CARD_GAP * (rows - 1)) / rows
    for i, (bit, label) in enumerate(ROAD_OPTIONS):
      c = rl.Rectangle(body.x + (i % cols) * (w + CARD_GAP), body.y + (i // cols) * (h + CARD_GAP), w, h)
      rl.draw_rectangle_rounded(c, roundness(c, CARD_RADIUS), 8, Console.BG_RAISED)
      on = road_prefs.on(bit)
      D.text(D.fit(tr(label), D.BODY, w - 2 * CARD_PAD - 120, semi=True), c.x + CARD_PAD, c.y + (h - D.BODY) / 2 - 2, D.BODY,
             Console.TEXT_PRIMARY if on else Console.TEXT_MUTED, semi=True)
      D.toggle(c.x + w - CARD_PAD - 104, c.y + (h - 60) / 2, on)
      self._hits.append((c, lambda b=bit: road_prefs.toggle(b)))

    # Lead marker style: tap to step through floor, bracket, corners, chevron
    i = len(ROAD_OPTIONS)
    c = rl.Rectangle(body.x + (i % cols) * (w + CARD_GAP), body.y + (i // cols) * (h + CARD_GAP), w, h)
    rl.draw_rectangle_rounded(c, roundness(c, CARD_RADIUS), 8, Console.BG_HIGH if self._pressed(c) else Console.BG_RAISED)
    D.text(tr("Marker"), c.x + CARD_PAD, c.y + (h - D.BODY) / 2 - 2, D.BODY, semi=True)
    D.icon("chevron", c.x + w - CARD_PAD - 32, c.y + (h - 32) / 2, 32, Console.TEXT_MUTED)
    D.text_right(tr(LEAD_STYLE_LABELS[road_prefs.marker]), c.x + w - CARD_PAD - 44, c.y + (h - D.BODY) / 2 - 2, D.BODY,
                 Console.ACCENT_TEXT, semi=True)
    self._hits.append((c, road_prefs.next_marker))

  def _set_preset(self, v: int):
    try:
      self._params.put("BPLayoutPreset", int(v))
    except Exception:
      pass
    ui_state.layout_preset = int(v)

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
