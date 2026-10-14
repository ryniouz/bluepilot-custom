"""
Console EV HUD for the F-150 Lightning (driving screen items 6-11 in the Comma investigation).

A single Console card on the right edge, under the steering-wheel button:

  Standard  Battery (SOC bar), Power (center-zero regen/drive meter), Range and efficiency
  Dense     + pack and coolant temperature, charge/discharge limits, trip energy,
              tire pressures, 12 V battery, outside temperature with range impact

Rows hide themselves when their signal is missing, and the whole card hides when the truck
sends no battery data at all. Status colours mark state only (low charge, low tire, low 12 V).
"""

from __future__ import annotations

import pyray as rl

from openpilot.selfdrive.ui import UI_BORDER_SIZE
from openpilot.selfdrive.ui.onroad.hud_renderer import UI_CONFIG
from openpilot.selfdrive.ui.sunnypilot.onroad.developer_ui import DeveloperUiState
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from bluepilot.ui.lib.ev_data import EvDataSource, EvSnapshot, finite, temp_range_factor, PACK_TEMP_LOW_C, PACK_TEMP_HIGH_C
from bluepilot.ui.lib.layout_presets import LayoutPreset
from bluepilot.ui.lib.theme import Console, Onroad, Radius, roundness, draw_bar

KM_TO_MI = 0.621371
KPA_TO_PSI = 0.145038

CARD_W = 380
PAD = 24
ROW_GAP = 18
LABEL = 28
VALUE = 48
SMALL = 30
BAR_H = 12
DEV_UI_RIGHT_W = 184

TIRE_LOW_PSI = 30.0  # Lightning placard is 42 psi; the TPMS warning sits near 32


def _c_to_f(c: float) -> float:
  return c * 9.0 / 5.0 + 32.0


class EvHudRenderer:
  def __init__(self):
    self.data = EvDataSource()
    self._font = gui_app.font(FontWeight.NORMAL)
    self._font_semi = gui_app.font(FontWeight.SEMI_BOLD)
    self.last_rect: rl.Rectangle | None = None

  # -- data -----------------------------------------------------------------

  def update(self) -> EvSnapshot:
    return self.data.update(ui_state.sm, ui_state.started_frame)

  # -- layout ---------------------------------------------------------------

  def _rows(self, s: EvSnapshot, preset: LayoutPreset) -> list[tuple[str, int]]:
    rows: list[tuple[str, int]] = []
    if finite(s.soc):
      rows.append(("soc", 96))
    if finite(s.power_kw):
      rows.append(("power", 96))
    if finite(s.range_km):
      rows.append(("range", 96))
    if preset == LayoutPreset.DENSE:
      if finite(s.pack_temp_c) or finite(s.coolant_temp_c):
        rows.append(("temps", 64))
      if finite(s.charge_limit_kw) or finite(s.discharge_limit_kw):
        rows.append(("limits", 64))
      if s.trip_km > 0.05:
        rows.append(("trip", 64))
      if len(s.tire_kpa) == 4 and all(finite(t) and t > 0 for t in s.tire_kpa):
        rows.append(("tires", 112))
      if finite(s.lv_volts):
        rows.append(("lv", 64))
      if finite(s.outside_temp_c):
        rows.append(("outside", 64))
    else:
      # Contextual rows (feasibility report C2): temperatures only when abnormal, problems as one row
      if finite(s.pack_temp_c) and not (PACK_TEMP_LOW_C <= s.pack_temp_c <= PACK_TEMP_HIGH_C):
        rows.append(("temps", 64))
      if s.tire_low or s.lv_low:
        rows.append(("warn", 64))
    return rows

  def render(self, content_rect: rl.Rectangle, preset: LayoutPreset) -> rl.Rectangle | None:
    self.last_rect = None
    if preset == LayoutPreset.MINIMAL or not getattr(ui_state, "ev_hud", True):
      return None
    s = self.update()
    if not s.available:
      return None
    rows = self._rows(s, preset)
    if not rows:
      return None

    h = PAD * 2 + sum(r[1] for r in rows) + ROW_GAP * (len(rows) - 1)
    right = content_rect.x + content_rect.width - UI_BORDER_SIZE
    if ui_state.developer_ui in (DeveloperUiState.RIGHT, DeveloperUiState.BOTH):
      right -= DEV_UI_RIGHT_W + UI_BORDER_SIZE
    x = right - CARD_W
    y = content_rect.y + UI_CONFIG.border_size + UI_CONFIG.button_size + 36
    max_h = content_rect.y + content_rect.height - y - 40
    if h > max_h:  # drop the lowest rows rather than overflow onto the alerts
      while rows and h > max_h:
        dropped = rows.pop()
        h -= dropped[1] + ROW_GAP
    card = rl.Rectangle(x, y, CARD_W, h)
    rl.draw_rectangle_rounded(card, roundness(card, Radius.MD * 2), 8, Onroad.PANEL)

    cy = y + PAD
    inner = rl.Rectangle(x + PAD, 0, CARD_W - 2 * PAD, 0)
    for name, rh in rows:
      inner.y, inner.height = cy, rh
      getattr(self, f"_row_{name}")(inner, s)
      cy += rh + ROW_GAP
    self.last_rect = card
    return card

  # -- primitives -----------------------------------------------------------

  def _label(self, x, y, text, color=None):
    rl.draw_text_ex(self._font, text, rl.Vector2(x, y), LABEL, 0, color or Console.TEXT_MUTED)

  def _value_right(self, r: rl.Rectangle, y, value: str, unit: str = "", color=None, size=VALUE):
    """Right-aligned value with a muted unit, Console number formatting."""
    unit_w = measure_text_cached(self._font, unit, SMALL).x if unit else 0
    gap = 8 if unit else 0
    val_w = measure_text_cached(self._font_semi, value, size).x
    vx = r.x + r.width - unit_w - gap - val_w
    rl.draw_text_ex(self._font_semi, value, rl.Vector2(vx, y), size, 0, color or Console.TEXT_PRIMARY)
    if unit:
      rl.draw_text_ex(self._font, unit, rl.Vector2(r.x + r.width - unit_w, y + size - SMALL - 4), SMALL, 0, Console.TEXT_MUTED)

  def _pair(self, r: rl.Rectangle, label: str, value: str, unit: str = "", color=None, dot=None):
    self._label(r.x + (22 if dot else 0), r.y + 18, label)
    if dot is not None:
      rl.draw_circle(int(r.x + 7), int(r.y + 18 + LABEL / 2), 7, dot)
    self._value_right(r, r.y + 8, value, unit, color, size=40)

  # -- rows -----------------------------------------------------------------

  def _row_soc(self, r: rl.Rectangle, s: EvSnapshot):
    soc = max(0.0, min(100.0, s.soc))
    if soc < 10 or s.low_soc:
      fill, word = Console.DANGER, "Low"
    elif soc < 20:
      fill, word = Console.WARNING, "Low"
    else:
      fill, word = Console.SUCCESS, ""
    self._label(r.x, r.y, "Battery" + (f" · {word}" if word else ""))
    self._value_right(r, r.y - 6, f"{soc:.0f}", "%")
    draw_bar(rl.Rectangle(r.x, r.y + r.height - BAR_H - 4, r.width, BAR_H), soc / 100.0, fill)

  def _row_power(self, r: rl.Rectangle, s: EvSnapshot):
    kw = s.power_kw
    regen = kw < -0.5
    self._label(r.x, r.y, "Regen" if regen else "Power")
    self._value_right(r, r.y - 6, f"{abs(kw):.0f}", "kW", Console.SUCCESS if regen else Console.TEXT_PRIMARY)

    # Center-zero meter: regen grows left in success, drive grows right in accent.
    bar = rl.Rectangle(r.x, r.y + r.height - BAR_H - 4, r.width, BAR_H)
    rl.draw_rectangle_rounded(bar, roundness(bar, Radius.XS), 4, Console.BG_TRACK)
    mid = bar.x + bar.width / 2
    drive_max = s.discharge_limit_kw if finite(s.discharge_limit_kw) and s.discharge_limit_kw > 50 else 300.0
    regen_max = s.charge_limit_kw if finite(s.charge_limit_kw) and s.charge_limit_kw > 20 else 150.0
    if kw >= 0:
      w = min(1.0, kw / drive_max) * bar.width / 2
      seg = rl.Rectangle(mid, bar.y, w, bar.height)
      color = Console.ACCENT
    else:
      w = min(1.0, -kw / regen_max) * bar.width / 2
      seg = rl.Rectangle(mid - w, bar.y, w, bar.height)
      color = Console.SUCCESS
    if w >= 1:
      rl.draw_rectangle_rounded(seg, roundness(seg, Radius.XS), 4, color)
    rl.draw_rectangle(int(mid - 1), int(bar.y - 4), 2, int(bar.height + 8), Console.TEXT_MUTED)

  def _row_range(self, r: rl.Rectangle, s: EvSnapshot):
    metric = ui_state.is_metric
    rng = s.range_km if metric else s.range_km * KM_TO_MI
    self._label(r.x, r.y, "Range est." if s.range_estimated else "Range")
    self._value_right(r, r.y - 6, f"{rng:.0f}", "km" if metric else "mi")
    if finite(s.wh_per_km) and s.wh_per_km > 1:
      eff = f"{s.wh_per_km:.0f} Wh/km" if metric else f"{1000.0 / (s.wh_per_km / KM_TO_MI):.1f} mi/kWh"
      text = f"Trip {eff}"
    else:
      text = "Efficiency after 0.5 km" if metric else "Efficiency after 0.3 mi"
    rl.draw_text_ex(self._font, text, rl.Vector2(r.x, r.y + r.height - SMALL), SMALL, 0, Console.TEXT_MUTED)

  def _temp(self, c: float) -> str:
    if not finite(c):
      return "–"
    return f"{c:.0f}°" if ui_state.is_metric else f"{_c_to_f(c):.0f}°"

  def _row_temps(self, r: rl.Rectangle, s: EvSnapshot):
    self._pair(r, "Pack / coolant", f"{self._temp(s.pack_temp_c)} / {self._temp(s.coolant_temp_c)}",
               "C" if ui_state.is_metric else "F")

  def _row_limits(self, r: rl.Rectangle, s: EvSnapshot):
    chg = f"{s.charge_limit_kw:.0f}" if finite(s.charge_limit_kw) else "–"
    dis = f"{s.discharge_limit_kw:.0f}" if finite(s.discharge_limit_kw) else "–"
    self._pair(r, "Regen / drive limit", f"{chg} / {dis}", "kW")

  def _row_trip(self, r: rl.Rectangle, s: EvSnapshot):
    self._pair(r, "Trip used / regen", f"{s.trip_used_kwh:.1f} / {s.trip_regen_kwh:.1f}", "kWh")

  def _row_tires(self, r: rl.Rectangle, s: EvSnapshot):
    metric = ui_state.is_metric
    vals = [t if metric else t * KPA_TO_PSI for t in s.tire_kpa]
    low = [(t * KPA_TO_PSI) < TIRE_LOW_PSI for t in s.tire_kpa]
    any_low = s.tire_low or any(low)
    self._label(r.x + 22, r.y, "Tires · Low" if any_low else "Tires")
    rl.draw_circle(int(r.x + 7), int(r.y + LABEL / 2), 7, Console.DANGER if any_low else Console.SUCCESS)
    unit = "kPa" if metric else "psi"
    unit_w = measure_text_cached(self._font, unit, SMALL).x
    rl.draw_text_ex(self._font, unit, rl.Vector2(r.x + r.width - unit_w, r.y), SMALL, 0, Console.TEXT_MUTED)
    # 2x2 grid in car layout: FL FR / RL RR
    col_w = r.width / 2
    for i, v in enumerate(vals):
      cx = r.x + (i % 2) * col_w
      cy = r.y + 40 + (i // 2) * 36
      color = Console.DANGER if low[i] else Console.TEXT_PRIMARY
      text = f"{v:.0f}"
      rl.draw_text_ex(self._font_semi, text, rl.Vector2(cx + (0 if i % 2 == 0 else col_w - measure_text_cached(self._font_semi, text, 34).x),
                                                        cy), 34, 0, color)

  def _row_lv(self, r: rl.Rectangle, s: EvSnapshot):
    low = s.lv_low
    self._pair(r, "12 V battery" + (" · Low" if low else ""), f"{s.lv_volts:.1f}", "V",
               dot=Console.DANGER if low else Console.SUCCESS)

  def _row_outside(self, r: rl.Rectangle, s: EvSnapshot):
    f = temp_range_factor(s.outside_temp_c)
    impact = (f - 1.0) * 100.0 if finite(f) else 0.0
    label = "Outside" if abs(impact) < 2 else f"Outside · range {impact:+.0f}%"
    self._pair(r, label, self._temp(s.outside_temp_c), "C" if ui_state.is_metric else "F",
               dot=Console.WARNING if impact <= -15 else None)

  def _row_warn(self, r: rl.Rectangle, s: EvSnapshot):
    parts = []
    if s.tire_low:
      parts.append("Tire pressure low")
    if s.lv_low:
      parts.append("12 V low")
    rl.draw_circle(int(r.x + 7), int(r.y + r.height / 2), 7, Console.DANGER)
    rl.draw_text_ex(self._font_semi, " · ".join(parts), rl.Vector2(r.x + 24, r.y + (r.height - 32) / 2), 32, 0, Console.TEXT_PRIMARY)
