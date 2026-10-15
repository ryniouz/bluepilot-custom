"""
Console Uploads page (Drives > Uploads): the old Offloading and Upload settings pages in one. Each service
shows its own status first, then its switches.

  comma connect     status, what's waiting, Wi-Fi only (BPCommaConnectWifiOnly; without it, stock GsmMetered)
  Citadel live      Road Trip Mode (BPRoadTripMode), over LTE (BPRoadTripCellular), low-res video
                    (BPRoadTripVideo), remote access (BPRemoteLink, status in services.citadel.link)
  Citadel home sync status and what's waiting (runs by itself on home Wi-Fi)
  LTE data limit    monthly limit (BPCellLimitMB), what happens at the limit (BPCellLimitAction), the day the
                    month starts (BPCellResetDay)

Statuses come from bluepilot/ui/lib/upload_status.py. The Citadel and limit keys belong to the data export
bridge (PR #1); each row shows only once its key exists. The old page keys, drives_offload and
upload_settings, open this page.
"""

from __future__ import annotations

from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.console.form import Choice, FormPage, Info, Note, Section, Stepper, Toggle
from bluepilot.ui.lib import bridge_status as bridge
from bluepilot.ui.lib import upload_status as us
from bluepilot.ui.lib.drive_index import indexer

LIMITS_MB = [0, 2000, 5000, 10000, 20000]
LIMIT_LABELS = ["Off", "2 GB", "5 GB", "10 GB", "20 GB"]


def link_text(on: bool) -> str:
  """services.citadel.link from the bridge: settings and live data from Citadel while away."""
  if not on:
    return tr("Citadel can't reach the truck while away")
  st = bridge.get("services", "citadel", "link")
  if not isinstance(st, dict):
    return tr("From Citadel while away")
  state = str(st.get("state") or "")
  reason = {"no_server": tr("no server"), "no_network": tr("no signal"), "over_limit": tr("data limit reached"),
            "server_error": tr("server error"), "disabled": tr("turned off")}.get(str(st.get("pausedReason")), "")
  return {"connected": tr("Connected"), "connecting": tr("Connecting"), "waiting": tr("Waiting for a connection"),
          "paused": tr("Paused") + (f": {reason}" if reason else "")}.get(state, tr("From Citadel while away"))


class UploadsPage(FormPage):
  def __init__(self, wifi_manager=None):
    super().__init__()
    self._wifi = wifi_manager

  def show_event(self):
    super().show_event()
    indexer().request(force=True)

  @staticmethod
  def _status(svc: us.Service) -> list:
    return [Info(tr("Status"), svc.state, dot=svc.color)] + [Info(label, value) for label, value in svc.rows]

  def sections(self) -> list[Section]:
    indexer().request()
    idx = indexer().index
    params = self.p._params
    return [self._comma(us.comma_connect(params, idx)), self._live(us.citadel_live(params)),
            self._sync(us.citadel_sync(params, idx)), self._limit()]

  def _comma(self, svc: us.Service) -> Section:
    rows = self._status(svc)
    if self.p.has("BPCommaConnectWifiOnly"):
      rows.append(Toggle(tr("Wi-Fi only"), tr("Off: logs and small video also go over LTE"),
                         self.p.bool("BPCommaConnectWifiOnly", True), self.p.flip("BPCommaConnectWifiOnly", True)))
    else:
      rows.append(Toggle(tr("Also upload over LTE"), tr("Small files go over LTE either way"),
                         not self.p.bool("GsmMetered", True), self._toggle_metered))
    return Section(tr("comma connect"), "cloud", rows,
                   note=svc.note or tr("Works as before. Full video goes only when you ask for it in comma connect."))

  def _live(self, svc: us.Service) -> Section:
    rows = self._status(svc)
    if not self.p.has("BPRoadTripMode"):
      rows.append(Note(tr("Live uploads to Citadel come with the data export update. Home sync works without it.")))
      return Section(svc.name, "pulse", rows)
    configured = us.citadel_configured(self.p._params)
    on = self.p.bool("BPRoadTripMode") and configured
    rows.append(Toggle(tr("Road Trip Mode"), tr("Upload while you drive") if configured else tr("Needs your Citadel server"),
                       on, self.p.flip("BPRoadTripMode"), enabled=configured))
    if self.p.has("BPRoadTripCellular"):
      rows.append(Toggle(tr("Over LTE"), tr("Off: waits for Wi-Fi"), self.p.bool("BPRoadTripCellular", True),
                         self.p.flip("BPRoadTripCellular", True), enabled=on))
    if self.p.has("BPRoadTripVideo"):
      video = self.p.int("BPRoadTripVideo", 1)
      rows.append(Toggle(tr("Low-res video"), tr("Off: logs only"), bool(video) and on,
                         lambda: self.p.put("BPRoadTripVideo", 0 if video else 1), enabled=on, adv=True))
    if self.p.has("BPRemoteLink"):
      link = self.p.bool("BPRemoteLink", True)
      rows.append(Toggle(tr("Remote access"), link_text(link), link and configured, self.p.flip("BPRemoteLink", True),
                         enabled=configured))
    return Section(svc.name, "pulse", rows, note=svc.note)

  def _sync(self, svc: us.Service) -> Section:
    return Section(svc.name, "export", self._status(svc), note=svc.note)

  def _limit(self) -> Section:
    if not self.p.has("BPCellLimitMB"):
      return Section(tr("LTE data limit"), "cell", [
        Note(tr("The monthly LTE limit comes with the data export update. Data used is still counted on Connect > Cellular."))])
    cur = self.p.int("BPCellLimitMB", 0)
    rows: list = [Choice(tr("Monthly limit"), [tr(t) for t in LIMIT_LABELS], LIMITS_MB.index(cur) if cur in LIMITS_MB else 0,
                         self.p.setter("BPCellLimitMB", LIMITS_MB))]
    if self.p.has("BPCellLimitAction"):
      rows.append(Choice(tr("When it's reached"), [tr("Logs only"), tr("Stop uploads")],
                         1 if self.p.int("BPCellLimitAction") else 0, self.p.setter("BPCellLimitAction"), enabled=cur > 0,
                         adv=True))
    if self.p.has("BPCellResetDay"):
      day = max(1, min(31, self.p.int("BPCellResetDay", 1)))
      rows.append(Stepper(tr("Month starts on day"), str(day),
                          lambda: self.p.put("BPCellResetDay", max(1, day - 1)),
                          lambda: self.p.put("BPCellResetDay", min(31, day + 1)), adv=True))
    return Section(tr("LTE data limit"), "cell", rows,
                   note=tr("Counts this comma's LTE use, not your whole plan. comma connect's small logs count too."))

  # -- actions --------------------------------------------------------------------------------

  def _toggle_metered(self):
    metered = not self.p.bool("GsmMetered", True)
    self.p.put("GsmMetered", metered)
    if self._wifi is not None:
      try:
        apn = str(self.p.get("GsmApn", "") or "").strip()
        self._wifi.update_gsm_settings(self.p.bool("GsmRoaming"), apn, metered)
      except Exception:
        pass
