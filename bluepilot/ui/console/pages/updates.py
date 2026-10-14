"""
Console Updates page (System > Updates): Citadel Auto OS updates from Lucas's own repository, with the old
Software page merged in.

  Update        status (up to date / available / ready / checking), installed and new version, last
                check, the one next step (Check, Download, Install and restart), release notes
  Source        repository, branch (opens a radio list of the branches the updater found)
  This software version, branch, commit and date, what it is built on
  Advanced      automatic updates (DisableUpdates, offroad only, reboots to apply), uninstall

The updater (system/updated/updated.py, Custom block) points git's origin at BPUpdateRepo
(default github.com/ryniouz/bluepilot-custom) before every check and download, and follows BPUpdateBranch.
This page drives it the way the stock Software panel does: SIGUSR1 to check, SIGHUP to download,
DoReboot to install, DoUninstall to uninstall.
"""

from __future__ import annotations

import os
import re
import time

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.console.form import Action, Choice, FormPage, Info, Nav, Note, Section, Toggle
from bluepilot.ui.lib.theme import Console

DEFAULT_REPO = "https://github.com/ryniouz/bluepilot-custom.git"


def _text(v) -> str:
  if isinstance(v, bytes):
    v = v.decode(errors="ignore")
  return str(v or "").strip("\x00").strip()


def repo_name(url: str) -> str:
  url = url.removesuffix(".git").rstrip("/")
  parts = url.split("/")
  return "/".join(parts[-2:]) if len(parts) >= 2 else url


def commit_date(raw: str) -> str:
  """GitCommitDate is git's "'<unix time> <iso date>'"; show the day."""
  parts = raw.strip("'\" ").split()
  if parts and parts[0].isdigit():
    return time.strftime("%Y-%m-%d", time.localtime(int(parts[0])))
  return parts[0][:10] if parts else ""


def plain_notes(html: str) -> str:
  """Release notes arrive as simple HTML; the page shows them as one paragraph."""
  text = re.sub(r"<[^>]+>", " ", html)
  return re.sub(r"\s+", " ", text).strip()


class UpdatesPage(FormPage):
  def __init__(self):
    super().__init__()
    self._picking = False

  def show_event(self):
    super().show_event()
    self._picking = False

  def _get(self, key: str) -> str:
    return _text(self.p.get(key, ""))

  def branch(self) -> str:
    return self._get("BPUpdateBranch") or self._get("UpdaterTargetBranch") or self._get("GitBranch")

  def branches(self) -> list[str]:
    raw = self._get("UpdaterAvailableBranches")
    found = [b for b in (x.strip() for x in raw.split(",")) if b] if raw else []
    current = self._get("GitBranch")
    if current in found:  # the installed branch first, the rest as the updater lists them
      found.remove(current)
      found.insert(0, current)
    return found

  # -- sections -------------------------------------------------------------------------------

  def sections(self) -> list[Section]:
    if self._picking:
      return self._picker()
    return [self._update(), self._source(), self._software(), self._advanced()]

  def _update(self) -> Section:
    available = self.p.bool("UpdateAvailable")
    fetch_ready = self.p.bool("UpdaterFetchAvailable")
    state = self._get("UpdaterState")
    busy = state not in ("", "idle")
    if available:
      status, color = tr("Ready to install"), Console.ACCENT
    elif fetch_ready:
      status, color = tr("Update available"), Console.ACCENT
    elif busy:
      status, color = state[:1].upper() + state[1:].rstrip("."), Console.ACCENT
    elif self._get("UpdaterFetchFailed") or "failed" in state:
      status, color = tr("Couldn't check"), Console.WARNING
    else:
      status, color = tr("Up to date"), Console.SUCCESS

    current = self._get("UpdaterCurrentDescription") or self._get("Version")
    new = self._get("UpdaterNewDescription")
    rows: list = [Info(tr("Status"), status, dot=color),
                  Info(tr("Installed"), current.split(" / ")[0] if current else "–")]
    if new and (available or fetch_ready):
      rows.append(Info(tr("New version"), new.split(" / ")[0]))
    last = self.p.get("LastUpdateTime", None)
    if last is not None and hasattr(last, "strftime"):
      rows.append(Info(tr("Last checked"), last.strftime("%b %-d, %-I:%M %p")))

    if available:
      parked = not ui_state.started
      rows.append(Action(tr("Install"), tr("Restarts the comma") if parked else tr("Once the truck is parked"),
                         tr("Install and restart"), self._install, primary=True, enabled=parked))
      notes = plain_notes(self._get("UpdaterNewReleaseNotes"))
      if notes:
        rows.append(Note(notes, lines=4))
    elif fetch_ready:
      rows.append(Action(tr("Download"), tr("Downloads in the background"), tr("Download"), self._download, primary=True))
    else:
      rows.append(Action(tr("Check for updates"), tr("Only while parked") if ui_state.started else tr("Takes a few seconds"),
                         tr("Checking…") if busy else tr("Check"), self._check, enabled=not busy))
    return Section(tr("Software update"), "download", rows)

  def _source(self) -> Section:
    repo = self._get("BPUpdateRepo") or DEFAULT_REPO
    return Section(tr("Source"), "code", [
      Info(tr("Repository"), repo_name(repo)),
      Nav(tr("Branch"), tr("Where updates come from"), self._open_picker, value=self.branch() or "–"),
    ], note=tr("Updates come only from this repository, never from upstream BluePilot or comma."))

  def _software(self) -> Section:
    commit = self._get("GitCommit")[:7]
    date = commit_date(self._get("GitCommitDate"))
    version = self._get("Version")
    rows = [Info(tr("Version"), version)] if version else []
    rows += [Info(tr("Branch"), self._get("GitBranch") or "–"),
             Info(tr("Commit"), (commit + (f"  ·  {date}" if date else "")) if commit else "–")]
    return Section(tr("This software"), "list", rows,
                   note=tr("Citadel Auto OS, built on BluePilot, sunnypilot and openpilot."))

  def _advanced(self) -> Section:
    rows: list = []
    offroad = ui_state.is_offroad()
    if self.p.has("DisableUpdates"):
      auto = not self.p.bool("DisableUpdates")
      rows.append(Toggle(tr("Automatic updates"),
                         (tr("Checks and downloads by itself") if auto else tr("Only when you check here"))
                         if offroad else tr("Change it while parked"),
                         auto, self._ask_auto_updates, enabled=offroad))
    rows.append(Action(tr("Uninstall"), tr("Removes this software from the comma"), tr("Uninstall"),
                       self._ask_uninstall, danger=True, enabled=offroad))
    return Section(tr("Advanced"), "sliders", rows)

  def _picker(self) -> list[Section]:
    branches = self.branches()
    current = self.branch()
    rows: list = [Nav(tr("Back"), "", self._close_picker, back=True)]
    if branches:
      sel = branches.index(current) if current in branches else -1
      rows.append(Choice(tr("Branch"), branches, sel, lambda i: self._pick(branches[i]), radio=True))
    else:
      rows.append(Note(tr("The branch list fills in after the first check for updates.")))
    return [Section(tr("Pick a branch"), "code", rows, wide=True)]

  # -- actions --------------------------------------------------------------------------------

  def _check(self):
    os.system("pkill -SIGUSR1 -f system.updated.updated")

  def _download(self):
    os.system("pkill -SIGHUP -f system.updated.updated")

  def _install(self):
    if not ui_state.started:
      self.p.put("DoReboot", True)

  def _open_picker(self):
    self._picking = True
    self._offset = 0.0

  def _close_picker(self):
    self._picking = False
    self._offset = 0.0

  def _pick(self, name: str):
    self.p.put("BPUpdateBranch", name)
    self.p.put("UpdaterTargetBranch", name)
    self._close_picker()
    self._check()

  def _ask_auto_updates(self):
    turn_off = not self.p.bool("DisableUpdates")

    def apply():
      self.p.put("DisableUpdates", turn_off)
      self.p.put("DoReboot", True)
    self.confirm(tr("Turn off automatic updates?") if turn_off else tr("Turn on automatic updates?"),
                 tr("The comma restarts to apply this."), tr("Restart"), apply)

  def _ask_uninstall(self):
    self.confirm(tr("Uninstall Citadel Auto OS?"),
                 tr("The comma removes this software and reinstalls from scratch on the next start."),
                 tr("Uninstall"), lambda: self.p.put("DoUninstall", True), danger=True)
