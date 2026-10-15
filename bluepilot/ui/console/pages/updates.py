"""
Console Updates page (System > Updates): Citadel Auto OS updates from Lucas's own repository, upstream
BluePilot marked when it has a newer release, and the old Software page merged in.

  Citadel Auto OS   a phone-style update card: the installed version and one state at a time (up to date,
                    checking, "0.0.2 is available" with Download and install, a thick progress bar with the
                    percentage, size and speed while it downloads, Install now once it is ready). Install now
                    shows a full-screen installing view, then the comma restarts and swaps the update in.
  BluePilot         what this build is based on and the newest BluePilot release. Marked only, never installed
                    from here: a BluePilot release reaches the comma once it is built into the fork.
  Source            repository, branch (opens a radio list of the branches the updater found)
  This software     the versions this build is made of (the full list is on About)
  Update options    automatic updates (DisableUpdates, offroad only, reboots to apply), uninstall

The updater (system/updated/updated.py, Custom blocks) points git's origin at BPUpdateRepo
(default github.com/ryniouz/bluepilot-custom), follows BPUpdateBranch, writes the download progress to
BPUpdateProgress and runs bluepilot/system/update_check.py (BPForkStatus, BPUpstreamStatus) on every check.
bluepilot/ui/lib/update_flow.py turns that into one state; on a PC it plays the flow without installing.
"""

from __future__ import annotations

import datetime
import re
import time

import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.console.boot import logo_texture
from bluepilot.ui.console.form import Action, Choice, Custom, FormPage, Info, Nav, Note, Section, Toggle
from bluepilot.ui.lib.theme import Console
from bluepilot.ui.lib.update_flow import State, UpdateFlow, progress_of, state_of
from bluepilot.ui.lib.versions import versions

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
  text = re.sub(r"</(li|h\d|p)>", " · ", html)   # list items and headings stay apart
  text = re.sub(r"<[^>]+>", " ", text)
  text = re.sub(r"\s+", " ", text)
  text = re.sub(r"(\s*·\s*)+", " · ", text)
  return text.strip(" ·")


def when(ts) -> str:
  """'Oct 15, 12:20 AM' from a datetime (LastUpdateTime) or unix seconds (the check params)."""
  try:
    if isinstance(ts, (int, float)):
      if ts <= 0:
        return ""
      ts = time.localtime(ts)
      return time.strftime("%b %-d, %-I:%M %p", ts)
    if hasattr(ts, "strftime"):
      if getattr(ts, "tzinfo", None) is None:   # updated writes LastUpdateTime as naive UTC
        ts = ts.replace(tzinfo=datetime.UTC)
      return ts.astimezone().strftime("%b %-d, %-I:%M %p")
  except (ValueError, OverflowError, OSError):
    pass
  return ""


STAGES = {"download": "Downloading", "resolve": "Verifying", "apply": "Preparing", "finalize": "Finishing"}
HERO_LOGO = 112
HERO_H = {State.UP_TO_DATE: 300, State.CHECKING: 300, State.AVAILABLE: 300, State.DOWNLOADING: 352,
          State.READY: 336, State.FAILED: 300}
INSTALL_S = 4.0     # the installing view before the comma restarts
INSTALL_TEXT = rl.Color(244, 246, 250, 255)   # the installing view is black in day and night
INSTALL_SUB = rl.Color(176, 182, 192, 255)


class InstallView(Widget):
  """Full screen while the update installs, like a phone's: the logo on black, what is installing and a thick bar,
  then the comma restarts (DoReboot) and the boot screens take over. On a PC it stops at a Done button."""

  def __init__(self, flow: UpdateFlow, label: str):
    super().__init__()
    self.flow = flow
    self.label = label
    self.started = time.monotonic()
    self.sent = False
    self._done: rl.Rectangle | None = None

  def _render(self, rect: rl.Rectangle):
    rl.draw_rectangle_rec(rect, rl.BLACK)   # black like the boot screens that follow
    cx = rect.x + rect.width / 2
    frac = min(1.0, (time.monotonic() - self.started) / INSTALL_S)
    y = rect.y + rect.height * 0.14
    tex = logo_texture(220)
    if tex is not None:
      rl.draw_texture_ex(tex, rl.Vector2(cx - tex.width / 2, y), 0, 1, rl.WHITE)
    y += 220 + 80
    D.text_center(D.fit(tr("Installing") + " " + self.label, D.H1, rect.width - 256, semi=True), cx, y, D.H1, INSTALL_TEXT,
                  semi=True)   # always on black, so bright in day mode too
    bar_w = min(1100, rect.width - 256)
    bar = rl.Rectangle(cx - bar_w / 2, y + 108, bar_w, 36)
    K.bar(bar, frac, Console.ACCENT)
    self._done = None
    if self.flow.simulated and frac >= 1.0:
      D.text_center(tr("Simulator: the comma would restart now. Nothing was installed."), cx, bar.y + 84, D.LABEL,
                    INSTALL_SUB)
      self._done = rl.Rectangle(cx - 200, bar.y + 168, 400, 96)
      D.button(self._done, tr("Done"), primary=False)
      return
    D.text_center(tr("The comma restarts to finish. Keep it plugged in."), cx, bar.y + 84, D.LABEL, INSTALL_SUB)
    if frac >= 1.0 and not self.sent and not self.flow.simulated:
      self.sent = True
      self.flow.install()

  def _handle_mouse_release(self, pos) -> bool:
    if self._done is not None and D.hit(self._done, pos):
      self.flow.install()
      gui_app.pop_widget()
    return True


class UpdatesPage(FormPage):
  def __init__(self):
    super().__init__()
    self._picking = False
    self.flow = UpdateFlow(self.p)

  def show_event(self):
    super().show_event()
    self._picking = False

  def _get(self, key: str) -> str:
    return _text(self.p.get(key, ""))

  def _json(self, key: str) -> dict:
    v = self.p.get(key, None)
    return v if isinstance(v, dict) else {}

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

  def new_label(self) -> str:
    """'Citadel Auto OS 0.0.2', or '0.0.1 (1f692da)' when the new build keeps the version number."""
    fork = self._json("BPForkStatus")
    desc = self._get("UpdaterNewDescription").split(" / ")
    version = fork.get("version") or (desc[0] if desc and desc[0] else "")
    commit = fork.get("commit") or (desc[2] if len(desc) > 2 else "")
    installed = versions().citadel
    if version and version != installed:
      return f"Citadel Auto OS {version}"
    if version and commit:
      return f"Citadel Auto OS {version} ({commit})"
    return tr("A new build") + (f" ({commit})" if commit else "")

  # -- sections -------------------------------------------------------------------------------

  def sections(self) -> list[Section]:
    if self._picking:
      return self._picker()
    return [self._update(), self._bluepilot(), self._software(), self._source(), self._advanced()]

  def _update(self) -> Section:
    state = state_of(self.p)
    rows: list = [Custom(HERO_H[state], lambda r, st=state: self._hero(r, st))]
    if state in (State.AVAILABLE, State.READY, State.DOWNLOADING):
      notes = plain_notes(self._get("UpdaterNewReleaseNotes"))
      if notes:
        rows.append(Note(notes, lines=4))
    return Section(tr("Software update"), "download", rows, wide=True)

  def _hero(self, r: rl.Rectangle, state: State):
    hits: list = []
    x, w = r.x, r.width
    tex = logo_texture(HERO_LOGO)
    tx = x
    if tex is not None:
      rl.draw_texture_ex(tex, rl.Vector2(x, r.y + 16), 0, 1, rl.WHITE)
      tx = x + tex.width + 40
    v = versions()
    D.text(D.fit(f"Citadel Auto OS {v.citadel}", D.H1, x + w - tx, semi=True), tx, r.y + 22, D.H1, semi=True)
    D.text(D.fit(tr("Built on BluePilot") + f" {v.bluepilot}  ·  " + tr("For the Ford F-150 Lightning"),
                 D.LABEL, x + w - tx), tx, r.y + 92, D.LABEL, Console.TEXT_MUTED)
    y = r.y + HERO_LOGO + 52
    K.hline(x, x + w, y - 20)
    btn_w, btn_h = 440, 92
    btn = rl.Rectangle(x + w - btn_w, y + 8, btn_w, btn_h)
    text_w = btn.x - x - 40
    parked = not ui_state.started

    def headline(color, title: str, sub: str):
      D.dot(x + 12, y + 30, 12, color)
      D.text(D.fit(title, D.H2, text_w - 44, semi=True), x + 44, y + 10, D.H2, semi=True)
      if sub:
        D.text(D.fit(sub, D.LABEL, text_w - 44), x + 44, y + 66, D.LABEL, Console.TEXT_MUTED)

    fork = self._json("BPForkStatus")
    source = " · ".join(b for b in (fork.get("repo", ""), fork.get("branch") or self.branch()) if b)
    if state == State.UP_TO_DATE:
      last = when(self.p.get("LastUpdateTime", None)) or when(fork.get("checkedAt", 0))
      if last:
        headline(Console.SUCCESS, tr("Your software is up to date"),
                 tr("Last checked") + " " + last + (f"  ·  {source}" if source else ""))
      else:   # nothing to vouch for until the first check
        headline(Console.TEXT_MUTED, tr("Not checked yet"),
                 tr("Check for updates from") + " " + (source or tr("your repository")))
      D.button(btn, tr("Check for updates"), primary=False, size=D.LABEL)
      hits.append((btn, self.flow.check))
    elif state == State.CHECKING:
      headline(Console.ACCENT, tr("Checking for updates…"), source)
      phase = (time.monotonic() * 0.6) % 1.0     # an indeterminate sweep, phone style
      bar = rl.Rectangle(x, y + 124, w, 20)
      rl.draw_rectangle_rounded(bar, 1.0, 8, Console.BG_TRACK)
      seg = w * 0.25
      sx = x + (w + seg) * phase - seg
      a, b = max(x, sx), min(x + w, sx + seg)
      if b > a:
        rl.draw_rectangle_rounded(rl.Rectangle(a, bar.y, b - a, bar.height), 1.0, 8, Console.ACCENT)
    elif state == State.AVAILABLE:
      headline(Console.ACCENT, self.new_label() + " " + tr("is available"),
               tr("From") + " " + (source or tr("your repository")))
      D.button(btn, tr("Download and install"), size=D.LABEL)
      hits.append((btn, self.flow.download))
    elif state == State.DOWNLOADING:
      stage, pct, detail = progress_of(self.p)
      D.text(D.fit(self.new_label(), D.H2, w - 260, semi=True), x, y + 4, D.H2, semi=True)
      D.text_right(f"{pct} %", x + w, y + 4, D.H2, Console.TEXT_SECONDARY, semi=True)
      bar = rl.Rectangle(x, y + 70, w, 48)
      K.bar(bar, pct / 100.0, Console.ACCENT)
      D.text(tr(STAGES.get(stage, "Downloading")) + "…" + (f"  {detail}" if detail else ""), x, y + 140, D.LABEL,
             Console.TEXT_SECONDARY)
      D.text_right(tr("Keep the comma on and connected"), x + w, y + 140, D.LABEL, Console.TEXT_MUTED)
    elif state == State.READY:
      headline(Console.SUCCESS, self.new_label() + " " + tr("is ready"),
               tr("The comma restarts to install it. About a minute.") if parked
               else tr("Installs once the truck is parked."))
      K.bar(rl.Rectangle(x, y + 124, text_w, 24), 1.0, Console.SUCCESS)
      D.button(btn, tr("Install now") if parked else tr("When parked"), primary=parked, size=D.LABEL)
      if parked:
        hits.append((btn, self._ask_install))
    else:  # FAILED
      err = self._get("LastUpdateException").splitlines()
      headline(Console.WARNING, tr("Couldn't check for updates"),
               D.fit(err[0] if err else tr("Check the connection and try again."), D.LABEL, text_w - 44))
      D.button(btn, tr("Try again"), primary=False, size=D.LABEL)
      hits.append((btn, self.flow.check))
    return hits

  def _bluepilot(self) -> Section:
    up = self._json("BPUpstreamStatus")
    v = versions()
    rel = up.get("release") or {}
    dev = up.get("dev") or {}
    if up.get("error") and not rel:
      status, color = tr("Couldn't check"), Console.WARNING
    elif not up:
      status, color = tr("Not checked yet"), Console.TEXT_MUTED
    elif up.get("available"):
      status, color = "BluePilot " + (rel.get("version") or rel.get("branch", "")) + " " + tr("is out"), Console.ACCENT
    else:
      status, color = tr("Up to date"), Console.SUCCESS
    rows: list = [Info(tr("Status"), status, dot=color),
                  Info(tr("This build"), f"{v.bluepilot}  ·  {up.get('baseBranch', 'bp-dev')} {up.get('baseCommit', '')}".strip())]
    if rel:
      rows.append(Info(tr("Newest release"), " · ".join(x for x in (rel.get("version", ""), rel.get("branch", "")) if x)))
    if dev:
      ahead = int(dev.get("ahead", 0))
      rows.append(Info(tr("Development") + f" ({dev.get('branch', 'bp-dev')})",
                       tr("No new changes") if ahead == 0 else tr("Has new changes") if ahead < 0
                       else f"{ahead} " + (tr("new change") if ahead == 1 else tr("new changes")), adv=True))
    last = when(up.get("checkedAt", 0))
    if last:
      rows.append(Info(tr("Last checked"), last, adv=True))
    note = (tr("Marked only. A BluePilot release reaches the comma once it's built into your fork, then it shows "
               + "above as a Citadel Auto OS update.") if up.get("available") else
            tr("Checked with every update check. BluePilot is shown here, never installed straight from BluePilot."))
    return Section("BluePilot", "code", rows, note=note)

  def _source(self) -> Section:
    repo = self._get("BPUpdateRepo") or DEFAULT_REPO
    return Section(tr("Source"), "code", [
      Info(tr("Repository"), repo_name(repo)),
      Nav(tr("Branch"), tr("Where updates come from"), self._open_picker, value=self.branch() or "–"),
    ], note=tr("Updates install only from this repository, never from upstream BluePilot or comma."), adv=True)

  def _software(self) -> Section:
    commit = self._get("GitCommit")[:7]
    date = commit_date(self._get("GitCommitDate"))
    v = versions()
    rows = [Info("Citadel Auto OS", v.citadel), Info("BluePilot", v.bluepilot or "–")]
    rows += [Info(tr("Branch"), self._get("GitBranch") or "–", adv=True),
             Info(tr("Commit"), (commit + (f"  ·  {date}" if date else "")) if commit else "–", adv=True)]
    return Section(tr("This software"), "list", rows,
                   note=tr("sunnypilot, openpilot and AGNOS versions are on System > About."))

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
    return Section(tr("Update options"), "sliders", rows, adv=True)

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

  def _ask_install(self):
    label = self.new_label()

    def go():
      if not ui_state.started:
        gui_app.push_widget(InstallView(self.flow, label))
    self.confirm(tr("Install") + f" {label}?", tr("The comma restarts to install it. It's back in about a minute."),
                 tr("Install now"), go)

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
    self.flow.check()

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
