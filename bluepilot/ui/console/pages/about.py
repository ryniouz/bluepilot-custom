"""
Console About page (System > About), laid out like a phone's About screen: the name and version on top, then
everything about this comma in plain rows. Rows that only matter when digging in are Advanced (adv=True).

  Citadel Auto OS  logo, name, version (CITADEL_VERSION, Lucas's own number), "For the Ford F-150 Lightning"
  Software         Citadel Auto OS, BluePilot, sunnypilot, openpilot and AGNOS versions; branch, commit, install
                   date and update source (Advanced)
  This comma       model, serial, dongle ID, truck, uptime
  Storage          capacity, used, available with the storage bar, drives on the comma, not yet synced
  Cellular         carrier, network type and band, signal, SIM, modem firmware, IMEI and ICCID (last digits)
  Network          connection, IP address, Wi-Fi address (MAC), Bluetooth
  Health           temperature, memory, CPU, power draw, fan (Advanced)
  Credits          BluePilot, sunnypilot and openpilot are MIT-licensed; their notices stay with the code

Live values come from deviceState (hardwared) and the Cellular page's modem snapshot (ModemManager, refreshed
in the background); the boot screens show the logo only, so the name lives here.
"""

from __future__ import annotations

import datetime
import socket
import time

import psutil
import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.hardware import PC
from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.console import draw as D
from bluepilot.ui.console.boot import logo_texture
from bluepilot.ui.console.form import Custom, FormPage, Info, Note, Section
from bluepilot.ui.console.pages.drives import fmt_bytes, storage_bar, storage_breakdown
from bluepilot.ui.console.pages.updates import commit_date, repo_name, DEFAULT_REPO
from bluepilot.ui.console.pages.vehicle import LIGHTNING, platform_name
from bluepilot.ui.lib.drive_index import indexer
from bluepilot.ui.lib.modem_info import mask, modem_info
from bluepilot.ui.lib.theme import Console
from bluepilot.ui.lib.versions import versions

NAME = "Citadel Auto OS"
LOGO_H = 168
NET_TTL_S = 3.0
NETWORK_TYPES = {"none": "Not connected", "wifi": "Wi-Fi", "cell2G": "2G", "cell3G": "3G", "cell4G": "LTE",
                 "cell5G": "5G", "ethernet": "Ethernet"}
STRENGTH = {"unknown": "–", "poor": "Poor", "moderate": "Fair", "good": "Good", "great": "Excellent"}


def _size(n: int) -> str:
  v, u = fmt_bytes(n)
  return f"{v} {u}"


def uptime_label(seconds: float) -> str:
  m = int(seconds // 60)
  if m < 60:
    return f"{m} min"
  h, m = divmod(m, 60)
  if h < 24:
    return f"{h} h {m} min"
  d, h = divmod(h, 24)
  return f"{d} d {h} h"


def _uptime() -> float:
  try:
    with open("/proc/uptime") as f:
      return float(f.read().split()[0])
  except (OSError, ValueError, IndexError):
    return 0.0


class _Net:
  """IP and MAC addresses, read at most every few seconds (psutil walks every interface)."""

  def __init__(self):
    self.read_at = -1e9
    self.ip = ""
    self.mac = ""

  def refresh(self):
    if time.monotonic() - self.read_at < NET_TTL_S:
      return
    self.read_at = time.monotonic()
    ip = mac = ""
    try:
      addrs = psutil.net_if_addrs()
      order = ["wlan0"] + [n for n in addrs if n not in ("wlan0", "lo")]
      for name in order:
        for a in addrs.get(name, []):
          if a.family == socket.AF_INET and not ip and not a.address.startswith("127."):
            ip = a.address
          if a.family == psutil.AF_LINK and not mac and name == "wlan0":
            mac = a.address.upper()
    except Exception:
      pass
    self.ip, self.mac = ip, mac


class AboutPage(FormPage):
  def __init__(self):
    super().__init__()
    self._net = _Net()

  def show_event(self):
    super().show_event()
    modem_info().request(force=True)
    indexer().request()

  def _get(self, key: str) -> str:
    v = self.p.get(key, "")
    if isinstance(v, bytes):
      v = v.decode(errors="ignore")
    return str(v or "").strip("\x00").strip()

  @staticmethod
  def _ds():
    try:
      return ui_state.sm["deviceState"]
    except Exception:
      return None

  def sections(self) -> list[Section]:
    modem_info().request()
    self._net.refresh()
    ds = self._ds()
    return [self._hero(), self._software(), self._this_comma(), self._storage(), self._cellular(ds),
            self._network(ds), self._health(ds), self._credits()]

  # -- cards ----------------------------------------------------------------------------------

  def _hero(self) -> Section:
    v = versions()

    def draw(r: rl.Rectangle):
      tex = logo_texture(LOGO_H)
      x = r.x
      if tex is not None:
        rl.draw_texture_ex(tex, rl.Vector2(r.x + 8, r.y + (r.height - tex.height) / 2), 0, 1, rl.WHITE)
        x = r.x + tex.width + 56
      y = r.y + (r.height - (64 + 56 + 44)) / 2
      D.text(D.fit(NAME, D.H1 + 8, r.x + r.width - x, semi=True), x, y, D.H1 + 8, semi=True)
      D.text(tr("Version") + " " + v.citadel, x, y + 72, D.BODY, Console.TEXT_SECONDARY, semi=True)
      D.text(tr("For the Ford F-150 Lightning"), x, y + 124, D.LABEL, Console.TEXT_MUTED)
    return Section(tr("About"), "info", [Custom(LOGO_H + 40, draw)], wide=True)

  def _software(self) -> Section:
    v = versions()
    if v.agnos:
      agnos = Info("AGNOS", v.agnos + (f"  ({tr('needs')} {v.agnos_wanted})" if v.agnos_wanted and v.agnos != v.agnos_wanted else ""),
                   dot=Console.WARNING if v.agnos_wanted and v.agnos != v.agnos_wanted else None)
    else:
      agnos = Info("AGNOS", (tr("Simulator") + f" · {tr('build wants')} {v.agnos_wanted}") if PC else "–")
    commit = self._get("GitCommit")[:7]
    date = commit_date(self._get("GitCommitDate"))
    installed = self.p.get("InstallDate", None)
    rows: list = [
      Info(NAME, v.citadel),
      Info("BluePilot", v.bluepilot or "–"),
      Info("sunnypilot", v.sunnypilot or "–"),
      Info("openpilot", v.openpilot or "–"),
      agnos,
      Info(tr("Branch"), self._get("GitBranch") or "–", adv=True),
      Info(tr("Commit"), (commit + (f"  ·  {date}" if date else "")) if commit else "–", adv=True),
    ]
    if isinstance(installed, datetime.datetime):
      rows.append(Info(tr("Installed"), installed.strftime("%b %-d, %Y"), adv=True))
    rows.append(Info(tr("Updates from"), repo_name(self._get("BPUpdateRepo") or DEFAULT_REPO), adv=True))
    return Section(tr("Software"), "code", rows)

  def _this_comma(self) -> Section:
    cp = ui_state.CP
    fp = str(cp.carFingerprint) if cp is not None else ""
    truck = tr("Ford F-150 Lightning") if fp == LIGHTNING else (platform_name(fp) if fp else tr("Not seen yet"))
    rows: list = [
      Info(tr("Model"), "comma 3X"),
      Info(tr("Serial number"), self._get("HardwareSerial") or tr("Not available")),
      Info(tr("Dongle ID"), self._get("DongleId") or tr("Not available")),
      Info(tr("Truck"), truck),
      Info(tr("Truck platform"), fp or "–", adv=True),
    ]
    up = _uptime()
    if up > 0:
      rows.append(Info(tr("On for"), uptime_label(up)))
    return Section(tr("This comma"), "cpu", rows)

  def _storage(self) -> Section:
    st = storage_breakdown()
    if st is None:
      return Section(tr("Storage"), "storage", [Info(tr("Capacity"), tr("Not available"))])
    used = st.total - st.free

    def bar(r: rl.Rectangle):
      storage_bar(rl.Rectangle(r.x, r.y + 16, r.width, 36), st)
    idx = indexer().index
    rows: list = [
      Info(tr("Capacity"), _size(st.total)),
      Info(tr("Used"), _size(used)),
      Info(tr("Available"), _size(st.free) + (f"  ({100 * st.free / st.total:.0f} %)" if st.total else "")),
      Custom(68, bar),
    ]
    if idx.scanned_at or idx.drives:
      rows.append(Info(tr("Drives on the comma"), str(len(idx.drives))))
    if st.unsynced > 0:
      rows.append(Info(tr("Not synced to Citadel yet"), _size(st.unsynced), dot=Console.WARNING))
    return Section(tr("Storage"), "storage", rows)

  def _cellular(self, ds) -> Section:
    snap = modem_info().snapshot
    info = getattr(ds, "networkInfo", None) if ds is not None else None
    operator = str(getattr(info, "operator", "") or "") if info is not None else ""
    tech = str(getattr(info, "technology", "") or "") if info is not None else ""
    band = str(getattr(info, "band", "") or "") if info is not None else ""
    strength = str(getattr(ds, "networkStrength", "unknown")) if ds is not None else "unknown"
    reading = not snap.read_at
    rows: list = [
      Info(tr("Carrier"), operator or (tr("Reading…") if reading else tr("No service"))),
      Info(tr("Network"), " · ".join(x for x in (tech, band) if x) or "–"),
      Info(tr("Signal"), tr(STRENGTH.get(strength, "–"))),
      Info(tr("SIM"), tr("Ready") if snap.sim_present else (tr("Reading…") if reading else tr("No SIM")),
           dot=Console.SUCCESS if snap.sim_present else None),
      Info(tr("Modem firmware"), snap.modem_version or "–"),
      Info("IMEI", mask(snap.imei) if snap.imei else "–"),
      Info("ICCID", mask(snap.sim_id) if snap.sim_id else "–", adv=True),
      Info("MCC/MNC", snap.mcc_mnc or "–", adv=True),
    ]
    temps = list(getattr(ds, "modemTempC", []) or []) if ds is not None else []
    if temps:
      rows.append(Info(tr("Modem temperature"), f"{max(temps):.0f} °C", adv=True))
    return Section(tr("Cellular"), "cell", rows)

  def _network(self, ds) -> Section:
    kind = str(getattr(ds, "networkType", "none")) if ds is not None else "none"
    bt = self.p.bool("BPBluetoothEnabled") if self.p.has("BPBluetoothEnabled") else False
    rows: list = [
      Info(tr("Connection"), tr(NETWORK_TYPES.get(kind, kind))),
      Info(tr("IP address"), self._net.ip or "–"),
      Info(tr("Wi-Fi address"), self._net.mac or "–"),
      Info("Bluetooth", tr("On") if bt else tr("Off")),
    ]
    if ds is not None and getattr(ds, "networkMetered", False):
      rows.append(Info(tr("Metered"), tr("Yes"), adv=True))
    return Section(tr("Network"), "wifi", rows)

  def _health(self, ds) -> Section:
    if ds is None:
      return Section(tr("Health"), "thermo", [Info(tr("Status"), tr("Not available"))], adv=True)
    cpu = list(getattr(ds, "cpuUsagePercent", []) or [])
    rows: list = [
      Info(tr("Temperature"), f"{ds.maxTempC:.0f} °C"),
      Info(tr("Memory used"), f"{ds.memoryUsagePercent} %"),
      Info(tr("Processor"), f"{sum(cpu) / len(cpu):.0f} %" if cpu else "–"),
      Info(tr("Power draw"), f"{ds.powerDrawW:.1f} W"),
      Info(tr("Fan"), f"{ds.fanSpeedPercentDesired} %"),
    ]
    return Section(tr("Health"), "thermo", rows, adv=True)

  def _credits(self) -> Section:
    return Section(tr("Credits"), "list", [
      Note(tr("Built on BluePilot, sunnypilot and openpilot. They are MIT-licensed, and their licences and notices "
              + "are kept with the software."), lines=3),
    ])

