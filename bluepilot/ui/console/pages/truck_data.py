"""
Console Truck data page (Energy > Truck data): what the OBD adapter reads that the comma's own CAN
connection can't (bp_obdd, PR #2; values by short name from selfdrive/car/obd/catalog.py).

Two modes:
  connected      cards for the HV battery (health), charger, 12 V battery and tires, plus anything else a
                 user catalog adds; a value missing from the latest answers is simply left out
  not connected  one calm card: what an adapter adds, the adapter's state in a word, and a button to the
                 OBD setup. Nothing half-empty, no dashes, no red.
"""

from __future__ import annotations

from collections.abc import Callable

import pyray as rl

from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.console.pages.cards import GAP, CardPage
from bluepilot.ui.lib.obd_link import ObdValue, fmt_value, live_values, status
from bluepilot.ui.lib.theme import Console

ROW = 64

BATTERY = [("HvbSoh", "Health"), ("HvbCapAh", "Capacity"), ("HvbSocD", "Charge"), ("HvbEte", "Energy left"),
           ("HvbT", "Temperature"), ("HvbCit", "Coolant in"), ("HvbCHP", "Coolant heater"), ("HvbAvgModV", "Modules avg"),
           ("HvbMinModV", "Modules low"), ("HvbAge", "Age"), ("HvbSoc", "Charge (cells)")]
CHARGER = [("HvbV", "Pack"), ("HvbA", "Current"), ("ChgOV", "Output"), ("ChgInPwr", "Input"), ("ChgMaxP", "Maximum"),
           ("ChgACT", "Port temp"), ("ACInV", "AC volts"), ("ACInA", "AC amps"), ("ACInF", "AC Hz"),
           ("PilotDC", "Pilot duty")]
LOW_VOLT = [("LvV", "Voltage"), ("LvSoc", "Charge")]
TIRES = [("TireLF", "Front left"), ("TireRF", "Front right"), ("TireLR", "Rear left"), ("TireRR", "Rear right")]
# status codes whose meanings aren't mapped yet stay off the page rather than show a bare number
CODES = {"ChgSt", "Evse", "HvbCHOp", "DCChgSt", "ProxSt"}
KNOWN = {k for group in (BATTERY, CHARGER, LOW_VOLT, TIRES) for k, _ in group} | CODES


def fmt(short: str, v: ObdValue) -> str:
  if short == "HvbAge":
    months = int(round(v.value))
    y, m = divmod(months, 12)
    return f"{y} yr {m} mo" if y else f"{m} mo"
  if v.unit == "V" and short in ("HvbAvgModV", "HvbMinModV"):
    return f"{v.value:.3f} V"
  return fmt_value(v)


def spread_mv(vals: dict[str, ObdValue]) -> float | None:
  a, m = vals.get("HvbAvgModV"), vals.get("HvbMinModV")
  return (a.value - m.value) * 1000 if a is not None and m is not None else None


class TruckDataPage(CardPage):
  def __init__(self):
    super().__init__()
    self.on_open_setup: Callable[[], None] | None = None

  def subtitle(self) -> str:
    return tr("Energy") + " | " + tr("OBD") + " " + tr(status()[1]).lower()

  def sub_dot(self):
    return {"connected": Console.SUCCESS, "waiting": Console.ACCENT}.get(status()[0], Console.TEXT_GHOST)

  def _render(self, rect: rl.Rectangle):
    self._hits = []
    vals = live_values()
    if not vals:
      self._not_connected(rect)
      return
    c1, c2, c3 = K.split_cols(rect, [1.2, 1.0, 1.0])
    c1.width -= GAP * 2 / 3
    c2.x += GAP / 3
    c2.width -= GAP * 2 / 3
    c3.x += GAP * 2 / 3
    c3.width -= GAP * 2 / 3

    self._group(c1, tr("HV battery"), "battery", BATTERY, vals, extra=self._spread_row(vals))
    self._stack(c2, [(tr("Charger"), "charging", CHARGER)], vals)
    others = [(v.name, v.label or v.name) for k, v in sorted(vals.items()) if k not in KNOWN]
    low_volt = tr("12 V battery") if D.text_w(tr("12 V battery"), D.H2, semi=True) + 64 + 2 * D.CARD_PAD <= c3.width else tr("12 V")
    col3 = [(tr("Tires"), "gauge", TIRES), (low_volt, "bolt", LOW_VOLT)] + ([(tr("Other"), "list", others)] if others else [])
    self._stack(c3, col3, vals)

  # -- connected ------------------------------------------------------------------------------

  def _height(self, rows: int) -> float:
    return 76 + rows * ROW + 2 * D.CARD_PAD

  def _stack(self, r: rl.Rectangle, groups, vals):
    y = r.y
    shown = [(t, i, [(k, lbl) for k, lbl in g if k in vals]) for t, i, g in groups]
    shown = [s for s in shown if s[2]]
    for n, (title, icon, rows) in enumerate(shown):
      last = n == len(shown) - 1
      h = r.y + r.height - y if last else min(self._height(len(rows)), r.y + r.height - y)
      if h < 76 + ROW + 2 * D.CARD_PAD:
        break
      self._group(rl.Rectangle(r.x, y, r.width, h), title, icon, rows, vals)
      y += h + GAP

  def _spread_row(self, vals) -> tuple[str, str, rl.Color] | None:
    mv = spread_mv(vals)
    if mv is None:
      return None
    color = Console.SUCCESS if mv < 30 else (Console.WARNING if mv < 80 else Console.DANGER)
    return tr("Spread"), f"{mv:.0f} mV", color

  def _group(self, r: rl.Rectangle, title: str, icon: str, rows, vals, extra=None):
    y = self._title(r, title, icon)
    p = D.CARD_PAD
    x, right = r.x + p, r.x + r.width - p
    bottom = r.y + r.height - p
    items = [(tr(lbl), fmt(k, vals[k]), None) for k, lbl in rows if k in vals]
    if extra is not None:
      items.append(extra)
    for label, value, color in items:
      if y + ROW > bottom + 8:
        break
      K.hline(x, right, y)
      vw = min(D.text_w(value, D.BODY, semi=True), (right - x) * 0.6)
      D.text(D.fit(label, D.LABEL, right - x - vw - (44 if color is not None else 20)), x, y + 14, D.LABEL, Console.TEXT_MUTED)
      if color is not None:
        D.dot(right - vw - 24, y + 14 + D.BODY / 2, 8, color)
      D.text_right(D.fit(value, D.BODY, (right - x) * 0.6, semi=True), right, y + 10, D.BODY, semi=True)
      y += ROW

  # -- not connected --------------------------------------------------------------------------

  def _not_connected(self, rect: rl.Rectangle):
    w = min(rect.width, 1100)
    r = rl.Rectangle(rect.x + (rect.width - w) / 2, rect.y + 24, w, min(rect.height - 24, 620))
    D.card(r)
    p = D.CARD_PAD + 16
    x = r.x + p
    y = r.y + p
    D.icon("plug", x, y, 64, Console.TEXT_SECONDARY)
    D.text(D.fit(tr("More truck data with an OBD adapter"), D.H2, r.width - 2 * p - 96, semi=True), x + 96, y + 8, D.H2, semi=True)
    y += 112
    body = tr("A Wi-Fi or USB OBD adapter adds battery health (module voltages, battery age, energy left), " +
              "charger readings, the 12 V battery's charge and tire pressures. These show here once it's connected.")
    for ln in D.wrap(body, D.BODY - 2, r.width - 2 * p, 4):
      D.text(ln, x, y, D.BODY - 2, Console.TEXT_SECONDARY)
      y += 48
    y += 24
    state, text = status()
    dot = {"connected": Console.SUCCESS, "waiting": Console.ACCENT}.get(state, Console.TEXT_GHOST)
    D.dot(x + 10, y + D.LABEL / 2 + 4, 10, dot)
    D.text(tr("Adapter") + ": " + tr(text), x + 36, y, D.LABEL, Console.TEXT_MUTED, semi=True)
    label = tr("Set up adapter") if state in ("setup", "off") else tr("Adapter settings")
    bw = D.text_w(label, D.LABEL, semi=True) + 72
    b = rl.Rectangle(r.x + r.width - p - bw, r.y + r.height - p - 80, bw, 80)
    D.button(b, label, primary=state in ("setup", "off"), size=D.LABEL)
    self._hits.append((b, lambda: self.on_open_setup and self.on_open_setup()))
