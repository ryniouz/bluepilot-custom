"""
Console Charging settings page (Energy > Charging settings).

  Charging screen   show it while the truck charges; how long the screen stays on with the truck off
  The comma         what it does while parked and charging; the settings themselves live once, on
                    System > Truck (Charge and 12 V tabs), so this card summarises and links there

Same params as the old BluePilot rows: BPChargingScreen, BPChargeSleepMin.
"""

from __future__ import annotations

from collections.abc import Callable

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.console.form import Choice, FormPage, Info, Nav, Note, Section, Toggle

SLEEP_STEPS = [10, 30, 60, 0]           # BPChargeSleepMin; 0 = never
SLEEP_LABELS = ["10 min", "30 min", "1 h", "Never"]


def fmt_min(m: int) -> str:
  return f"{m} min" if m < 60 else f"{m / 60:g} h"


class ChargingSettingsPage(FormPage):
  def __init__(self):
    super().__init__()
    self.on_open_power: Callable[[], None] | None = None

  def set_screen(self, on: bool):
    self.p.put("BPChargingScreen", on)
    ui_state.charging_screen_enabled = on

  def set_sleep(self, i: int):
    self.p.put("BPChargeSleepMin", SLEEP_STEPS[i])
    ui_state.charge_sleep_min = SLEEP_STEPS[i]

  def sections(self) -> list[Section]:
    p = self.p
    out = []
    if p.has("BPChargingScreen"):
      on = p.bool("BPChargingScreen", True)
      rows: list = [Toggle(tr("Show while charging"), tr("Opens when you plug in"), on, lambda: self.set_screen(not on))]
      if p.has("BPChargeSleepMin"):
        m = p.int("BPChargeSleepMin", 30)
        rows.append(Choice(tr("Screen stays on"), [tr(s) for s in SLEEP_LABELS], SLEEP_STEPS.index(m) if m in SLEEP_STEPS else 1,
                           self.set_sleep, enabled=on))
      rows.append(Note(tr("With the truck off, the screen turns off after this and wakes when you tap it. " +
                          "With the truck on it stays up until you minimize it.")))
      out.append(Section(tr("Charging screen"), "plug", rows))

    rows = []
    if p.has("BPChargeKeepAwake"):
      rows.append(Info(tr("Stays on while charging"), tr("Yes") if p.bool("BPChargeKeepAwake", True) else tr("No")))
    if p.has("BPChargeSleepDelayMin"):
      d = p.int("BPChargeSleepDelayMin", 30)
      rows.append(Info(tr("Powers down after the charge"), tr("Default timer") if d == 0 else fmt_min(d)))
    if p.has("BPLvSaver"):
      rows.append(Info(tr("12 V power saver"), tr("On") if p.bool("BPLvSaver") else tr("Off")))
    if not rows:
      rows.append(Note(tr("These settings come with the Lightning control update.")))
    rows.append(Nav(tr("Power while parked"), tr("System > Truck"), lambda: self.on_open_power and self.on_open_power()))
    out.append(Section(tr("The comma while charging"), "battery", rows))
    return out
