"""
Console parked standby: the splash shown when the comma is offroad and idle.

Brand line and status chips on top, a large clock with the date, the charge with a thick
squared bar and range, and a strip of readiness facts. Any tap opens Home.
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
from bluepilot.ui.console.home import KM_TO_MI, KPA_TO_PSI, _plugged_in, network_status, soc_color, temp, truck_snapshot
from bluepilot.ui.lib.ev_data import finite
from bluepilot.ui.lib.theme import Console

MARGIN = 80


class ConsoleStandby(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()

  def _render(self, rect: rl.Rectangle):
    rl.draw_rectangle_rec(rect, Console.BG_PAGE)
    left, right = rect.x + MARGIN, rect.x + rect.width - MARGIN
    s, live = truck_snapshot()

    # Truck name and status
    mark = rl.Rectangle(left, rect.y + 56, 60, 60)
    D.text(tr("F-150 Lightning"), left, mark.y + 13, 32, semi=True)
    cx = right
    net = network_status()
    if net is not None:
      cx = K.signal_chip(cx, mark.y, net[0], net[1], net[2]).x - 16
    try:
      if self._params.get_bool("UpdateAvailable"):
        label = tr("Update ready")
        w = 22 + 32 + D.text_w(label, K.CAP, semi=True) + 22
        K.chip(cx - w, mark.y, label, Console.ACCENT, accent=True)
    except Exception:
      pass

    # Clock and date
    now = time.localtime()
    D.text(time.strftime("%-I:%M", now), left - 8, rect.y + 170, 300, light=True)
    D.text(time.strftime("%A, %B %-d", now), left, rect.y + 500, 40, Console.TEXT_SECONDARY)

    # Battery: big charge, range, one thick squared bar
    bx, bw = right - 820, 820
    by0 = rect.y + 196
    if s is not None and finite(s.soc):
      D.text(tr("Battery") + " · " + (tr("Live") if live else tr("Last known")), bx, by0, K.CAP, Console.TEXT_MUTED)
      D.value_unit(f"{s.soc:.0f}", "%", bx, by0 + 44, 140, 52, light=True)
      if finite(s.range_km):
        rng = s.range_km if ui_state.is_metric else s.range_km * KM_TO_MI
        unit = "km" if ui_state.is_metric else "mi"
        D.text_right(tr("Range"), right, by0, K.CAP, Console.TEXT_MUTED)
        vw = D.text_w(f"{rng:.0f}", 72, semi=True) + 10 + D.text_w(unit, 32)
        D.value_unit(f"{rng:.0f}", unit, right - vw, by0 + 92, 72, 32)
      K.bar(rl.Rectangle(bx, by0 + 220, bw, 48), s.soc / 100.0, soc_color(s.soc))
      plugged = _plugged_in()
      D.dot(bx + 10, by0 + 312 + K.KV / 2, 10, Console.SUCCESS if plugged else Console.TEXT_GHOST)
      D.text(tr("Charging") if plugged else tr("Not plugged in"), bx + 36, by0 + 310, K.KV, Console.TEXT_SECONDARY)
    else:
      D.text(tr("Battery"), bx, by0, K.CAP, Console.TEXT_MUTED)
      D.text(tr("No data yet"), bx, by0 + 52, 72, Console.TEXT_MUTED, light=True)
      K.bar(rl.Rectangle(bx, by0 + 220, bw, 48), 0.0, Console.SUCCESS)

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
    if s is not None and finite(s.lv_volts):
      cells.append(K.Stat(tr("12 V"), f"{s.lv_volts:.1f}", "V", tr("Low") if s.lv_low else tr("Healthy"),
                          Console.WARNING if s.lv_low else None))
    else:
      cells.append(K.Stat(tr("12 V"), dash))
    if s is not None and finite(s.outside_temp_c):
      v, u = temp(s.outside_temp_c)
      cells.append(K.Stat(tr("Outside"), v, u))
    else:
      cells.append(K.Stat(tr("Outside"), dash))
    K.stat_strip(rl.Rectangle(left, rect.y + rect.height - 120 - K.STRIP_H, right - left, K.STRIP_H), cells)

    by = rect.y + rect.height - 76
    D.text_right(tr("Tap anywhere to open Home"), right, by, K.CAP, Console.TEXT_MUTED)
