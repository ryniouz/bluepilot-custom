"""
Console parked standby: the splash shown when the comma is offroad and idle.

Brand line and status chips on top, a large clock with the date, the battery gauge with
range, and a Citadel stat strip of readiness facts. Any tap opens Home.
"""

from __future__ import annotations

import time

import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.console.home import KM_TO_MI, KPA_TO_PSI, temp, truck_snapshot
from bluepilot.ui.lib.ev_data import finite
from bluepilot.ui.lib.theme import Console, roundness

MARGIN = 80


class ConsoleStandby(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()

  def _render(self, rect: rl.Rectangle):
    rl.draw_rectangle_rec(rect, Console.BG_PAGE)
    left, right = rect.x + MARGIN, rect.x + rect.width - MARGIN
    s, live = truck_snapshot()

    # Brand line and status
    mark = rl.Rectangle(left, rect.y + 56, 60, 60)
    rl.draw_rectangle_rounded(mark, roundness(mark, 14), 8, Console.ACCENT_FILL)
    D.text_center("BP", mark.x + 30, mark.y + 16, 24, Console.ON_ACCENT, semi=True)
    x = mark.x + 60 + 20
    x += D.text("BLUEPILOT", x, mark.y + 15, 28, semi=True) + 20
    D.text(tr("F-150 Lightning"), x, mark.y + 15, 28, Console.TEXT_MUTED)
    chips = []
    try:
      if self._params.get_bool("UpdateAvailable"):
        chips.append((tr("Update ready"), Console.ACCENT, True))
    except Exception:
      pass
    try:
      nt = str(ui_state.sm["deviceState"].networkType)
      chips.append((tr("Offline") if nt in ("none", "") else ("Wi-Fi" if nt == "wifi" else tr("Cellular")),
                    Console.TEXT_GHOST if nt in ("none", "") else Console.SUCCESS, False))
    except Exception:
      pass
    cx = right
    for label, color, accent in chips:
      w = 18 + 28 + D.text_w(label, K.CAP, semi=True) + 18
      cx -= w
      K.chip(cx, mark.y + 6, label, color, accent=accent)
      cx -= 16

    # Clock and date
    now = time.localtime()
    D.text(time.strftime("%-I:%M", now), left - 8, rect.y + 170, 300, light=True)
    D.text(time.strftime("%A, %B %-d", now), left, rect.y + 500, 40, Console.TEXT_SECONDARY)

    # Battery gauge and range
    if s is not None and finite(s.soc):
      fill = Console.DANGER if s.soc < 10 else (Console.WARNING if s.soc < 20 else Console.SUCCESS)
      gx, gy, gr = right - 560 + 132, rect.y + 340, 132
      K.gauge(gx, gy, gr, s.soc / 100.0, fill, f"{s.soc:.0f}%", tr("Battery"))
      tx = gx + gr + 56
      if finite(s.range_km):
        rng = s.range_km if ui_state.is_metric else s.range_km * KM_TO_MI
        D.text(tr("Range"), tx, gy - 110, K.CAP, Console.TEXT_MUTED)
        D.value_unit(f"{rng:.0f}", "km" if ui_state.is_metric else "mi", tx, gy - 76, 60, K.CAP)
      D.text(tr("Plug"), tx, gy + 24, K.CAP, Console.TEXT_MUTED)
      plugged = getattr(ui_state, "charging_screen", False)
      D.text(tr("Charging") if plugged else tr("Not plugged in"), tx, gy + 58, K.KV)

    # Readiness strip
    ready = ui_state.panda_type is not None and str(ui_state.panda_type) != "unknown"
    dash = "–"
    cells = [K.Stat(tr("Truck"), tr("Ready") if ready else tr("Waiting"), "", tr("Car and camera OK") if ready else tr("Start the truck"),
                    Console.SUCCESS if ready else Console.TEXT_GHOST)]
    if s is not None and len(s.tire_kpa) == 4 and all(finite(t) and t > 0 for t in s.tire_kpa):
      psi = [t * KPA_TO_PSI for t in s.tire_kpa]
      cells.append(K.Stat(tr("Tires"), f"{min(psi):.0f}–{max(psi):.0f}", "psi", tr("One is low") if s.tire_low else tr("All four OK"),
                          Console.WARNING if s.tire_low else None))
    else:
      cells.append(K.Stat(tr("Tires"), dash))
    cells.append(K.Stat(tr("12 V"), f"{s.lv_volts:.1f}" if s is not None and finite(s.lv_volts) else dash,
                        "V" if s is not None and finite(s.lv_volts) else ""))
    if s is not None and finite(s.pack_temp_c):
      v, u = temp(s.pack_temp_c)
      cells.append(K.Stat(tr("Pack"), v, u))
    else:
      cells.append(K.Stat(tr("Pack"), dash))
    if s is not None and finite(s.outside_temp_c):
      v, u = temp(s.outside_temp_c)
      cells.append(K.Stat(tr("Outside"), v, u))
    else:
      cells.append(K.Stat(tr("Outside"), dash))
    cells.append(K.Stat(tr("Data"), tr("Live") if live else tr("Last known"), ""))
    K.stat_strip(rl.Rectangle(left, rect.y + rect.height - 132 - K.STRIP_H, right - left, K.STRIP_H), cells)

    by = rect.y + rect.height - 84
    D.text("BluePilot 6.0 · bp-6.0 · Lightning", left, by, K.CAP, Console.TEXT_MUTED)
    D.text_right(tr("Tap anywhere to open Home"), right, by, K.CAP, Console.TEXT_MUTED)
