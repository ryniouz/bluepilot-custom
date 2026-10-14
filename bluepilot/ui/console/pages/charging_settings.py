"""
Console Charging settings page (Energy > Charging settings).

  Charging screen   show it while the truck charges
  Someone inside /  how long it stays at full brightness (AC and DC apart), then dim or off; the minimal
  nobody inside     dark screen with nobody inside. Someone is inside when the truck is on or in accessory
                    mode (bluepilot/ui/lib/charge_screen.py has the rules)
  The comma         what it does while parked and charging; the settings themselves live once, on
                    System > Truck (Charge and 12 V tabs), so this card summarises and links there

Same params as the old BluePilot rows (BPChargingScreen, BPChargeSleepMin) plus the BPChargeOn* / Off* ones.
"""

from __future__ import annotations

from collections.abc import Callable

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.console.form import Choice, FormPage, Info, Nav, Note, Section, Stepper, Toggle
from bluepilot.ui.lib.charge_screen import ChargePolicy, fmt_minutes, step_minutes



def fmt_min(m: int) -> str:
  return f"{m} min" if m < 60 else f"{m / 60:g} h"


class ChargingSettingsPage(FormPage):
  def __init__(self):
    super().__init__()
    self.on_open_power: Callable[[], None] | None = None

  def set_screen(self, on: bool):
    self.p.put("BPChargingScreen", on)
    ui_state.charging_screen_enabled = on

  def _set(self, key: str, value):
    """Write, then refresh the policy the display follows, so a change applies now, not at the next param poll."""
    self.p.put(key, value)
    ui_state.charge_policy = ChargePolicy.from_params(self.p._params)

  def _window(self, key: str, title: str, sub: str, default: int) -> Stepper | None:
    if not self.p.has(key):
      return None
    m = self.p.int(key, default)
    return Stepper(title, tr(fmt_minutes(m)), lambda: self._set(key, step_minutes(m, -1)),
                   lambda: self._set(key, step_minutes(m, 1)), sub, adv=True)

  def _then(self, key: str, default: int) -> Choice | None:
    if not self.p.has(key):
      return None
    return Choice(tr("Then"), [tr("Dim"), tr("Turn off")], max(0, min(1, self.p.int(key, default))),
                  lambda i: self._set(key, int(i)), adv=True)

  def _after_note(self) -> str:
    pol = ChargePolicy.from_params(self.p._params)
    ac, dc = pol.minutes(False, False), pol.minutes(False, True)
    if ac <= 0 and dc <= 0:
      return tr("It stays at full brightness.")
    then = tr("dims") if pol.off_then == "dim" else tr("turns off")
    return tr("It {} after {} on AC, {} on DC.").format(then, tr(fmt_minutes(ac)).lower(), tr(fmt_minutes(dc)).lower())

  def sections(self) -> list[Section]:
    p = self.p
    out = []
    keep = lambda *r: [x for x in r if x is not None]  # noqa: E731
    on = p.bool("BPChargingScreen", True) if p.has("BPChargingScreen") else True
    if p.has("BPChargingScreen"):
      out.append(Section(tr("Charging screen"), "plug", [
        Toggle(tr("Show while charging"), tr("Opens when you plug in and stop"), on, lambda: self.set_screen(not on)),
        Note(tr("A tap minimizes it. Home's Charging card brings it back.")),
      ]))
    out.append(Section(tr("Someone inside"), "car", [
      Info(tr("Charging screen"), tr("Full, never dims")),
    ], note=tr("Truck on or in accessory mode.")))
    out.append(Section(tr("Nobody inside"), "battery", keep(
      Toggle(tr("Minimal dark screen"), tr("Charge and power only"), p.bool("BPChargeMinimal", True),
             lambda: self._set("BPChargeMinimal", not p.bool("BPChargeMinimal", True))) if p.has("BPChargeMinimal") else None,
      self._window("BPChargeSleepMin", tr("AC charging"), tr("From plug-in or a tap"), 30),
      self._window("BPChargeOffDcMin", tr("DC fast charging"), tr("From plug-in or a tap"), 60),
      self._then("BPChargeOffThen", 0),
    ), note=tr("Truck off. The minimal screen is grey on black and moves a little every minute, so nothing burns in. "
               + self._after_note())))

    rows = []
    if p.has("BPChargeKeepAwake"):
      rows.append(Info(tr("Stays on while charging"), tr("Yes") if p.bool("BPChargeKeepAwake", True) else tr("No")))
    if p.has("BPChargeSleepDelayMin"):
      d = p.int("BPChargeSleepDelayMin", 30)
      rows.append(Info(tr("Sleeps after charging"), tr("Default timer") if d == 0 else fmt_min(d)))
    if p.has("BPLvSaver"):
      rows.append(Info(tr("12 V power saver"), tr("On") if p.bool("BPLvSaver") else tr("Off")))
    rows.append(Nav(tr("Power while parked"), tr("System > Truck"), lambda: self.on_open_power and self.on_open_power()))
    out.append(Section(tr("The comma while charging"), "cpu", rows))
    return out
