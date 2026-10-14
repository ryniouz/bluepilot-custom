"""
Console quick-controls sheet for the driving view.

Replaces the stock sidebar onroad: a tap on the camera opens a sheet along the bottom with
experimental mode, following distance, screen layout, mark-this-moment and diagnostics.
It closes on a tap outside it or after a few seconds without a touch, so the road stays clear.
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
SHEET_H = 300


class QuickControls:
  def __init__(self):
    self._params = Params()
    self.visible = False
    self._opened_t = 0.0
    self._sheet: rl.Rectangle | None = None
    self._hits: list[tuple[rl.Rectangle, Callable[[], None]]] = []
    self.on_bookmark: Callable[[], None] | None = None
    self.on_diagnostics: Callable[[], None] | None = None

  def open(self):
    self.visible = True
    self._opened_t = time.monotonic()

  def close(self):
    self.visible = False

  def toggle(self):
    self.close() if self.visible else self.open()

  def _get_int(self, key, default):
    try:
      return int(self._params.get(key, return_default=True))
    except Exception:
      return default

  def render(self, rect: rl.Rectangle):
    if not self.visible:
      return
    if time.monotonic() - self._opened_t > AUTO_CLOSE_S:
      self.close()
      return
    self._hits = []
    sheet = rl.Rectangle(rect.x + 48, rect.y + rect.height - SHEET_H - 32, rect.width - 96, SHEET_H)
    self._sheet = sheet
    rl.draw_rectangle_rounded(sheet, roundness(sheet, 28), 12, Console.BG_PANEL)
    rl.draw_rectangle_rounded_lines_ex(sheet, roundness(sheet, 28), 12, 2, Console.BORDER_DEFAULT)
    grab = rl.Rectangle(sheet.x + sheet.width / 2 - 48, sheet.y + 20, 96, 10)
    rl.draw_rectangle_rounded(grab, 1.0, 8, Console.BORDER_STRONG)

    inner = rl.Rectangle(sheet.x + 40, sheet.y + 56, sheet.width - 80, sheet.height - 92)
    weights = [0.75, 1.55, 1.55, 0.7, 0.7]
    gap = 24
    unit = (inner.width - gap * (len(weights) - 1)) / sum(weights)
    x = inner.x
    tiles = []
    for wgt in weights:
      tiles.append(rl.Rectangle(x, inner.y, unit * wgt, inner.height))
      x += unit * wgt + gap

    for t in tiles[:3]:
      rl.draw_rectangle_rounded(t, roundness(t, 16), 8, Console.BG_RAISED)

    # Experimental
    t = tiles[0]
    D.text(tr("Experimental"), t.x + 28, t.y + 26, D.LABEL + 2, semi=True)
    exp = bool(self._params.get_bool("ExperimentalMode"))
    confirmed = bool(self._params.get_bool("ExperimentalModeConfirmed"))
    tg = D.toggle(t.x + 28, t.y + t.height - 92, exp, enabled=confirmed)
    if confirmed:
      self._hits.append((tg, lambda: self._params.put_bool("ExperimentalMode", not exp)))

    # Following distance
    t = tiles[1]
    D.text(tr("Following distance"), t.x + 28, t.y + 26, D.LABEL + 2, semi=True)
    pers = self._get_int("LongitudinalPersonality", 1)
    sel = PERSONALITY_VALUES.index(pers) if pers in PERSONALITY_VALUES else 1
    seg = rl.Rectangle(t.x + 24, t.y + t.height - 104, t.width - 48, D.CONTROL_H)
    for i, sr in enumerate(D.segmented(seg, [tr(s) for s in PERSONALITY_LABELS], sel, track=Console.BG_HIGH)):
      self._hits.append((sr, lambda v=PERSONALITY_VALUES[i]: self._params.put("LongitudinalPersonality", v)))

    # Screen layout
    t = tiles[2]
    D.text(tr("Screen"), t.x + 28, t.y + 26, D.LABEL + 2, semi=True)
    preset = int(getattr(ui_state, "layout_preset", 1))
    seg = rl.Rectangle(t.x + 24, t.y + t.height - 104, t.width - 48, D.CONTROL_H)
    for i, sr in enumerate(D.segmented(seg, [tr(s) for s in PRESET_LABELS], preset, track=Console.BG_HIGH)):
      self._hits.append((sr, lambda v=i: self._set_preset(v)))

    # Actions
    for t, ic, label, fn in ((tiles[3], "bookmark", tr("Mark moment"), self.on_bookmark),
                             (tiles[4], "pulse", tr("Diagnostics"), self.on_diagnostics)):
      pressed = rl.is_mouse_button_down(rl.MouseButton.MOUSE_BUTTON_LEFT) and rl.check_collision_point_rec(rl.get_mouse_position(), t)
      rl.draw_rectangle_rounded(t, roundness(t, 16), 8, Console.BG_HIGH if pressed else Console.BG_RAISED)
      D.icon(ic, t.x + 28, t.y + 28, 48, Console.TEXT_PRIMARY)
      D.text(label, t.x + 28, t.y + t.height - 64, D.LABEL + 2, semi=True)
      self._hits.append((t, (lambda f=fn: (f and f(), self.close()))))

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
        self._opened_t = time.monotonic()
        return True
    if self._sheet is not None and D.hit(self._sheet, pos):
      self._opened_t = time.monotonic()
      return True
    self.close()
    return True
