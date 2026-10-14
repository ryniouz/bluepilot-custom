"""
Console Theme and layout page (Screen > Theme and layout).

Pictures instead of button rows: each choice is a tile that shows what you get.

  Appearance      theme (Auto / Day / Night as small previews of the page), accent (colour swatches),
                  UI size (the same "Aa" at the three sizes)
  Driving screen  layout (Minimal / Standard / Dense as sketches of the driving view), EV panel

Same params as before (BPConsoleMode, BPConsoleAccent, BPConsoleScale, BPLayoutPreset, BPEvHud), applied the
same way, so nothing else changes.
"""

from __future__ import annotations

from collections.abc import Callable

import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.console.pages.cards import GAP, CardPage, as_int
from bluepilot.ui.lib.layout_presets import PRESET_DESCRIPTIONS, PRESET_LABELS
from bluepilot.ui.lib.theme import (ACCENT_LABELS, ACCENT_NAMES, ACCENTS, MODE_LABELS, MODE_NAMES, PALETTES, Console,
                                    current_accent, hex_color, is_day, roundness, set_accent)
from bluepilot.ui.lib.ui_scale import LABELS as SCALE_LABELS, set_scale_index

LABEL_H = 56        # tile caption strip
TILE_R = 20


def _param(params: Params, key: str, default):
  try:
    v = params.get(key, return_default=True)
  except Exception:
    return default
  if isinstance(v, bytes):
    v = v.decode(errors="ignore")
  return default if v is None else v


def _pal(mode: str, key: str) -> rl.Color:
  return hex_color(PALETTES[mode][key])


def _accent(name: str, mode: str | None = None) -> rl.Color:
  mode = mode or ("light" if is_day() else "dark")
  return hex_color(ACCENTS[name][mode]["ACCENT"])


# -- tiles ------------------------------------------------------------------------------------

def choice_tile(r: rl.Rectangle, label: str, selected: bool, preview: Callable[[rl.Rectangle], None]) -> rl.Rectangle:
  """A selectable tile: a preview above, its name below, an accent outline and check when chosen."""
  rl.draw_rectangle_rounded(r, roundness(r, TILE_R), 10, Console.BG_RAISED)
  pr = rl.Rectangle(r.x + 14, r.y + 14, r.width - 28, r.height - 28 - LABEL_H)
  preview(pr)
  ly = r.y + r.height - LABEL_H
  if selected:
    D.icon("check", r.x + r.width / 2 - D.text_w(label, D.LABEL, semi=True) / 2 - 22, ly + 12, 28, Console.ACCENT)
    D.text_center(label, r.x + r.width / 2 + 18, ly + 10, D.LABEL, Console.TEXT_PRIMARY, semi=True)
    rl.draw_rectangle_rounded_lines_ex(r, roundness(r, TILE_R), 10, 4, Console.ACCENT)
  else:
    D.text_center(label, r.x + r.width / 2, ly + 10, D.LABEL, Console.TEXT_SECONDARY)
    rl.draw_rectangle_rounded_lines_ex(r, roundness(r, TILE_R), 10, K.HAIR, Console.BORDER_DEFAULT)
  return r


def _mini_page(r: rl.Rectangle, mode: str, accent: rl.Color):
  """A thumbnail of a Console page in one palette: rail, title, a panel with two rows and a toggle."""
  rl.draw_rectangle_rounded(r, roundness(r, 12), 8, _pal(mode, "BG_PAGE"))
  rail = rl.Rectangle(r.x + 8, r.y + 8, r.width * 0.14, r.height - 16)
  rl.draw_rectangle_rounded(rail, roundness(rail, 8), 6, _pal(mode, "BG_PANEL"))
  for i in range(3):
    d = rl.Rectangle(rail.x + rail.width * 0.25, rail.y + 12 + i * 26, rail.width * 0.5, 12)
    rl.draw_rectangle_rounded(d, 1.0, 6, accent if i == 0 else _pal(mode, "BORDER_STRONG"))
  x0 = rail.x + rail.width + 12
  w = r.x + r.width - 10 - x0
  t = rl.Rectangle(x0, r.y + 14, w * 0.45, 12)
  rl.draw_rectangle_rounded(t, 1.0, 6, _pal(mode, "TEXT_PRIMARY"))
  card = rl.Rectangle(x0, r.y + 38, w, r.height - 48)
  rl.draw_rectangle_rounded(card, roundness(card, 10), 8, _pal(mode, "BG_PANEL"))
  if mode == "light":
    rl.draw_rectangle_rounded_lines_ex(card, roundness(card, 10), 8, 1, _pal(mode, "BORDER_DEFAULT"))
  for i in range(2):
    ry = card.y + 14 + i * (card.height - 20) / 2
    line = rl.Rectangle(card.x + 12, ry + 4, card.width * 0.42, 9)
    rl.draw_rectangle_rounded(line, 1.0, 6, _pal(mode, "TEXT_MUTED"))
    tg = rl.Rectangle(card.x + card.width - 12 - 36, ry, 36, 18)
    rl.draw_rectangle_rounded(tg, 1.0, 8, accent if i == 0 else _pal(mode, "TOGGLE_OFF"))
    kx = tg.x + (tg.width - 9 if i == 0 else 9)
    rl.draw_circle(int(kx), int(tg.y + 9), 6, _pal(mode, "TOGGLE_KNOB"))


def _mini_auto(r: rl.Rectangle, accent_name: str):
  """Day on the left half, Night on the right, split down the middle."""
  rl.begin_scissor_mode(int(r.x), int(r.y), int(r.width / 2), int(r.height))
  _mini_page(r, "light", _accent(accent_name, "light"))
  rl.end_scissor_mode()
  rl.begin_scissor_mode(int(r.x + r.width / 2), int(r.y), int(r.width / 2) + 1, int(r.height))
  _mini_page(r, "dark", _accent(accent_name, "dark"))
  rl.end_scissor_mode()
  rl.draw_rectangle_rec(rl.Rectangle(r.x + r.width / 2 - 1, r.y, 2, r.height), Console.ACCENT)


def _mini_drive(r: rl.Rectangle, preset: int):
  """A sketch of the driving view: road, path, speed card; the dock (Standard) and the details card (Dense)."""
  dark = not is_day()
  ground = _pal("dark" if dark else "light", "BG_HIGH")
  rl.draw_rectangle_rounded(r, roundness(r, 12), 8, ground)
  cx, top, bot = r.x + r.width / 2, r.y + r.height * 0.25, r.y + r.height
  road = Console.TEXT_GHOST
  rl.draw_line_ex(rl.Vector2(cx - 18, top), rl.Vector2(r.x + r.width * 0.12, bot), 3, road)
  rl.draw_line_ex(rl.Vector2(cx + 18, top), rl.Vector2(r.x + r.width * 0.88, bot), 3, road)
  path = K.rgba(Console.ACCENT, 0x70)
  rl.draw_triangle(rl.Vector2(cx - 8, top + 8), rl.Vector2(cx - r.width * 0.16, bot), rl.Vector2(cx + r.width * 0.16, bot), path)
  rl.draw_triangle(rl.Vector2(cx - 8, top + 8), rl.Vector2(cx + r.width * 0.16, bot), rl.Vector2(cx + 8, top + 8), path)
  speed = rl.Rectangle(r.x + 10, r.y + 10, r.width * 0.2, r.height * 0.3)
  rl.draw_rectangle_rounded(speed, roundness(speed, 8), 6, Console.BG_PANEL)
  num = rl.Rectangle(speed.x + speed.width * 0.2, speed.y + speed.height * 0.3, speed.width * 0.6, speed.height * 0.4)
  rl.draw_rectangle_rounded(num, 0.4, 6, Console.TEXT_PRIMARY)
  if preset >= 1:
    dock = rl.Rectangle(r.x + r.width * 0.18, bot - 10 - r.height * 0.16, r.width * 0.64, r.height * 0.16)
    rl.draw_rectangle_rounded(dock, roundness(dock, 8), 6, Console.BG_PANEL)
    for i in range(3):
      seg = rl.Rectangle(dock.x + 10 + i * (dock.width - 20) / 3, dock.y + dock.height * 0.35, (dock.width - 20) / 3 - 10,
                         dock.height * 0.3)
      rl.draw_rectangle_rounded(seg, 1.0, 6, Console.SUCCESS if i == 0 else Console.TEXT_MUTED)
  if preset >= 2:
    det = rl.Rectangle(r.x + r.width - 10 - r.width * 0.22, r.y + 10, r.width * 0.22, r.height * 0.5)
    rl.draw_rectangle_rounded(det, roundness(det, 8), 6, Console.BG_PANEL)
    for i in range(4):
      ln = rl.Rectangle(det.x + 8, det.y + 10 + i * (det.height - 16) / 4, det.width - 16, 7)
      rl.draw_rectangle_rounded(ln, 1.0, 6, Console.TEXT_MUTED)


def _size_preview(r: rl.Rectangle, i: int):
  rl.draw_rectangle_rounded(r, roundness(r, 12), 8, Console.BG_PANEL)
  size = (40, 56, 76)[i]
  D.text_center("Aa", r.x + r.width / 2, r.y + (r.height - size) / 2 - 4, size, semi=True)


class ThemePage(CardPage):
  def __init__(self):
    super().__init__()
    self._params = Params()

  def _put(self, key: str, value):
    try:
      if isinstance(value, bool):
        self._params.put_bool(key, value)
      else:
        self._params.put(key, value)
    except Exception:
      pass

  # -- setters (same effect as the old BluePilot rows) ---------------------------------------

  def set_mode(self, i: int):
    name = MODE_NAMES[i]
    self._put("BPConsoleMode", name)
    ui_state.console_mode_pref = name

  def set_accent(self, i: int):
    name = ACCENT_NAMES[i]
    self._put("BPConsoleAccent", name)
    set_accent(name)

  def set_scale(self, i: int):
    self._put("BPConsoleScale", i)
    set_scale_index(i)

  def set_preset(self, i: int):
    self._put("BPLayoutPreset", i)
    ui_state.layout_preset = i

  def set_ev_hud(self, on: bool):
    self._put("BPEvHud", on)
    ui_state.ev_hud = on

  # -- current values --------------------------------------------------------------------------

  def mode_index(self) -> int:
    m = str(getattr(ui_state, "console_mode_pref", None) or _param(self._params, "BPConsoleMode", "auto")).lower()
    return MODE_NAMES.index(m) if m in MODE_NAMES else 0

  def scale_index(self) -> int:
    return max(0, min(2, as_int(_param(self._params, "BPConsoleScale", 1), 1)))

  def preset_index(self) -> int:
    return max(0, min(2, int(getattr(ui_state, "layout_preset", 1))))

  # -- render ----------------------------------------------------------------------------------

  def _render(self, rect: rl.Rectangle):
    self._hits = []
    left, right = K.split_cols(rect, [1.08, 1.0])
    left.width -= GAP / 2
    right.x += GAP / 2
    right.width -= GAP / 2
    self._appearance(left)
    self._driving(right)

  def _row_title(self, x: float, y: float, title: str, note: str = "", right: float = 0) -> float:
    D.text(title, x, y, D.BODY, semi=True)
    if note and right:
      D.text_right(D.fit(note, D.LABEL, right - x - D.text_w(title, D.BODY, semi=True) - 32), right, y + 4, D.LABEL,
                   Console.TEXT_MUTED)
    return y + D.BODY + 20

  def _tiles(self, x: float, y: float, w: float, h: float, n: int, gap: float = 20) -> list[rl.Rectangle]:
    tw = (w - gap * (n - 1)) / n
    return [rl.Rectangle(x + i * (tw + gap), y, tw, h) for i in range(n)]

  def _appearance(self, r: rl.Rectangle):
    y = self._title(r, tr("Appearance"), "palette")
    p = D.CARD_PAD
    x, right = r.x + p, r.x + r.width - p
    avail = r.y + r.height - p - y
    tile_h = max(150.0, min(250.0, avail * 0.36))

    # Theme
    mode = self.mode_index()
    notes = [tr("Follows light and time of day"), tr("Light, for daytime"), tr("Dark, easy at night")]
    y = self._row_title(x, y, tr("Theme"), notes[mode], right)
    acc = current_accent()
    previews = [lambda pr: _mini_auto(pr, acc),
                lambda pr: _mini_page(pr, "light", _accent(acc, "light")),
                lambda pr: _mini_page(pr, "dark", _accent(acc, "dark"))]
    for i, tr_ in enumerate(self._tiles(x, y, right - x, tile_h, 3)):
      choice_tile(tr_, tr(MODE_LABELS[i]), i == mode, previews[i])
      self._hits.append((tr_, lambda i=i: self.set_mode(i)))
    y += tile_h + 36

    # Accent: swatches
    y = self._row_title(x, y, tr("Accent"), tr("Buttons and selections"), right)
    sw_h = 124
    for i, sr in enumerate(self._tiles(x, y, right - x, sw_h, len(ACCENT_NAMES), 16)):
      on = ACCENT_NAMES[i] == acc
      rl.draw_rectangle_rounded(sr, roundness(sr, 16), 10, Console.BG_RAISED)
      rl.draw_rectangle_rounded_lines_ex(sr, roundness(sr, 16), 10, 4 if on else K.HAIR,
                                         Console.ACCENT if on else Console.BORDER_DEFAULT)
      cx, cy = sr.x + sr.width / 2, sr.y + 42
      rl.draw_circle(int(cx), int(cy), 24, _accent(ACCENT_NAMES[i]))
      if on:
        D.icon("check", cx - 14, cy - 14, 28, Console.ON_ACCENT)
      D.text_center(D.fit(tr(ACCENT_LABELS[i]), D.LABEL, sr.width - 16, semi=on), cx, sr.y + sw_h - D.LABEL - 14, D.LABEL,
                    Console.TEXT_PRIMARY if on else Console.TEXT_SECONDARY, semi=on)
      self._hits.append((sr, lambda i=i: self.set_accent(i)))
    y += sw_h + 36

    # UI size
    if y + D.BODY + 20 + 120 <= r.y + r.height - p + 4:
      scale = self.scale_index()
      y = self._row_title(x, y, tr("UI size"), tr("Outside the driving view"), right)
      size_h = max(120.0, min(170.0, r.y + r.height - p - y))
      for i, sr in enumerate(self._tiles(x, y, right - x, size_h, 3)):
        choice_tile(sr, tr(SCALE_LABELS[i]), i == scale, lambda pr, i=i: _size_preview(pr, i))
        self._hits.append((sr, lambda i=i: self.set_scale(i)))

  def _driving(self, r: rl.Rectangle):
    y = self._title(r, tr("Driving screen"), "wheel")
    p = D.CARD_PAD
    x, right = r.x + p, r.x + r.width - p
    preset = self.preset_index()
    y = self._row_title(x, y, tr("Layout"))
    tile_h = max(190.0, min(360.0, (r.y + r.height - p - y) * 0.56))
    for i, tr_ in enumerate(self._tiles(x, y, right - x, tile_h, 3)):
      choice_tile(tr_, tr(PRESET_LABELS[i]), i == preset, lambda pr, i=i: _mini_drive(pr, i))
      self._hits.append((tr_, lambda i=i: self.set_preset(i)))
    y += tile_h + 16
    y = self._note(r, y, tr(PRESET_DESCRIPTIONS[preset]), 2) + 24

    ev = bool(getattr(ui_state, "ev_hud", True))
    self._toggle_row(r, y, tr("EV panel"), tr("Charge, power and range"), ev,
                     lambda: self.set_ev_hud(not ev))
