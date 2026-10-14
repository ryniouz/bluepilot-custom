"""
Console quick-controls sheet for the driving view.

The expanded form of the bottom dock: a tap on the camera slides up a sheet with three big
cards (experimental mode, following distance, screen layout) and two actions in its header
(mark this moment, diagnostics). It closes on a tap outside it, on its close button, or after
a few seconds without a touch, so the road stays clear.
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
from bluepilot.ui.lib.theme import Console, roundness

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
SLIDE_S = 0.18           # open animation


class QuickControls:
  def __init__(self):
    self._params = Params()
    self.visible = False
    self._opened_t = 0.0
    self._touched_t = 0.0
    self._sheet: rl.Rectangle | None = None
    self._hits: list[tuple[rl.Rectangle, Callable[[], None]]] = []
    self.on_bookmark: Callable[[], None] | None = None
    self.on_diagnostics: Callable[[], None] | None = None

  def open(self):
    self.visible = True
    self._opened_t = self._touched_t = time.monotonic()

  def close(self):
    self.visible = False

  def toggle(self):
    self.close() if self.visible else self.open()

  def _get_int(self, key, default):
    try:
      return int(self._params.get(key, return_default=True))
    except Exception:
      return default

  def _pressed(self, r: rl.Rectangle) -> bool:
    return rl.is_mouse_button_down(rl.MouseButton.MOUSE_BUTTON_LEFT) and rl.check_collision_point_rec(rl.get_mouse_position(), r)

  def render(self, rect: rl.Rectangle):
    if not self.visible:
      return
    now = time.monotonic()
    if now - self._touched_t > AUTO_CLOSE_S:
      self.close()
      return
    self._hits = []

    # Slide up from the bottom edge (eased), so it reads as the dock expanding
    t = min(1.0, (now - self._opened_t) / SLIDE_S)
    ease = 1 - (1 - t) ** 3
    y_open = rect.y + rect.height - SHEET_H - SHEET_MARGIN
    sheet = rl.Rectangle(rect.x + SHEET_MARGIN, y_open + (1 - ease) * (SHEET_H + SHEET_MARGIN), rect.width - 2 * SHEET_MARGIN, SHEET_H)
    self._sheet = sheet
    rl.draw_rectangle_rounded(sheet, roundness(sheet, SHEET_RADIUS), 12, Console.BG_PANEL)
    rl.draw_rectangle_rounded_lines_ex(sheet, roundness(sheet, SHEET_RADIUS), 12, 2, Console.BORDER_DEFAULT)
    grab = rl.Rectangle(sheet.x + sheet.width / 2 - 36, sheet.y + 12, 72, 6)
    rl.draw_rectangle_rounded(grab, 1.0, 6, Console.BORDER_STRONG)

    # Header: title on the left; actions and close on the right
    hx, hy = sheet.x + SHEET_PAD, sheet.y + SHEET_PAD - 4
    D.text(tr("Quick controls"), hx, hy + (HEADER_H - D.H1) / 2 - 2, D.H1, semi=True)
    right = sheet.x + sheet.width - SHEET_PAD
    close = rl.Rectangle(right - HEADER_H, hy, HEADER_H, HEADER_H)
    rl.draw_rectangle_rounded(close, roundness(close, 16), 8, Console.BG_HIGH if self._pressed(close) else Console.BG_RAISED)
    D.icon("close", close.x + (HEADER_H - 40) / 2, close.y + (HEADER_H - 40) / 2, 40, Console.TEXT_SECONDARY)
    self._hits.append((close, self.close))
    ax = close.x - CARD_GAP / 2
    for ic, label, fn in (("pulse", tr("Diagnostics"), self.on_diagnostics), ("bookmark", tr("Mark"), self.on_bookmark)):
      ax -= ACTION_W + CARD_GAP / 2
      a = rl.Rectangle(ax, hy, ACTION_W, HEADER_H)
      rl.draw_rectangle_rounded(a, roundness(a, 16), 8, Console.BG_HIGH if self._pressed(a) else Console.BG_RAISED)
      D.icon(ic, a.x + 28, a.y + (HEADER_H - 40) / 2, 40, Console.TEXT_PRIMARY)
      D.text(D.fit(label, D.BODY, ACTION_W - 108, semi=True), a.x + 84, a.y + (HEADER_H - D.BODY) / 2 - 2, D.BODY, semi=True)
      self._hits.append((a, (lambda f=fn: (f and f(), self.close()))))

    # Cards
    top = hy + HEADER_H + CARD_GAP
    body = rl.Rectangle(sheet.x + SHEET_PAD, top, sheet.width - 2 * SHEET_PAD, sheet.y + sheet.height - SHEET_PAD - top)
    weights = [1.0, 1.0, 1.0]
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
      state, color = tr("Turn on in Drive settings"), Console.TEXT_GHOST
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
