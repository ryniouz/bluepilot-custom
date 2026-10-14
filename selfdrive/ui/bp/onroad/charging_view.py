"""
Console charging screen for the F-150 Lightning.

Replaces the driving view while the truck reports AC or DC charging and is standing still
(ChargeSession in bluepilot/ui/lib/ev_data.py decides when). A tap returns to the driving view
for the rest of the session; driving off or the charge ending returns it automatically.

  left   charge state, SOC ring with the target marked, target and time to full
  right  tiles: charging power (with session peak), energy added, elapsed time, range,
         battery temperature, 12 V
"""

from __future__ import annotations

import time

import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.widgets import Widget
from bluepilot.ui.lib.ev_data import EvSnapshot, ChargeSession, finite, PACK_TEMP_LOW_C, PACK_TEMP_HIGH_C
from bluepilot.ui.console import draw as D
from bluepilot.ui.lib.theme import Console, Radius, draw_panel, draw_status_dot

KM_TO_MI = 0.621371

MARGIN = 64
GAP = 24
TILE_PAD = 32

CHARGE_TYPE_TITLE = {1: "AC charging", 2: "DC fast charging"}

# CarStateBP.charging.state (PR #2) in words; charging states themselves need no subtitle
STATUS_TEXT = {
  "targetReached": "Charge target reached",
  "maintaining": "Holding at the target",
  "evsePaused": "Paused by the charger",
  "scheduled": "Waiting for the scheduled time",
  "evseNotDetected": "Charger not detected",
  "evseNotCompatible": "Charger not compatible",
  "fault": "Charging fault",
  "cabinPreconditioning": "Preconditioning the cabin",
  "driveConditioning": "Conditioning the battery for the drive",
  "notReady": "Not ready",
}
WARN_STATES = ("evsePaused", "evseNotDetected", "evseNotCompatible", "fault")


def _fmt_duration(minutes: float) -> str:
  minutes = max(0, int(round(minutes)))
  h, m = divmod(minutes, 60)
  return f"{h} h {m:02d} min" if h else f"{m} min"


class ChargingView(Widget):
  def __init__(self):
    super().__init__()
    self._font = gui_app.font(FontWeight.NORMAL)
    self._font_semi = gui_app.font(FontWeight.SEMI_BOLD)

  # -- text helpers ----------------------------------------------------------

  def _text(self, text, x, y, size, color, semi=False):
    rl.draw_text_ex(self._font_semi if semi else self._font, text, rl.Vector2(x, y), size, 0, color)

  def _width(self, text, size, semi=False) -> float:
    return measure_text_cached(self._font_semi if semi else self._font, text, size).x

  def _value_unit(self, x, y, value, unit, size, unit_size, color=None):
    self._text(value, x, y, size, color or Console.TEXT_PRIMARY, semi=True)
    if unit:
      vx = x + self._width(value, size, semi=True) + 10
      self._text(unit, vx, y + size - unit_size - size * 0.08, unit_size, Console.TEXT_MUTED)

  # -- render ------------------------------------------------------------------

  def _render(self, rect: rl.Rectangle):
    rl.draw_rectangle_rec(rect, Console.BG_PAGE)
    s: EvSnapshot | None = getattr(ui_state, "ev", None)
    session: ChargeSession | None = getattr(ui_state, "charge_session", None)
    if s is None or session is None:
      return

    inner = rl.Rectangle(rect.x + MARGIN, rect.y + MARGIN, rect.width - 2 * MARGIN, rect.height - 2 * MARGIN)
    left_w = inner.width * 0.46
    left = rl.Rectangle(inner.x, inner.y, left_w, inner.height)
    right = rl.Rectangle(inner.x + left_w + GAP * 2, inner.y, inner.width - left_w - GAP * 2, inner.height)

    self._draw_state(left, s, session)
    self._draw_tiles(right, s, session)

  def _draw_state(self, r: rl.Rectangle, s: EvSnapshot, session: ChargeSession):
    # Header: status dot + charge type
    title = CHARGE_TYPE_TITLE.get(s.charge_type, "Charging")
    dot_color = Console.WARNING if s.charge_inhibit_thermal else Console.SUCCESS
    if s.charge_status in WARN_STATES:
      dot_color = Console.DANGER if s.charge_status == "fault" else Console.WARNING
    elif s.charge_status in ("targetReached", "maintaining"):
      dot_color = Console.INFO
    draw_status_dot(r.x + 14, r.y + 30, 14, dot_color)
    self._text(title, r.x + 44, r.y, 60, Console.TEXT_PRIMARY, semi=True)
    sub = STATUS_TEXT.get(s.charge_status, "")
    if s.charge_inhibit_thermal:
      sub = "Limited by battery temperature"
    elif not sub and s.charge_conditioning:
      sub = "Conditioning the battery"
    if sub:
      warn = s.charge_inhibit_thermal or s.charge_status in WARN_STATES
      self._text(sub, r.x + 44, r.y + 76, 40, Console.WARNING if warn else Console.TEXT_MUTED)

    # SOC ring with the charge target marked
    ring_r = min(r.width * 0.5 - 20, (r.height - 360) * 0.5)
    cx, cy = r.x + ring_r + 10, r.y + 150 + ring_r
    frac = s.soc / 100.0 if finite(s.soc) else 0.0
    fill = Console.DANGER if finite(s.soc) and s.soc < 10 else Console.SUCCESS
    target = s.charge_target_soc / 100.0 if finite(s.charge_target_soc) and 0 < s.charge_target_soc <= 100 else None
    D.ring_gauge(cx, cy, ring_r, 40, frac, fill, marker=target)
    if finite(s.soc):
      value, unit = f"{s.soc:.0f}", "%"
      w = self._width(value, 200, semi=True) + 10 + self._width(unit, 72)
      self._value_unit(cx - w / 2, cy - 130, value, unit, 200, 72)
    else:
      D.text_center("--", cx, cy - 130, 200, Console.TEXT_GHOST, semi=True)
    D.text_center("Battery", cx, cy + 90, 40, Console.TEXT_MUTED)

    # Target and time to full, beside the ring
    tx = cx + ring_r + 56
    ty = cy - 110
    if finite(s.charge_target_soc):
      self._text("Target", tx, ty, 36, Console.TEXT_MUTED)
      self._value_unit(tx, ty + 46, f"{s.charge_target_soc:.0f}", "%", 72, 36)
      ty += 160
    if finite(s.charge_time_to_full_min) and s.charge_time_to_full_min > 0:
      self._text("Done in", tx, ty, 36, Console.TEXT_MUTED)
      self._text(_fmt_duration(s.charge_time_to_full_min), tx, ty + 46, 60, Console.TEXT_PRIMARY, semi=True)

    # Footer hint
    hint = "Tap to show the driving view" if ui_state.started else "Tap to open Home"
    self._text(hint, r.x, r.y + r.height - 40, 36, Console.TEXT_GHOST)

  def _tile(self, rect: rl.Rectangle, label: str, value: str, unit: str = "", sub: str = "",
            color=None, sub_color=None):
    draw_panel(rect, Console.BG_PANEL, Radius.LG, Console.BORDER_SUBTLE)
    x, y = rect.x + TILE_PAD, rect.y + TILE_PAD
    self._text(label, x, y, 36, Console.TEXT_MUTED)
    self._value_unit(x, y + 56, value, unit, 104, 44, color)
    if sub:
      self._text(sub, x, rect.y + rect.height - TILE_PAD - 36, 34, sub_color or Console.TEXT_MUTED)

  def _draw_tiles(self, r: rl.Rectangle, s: EvSnapshot, session: ChargeSession):
    cols, rows = 2, 3
    tw = (r.width - GAP * (cols - 1)) / cols
    th = (r.height - GAP * (rows - 1)) / rows
    cells = [rl.Rectangle(r.x + c * (tw + GAP), r.y + row * (th + GAP), tw, th) for row in range(rows) for c in range(cols)]

    # Power
    if finite(s.charge_power_kw):
      peak = ""
      if finite(session.peak_kw):
        peak = f"Peak {session.peak_kw:.0f} kW" if session.peak_kw >= 10 else f"Peak {session.peak_kw:.1f} kW"
      self._tile(cells[0], "Charging power", f"{s.charge_power_kw:.0f}" if s.charge_power_kw >= 10 else f"{s.charge_power_kw:.1f}",
                 "kW", peak, color=Console.ACCENT)
    else:
      self._tile(cells[0], "Charging power", "--", "kW", "Waiting for the truck")

    # Energy added this session
    gained = ""
    if finite(s.soc) and finite(session.start_soc) and s.soc >= session.start_soc:
      gained = f"+{s.soc - session.start_soc:.0f} % since plug-in"
    self._tile(cells[1], "Energy added", f"{session.energy_kwh:.1f}", "kWh", gained)

    # Elapsed
    elapsed_min = int(session.elapsed_s(time.monotonic()) // 60)
    if elapsed_min >= 60:
      self._tile(cells[2], "Charging for", f"{elapsed_min // 60}:{elapsed_min % 60:02d}", "h")
    else:
      self._tile(cells[2], "Charging for", f"{elapsed_min}", "min")

    # Range
    if finite(s.range_km):
      metric = ui_state.is_metric
      val = s.range_km if metric else s.range_km * KM_TO_MI
      self._tile(cells[3], "Range", f"{val:.0f}", "km" if metric else "mi", "Estimated" if s.range_estimated else "")
    else:
      self._tile(cells[3], "Range", "--")

    # Battery temperature
    if finite(s.pack_temp_c):
      abnormal = not (PACK_TEMP_LOW_C <= s.pack_temp_c <= PACK_TEMP_HIGH_C)
      metric = ui_state.is_metric
      t = s.pack_temp_c if metric else s.pack_temp_c * 9 / 5 + 32
      sub = ("Cold battery charges slower" if s.pack_temp_c < PACK_TEMP_LOW_C else "Hot battery") if abnormal else ""
      self._tile(cells[4], "Battery temperature", f"{t:.0f}", "°C" if metric else "°F", sub,
                 color=Console.WARNING if abnormal else None, sub_color=Console.WARNING)
    else:
      self._tile(cells[4], "Battery temperature", "--")

    # 12 V
    if finite(s.lv_volts):
      self._tile(cells[5], "12 V battery", f"{s.lv_volts:.1f}", "V", "Low" if s.lv_low else "",
                 color=Console.WARNING if s.lv_low else None, sub_color=Console.WARNING)
    else:
      self._tile(cells[5], "12 V battery", "--")

