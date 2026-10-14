"""
Console Device page (System > Device), in place of openpilot's DeviceLayout and sunnypilot's DeviceLayoutSP.

  This comma    model, serial, dongle ID, pairing with comma connect (only while unpaired)
  Power         parked mode (OffroadMode), what it does after waking (DeviceBootMode), power off after
                parking (MaxTimeOffroad), restart, power off
  Sound, camera quiet mode (QuietMode), driver camera preview, language (a radio list)
  Help          training guide, regulatory
  Reset         every setting back to default (two confirmations, then a restart)

The param writes and checks are the legacy panels': nothing that restarts or powers off runs while engaged,
power off only parked. Calibration has its own page (System > Calibration).
"""

from __future__ import annotations

import os

from openpilot.common.basedir import BASEDIR
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.hardware import HARDWARE
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import multilang, tr
from bluepilot.ui.console.form import Action, Choice, FormPage, Info, Nav, Section, Stepper, Toggle

OFFROAD_MIN = [0, 5, 10, 15, 30, 60, 120, 180, 300, 600, 1440, 1800]  # sunnypilot's MaxTimeOffroad choices, minutes


def offroad_label(m: int) -> str:
  if m == 0:
    return tr("Never")
  return f"{m} min" if m < 60 else f"{m // 60} h"


class DevicePage(FormPage):
  def __init__(self):
    super().__init__()
    self._languages = False
    self._dialog = None

  def show_event(self):
    super().show_event()
    self._languages = False

  def sections(self) -> list[Section]:
    if self._languages:
      return [self._language_list()]
    return [self._this_comma(), self._power(), self._sound_camera(), self._help(), self._reset()]

  def _this_comma(self) -> Section:
    rows: list = [Info(tr("Device"), "comma 3X"),
                  Info(tr("Serial"), self.p.get("HardwareSerial", "") or tr("Not available")),
                  Info(tr("Dongle ID"), self.p.get("DongleId", "") or tr("Not available"))]
    try:
      paired = ui_state.prime_state.is_paired()
    except Exception:
      paired = True
    if not paired:
      rows.append(Action(tr("comma connect"), tr("Pair to see drives in the comma app"), tr("Pair"), self._pair, primary=True))
    return Section(tr("This comma"), "cpu", rows)

  def _power(self) -> Section:
    offroad = ui_state.is_offroad()
    parked_mode = self.p.bool("OffroadMode")
    rows: list = [
      Toggle(tr("Parked mode"), tr("Keeps driver assist off") if not parked_mode
             else tr("Driver assist is off"), parked_mode, self._ask_parked_mode, enabled=not ui_state.engaged),
    ]
    if self.p.has("DeviceBootMode"):
      rows.append(Choice(tr("After waking up"), [tr("Ready to drive"), tr("Parked mode")],
                         max(0, min(1, self.p.int("DeviceBootMode"))), self.p.setter("DeviceBootMode"), adv=True))
    if self.p.has("MaxTimeOffroad"):
      m = self.p.int("MaxTimeOffroad", 1800)
      i = min(range(len(OFFROAD_MIN)), key=lambda k: abs(OFFROAD_MIN[k] - m))
      rows.append(Stepper(tr("Power off after"), offroad_label(OFFROAD_MIN[i]),
                          lambda: self.p.put("MaxTimeOffroad", OFFROAD_MIN[max(0, i - 1)]),
                          lambda: self.p.put("MaxTimeOffroad", OFFROAD_MIN[min(len(OFFROAD_MIN) - 1, i + 1)]),
                          sub=tr("Parked; default 30 h")))
    rows.append(Action(tr("Restart"), tr("Takes about a minute"), tr("Restart"), self._ask_reboot, enabled=not ui_state.engaged))
    rows.append(Action(tr("Power off"), tr("Only while parked") if not offroad else tr("Wakes when the truck starts"),
                       tr("Power off"), self._ask_power_off, danger=True, enabled=offroad))
    return Section(tr("Power"), "battery", rows)

  def _sound_camera(self) -> Section:
    offroad = ui_state.is_offroad()
    rows: list = []
    if self.p.has("QuietMode"):
      quiet = self.p.bool("QuietMode")
      rows.append(Toggle(tr("Quiet mode"), tr("Only warnings make a sound"), quiet, self.p.flip("QuietMode")))
    rows.append(Action(tr("Driver camera"), tr("Check the driver monitoring view") if offroad else tr("Only while parked"),
                       tr("Preview"), self._driver_camera, enabled=offroad, adv=True))
    lang = multilang.codes.get(multilang.language, multilang.language)
    rows.append(Nav(tr("Language"), tr("For menus and alerts"), self._open_languages, value=str(lang)))
    return Section(tr("Sound, camera and language"), "eye", rows)

  def _help(self) -> Section:
    offroad = ui_state.is_offroad()
    return Section(tr("Help"), "list", [
      Action(tr("Training guide"), tr("How the driver assist works"), tr("Open"), self._training, enabled=offroad),
      Action(tr("Regulatory"), tr("Certifications and notices"), tr("Open"), self._regulatory, enabled=offroad, adv=True),
    ])

  def _reset(self) -> Section:
    return Section(tr("Reset"), "warning", [
      Action(tr("Reset all settings"), tr("Back to defaults, then restarts") if ui_state.is_offroad() else tr("Only while parked"),
             tr("Reset"), self._ask_reset, danger=True, enabled=ui_state.is_offroad()),
    ], adv=True)

  def _language_list(self) -> Section:
    names = list(multilang.languages.keys())   # display name -> code
    codes = [multilang.languages[n] for n in names]
    sel = codes.index(multilang.language) if multilang.language in codes else -1
    return Section(tr("Language"), "list", [
      Nav(tr("Back"), "", self._close_languages, back=True),
      Choice(tr("Language"), names, sel, lambda i: self._set_language(codes[i]), radio=True, unifont=True),
    ], note=tr("Some settings stay in English until they are translated."), wide=True)

  # -- actions --------------------------------------------------------------------------------

  def _push(self, widget):
    self._dialog = widget
    gui_app.push_widget(widget)

  def _pair(self):
    from openpilot.selfdrive.ui.widgets.pairing_dialog import PairingDialog
    self._push(PairingDialog())

  def _driver_camera(self):
    from openpilot.selfdrive.ui.onroad.driver_camera_dialog import DriverCameraDialog
    self._push(DriverCameraDialog())

  def _training(self):
    from openpilot.selfdrive.ui.layouts.onboarding import TrainingGuide
    self._push(TrainingGuide())

  def _regulatory(self):
    from openpilot.system.ui.widgets.html_render import HtmlModal
    self._push(HtmlModal(os.path.join(BASEDIR, "selfdrive/assets/offroad/fcc.html")))

  def _open_languages(self):
    self._languages = True
    self._offset = 0.0

  def _close_languages(self):
    self._languages = False
    self._offset = 0.0

  def _set_language(self, code: str):
    multilang.change_language(code)
    self._close_languages()

  def _ask_parked_mode(self):
    on = self.p.bool("OffroadMode")

    def apply():
      if not ui_state.engaged:
        self.p.put("OffroadMode", not on)
    self.confirm(tr("Leave parked mode?") if on else tr("Turn on parked mode?"),
                 tr("Driver assist works again on the next start.") if on else
                 tr("Driver assist stays off, even when the truck starts, until you turn this off."),
                 tr("Leave") if on else tr("Turn on"), apply)

  def _ask_reboot(self):
    self.confirm(tr("Restart the comma?"), tr("It's back in about a minute."), tr("Restart"),
                 lambda: None if ui_state.engaged else self.p.put("DoReboot", True))

  def _ask_power_off(self):
    self.confirm(tr("Power off the comma?"), tr("It wakes again when the truck starts."), tr("Power off"),
                 lambda: None if ui_state.engaged else self.p.put("DoShutdown", True), danger=True)

  def _ask_reset(self):
    def really():
      self.confirm(tr("This can't be undone"), tr("Every setting goes back to its default and the comma restarts."),
                   tr("Reset everything"), self._do_reset, danger=True)
    self.confirm(tr("Reset all settings?"),
                 tr("Driving, screen, connection and truck settings go back to their defaults. Drives are kept."),
                 tr("Continue"), really, danger=True)

  def _do_reset(self):
    params = ui_state.params
    for key in params.all_keys():
      params.remove(key)
    HARDWARE.reboot()

