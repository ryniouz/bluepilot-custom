"""
Shared pieces for Console settings pages built from cards: a titled card, toggle rows, segmented rows,
-/+ step rows and notes. Each row returns the next y, and skips itself when the card has no room left.
"""

from __future__ import annotations

from collections.abc import Callable

import pyray as rl

from openpilot.system.ui.widgets import Widget
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.lib.theme import Console

GAP = 32
SET_ROW = 104
SEG_ROW = 130


def as_int(v, default: int) -> int:
  try:
    if isinstance(v, bytes):
      v = v.decode(errors="ignore")
    return int(float(v))
  except (TypeError, ValueError):
    return default


def as_float(v, default: float) -> float:
  try:
    if isinstance(v, bytes):
      v = v.decode(errors="ignore")
    return float(v)
  except (TypeError, ValueError):
    return default


class CardPage(Widget):
  def __init__(self):
    super().__init__()
    self._hits: list[tuple[rl.Rectangle, Callable[[], None]]] = []

  def _title(self, r: rl.Rectangle, title: str, icon: str) -> float:
    D.card(r)
    p = D.CARD_PAD
    D.icon(icon, r.x + p, r.y + p - 2, 44, Console.TEXT_SECONDARY)
    D.text(D.fit(title, D.H2, r.width - 2 * p - 64, semi=True), r.x + p + 64, r.y + p, D.H2, semi=True)
    return r.y + p + 76

  def _toggle_row(self, r: rl.Rectangle, y: float, title: str, sub: str, on: bool, fn: Callable[[], None] | None,
                  enabled: bool = True) -> float:
    p = D.CARD_PAD
    x, right = r.x + p, r.x + r.width - p
    if y + SET_ROW > r.y + r.height - p + 8:
      return y
    K.hline(x, right, y)
    col = Console.TEXT_PRIMARY if enabled else Console.TEXT_GHOST
    D.text(D.fit(title, D.BODY, right - x - 140, semi=True), x, y + 16, D.BODY, col, semi=True)
    D.text(D.fit(sub, D.LABEL, right - x - 140), x, y + 62, D.LABEL, Console.TEXT_MUTED)
    D.toggle(right - 104, y + (SET_ROW - 60) / 2, on, enabled=enabled)
    if enabled and fn is not None:
      self._hits.append((rl.Rectangle(x, y, right - x, SET_ROW), fn))
    return y + SET_ROW

  def _seg_row(self, r: rl.Rectangle, y: float, title: str, labels: list[str], sel: int,
               fn: Callable[[int], None], enabled: bool = True) -> float:
    p = D.CARD_PAD
    x, right = r.x + p, r.x + r.width - p
    if y + SEG_ROW > r.y + r.height - p + 8:
      return y
    K.hline(x, right, y)
    D.text(D.fit(title, D.BODY, right - x, semi=True), x, y + 12, D.BODY,
           Console.TEXT_PRIMARY if enabled else Console.TEXT_GHOST, semi=True)
    seg = rl.Rectangle(x, y + 56, right - x, 60)
    rects = D.segmented(seg, labels, sel if enabled else -1)
    if enabled:
      for i, sr in enumerate(rects):
        self._hits.append((sr, lambda i=i: fn(i)))
    return y + SEG_ROW

  def _step_row(self, r: rl.Rectangle, y: float, title: str, value: str, on_minus: Callable[[], None],
                on_plus: Callable[[], None], sub: str = "") -> float:
    p = D.CARD_PAD
    x, right = r.x + p, r.x + r.width - p
    if y + SET_ROW > r.y + r.height - p + 8:
      return y
    K.hline(x, right, y)
    val_w = max(96, D.text_w(value, D.H2, semi=True) + 24)
    plus = rl.Rectangle(right - 72, y + 20, 72, 64)
    minus = rl.Rectangle(plus.x - val_w - 72, y + 20, 72, 64)
    room = minus.x - x - 16
    if sub:
      D.text(D.fit(title, D.BODY, room, semi=True), x, y + 16, D.BODY, semi=True)
      D.text(D.fit(sub, D.LABEL, room), x, y + 62, D.LABEL, Console.TEXT_MUTED)
    else:
      D.text(D.fit(title, D.BODY, room, semi=True), x, y + 34, D.BODY, semi=True)
    D.button(minus, "-", primary=False)
    D.text_center(value, minus.x + 72 + val_w / 2, y + 30, D.H2, semi=True)
    D.button(plus, "+", primary=False)
    self._hits.append((minus, on_minus))
    self._hits.append((plus, on_plus))
    return y + SET_ROW

  def _button_row(self, r: rl.Rectangle, y: float, title: str, sub: str, label: str, fn: Callable[[], None]) -> float:
    p = D.CARD_PAD
    x, right = r.x + p, r.x + r.width - p
    if y + SET_ROW > r.y + r.height - p + 8:
      return y
    K.hline(x, right, y)
    bw = D.text_w(label, D.LABEL, semi=True) + 64
    b = rl.Rectangle(right - bw, y + (SET_ROW - 72) / 2, bw, 72)
    D.text(D.fit(title, D.BODY, b.x - x - 16, semi=True), x, y + 16, D.BODY, semi=True)
    D.text(D.fit(sub, D.LABEL, b.x - x - 16), x, y + 62, D.LABEL, Console.TEXT_MUTED)
    D.button(b, label, primary=False, size=D.LABEL)
    self._hits.append((b, fn))
    return y + SET_ROW

  def _note(self, r: rl.Rectangle, y: float, text: str, lines: int = 3, color: rl.Color | None = None) -> float:
    p = D.CARD_PAD
    wrapped = D.wrap(text, D.LABEL, r.width - 2 * p, lines)
    if y + 12 + 40 * len(wrapped) > r.y + r.height - p + 4:  # all of it or none of it
      return y
    for ln in wrapped:
      D.text(ln, r.x + p, y + 12, D.LABEL, color or Console.TEXT_MUTED)
      y += 40
    return y

  def _handle_mouse_release(self, pos) -> bool:
    for r, fn in self._hits:
      if D.hit(r, pos):
        fn()
        return True
    return False
