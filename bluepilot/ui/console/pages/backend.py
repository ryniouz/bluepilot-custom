"""
Console Connect backend page (Connect > Connect backend), built from the Console form components. It replaces the
BluePilot panel's Connect Backend and Restore Cached Dongle ID rows, with the same params and side effects:

  Backend      BPConnectBackend: comma connect / Konik Stable / Offline. Picking one asks first, writes the param,
               then offers to restart (DoReboot), as the old dialog did. launch_env.sh and
               bluepilot.backend_switch.reconcile_backend() apply it at the next start.
  This device  the dongle ID it runs with, where it pairs, and Restore dongle ID: adopts a cached ID
               (find_recoverable_dongle_id / restore_cached_dongle_id) after a danger confirm, then offers a restart.
"""

from __future__ import annotations

from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from bluepilot import backend_switch as bs
from bluepilot.ui.console.form import Action, Choice, FormPage, Info, Note, Section
from bluepilot.ui.lib import wifi_settings as ws
from bluepilot.ui.lib.theme import Console

LABELS = {bs.BACKEND_COMMA: "comma connect", bs.BACKEND_KONIK: "Konik Stable", bs.BACKEND_OFFLINE: "Offline"}
SUBS = {
  bs.BACKEND_COMMA: "connect.comma.ai, comma's own servers",
  bs.BACKEND_KONIK: "stable.konik.ai, with its own dongle ID",
  bs.BACKEND_OFFLINE: "No uploads and no remote access",
}


class ConnectBackendPage(FormPage):
  def __init__(self):
    super().__init__()
    self._restore_candidate: str | None = None

  def show_event(self):
    super().show_event()
    self._read_candidate()

  def _read_candidate(self):
    try:
      self._restore_candidate = bs.find_recoverable_dongle_id(self.p._params)
    except Exception:
      self._restore_candidate = None

  # -- data -----------------------------------------------------------------------------------

  def selected(self) -> str:
    try:
      return bs.get_connect_backend(self.p._params)
    except Exception:
      return bs.BACKEND_COMMA

  def active(self) -> str:
    return ws.text(self.p.get("BPActiveBackend", ""))

  # -- sections -------------------------------------------------------------------------------

  def sections(self) -> list[Section]:
    return [self._backend_section(), self._device_section()]

  def _backend_section(self) -> Section:
    sel = self.selected()
    active = self.active()
    rows: list = [Choice(tr("Send drives to"), [tr(LABELS[b]) for b in bs.BACKENDS], bs.backend_index(sel), self._pick,
                         subs=[tr(SUBS[b]) for b in bs.BACKENDS])]
    if ws.backend_pending(sel, active):
      rows.append(Note(tr("Running on {now} until the comma restarts.").format(now=tr(LABELS.get(active, active))),
                       Console.WARNING))
      rows.append(self._restart_row())
    return Section(tr("Connect backend"), "cloud", rows,
                   note=tr("Each backend keeps its own dongle ID, so switching back later picks up where you left off."))

  def _device_section(self) -> Section:
    dongle = ws.text(self.p.get("DongleId", ""))
    registered = bool(dongle) and dongle != bs.UNREGISTERED_DONGLE_ID
    running = self.active() or self.selected()
    rows: list = [
      Info(tr("Dongle ID"), dongle if registered else tr("Not registered"), None if registered else Console.WARNING),
      Info(tr("Pairs with"), bs.pairing_host(running) if running != bs.BACKEND_OFFLINE else tr("Nothing, offline")),
    ]
    cand = self._restore_candidate
    rows.append(Action(tr("Restore dongle ID"),
                       (tr("Found") + f" {ws.short_id(cand)}") if cand else
                       (tr("Not needed, registered") if registered else tr("Nothing cached")),
                       tr("Restore"), self._ask_restore, danger=bool(cand), enabled=cand is not None))
    return Section(tr("This device"), "cpu", rows,
                   note=tr("Restore is for a comma that switching backends left unregistered: it brings back an ID " +
                           "it was registered with before."))

  def _restart_row(self) -> Action:
    parked = ui_state.is_offroad()
    return Action(tr("Restart to apply"), tr("Takes about a minute") if parked else tr("Restart it while parked"),
                  tr("Restart"), self._reboot, primary=True, enabled=parked)

  # -- actions --------------------------------------------------------------------------------

  def _reboot(self):
    self.p.put("DoReboot", True)

  def _offer_restart(self, title: str):
    if ui_state.is_offroad():
      self.confirm(title, tr("The change applies when the comma restarts. Restart now?"), tr("Restart"), self._reboot)

  def _pick(self, i: int):
    target = bs.BACKENDS[i]
    if target == self.selected():
      return
    body = {
      bs.BACKEND_COMMA: tr("Drives upload to comma connect again, with this comma's comma dongle ID."),
      bs.BACKEND_KONIK: tr("Drives upload to Konik instead of comma connect. Konik gives this comma its own dongle ID."),
      bs.BACKEND_OFFLINE: tr("Nothing uploads and remote access stops, until you pick a backend again."),
    }[target]

    def apply():
      self.p.put(bs.PARAM_KEY, i)
      self._offer_restart(tr("Switched to {name}").format(name=tr(LABELS[target])))
    self.confirm(tr("Switch to {name}?").format(name=tr(LABELS[target])), body + " " + tr("It applies after a restart."),
                 tr("Switch"), apply)

  def _ask_restore(self):
    cand = self._restore_candidate
    if cand is None:
      return

    def restore():
      try:
        bs.restore_cached_dongle_id(self.p._params, cand)
      except Exception:
        cloudlog.exception("bp_dongle_id_recovery_ui failed")
        return
      self.p.invalidate()
      self._read_candidate()
      self._offer_restart(tr("Dongle ID restored"))
    self.confirm(tr("Restore dongle ID {id}?").format(id=ws.short_id(cand)),
                 tr("This replaces the current, unregistered device ID. Restart afterwards to use it."),
                 tr("Restore"), restore, danger=True)
