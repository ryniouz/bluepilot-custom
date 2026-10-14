"""
Console charging page for the F-150 Lightning.

One layout, drawn in two places:
  ChargingScreen  full screen; takes over while the truck charges at a standstill (ignition on or
                  off). A tap anywhere minimizes it to the driving view or Home.
  ChargingPage    Energy > Charging in the shell; reopens the full screen while plugged in and
                  shows the last session when not.

  header   status dot, charge type, what the truck says (paused, heating the battery, ...)
  battery  big SOC, range with the range added, and one thick squared bar: the charge the
           session started with, plus what it added
  tiles    power (with a bar against the truck's maximum), energy added, time, battery thermal

No charge limits (the truck does not report them) and no charts (those live on Statistics).
"""

from __future__ import annotations

import time
from collections.abc import Callable

import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.lib.ev_data import ChargeSession, EvSnapshot, finite, PACK_TEMP_LOW_C, PACK_TEMP_HIGH_C
from bluepilot.ui.lib.obd_link import fmt_value, live_values
from bluepilot.ui.lib.theme import Console, roundness

# Lightning maximum charge power, for the power bar: DC about 155 kW (Extended Range), AC 19.2 kW (80 A)
MAX_DC_KW = 155.0
MAX_AC_KW = 19.2

MARGIN = 72
GAP = 24
TILE_PAD = 32

# Type sizes (device px)
SOC = 240
SOC_UNIT = 80
TITLE = 56
BIG = 96
BIG_UNIT = 40
LABEL = 30
NOTE = 28

CHARGE_TYPE_TITLE = {1: "AC charging", 2: "DC fast charging", 3: "Charging"}

STATUS_TEXT = {
  "targetReached": "Charge complete",
  "maintaining": "Holding the charge",
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

THERMAL_TEXT = {
  "cooling": "Cooling",
  "heating": "Heating",
  "conditioning": "Conditioning",
  "circulating": "Circulating",
  "off": "Off",
  "": "No data",
}


def thermal_color(mode: str) -> rl.Color:
  return {
    "cooling": Console.INFO,
    "heating": Console.WARNING,
    "conditioning": Console.PURPLE,
    "circulating": Console.TEXT_SECONDARY,
    "off": Console.TEXT_MUTED,
  }.get(mode, Console.TEXT_GHOST)


def fmt_duration(minutes: float) -> tuple[str, str]:
  """('1:05', 'h') or ('23', 'min')."""
  minutes = max(0, int(round(minutes)))
  if minutes >= 60:
    return f"{minutes // 60}:{minutes % 60:02d}", "h"
  return f"{minutes}", "min"


def fmt_kw(kw: float) -> str:
  return f"{kw:.0f}" if kw >= 10 else f"{kw:.1f}"


# Canadian units throughout, whatever IsMetric says: °C and km (Lucas, 2026-10-14)
def fmt_temp(c: float) -> tuple[str, str]:
  return f"{c:.0f}", "°C"


def fmt_dist(km: float) -> tuple[str, str]:
  return f"{km:.0f}", "km"


def charge_title(s: EvSnapshot) -> str:
  return tr(CHARGE_TYPE_TITLE.get(s.charge_type, "Charging"))


def status_line(s: EvSnapshot) -> tuple[str, bool]:
  """What the truck says about the charge, and whether it is a warning."""
  if s.charge_inhibit_thermal:
    return tr("Slowed by battery temperature"), True
  text = STATUS_TEXT.get(s.charge_status, "")
  if not text and s.thermal_mode == "heating":
    text = "Heating the battery"
  elif not text and s.thermal_mode == "conditioning":
    text = "Conditioning the battery"
  return tr(text) if text else "", s.charge_status in WARN_STATES


def status_dot(s: EvSnapshot) -> rl.Color:
  if s.charge_status == "fault":
    return Console.DANGER
  if s.charge_inhibit_thermal or s.charge_status in WARN_STATES:
    return Console.WARNING
  if s.charge_status in ("targetReached", "maintaining"):
    return Console.INFO
  return Console.SUCCESS


# -- drawing ---------------------------------------------------------------------------------

def soc_bar(r: rl.Rectangle, soc: float, start_soc: float | None, fill: rl.Color):
  """Thick squared Console bar. The charge the session started with is drawn dimmer than what it added."""
  rl.draw_rectangle_rounded(r, roundness(r, 8), 6, Console.BG_TRACK)
  if not finite(soc) or soc <= 0:
    return
  frac = max(0.0, min(1.0, soc / 100.0))
  full = rl.Rectangle(r.x, r.y, max(8.0, r.width * frac), r.height)
  if start_soc is not None and finite(start_soc) and 0 < start_soc < soc:
    rl.draw_rectangle_rounded(full, roundness(full, 8), 6, fill)
    # the charge it arrived with: page ground, then the empty track, then a translucent fill
    base = rl.Rectangle(r.x, r.y, r.width * start_soc / 100.0, r.height)
    for c in (Console.BG_PAGE, Console.BG_TRACK, K.rgba(fill, 0x80)):
      rl.draw_rectangle_rounded(base, roundness(base, 8), 6, c)
      rl.draw_rectangle_rec(rl.Rectangle(base.x + base.width - 8, base.y, 8, base.height), c)
    rl.draw_rectangle_rec(rl.Rectangle(base.x + base.width, base.y, 4, base.height), Console.BG_PAGE)
  else:
    rl.draw_rectangle_rounded(full, roundness(full, 8), 6, fill)


def tile(r: rl.Rectangle, label: str, value: str, unit: str = "", note: str = "", value_color: rl.Color | None = None,
         note_color: rl.Color | None = None, note_dot: rl.Color | None = None, meter: float | None = None,
         meter_color: rl.Color | None = None):
  K.panel(r)
  x, y = r.x + TILE_PAD, r.y + TILE_PAD
  w = r.width - 2 * TILE_PAD
  D.text(D.fit(label, LABEL, w), x, y, LABEL, Console.TEXT_MUTED)
  need = D.text_w(value, BIG, semi=True) + (10 + D.text_w(unit, BIG_UNIT) if unit else 0)
  k = min(1.0, w / need) if need > 0 else 1.0  # shrink the numeral rather than clip the unit (UI size Large)
  D.value_unit(value, unit, x, y + LABEL + 16 + BIG * (1 - k) * 0.86, BIG * k, BIG_UNIT * max(k, 0.8), value_color)
  bottom = r.y + r.height - TILE_PAD
  if note:
    ny = bottom - NOTE
    nx = x
    if note_dot is not None:
      D.dot(nx + 9, ny + NOTE / 2 + 2, 9, note_dot)
      nx += 30
    D.text(D.fit(note, NOTE, w - (nx - x)), nx, ny, NOTE, note_color or Console.TEXT_SECONDARY)
    bottom = ny - 20
  if meter is not None:
    K.bar(rl.Rectangle(x, bottom - 16, w, 16), meter, meter_color or Console.ACCENT)


def draw_header(r: rl.Rectangle, s: EvSnapshot, session: ChargeSession, hint: str = "") -> rl.Rectangle | None:
  """Title row of the full screen. Returns the minimize button rect."""
  D.dot(r.x + 14, r.y + TITLE / 2 + 4, 14, status_dot(s))
  D.text(charge_title(s), r.x + 48, r.y, TITLE, semi=True)
  sub, warn = status_line(s)
  if not sub:
    plugged = time.localtime(time.mktime(time.localtime()) - session.elapsed_s())
    sub = tr("Plugged in at") + " " + time.strftime("%-I:%M %p", plugged).lower()
  D.text(sub, r.x + 48, r.y + TITLE + 14, 32, Console.WARNING if warn else Console.TEXT_MUTED)
  if not hint:
    return None
  w = D.text_w(hint, LABEL, semi=True) + 48 + 40
  b = rl.Rectangle(r.x + r.width - w, r.y + 4, w, 80)
  rl.draw_rectangle_rounded(b, roundness(b, 12), 8, Console.BG_RAISED)
  # chevron pointing down
  cx, cy = b.x + 24 + 16, b.y + 40
  rl.draw_line_ex(rl.Vector2(cx - 12, cy - 6), rl.Vector2(cx, cy + 6), 4, Console.TEXT_SECONDARY)
  rl.draw_line_ex(rl.Vector2(cx, cy + 6), rl.Vector2(cx + 12, cy - 6), 4, Console.TEXT_SECONDARY)
  D.text(hint, b.x + 24 + 40, b.y + (80 - LABEL) / 2 - 2, LABEL, Console.TEXT_SECONDARY, semi=True)
  return b


def draw_battery(r: rl.Rectangle, s: EvSnapshot, session: ChargeSession | None, live: bool = True) -> float:
  """SOC, range and the thick bar. Returns the bottom y."""
  D.text(tr("Battery"), r.x, r.y, LABEL, Console.TEXT_MUTED)
  vy = r.y + LABEL + 12
  if finite(s.soc):
    D.value_unit(f"{s.soc:.0f}", "%", r.x, vy, SOC, SOC_UNIT)
  else:
    D.text("--", r.x, vy, SOC, Console.TEXT_GHOST, semi=True)

  # Range column, right half
  rx = r.x + r.width * 0.52
  D.text(tr("Range"), rx, r.y, LABEL, Console.TEXT_MUTED)
  if finite(s.range_km):
    v, u = fmt_dist(s.range_km)
    D.value_unit(v, u, rx, vy + 24, 120, 48)
    added = session.range_added_km(s) if session is not None and session.active else float("nan")
    if finite(added) and added >= 1:
      av, au = fmt_dist(added)
      D.text(f"+{av} {au} " + tr("since plug-in"), rx, vy + 24 + 120 + 20, 32, Console.SUCCESS)
    elif s.range_estimated:
      D.text(tr("Estimated from charge"), rx, vy + 24 + 120 + 20, 32, Console.TEXT_MUTED)
  else:
    D.text("--", rx, vy + 24, 120, Console.TEXT_GHOST, semi=True)

  by = vy + SOC + 28
  bar = rl.Rectangle(r.x, by, r.width, 72)
  low = finite(s.soc) and s.soc < 10
  fill = Console.DANGER if low else (Console.SUCCESS if live else Console.TEXT_MUTED)
  start = session.start_soc if session is not None and session.active else None
  soc_bar(bar, s.soc, start, fill)

  ly = by + 72 + 14
  D.text("0", r.x, ly, 26, Console.TEXT_GHOST)
  D.text_right("100 %", r.x + r.width, ly, 26, Console.TEXT_GHOST)
  if start is not None and finite(start) and finite(s.soc) and start < s.soc:
    sx = r.x + r.width * start / 100.0
    label = tr("Plugged in at") + f" {start:.0f} %"
    lw = D.text_w(label, 26)
    lx = max(r.x + 60, min(sx - lw / 2, r.x + r.width - lw - 120))
    D.text(label, lx, ly, 26, Console.TEXT_MUTED)
  return ly + 26


def draw_tiles(r: rl.Rectangle, s: EvSnapshot, session: ChargeSession):
  cells = [rl.Rectangle(r.x + i * (r.width - 3 * GAP) / 4 + i * GAP, r.y, (r.width - 3 * GAP) / 4, r.height) for i in range(4)]

  # Power, against the truck's maximum for this kind of charge
  max_kw = MAX_DC_KW if s.charge_type == 2 else MAX_AC_KW
  if finite(s.charge_power_kw):
    peak = tr("Peak") + f" {fmt_kw(session.peak_kw)} kW" if finite(session.peak_kw) else ""
    tile(cells[0], tr("Power"), fmt_kw(s.charge_power_kw), "kW", peak, value_color=Console.ACCENT,
         meter=s.charge_power_kw / max_kw, meter_color=Console.ACCENT)
  else:
    tile(cells[0], tr("Power"), "--", "kW", tr("Waiting for the truck"), meter=0.0)

  # Energy added
  gained = ""
  if finite(s.soc) and finite(session.start_soc) and s.soc >= session.start_soc:
    gained = f"+{s.soc - session.start_soc:.0f} % " + tr("since plug-in")
  tile(cells[1], tr("Energy added"), f"{session.energy_kwh:.1f}", "kWh", gained)

  # Time: to full when the truck says, otherwise time on the charger
  elapsed_min = session.elapsed_s() / 60.0
  ev, eu = fmt_duration(elapsed_min)
  if finite(s.charge_time_to_full_min) and s.charge_time_to_full_min > 0:
    v, u = fmt_duration(s.charge_time_to_full_min)
    tile(cells[2], tr("Time to full"), v, u, tr("Charging for") + f" {ev} {eu}")
  else:
    tile(cells[2], tr("Charging for"), ev, eu, tr("No estimate from the truck"), note_color=Console.TEXT_MUTED)

  # Battery thermal
  mode = s.thermal_mode
  note = tr(THERMAL_TEXT.get(mode, "No data"))
  wide = cells[3].width > 420
  if wide and finite(s.coolant_temp_c):
    cv, cu = fmt_temp(s.coolant_temp_c)
    note += " · " + tr("coolant") + f" {cv} {cu}"
  if finite(s.pack_temp_c):
    tv, tu = fmt_temp(s.pack_temp_c)
    abnormal = not (PACK_TEMP_LOW_C <= s.pack_temp_c <= PACK_TEMP_HIGH_C)
    tile(cells[3], tr("Battery temperature") if wide else tr("Battery"), tv, tu, note, value_color=Console.WARNING if abnormal else None,
         note_dot=thermal_color(mode))
  else:
    tile(cells[3], tr("Battery temperature") if wide else tr("Battery"), "--", "", note, note_dot=thermal_color(mode))


def obd_items() -> list[tuple[str, str]]:
  """Extra charging readings from the OBD adapter; empty unless it is connected (then the row isn't drawn)."""
  vals = live_values()
  out = []
  v, a = vals.get("HvbV"), vals.get("HvbA")
  if v is not None:
    out.append((tr("Pack"), fmt_value(v) + (f" · {abs(a.value):.0f} A" if a is not None else "")))
  if "ChgOV" in vals:
    out.append((tr("Charger out"), fmt_value(vals["ChgOV"])))
  if "HvbMinModV" in vals and "HvbAvgModV" in vals:
    out.append((tr("Modules"), f"{vals['HvbMinModV'].value:.2f}–{vals['HvbAvgModV'].value:.2f} V"))
  if "HvbCit" in vals:
    cv, cu = fmt_temp(vals["HvbCit"].value)
    out.append((tr("Coolant in"), f"{cv} {cu}"))
  if "LvV" in vals:
    out.append((tr("12 V"), fmt_value(vals["LvV"])))
  return out


def draw_obd_row(r: rl.Rectangle, items: list[tuple[str, str]]):
  """One quiet line under the tiles: OBD label, then label/value pairs that fit."""
  x, right, y = r.x, r.x + r.width, r.y + (r.height - LABEL) / 2
  D.icon("plug", x, y - 2, 36, Console.TEXT_MUTED)
  x += 52
  for label, value in items:
    w = D.text_w(label, LABEL) + 12 + D.text_w(value, LABEL, semi=True)
    if x + w > right:
      break
    D.text(label, x, y, LABEL, Console.TEXT_MUTED)
    D.text(value, x + D.text_w(label, LABEL) + 12, y, LABEL, Console.TEXT_SECONDARY, semi=True)
    x += w + 48


def draw_body(r: rl.Rectangle, s: EvSnapshot, session: ChargeSession):
  bottom = draw_battery(rl.Rectangle(r.x, r.y, r.width, r.height), s, session)
  obd = obd_items()
  top = bottom + (36 if obd else 56)
  # the OBD row may use part of the screen margin below; the tiles keep their height so the meter fits
  row_h = 60 if obd else 0
  tiles_h = min(300.0, max(280.0, r.y + r.height - top - row_h))
  draw_tiles(rl.Rectangle(r.x, top, r.width, tiles_h), s, session)
  if obd:
    draw_obd_row(rl.Rectangle(r.x, top + tiles_h + 4, r.width, row_h), obd)


def draw_idle(r: rl.Rectangle, s: EvSnapshot | None, session: ChargeSession | None):
  """Not plugged in: last known charge and the previous session."""
  snap = s if s is not None and s.available else getattr(getattr(ui_state, "ev_source", None), "last_good", None)
  tiles_h = min(300.0, r.height * 0.36)
  if snap is not None:
    draw_battery(rl.Rectangle(r.x, r.y, r.width, r.height - tiles_h - GAP), snap, None, live=s is not None and s.available)
  else:
    D.text(tr("No battery data yet"), r.x, r.y, 44, Console.TEXT_MUTED, semi=True)

  last = session.last if session is not None else None
  tr_ = rl.Rectangle(r.x, r.y + r.height - tiles_h, r.width, tiles_h)
  cells = [rl.Rectangle(tr_.x + i * (tr_.width - 3 * GAP) / 4 + i * GAP, tr_.y, (tr_.width - 3 * GAP) / 4, tr_.height) for i in range(4)]
  if last is None:
    K.panel(tr_)
    D.text(tr("Not plugged in"), tr_.x + TILE_PAD, tr_.y + TILE_PAD, 44, semi=True)
    D.text(tr("This page opens by itself when the truck starts charging."), tr_.x + TILE_PAD, tr_.y + TILE_PAD + 68, 32,
           Console.TEXT_MUTED)
    return
  ended = last["ended"]
  v, u = fmt_duration(last["minutes"])
  tile(cells[0], tr("Last charge"), f"{last['energy_kwh']:.1f}", "kWh", tr("Ended") + " " + ended)
  tile(cells[1], tr("Took"), v, u)
  if finite(last["start_soc"]) and finite(last["end_soc"]):
    tile(cells[2], tr("Battery"), f"{last['start_soc']:.0f}–{last['end_soc']:.0f}", "%")
  else:
    tile(cells[2], tr("Battery"), "--")
  tile(cells[3], tr("Peak power"), fmt_kw(last["peak_kw"]) if finite(last["peak_kw"]) else "--", "kW")


def _state():
  return getattr(ui_state, "ev", None), getattr(ui_state, "charge_session", None)


class ChargingScreen(Widget):
  """Full-screen charging view. Any tap calls the click callback (main_layout minimizes it)."""

  def _render(self, rect: rl.Rectangle):
    rl.draw_rectangle_rec(rect, Console.BG_PAGE)
    s, session = _state()
    if s is None or session is None:
      return
    inner = rl.Rectangle(rect.x + MARGIN, rect.y + 56, rect.width - 2 * MARGIN, rect.height - 56 - MARGIN)
    draw_header(rl.Rectangle(inner.x, inner.y, inner.width, 120), s, session, tr("Minimize"))
    body = rl.Rectangle(inner.x, inner.y + 160, inner.width, inner.height - 160)
    draw_body(body, s, session)


class ChargingPage(Widget):
  """Energy > Charging inside the shell."""

  def __init__(self):
    super().__init__()
    self.on_open_full: Callable[[], None] | None = None

  @staticmethod
  def plugged() -> bool:
    session = getattr(ui_state, "charge_session", None)
    return session is not None and session.active

  def subtitle(self) -> str:
    s, session = _state()
    if s is None or not self.plugged():
      return tr("Energy") + " | " + tr("Not plugged in")
    sub, _ = status_line(s)
    return tr("Energy") + " | " + charge_title(s) + (" · " + sub if sub else "")

  def sub_dot(self):
    s, _ = _state()
    if s is None or not self.plugged():
      return Console.TEXT_GHOST
    return status_dot(s)

  def action(self) -> str | None:
    return tr("Full screen") if self.plugged() else None

  def _render(self, rect: rl.Rectangle):
    s, session = _state()
    if s is not None and session is not None and session.active:
      draw_body(rect, s, session)
    else:
      draw_idle(rect, s, session)

  def _handle_mouse_release(self, mouse_pos) -> bool:
    # Tapping the page while plugged in reopens the full screen, like Home's Charging card
    if self.plugged() and self.on_open_full is not None:
      self.on_open_full()
      return True
    return False
