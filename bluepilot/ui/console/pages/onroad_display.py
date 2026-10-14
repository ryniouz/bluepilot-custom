"""
Console Onroad display page (Screen > Onroad display): what the driving screen shows. Replaces sunnypilot's
Visuals panel (selfdrive/ui/sunnypilot/layouts/settings/visuals.py) with the same params and the same writes.

  Speed and steering   speedometer, true speed, acceleration bar, steering arc
  Around the truck     blind spot, turn signals, road name, stopped timer
  Chimes               green light, car ahead moved
  Path and details     rainbow path, lead car details, developer readouts

As in the legacy panel, lead car details need the comma's speed control: without it the row is disabled and
ChevronInfo is held at 0.
"""

from __future__ import annotations

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.console.form import Choice, FormPage, Section, Toggle

CHEVRON_LABELS = ["Off", "Gap", "Speed", "Time", "All"]  # ChevronInfo 0..4 (Gap = "Distance")
DEV_UI_LABELS = ["Off", "Bottom", "Right", "Both"]             # DevUIInfo 0..3 ("Right & Bottom")


class OnroadDisplayPage(FormPage):
  def _toggle(self, key: str, title: str, sub: str, invert: bool = False) -> Toggle | None:
    if not self.p.has(key):
      return None
    on = self.p.bool(key)
    return Toggle(title, sub, (not on) if invert else on, self.p.flip(key))

  def _choice(self, key: str, title: str, labels: list[str], enabled: bool = True, sub: str = "") -> Choice | None:
    if not self.p.has(key):
      return None
    sel = max(0, min(len(labels) - 1, self.p.int(key)))
    return Choice(title, [tr(s) for s in labels], sel, self.p.setter(key), enabled=enabled, radio=False, sub=sub)

  def sections(self) -> list[Section]:
    t = self._toggle
    long_ok = bool(getattr(ui_state, "has_longitudinal_control", False))
    if not long_ok and self.p.has("ChevronInfo") and self.p.int("ChevronInfo") != 0:
      self.p.put("ChevronInfo", 0)  # the legacy panel's rule: no speed control, no lead car details

    rows = lambda *r: [x for x in r if x is not None]  # noqa: E731
    return [
      Section(tr("Speed and steering"), "gauge", rows(
        t("HideVEgoUI", tr("Speedometer"), tr("Your speed on the driving screen"), invert=True),
        t("TrueVEgoUI", tr("True speed"), tr("From the wheel sensors")),
        t("RocketFuel", tr("Acceleration bar"), tr("Speeding up and slowing down")),
        t("TorqueBar", tr("Steering arc"), tr("How hard the comma is steering")),
      )),
      Section(tr("Around the truck"), "car", rows(
        t("BlindSpot", tr("Blind spot warnings"), tr("When a vehicle is beside you")),
        t("ShowTurnSignals", tr("Turn signals"), tr("Arrows on screen while you signal")),
        t("RoadNameToggle", tr("Road name"), tr("Needs the map for this area")),
        t("StandstillTimer", tr("Stopped timer"), tr("How long you have been stopped")),
      )),
      Section(tr("Chimes"), "bell", rows(
        t("GreenLightAlert", tr("Green light"), tr("Turns green with nothing ahead")),
        t("LeadDepartAlert", tr("Car ahead moved"), tr("When the car in front pulls away")),
      ), note=tr("Reminders only: watching the road is still up to you.")),
      Section(tr("Path and details"), "route", rows(
        t("RainbowMode", tr("Rainbow path"), tr("Colours the planned path")),
        self._choice("ChevronInfo", tr("Lead car details"), CHEVRON_LABELS, enabled=long_ok),
        self._choice("DevUIInfo", tr("Developer readouts"), DEV_UI_LABELS),
      ), note="" if long_ok else tr("Lead car details need the comma to control speed.")),
    ]
