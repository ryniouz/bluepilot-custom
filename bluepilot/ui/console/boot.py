"""
Console start-up screens that run before the UI: the loading spinner (system/ui/spinner.py) and the
error window (system/ui/text.py). Both are separate processes; the stock files swap these in under
'# Custom:' fences and keep their own stdin / argv handling.

  ConsoleSpinner     the Citadel Auto OS logo on black (the same as the boot image AGNOS shows before it,
                     selfdrive/assets/img_bluepilot_boot.jpg), a small rotating arc under it and any status
                     line; a number on stdin shows a thin squared progress bar instead. No product name here:
                     it is on System > About.
  ConsoleTextWindow  "Something went wrong", what to do next, the log in a scrolling card, and
                     Reboot (Exit on a PC).
"""

from __future__ import annotations

import os

import pyray as rl

from openpilot.system.hardware import HARDWARE, PC
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.scroll_panel import GuiScrollPanel
from openpilot.system.ui.text import wrap_text
from openpilot.system.ui.widgets import Widget
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.lib.theme import Console, set_accent

LOGO = os.path.join(os.path.dirname(__file__), "assets", "citadel_logo.png")
LOGO_H = 440          # same size as on the boot image, so the hand-off from AGNOS doesn't jump
RING_R = 26
RING_W = 6
ARC_DEG = 100.0
DEG_PER_S = 300.0
BAR_W = 520
LOG_SIZE = 30
LOG_LINE = 40


def apply_saved_theme():
  """The accent the driver picked; start-up screens stay on the night palette."""
  try:
    from openpilot.common.params import Params
    v = Params().get("BPConsoleAccent")
    set_accent(v.decode() if isinstance(v, bytes) else str(v or "blue"))
  except Exception:
    pass


_logos: dict[int, rl.Texture | None] = {}


def logo_texture(height: int = LOGO_H) -> rl.Texture | None:
  """The Citadel Auto OS logo (light blue on transparent) at this height; None if it can't be loaded."""
  if height not in _logos:
    tex = None
    if os.path.isfile(LOGO):
      try:
        img = rl.load_image(LOGO)
        rl.image_resize(img, round(img.width * height / img.height), height)
        tex = rl.load_texture_from_image(img)
        rl.set_texture_filter(tex, rl.TextureFilter.TEXTURE_FILTER_BILINEAR)
        rl.unload_image(img)
      except Exception:
        tex = None
    _logos[height] = tex
  return _logos[height]


class ConsoleSpinner(Widget):
  def __init__(self):
    super().__init__()
    self._angle = 0.0
    self._progress: int | None = None
    self._lines: list[str] = []

  def set_text(self, text: str) -> None:
    text = text.strip()
    if text.isdigit():
      self._progress = max(0, min(100, int(text)))
      self._lines = []
    else:
      self._progress = None
      self._lines = D.wrap(text, D.BODY, gui_app.width - 400, 3)

  def _render(self, rect: rl.Rectangle):
    rl.draw_rectangle_rec(rect, rl.BLACK)  # black like the AGNOS boot image before it
    cx, cy = rect.x + rect.width / 2, rect.y + rect.height / 2
    tex = logo_texture()
    if tex is not None:
      rl.draw_texture(tex, int(cx - tex.width / 2), int(cy - tex.height / 2), rl.WHITE)
    else:
      D.icon("bolt", cx - 60, cy - 60, 120, Console.TEXT_SECONDARY)

    y = cy + LOGO_H / 2 + 72
    if self._progress is not None:
      bar = rl.Rectangle(cx - BAR_W / 2, y, BAR_W, 16)
      K.bar(bar, self._progress / 100.0, Console.ACCENT)
      D.text_center(f"{self._progress} %", cx, y + 36, D.LABEL, Console.TEXT_MUTED, semi=True)
    else:
      self._angle = (self._angle + DEG_PER_S * rl.get_frame_time()) % 360.0
      c = rl.Vector2(cx, y + RING_R)
      rl.draw_ring(c, RING_R - RING_W / 2, RING_R + RING_W / 2, 0, 360, 48, Console.BG_TRACK)
      rl.draw_ring(c, RING_R - RING_W / 2, RING_R + RING_W / 2, self._angle, self._angle + ARC_DEG, 24, Console.ACCENT)
      for i, ln in enumerate(self._lines):
        D.text_center(ln, cx, y + 2 * RING_R + 40 + i * 44, D.LABEL, Console.TEXT_MUTED)


class ConsoleTextWindow(Widget):
  def __init__(self, text: str):
    super().__init__()
    self._text = text
    self._lines: list[str] = []
    self._wrap_w = 0.0
    self._scroll = GuiScrollPanel()
    self._button_rect = rl.Rectangle(0, 0, 0, 0)
    self._at_end = True

  def _render(self, rect: rl.Rectangle):
    rl.draw_rectangle_rec(rect, Console.BG_PAGE)
    pad = 64
    x, y = rect.x + pad, rect.y + 56
    D.icon("warning", x, y + 2, 64, Console.WARNING)
    D.text("Something went wrong", x + 92, y, D.H1, semi=True)
    D.text("The details are below. A reboot usually fixes it. If it keeps happening, take a photo of this screen.",
           x + 92, y + 72, D.LABEL, Console.TEXT_MUTED)

    btn_w = 280
    log = rl.Rectangle(x, y + 150, rect.width - 2 * pad - btn_w - 32, rect.height - (y + 150) - 48)
    D.card(log)
    inner = rl.Rectangle(log.x + D.CARD_PAD, log.y + D.CARD_PAD - 8, log.width - 2 * D.CARD_PAD, log.height - 2 * D.CARD_PAD + 16)
    if self._wrap_w != inner.width:
      self._wrap_w = inner.width
      self._lines = wrap_text(self._text, LOG_SIZE, inner.width - 8)
    content = rl.Rectangle(0, 0, inner.width, max(inner.height, len(self._lines) * LOG_LINE))
    if self._at_end:  # open at the end of the log, where the error is
      self._at_end = False
      self._scroll._offset_filter_y.x = -max(content.height - inner.height, 0)
    off = self._scroll.update(inner, content)
    rl.begin_scissor_mode(int(inner.x), int(inner.y), int(inner.width), int(inner.height))
    font = D.font()
    for i, ln in enumerate(self._lines):
      ly = inner.y + off + i * LOG_LINE
      if ly + LOG_LINE < inner.y or ly > inner.y + inner.height:
        continue
      rl.draw_text_ex(font, ln, rl.Vector2(inner.x, ly), LOG_SIZE, 0, Console.TEXT_SECONDARY)
    rl.end_scissor_mode()

    self._button_rect = rl.Rectangle(rect.x + rect.width - pad - btn_w, log.y + log.height - D.CONTROL_H, btn_w, D.CONTROL_H)
    D.button(self._button_rect, "Exit" if PC else "Reboot", primary=True)

  def _handle_mouse_release(self, pos) -> bool:
    if D.hit(self._button_rect, pos):
      gui_app.request_close()
      if not PC:
        HARDWARE.reboot()
      return True
    return False
