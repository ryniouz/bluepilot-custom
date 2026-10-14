"""
Console EV HUD for the F-150 Lightning (driving screen items 6-11 in the Comma investigation).

Two pieces, both hidden in the Minimal layout:

  Dock      A bar along the bottom edge, like a phone's dock: charge (thick squared SOC bar),
            power (center-zero drive/regen bar) and range. It is the collapsed form of the
            quick-controls sheet, so its grab handle hints that a tap opens the controls.
  Details   A card on the right edge, under the experimental button.
              Standard  only when something needs attention (pack temperature out of range,
                        low tire, low 12 V)
              Dense     pack and coolant temperature, trip energy, tire pressures, 12 V,
                        outside temperature with range impact

Rows hide themselves when their signal is missing, and everything hides when the truck sends
no battery data at all. Status colours mark state only (low charge, low tire, low 12 V).
"""

from __future__ import annotations

import pyray as rl

from openpilot.selfdrive.ui import UI_BORDER_SIZE
from openpilot.selfdrive.ui.onroad.hud_renderer import UI_CONFIG
from openpilot.selfdrive.ui.sunnypilot.onroad.developer_ui import DeveloperUiState, get_bottom_dev_ui_offset
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.system.ui.lib.text_measure import measure_text_cached
from bluepilot.ui.lib.ev_data import EvDataSource, EvSnapshot, finite, temp_range_factor, PACK_TEMP_LOW_C, PACK_TEMP_HIGH_C
from bluepilot.ui.lib.layout_presets import LayoutPreset
from bluepilot.ui.lib.obd_link import obd_link
from bluepilot.ui.console import kit as K
from bluepilot.ui.console.home import soc_color
from bluepilot.ui.lib.theme import Console, Onroad, roundness

KM_TO_MI = 0.621371
KPA_TO_PSI = 0.145038

CARD_W = 420
PAD = 12
PAD_X = 28
ROW_H = 68              # details row: label left, value right, hairline between rows
LABEL = 28
ROW_VALUE = 36
SMALL = 28
BAR_H = 12
DEV_UI_RIGHT_W = 184

CARD_RADIUS = 24        # kit PANEL_R

# Dock
DOCK_H = 148
DOCK_MARGIN = 24        # from the inner edge of the status frame
DOCK_PAD_X = 36
DOCK_PAD_Y = 22
DOCK_SEG_W = 320        # one segment: value line + bar
DOCK_GAP = 32           # between segments (a hairline sits in the middle)
DOCK_VALUE = 50
DOCK_UNIT = 30
DOCK_CAPTION = 30       # kit CAP
DOCK_BAR_H = 28         # thick squared Console bar (kit K.bar)
DOCK_RADIUS = 24        # kit PANEL_R

OBD_HEAD_H = 48
HEATER_SHOW_KW = 0.2
SOH_WARN_PCT = 80.0
CELL_SPREAD_WARN_MV = 50.0   # min module voltage this far below the average is worth a look

TIRE_LOW_PSI = 30.0  # Lightning placard is 42 psi; the TPMS warning sits near 32


class EvHudRenderer:
  def __init__(self):
    self.data = EvDataSource()
    self._font = gui_app.font(FontWeight.NORMAL)
    self._font_semi = gui_app.font(FontWeight.SEMI_BOLD)
    self.last_rect: rl.Rectangle | None = None
    self.dock_last_rect: rl.Rectangle | None = None
    self._obd: dict[str, float] = {}

  # -- data -----------------------------------------------------------------

  def _obd_values(self) -> dict[str, float] | None:
    """Fresh OBD values by short name while the adapter is connected; None otherwise, so the OBD
    rows simply are not there (no greyed-out or error rows) when it is off, asleep or failing."""
    try:
      snap = obd_link().snapshot()
    except Exception:
      return None
    if not (snap.received and snap.link == "connected"):
      return None
    vals = {v.name: v.value for v in snap.values if finite(v.value)}
    return vals or None

  def update(self) -> EvSnapshot:
    shared = getattr(ui_state, "ev", None)
    return shared if shared is not None else self.data.update(ui_state.sm, ui_state.started_frame)

  # -- layout ---------------------------------------------------------------

  def _rows(self, s: EvSnapshot, preset: LayoutPreset) -> list[tuple[str, int]]:
    rows: list[tuple[str, int]] = []
    if preset == LayoutPreset.DENSE:
      if finite(s.pack_temp_c):
        rows.append(("pack", ROW_H))
      if finite(s.coolant_temp_c):
        rows.append(("coolant", ROW_H))
      if s.trip_km > 0.05:
        rows.append(("trip", ROW_H))
      if len(s.tire_kpa) == 4 and all(finite(t) and t > 0 for t in s.tire_kpa):
        rows.append(("tires", ROW_H + 36))
      # OBD sits above the 12 V and outside rows, which drop first when the card runs out of room
      obd = self._obd_values()
      if obd is not None:
        self._obd = obd
        obd_rows = []
        if "HvbEte" in obd:
          obd_rows.append(("obd_energy", ROW_H))
        if obd.get("HvbCHP", 0.0) > HEATER_SHOW_KW:  # only while the heater is actually drawing power
          obd_rows.append(("obd_heater", ROW_H))
        if "HvbSoh" in obd:
          obd_rows.append(("obd_soh", ROW_H))
        if "HvbAvgModV" in obd and "HvbMinModV" in obd:
          obd_rows.append(("obd_cells", ROW_H))
        if "LvSoc" in obd:
          obd_rows.append(("obd_lv", ROW_H))
        if obd_rows:
          rows += [("obd_head", OBD_HEAD_H)] + obd_rows
      if finite(s.lv_volts):
        rows.append(("lv", ROW_H))
      if finite(s.outside_temp_c):
        rows.append(("outside", ROW_H))
    else:
      # Contextual rows (feasibility report C2): temperatures only when abnormal, problems as one row
      if finite(s.pack_temp_c) and not (PACK_TEMP_LOW_C <= s.pack_temp_c <= PACK_TEMP_HIGH_C):
        rows.append(("pack", ROW_H))
      if s.tire_low or s.lv_low:
        rows.append(("warn", ROW_H))
    return rows

  def _enabled(self, preset: LayoutPreset) -> EvSnapshot | None:
    if preset == LayoutPreset.MINIMAL or not getattr(ui_state, "ev_hud", True):
      return None
    s = self.update()
    return s if s.available else None

  def render(self, content_rect: rl.Rectangle, preset: LayoutPreset, bottom: float | None = None) -> rl.Rectangle | None:
    """Details card on the right edge. bottom: lowest y the card may reach (top of the dock)."""
    self.last_rect = None
    s = self._enabled(preset)
    if s is None:
      return None
    rows = self._rows(s, preset)
    if not rows:
      return None

    h = PAD * 2 + sum(r[1] for r in rows)
    right = content_rect.x + content_rect.width - UI_BORDER_SIZE
    if ui_state.developer_ui in (DeveloperUiState.RIGHT, DeveloperUiState.BOTH):
      right -= DEV_UI_RIGHT_W + UI_BORDER_SIZE
    x = right - CARD_W
    y = content_rect.y + UI_CONFIG.border_size + UI_CONFIG.button_size + 36
    floor = bottom if bottom is not None else content_rect.y + content_rect.height
    max_h = floor - y - 24
    if h > max_h:  # drop the lowest rows rather than overflow onto the alerts
      while rows and h > max_h:
        dropped = rows.pop()
        h -= dropped[1]
    card = rl.Rectangle(x, y, CARD_W, h)
    rl.draw_rectangle_rounded(card, roundness(card, CARD_RADIUS), 8, Onroad.PANEL)

    cy = y + PAD
    inner = rl.Rectangle(x + PAD_X, 0, CARD_W - 2 * PAD_X, 0)
    for k, (name, rh) in enumerate(rows):
      if k and rows[k - 1][0] != "obd_head":
        rl.draw_rectangle(int(inner.x), int(cy), int(inner.width), 2, Console.BORDER_SUBTLE)
      inner.y, inner.height = cy, rh
      getattr(self, f"_row_{name}")(inner, s)
      cy += rh
    self.last_rect = card
    return card

  # -- dock -----------------------------------------------------------------

  def dock_rect(self, content_rect: rl.Rectangle, preset: LayoutPreset) -> rl.Rectangle | None:
    """Where the dock would draw this frame, or None when it is hidden."""
    s = self._enabled(preset)
    if s is None:
      return None
    n = sum(1 for v in (s.soc, self._power_value(s), s.range_km) if finite(v))
    if n == 0:
      return None
    w = DOCK_PAD_X * 2 + n * DOCK_SEG_W + (n - 1) * DOCK_GAP
    x = content_rect.x + (content_rect.width - w) / 2
    y = content_rect.y + content_rect.height - DOCK_MARGIN - DOCK_H
    if ui_state.developer_ui in (DeveloperUiState.BOTTOM, DeveloperUiState.BOTH):
      y -= get_bottom_dev_ui_offset()
    return rl.Rectangle(x, y, w, DOCK_H)

  def render_dock(self, content_rect: rl.Rectangle, preset: LayoutPreset, torque_bar=None) -> rl.Rectangle | None:
    """Bottom dock: charge, power, range. torque_bar: TorqueBarRendererBP drawn as a strip along
    the dock's top edge when the driver has the torque bar switched on."""
    dock = self.dock_rect(content_rect, preset)
    if dock is None:
      return None
    s = self.update()
    rl.draw_rectangle_rounded(dock, roundness(dock, DOCK_RADIUS), 10, Onroad.PANEL)

    if torque_bar is not None and ui_state.torque_bar:
      torque_bar.render_strip(rl.Rectangle(dock.x + DOCK_RADIUS, dock.y + 6, dock.width - 2 * DOCK_RADIUS, 8))
    else:
      grab = rl.Rectangle(dock.x + dock.width / 2 - 36, dock.y + 9, 72, 6)
      rl.draw_rectangle_rounded(grab, 1.0, 6, Console.BORDER_STRONG)

    x = dock.x + DOCK_PAD_X
    first = True
    for name, v in (("soc", s.soc), ("power", self._power_value(s)), ("range", s.range_km)):
      if not finite(v):
        continue
      if not first:
        rl.draw_rectangle(int(x - DOCK_GAP / 2 - 1), int(dock.y + DOCK_PAD_Y + 6), 2, int(DOCK_H - 2 * DOCK_PAD_Y - 12),
                          Console.BORDER_SUBTLE)
      first = False
      seg = rl.Rectangle(x, dock.y + DOCK_PAD_Y, DOCK_SEG_W, DOCK_H - 2 * DOCK_PAD_Y)
      getattr(self, f"_dock_{name}")(seg, s)
      x += DOCK_SEG_W + DOCK_GAP
    self.dock_last_rect = dock
    return dock

  def _dock_value(self, r: rl.Rectangle, value: str, unit: str, caption: str, color=None, caption_color=None):
    """Value + unit on the left, caption right-aligned on the same baseline."""
    y = r.y + 2
    rl.draw_text_ex(self._font_semi, value, rl.Vector2(r.x, y), DOCK_VALUE, 0, color or Console.TEXT_PRIMARY)
    vw = measure_text_cached(self._font_semi, value, DOCK_VALUE).x
    base = y + DOCK_VALUE * 0.80
    if unit:
      rl.draw_text_ex(self._font, unit, rl.Vector2(r.x + vw + 8, base - DOCK_UNIT * 0.80), DOCK_UNIT, 0, Console.TEXT_MUTED)
    cw = measure_text_cached(self._font_semi, caption, DOCK_CAPTION).x
    rl.draw_text_ex(self._font_semi, caption, rl.Vector2(r.x + r.width - cw, base - DOCK_CAPTION * 0.80), DOCK_CAPTION, 0,
                    caption_color or Console.TEXT_MUTED)

  def _dock_bar_rect(self, r: rl.Rectangle) -> rl.Rectangle:
    return rl.Rectangle(r.x, r.y + r.height - DOCK_BAR_H, r.width, DOCK_BAR_H)

  def _dock_soc(self, r: rl.Rectangle, s: EvSnapshot):
    soc = max(0.0, min(100.0, s.soc))
    fill = Console.DANGER if s.low_soc else soc_color(soc)
    low = soc < 20 or s.low_soc
    self._dock_value(r, f"{soc:.0f}", "%", "Low" if low else "Charge", caption_color=fill if low else None)
    K.bar(self._dock_bar_rect(r), soc / 100.0, fill)

  @staticmethod
  def _power_value(s: EvSnapshot) -> float:
    """kW for the power tile: pack power, or while plugged in the charger's power into the pack
    (negative), which the charging reader reports even when pack current is not decoded."""
    if s.charging and finite(s.charge_power_kw):
      return -abs(s.charge_power_kw)
    return s.power_kw

  def _dock_power(self, r: rl.Rectangle, s: EvSnapshot):
    kw = self._power_value(s)
    # Plugged in with the ignition on, power flows into the pack from the charger, not from regen
    charging = s.charging
    regen = kw < -0.5
    caption = "Charging" if charging else ("Regen" if regen else "Power")
    self._dock_value(r, f"{abs(kw):.0f}", "kW", caption, caption_color=Console.SUCCESS if (regen or charging) else None)
    # Center-zero meter: regen grows left in success, drive grows right in accent
    bar = self._dock_bar_rect(r)
    rl.draw_rectangle_rounded(bar, roundness(bar, 6), 4, Console.BG_TRACK)
    mid = bar.x + bar.width / 2
    drive_max = s.discharge_limit_kw if finite(s.discharge_limit_kw) and s.discharge_limit_kw > 50 else 300.0
    regen_max = s.charge_limit_kw if finite(s.charge_limit_kw) and s.charge_limit_kw > 20 else 150.0
    if kw >= 0:
      w = min(1.0, kw / drive_max) * bar.width / 2
      seg, color = rl.Rectangle(mid, bar.y, w, bar.height), Console.ACCENT
    else:
      w = min(1.0, -kw / regen_max) * bar.width / 2
      seg, color = rl.Rectangle(mid - w, bar.y, w, bar.height), Console.SUCCESS
    if w >= 1:
      rl.draw_rectangle_rounded(seg, roundness(seg, 6), 4, color)
    rl.draw_rectangle(int(mid - 2), int(bar.y - 8), 4, int(bar.height + 16), Console.TEXT_PRIMARY)

  def _dock_range(self, r: rl.Rectangle, s: EvSnapshot):
    metric = ui_state.is_metric
    rng = s.range_km if metric else s.range_km * KM_TO_MI
    self._dock_value(r, f"{rng:.0f}", "km" if metric else "mi", "Range")
    if finite(s.wh_per_km) and s.wh_per_km > 1:
      eff = f"{s.wh_per_km / 10.0:.1f} kWh/100 km" if metric else f"{1000.0 / (s.wh_per_km / KM_TO_MI):.1f} mi/kWh"
      text = eff
    else:
      text = "Estimated" if s.range_estimated else "Efficiency soon"
    rl.draw_text_ex(self._font, text, rl.Vector2(r.x, r.y + r.height - DOCK_BAR_H / 2 - SMALL / 2 - 2), SMALL, 0, Console.TEXT_MUTED)

  # -- details rows ---------------------------------------------------------

  def _row(self, r: rl.Rectangle, label: str, value: str, unit: str = "", dot=None, color=None, label_color=None):
    """One details row: optional status dot, muted label, right-aligned value with unit."""
    lx = r.x
    if dot is not None:
      rl.draw_circle(int(r.x + 8), int(r.y + r.height / 2), 8, dot)
      lx += 26
    rl.draw_text_ex(self._font, label, rl.Vector2(lx, r.y + (r.height - LABEL) / 2), LABEL, 0, label_color or Console.TEXT_MUTED)
    unit_w = measure_text_cached(self._font, unit, SMALL).x if unit else 0
    gap = 8 if unit else 0
    val_w = measure_text_cached(self._font_semi, value, ROW_VALUE).x
    vy = r.y + (r.height - ROW_VALUE) / 2 - 2
    rl.draw_text_ex(self._font_semi, value, rl.Vector2(r.x + r.width - unit_w - gap - val_w, vy), ROW_VALUE, 0,
                    color or Console.TEXT_PRIMARY)
    if unit:
      rl.draw_text_ex(self._font, unit, rl.Vector2(r.x + r.width - unit_w, vy + ROW_VALUE * 0.8 - SMALL * 0.8), SMALL, 0,
                      Console.TEXT_MUTED)

  # Units are Canadian: temperatures always in °C and tire pressure always in psi; distance and
  # speed follow the IsMetric setting (km and km/h on the truck).
  def _temp(self, c: float) -> str:
    return f"{c:.0f}°" if finite(c) else "–"

  def _temp_unit(self) -> str:
    return "C"

  def _row_pack(self, r: rl.Rectangle, s: EvSnapshot):
    cold, hot = s.pack_temp_c < PACK_TEMP_LOW_C, s.pack_temp_c > PACK_TEMP_HIGH_C
    label = "Battery · Cold" if cold else ("Battery · Hot" if hot else "Battery temp")
    self._row(r, label, self._temp(s.pack_temp_c), self._temp_unit(), dot=Console.WARNING if (cold or hot) else None)

  def _row_coolant(self, r: rl.Rectangle, s: EvSnapshot):
    self._row(r, "Coolant", self._temp(s.coolant_temp_c), self._temp_unit())

  def _row_trip(self, r: rl.Rectangle, s: EvSnapshot):
    self._row(r, "Trip used", f"{s.trip_used_kwh:.1f}", "kWh")

  def _row_tires(self, r: rl.Rectangle, s: EvSnapshot):
    vals = [t * KPA_TO_PSI for t in s.tire_kpa]
    low = [(t * KPA_TO_PSI) < TIRE_LOW_PSI for t in s.tire_kpa]
    any_low = s.tire_low or any(low)
    rl.draw_circle(int(r.x + 8), int(r.y + r.height / 2), 8, Console.DANGER if any_low else Console.SUCCESS)
    rl.draw_text_ex(self._font, "Tires · Low" if any_low else "Tires", rl.Vector2(r.x + 26, r.y + (r.height - LABEL) / 2), LABEL, 0,
                    Console.TEXT_MUTED)
    unit = "psi"
    unit_w = measure_text_cached(self._font, unit, SMALL).x
    # 2x2 grid in truck layout (front row on top), right-aligned before the unit
    col_w = 76
    gx = r.x + r.width - unit_w - 12 - 2 * col_w
    for i, v in enumerate(vals):
      text = f"{v:.0f}"
      tw = measure_text_cached(self._font_semi, text, ROW_VALUE).x
      cx = gx + (i % 2) * col_w + col_w - tw
      cy = r.y + r.height / 2 - ROW_VALUE - 2 + (i // 2) * (ROW_VALUE + 4)
      rl.draw_text_ex(self._font_semi, text, rl.Vector2(cx, cy), ROW_VALUE, 0, Console.DANGER if low[i] else Console.TEXT_PRIMARY)
    rl.draw_text_ex(self._font, unit, rl.Vector2(r.x + r.width - unit_w, r.y + (r.height - SMALL) / 2), SMALL, 0, Console.TEXT_MUTED)

  def _row_lv(self, r: rl.Rectangle, s: EvSnapshot):
    low = s.lv_low
    self._row(r, "12 V · Low" if low else "12 V battery", f"{s.lv_volts:.1f}", "V", dot=Console.DANGER if low else None)

  def _row_outside(self, r: rl.Rectangle, s: EvSnapshot):
    f = temp_range_factor(s.outside_temp_c)
    impact = (f - 1.0) * 100.0 if finite(f) else 0.0
    label = "Outside" if abs(impact) < 2 else f"Outside · {impact:+.0f}%"
    self._row(r, label, self._temp(s.outside_temp_c), self._temp_unit(), dot=Console.WARNING if impact <= -15 else None)

  # -- OBD rows (only while the adapter is connected) ----------------------------------------

  def _row_obd_head(self, r: rl.Rectangle, s: EvSnapshot):
    rl.draw_circle(int(r.x + 6), int(r.y + r.height / 2 + 2), 6, Console.SUCCESS)
    rl.draw_text_ex(self._font_semi, "OBD", rl.Vector2(r.x + 22, r.y + (r.height - SMALL) / 2 + 2), SMALL, 0, Console.TEXT_SECONDARY)

  def _row_obd_energy(self, r: rl.Rectangle, s: EvSnapshot):
    self._row(r, "Energy left", f"{self._obd['HvbEte']:.1f}", "kWh")

  def _row_obd_heater(self, r: rl.Rectangle, s: EvSnapshot):
    self._row(r, "Heater", f"{self._obd['HvbCHP']:.1f}", "kW")

  def _row_obd_soh(self, r: rl.Rectangle, s: EvSnapshot):
    soh = self._obd["HvbSoh"]
    self._row(r, "Battery health", f"{soh:.0f}", "%", dot=Console.WARNING if soh < SOH_WARN_PCT else None)

  def _row_obd_cells(self, r: rl.Rectangle, s: EvSnapshot):
    spread = (self._obd["HvbAvgModV"] - self._obd["HvbMinModV"]) * 1000.0
    warn = spread > CELL_SPREAD_WARN_MV
    self._row(r, "Cell spread", f"{max(0.0, spread):.0f}", "mV", dot=Console.WARNING if warn else None)

  def _row_obd_lv(self, r: rl.Rectangle, s: EvSnapshot):
    soc = self._obd["LvSoc"]
    self._row(r, "12 V charge", f"{soc:.0f}", "%", dot=Console.WARNING if soc < 60 else None)

  def _row_warn(self, r: rl.Rectangle, s: EvSnapshot):
    parts = []
    if s.tire_low:
      parts.append("Tire pressure low")
    if s.lv_low:
      parts.append("12 V low")
    rl.draw_circle(int(r.x + 8), int(r.y + r.height / 2), 8, Console.DANGER)
    rl.draw_text_ex(self._font_semi, " · ".join(parts), rl.Vector2(r.x + 26, r.y + (r.height - 32) / 2), 32, 0, Console.TEXT_PRIMARY)
