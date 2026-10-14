"""
Console Developer page (System > Developer), in place of openpilot's DeveloperLayout and sunnypilot's
DeveloperLayoutSP.

  Access     ADB, SSH, SSH keys from a GitHub username
  Testing    joystick, longitudinal and lateral maneuver modes (one at a time), alpha longitudinal; not on release
  Screen     UI debug overlay (touches, FPS, mouse coordinates)
  Advanced   show advanced controls, copyparty, GitHub runner, quickboot
  Error log  the last crash log, shown in place, with Delete

The param writes and gating are the legacy panels': ADB, joystick and maneuver mode only while parked,
maneuver mode only with openpilot longitudinal, alpha longitudinal only when the car offers it (and it
restarts the drive), quickboot only with automatic updates off.
"""

from __future__ import annotations

import datetime
import os
import threading
from pathlib import Path

import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.hardware import PC
from openpilot.system.hardware.hw import Paths
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.keyboard import Keyboard
from bluepilot.ui.console import draw as D
from bluepilot.ui.console.form import Action, Custom, FormPage, Info, Nav, Note, Section, Toggle
from bluepilot.ui.lib.theme import Console

PREBUILT_PATH = os.path.join(Paths.comma_home(), "prebuilt") if PC else "/data/openpilot/prebuilt"
ERROR_LOG = os.path.join(Paths.crash_log_root(), "error.log")
LOG_TAIL = 6000  # characters of the error log shown
LOG_LINES = 80
LOG_LINE_H = 34


class DeveloperPage(FormPage):
  def __init__(self):
    super().__init__()
    self._log = False
    self._log_text = ""
    self._log_w = 1800.0
    self._ssh_busy = False
    self._ssh_error = ""
    self._keyboard: Keyboard | None = None
    self.set_ui_debug(self.p.bool("ShowDebugInfo"))

  def show_event(self):
    super().show_event()
    self._log = False
    self._sync_quickboot()

  # -- helpers --------------------------------------------------------------------------------

  def _release(self) -> bool:
    return self.p.bool("IsReleaseBranch")

  def _release_sp(self) -> bool:
    return self._release() or self.p.bool("IsReleaseSpBranch")

  def _dev_branch(self) -> bool:
    return self.p.bool("IsTestedBranch") or self.p.bool("IsDevelopmentBranch")

  def _sync_quickboot(self):
    exists = os.path.exists(PREBUILT_PATH)
    if self.p.has("QuickBootToggle") and exists != self.p.bool("QuickBootToggle"):
      self.p.put("QuickBootToggle", exists)

  @staticmethod
  def set_ui_debug(on: bool):
    gui_app.set_show_touches(on)
    gui_app.set_show_fps(on)
    gui_app.set_show_mouse_coords(on)

  # -- sections -------------------------------------------------------------------------------

  def sections(self) -> list[Section]:
    if self._log:
      return [self._log_view()]
    out = [self._access()]
    if not self._release():
      out.append(self._testing())
    out.append(self._screen())
    out.append(self._advanced())
    return out

  def _access(self) -> Section:
    offroad = ui_state.is_offroad()
    user = str(self.p.get("GithubUsername", "") or "")
    has_keys = bool(self.p.get("GithubSshKeys", ""))
    if self._ssh_busy:
      keys = Action(tr("SSH keys"), tr("Fetching keys from GitHub…"), tr("Loading…"), lambda: None, enabled=False)
    elif has_keys:
      keys = Action(tr("SSH keys"), tr("Keys from github.com/{}").format(user) if user else tr("Keys from GitHub"),
                    tr("Remove"), self._remove_keys)
    else:
      keys = Action(tr("SSH keys"), self._ssh_error or tr("Adds the public keys of a GitHub account"), tr("Add"), self._add_keys)
    rows: list = [
      Toggle(tr("ADB"), tr("Connect over USB or the network") if offroad else tr("Change it while parked"),
             self.p.bool("AdbEnabled"), self.p.flip("AdbEnabled"), enabled=offroad),
      Toggle(tr("SSH"), tr("Remote shell on the local network"), self.p.bool("SshEnabled"), self.p.flip("SshEnabled")),
      keys,
    ]
    return Section(tr("Access"), "code", rows,
                   note=tr("SSH keys give access to every key on that GitHub account. Only use your own username."))

  def _testing(self) -> Section:
    offroad = ui_state.is_offroad()
    cp = ui_state.CP
    rows: list = [
      Toggle(tr("Joystick mode"), tr("Drive with a joystick for testing") if offroad else tr("Change it while parked"),
             self.p.bool("JoystickDebugMode"), self._only("JoystickDebugMode"), enabled=offroad),
    ]
    long_ok = cp is not None and ui_state.has_longitudinal_control and offroad
    rows.append(Toggle(tr("Longitudinal maneuvers"),
                       tr("Runs scripted speed tests") if long_ok else
                       (tr("Change it while parked") if not offroad else tr("Needs openpilot longitudinal control")),
                       self.p.bool("LongitudinalManeuverMode"), self._only("LongitudinalManeuverMode"), enabled=long_ok))
    if self.p.has("LateralManeuverMode"):
      rows.append(Toggle(tr("Lateral maneuvers"), tr("Runs scripted steering tests; turns off Experimental mode"),
                         self.p.bool("LateralManeuverMode"), self._only("LateralManeuverMode"), enabled=cp is not None))
    if cp is not None:
      if cp.alphaLongitudinalAvailable:
        rows.append(Toggle(tr("Alpha longitudinal"), tr("openpilot controls speed; may turn off AEB"),
                           self.p.bool("AlphaLongitudinalEnabled"), self._ask_alpha, enabled=not ui_state.engaged))
      elif self.p.has("AlphaLongitudinalEnabled") and self.p.bool("AlphaLongitudinalEnabled"):
        ui_state.params.remove("AlphaLongitudinalEnabled")
        self.p.invalidate()
    return Section(tr("Testing"), "sliders", rows, note=tr("Only one test mode can be on at a time."))

  def _screen(self) -> Section:
    return Section(tr("Screen"), "eye", [
      Toggle(tr("UI debug"), tr("Touches, FPS and pointer position"), self.p.bool("ShowDebugInfo"), self._ui_debug),
    ] + ([Toggle(tr("UI debug log"), tr("Logs screen changes for bug reports"), self.p.bool("BPUIDebugLog"),
                 self.p.flip("BPUIDebugLog"))] if self.p.has("BPUIDebugLog") else []))

  def _advanced(self) -> Section:
    show = self.p.bool("ShowAdvancedControls")
    rows: list = []
    if self.p.has("ShowAdvancedControls"):
      rows.append(Toggle(tr("Show advanced controls"), tr("Shows or hides them only"),
                         show, self.p.flip("ShowAdvancedControls")))
    if show and self.p.has("EnableCopyparty"):
      rows.append(Toggle(tr("copyparty"), tr("File server for drives and logs"),
                         self.p.bool("EnableCopyparty"), self.p.flip("EnableCopyparty")))
    if show and not self._release_sp() and self.p.has("EnableGithubRunner"):
      rows.append(Toggle(tr("GitHub runner"), tr("Runs CI jobs on this comma"),
                         self.p.bool("EnableGithubRunner"), self.p.flip("EnableGithubRunner")))
    if show and not (self._release_sp() or self._dev_branch()) and self.p.has("QuickBootToggle"):
      updates_off = self.p.bool("DisableUpdates")
      rows.append(Toggle(tr("Quickboot"), tr("Skips the build at start; off to rebuild edited C++") if updates_off
                         else tr("Turn off automatic updates first (System > Updates)"),
                         self.p.bool("QuickBootToggle"), self._quickboot, enabled=updates_off))
    if not self._release_sp():
      has_log = os.path.exists(ERROR_LOG)
      rows.append(Nav(tr("Error log"), tr("The last crash") if has_log else tr("No crashes logged"), self._open_log,
                      value=self._log_date() if has_log else ""))
    return Section(tr("Advanced"), "list", rows)

  def _log_date(self) -> str:
    try:
      return datetime.datetime.fromtimestamp(os.path.getmtime(ERROR_LOG)).strftime("%b %-d, %H:%M")
    except OSError:
      return ""

  def _log_view(self) -> Section:
    rows: list = [Nav(tr("Back"), "", self._close_log, back=True)]
    if os.path.exists(ERROR_LOG):
      rows.append(Info(tr("Logged"), self._log_date(), dot=Console.WARNING))
      rows.append(self._log_body() if self._log_text else Note(tr("The log is empty.")))
      rows.append(Action(tr("Delete the log"), tr("Clears it until the next crash"), tr("Delete"), self._ask_delete_log, danger=True))
    else:
      rows.append(Note(tr("No crashes logged.")))
    return Section(tr("Error log"), "warning", rows, wide=True)

  def _log_body(self) -> Custom:
    """The log as written (line breaks kept), each line wrapped to the card."""
    lines: list[str] = []
    for raw in self._log_text.splitlines()[-LOG_LINES:]:
      lines += D.wrap(raw.replace("\t", "  "), D.CAPTION, self._log_w, 4) if raw.strip() else [""]

    def draw(r: rl.Rectangle):
      self._log_w = r.width
      for i, ln in enumerate(lines):
        D.text(ln, r.x, r.y + 8 + i * LOG_LINE_H, D.CAPTION, Console.TEXT_SECONDARY)
    return Custom(16 + len(lines) * LOG_LINE_H, draw)

  # -- actions --------------------------------------------------------------------------------

  MODES = ("JoystickDebugMode", "LongitudinalManeuverMode", "LateralManeuverMode")

  def _only(self, key: str):
    """Joystick, longitudinal and lateral maneuver modes are one-at-a-time; lateral turns off Experimental mode."""
    def flip():
      on = not self.p.bool(key)
      self.p.put(key, on)
      for other in self.MODES:
        if other != key and self.p.has(other):
          self.p.put(other, False)
      if key == "LateralManeuverMode" and on:
        self.p.put("ExperimentalMode", False)
    return flip

  def _ask_alpha(self):
    if self.p.bool("AlphaLongitudinalEnabled"):
      self.p.put("AlphaLongitudinalEnabled", False)
      self.p.put("OnroadCycleRequested", True)
      return

    def on():
      self.p.put("AlphaLongitudinalEnabled", True)
      self.p.put("OnroadCycleRequested", True)
    self.confirm(tr("Turn on alpha longitudinal?"),
                 tr("Longitudinal control is in alpha for this car and may turn off Automatic Emergency Braking. " +
                    "Experimental mode is recommended. The drive restarts if the truck is on."),
                 tr("Turn on"), on, danger=True)

  def _ui_debug(self):
    on = not self.p.bool("ShowDebugInfo")
    self.p.put("ShowDebugInfo", on)
    self.set_ui_debug(on)

  def _quickboot(self):
    on = not self.p.bool("QuickBootToggle")
    try:
      if on:
        Path(PREBUILT_PATH).touch(exist_ok=True)
      elif os.path.exists(PREBUILT_PATH):
        os.remove(PREBUILT_PATH)
    except OSError:
      return
    self.p.put("QuickBootToggle", on)

  def _add_keys(self):
    if self._keyboard is None:
      self._keyboard = Keyboard(min_text_size=1)
    kb = self._keyboard
    kb.reset()
    kb.set_title(tr("Enter your GitHub username"))

    def done(result: DialogResult):
      name = kb.text.strip()
      if result == DialogResult.CONFIRM and name:
        self._ssh_busy, self._ssh_error = True, ""
        threading.Thread(target=self._fetch_keys, args=(name,), daemon=True).start()
    kb.set_callback(done)
    gui_app.push_widget(kb)

  def _fetch_keys(self, name: str):
    import requests
    try:
      r = requests.get(f"https://github.com/{name}.keys", timeout=15)
      r.raise_for_status()
      keys = r.text.strip()
      if not keys:
        raise ValueError
      self.p.put("GithubUsername", name)
      self.p.put("GithubSshKeys", keys)
    except requests.exceptions.Timeout:
      self._ssh_error = tr("GitHub didn't answer. Try again.")
    except Exception:
      self._ssh_error = tr("No SSH keys found for '{}'").format(name)
    self._ssh_busy = False

  def _remove_keys(self):
    for k in ("GithubUsername", "GithubSshKeys"):
      ui_state.params.remove(k)
    self.p.invalidate()

  def _open_log(self):
    try:
      with open(ERROR_LOG, errors="replace") as f:
        text = f.read()
    except OSError:
      text = ""
    self._log_text = ("…" + text[-LOG_TAIL:]) if len(text) > LOG_TAIL else text
    self._log = True
    self._offset = 0.0

  def _close_log(self):
    self._log = False
    self._offset = 0.0

  def _ask_delete_log(self):
    def delete():
      try:
        os.remove(ERROR_LOG)
      except OSError:
        pass
      self._close_log()
    self.confirm(tr("Delete the error log?"), tr("It fills again on the next crash."), tr("Delete"), delete, danger=True)
