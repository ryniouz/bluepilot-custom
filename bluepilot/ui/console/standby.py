"""
Console parked standby: the splash shown when the comma is offroad and idle.

Big clock and date, last known charge and range, and readiness chips. Any tap opens Home.
"""

from __future__ import annotations

import time

import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from bluepilot.ui.console import draw as D
from bluepilot.ui.lib.ev_data import finite
from bluepilot.ui.lib.theme import Console, roundness

KM_TO_MI = 0.621371
KPA_TO_PSI = 0.145038
MARGIN = 144


class ConsoleStandby(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()

  def _render(self, rect: rl.Rectangle):
    rl.draw_rectangle_rec(rect, Console.BG_PAGE)
    now = time.localtime()
    clock = time.strftime("%-I:%M", now)
    D.text(clock, rect.x + MARGIN, rect.y + 110, 300, light=True)
    D.text(time.strftime("%A, %B %-d", now), rect.x + MARGIN, rect.y + 430, 44, Console.TEXT_MUTED)

    s = getattr(ui_state, "ev", None)
    if s is None or not s.available:
      src = getattr(ui_state, "ev_source", None)
      s = getattr(src, "last_good", None) if src is not None else None

    right = rect.x + rect.width - MARGIN
    col_w = 680
    if s is not None and finite(s.soc):
      vw = D.text_w(f"{s.soc:.0f}", 128, semi=True) + 10 + D.text_w("%", 48)
      D.value_unit(f"{s.soc:.0f}", "%", right - vw, rect.y + 150, 128, 48)
      fill = Console.DANGER if s.soc < 10 else (Console.WARNING if s.soc < 20 else Console.SUCCESS)
      D.bar(rl.Rectangle(right - col_w, rect.y + 320, col_w, 24), s.soc / 100.0, fill)
      if finite(s.range_km):
        rng = s.range_km if ui_state.is_metric else s.range_km * KM_TO_MI
        D.text(f"{rng:.0f} {'km' if ui_state.is_metric else 'mi'} " + tr("range"), right - col_w, rect.y + 372, 32, Console.TEXT_SECONDARY)
      plug = tr("Charging") if getattr(ui_state, "charging_screen", False) else tr("Not plugged in")
      D.text_right(plug, right, rect.y + 372, 32, Console.TEXT_SECONDARY)

    # Readiness chips
    x, y = rect.x + MARGIN, rect.y + 640
    ready = ui_state.panda_type is not None and str(ui_state.panda_type) != "unknown"
    chips = [(tr("Ready to drive") if ready else tr("Waiting for the truck"), Console.SUCCESS if ready else Console.TEXT_GHOST)]
    if s is not None and len(s.tire_kpa) == 4 and all(finite(t) and t > 0 for t in s.tire_kpa):
      psi = [t * KPA_TO_PSI for t in s.tire_kpa]
      chips.append((tr("Tires") + f" {min(psi):.0f}-{max(psi):.0f} psi", Console.WARNING if s.tire_low else Console.SUCCESS))
    if s is not None and finite(s.lv_volts):
      chips.append((f"12 V {s.lv_volts:.1f}", Console.WARNING if s.lv_low else Console.SUCCESS))
    try:
      if self._params.get_bool("UpdateAvailable"):
        chips.append((tr("Update ready"), Console.ACCENT))
    except Exception:
      pass
    for label, color in chips:
      r = D.chip(x, y, label, color, h=80, size=32)
      x += r.width + 24

    # Brand line
    by = rect.y + rect.height - 160
    rl.draw_rectangle_rec(rl.Rectangle(rect.x + MARGIN, by, rect.width - 2 * MARGIN, 2), Console.BORDER_SUBTLE)
    b = rl.Rectangle(rect.x + MARGIN, by + 40, 64, 64)
    rl.draw_rectangle_rounded(b, roundness(b, 12), 8, Console.ACCENT_FILL)
    D.text_center("BP", b.x + 32, b.y + 17, 26, Console.ON_ACCENT, semi=True)
    D.text("BluePilot", b.x + 88, b.y + 12, 36, semi=True)
    D.text("6.0 · Lightning", b.x + 88 + D.text_w("BluePilot", 36, semi=True) + 20, b.y + 14, 32, Console.TEXT_GHOST)
    D.text_right(tr("Tap anywhere to open Home"), rect.x + rect.width - MARGIN, b.y + 14, 32, Console.TEXT_MUTED)
