"""
Console Cellular page (Connect > Cellular), built from the Console form components.

  This month  data used against the optional limit, one stacked bar of where it went, the reset date
  Network     carrier and signal, connection, metered, SIM and modem identity
  Settings    data roaming, personal hotspot, APN, the monthly limit and LTE uploads (Uploads page), restart modem

Where the data went comes from the data export bridge's usage.categories (bluepilot/bridge/usage.py):
Citadel uploads, comma connect, live data, remote link, and other (the modem total minus those). Without the
bridge only the month total is known (bluepilot.ui.lib.net_usage counts it from the modem), so the bar shows that
total as one part and says why; nothing is estimated.

Carrier, band and data counters come from deviceState (hardwared). SIM and modem identity are read in the
background through HARDWARE (ModemManager), so nothing here blocks the UI. Network selection, preferred
network type and eSIM profiles have no supported path on AGNOS for a user SIM, so they are not offered.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable

import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.hardware import TICI
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.keyboard import Keyboard
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.console.form import Action, Custom, FormPage, Info, Nav, Note, Section, Stack, StackPart, Toggle
from bluepilot.ui.console.home import STRENGTH
from bluepilot.ui.lib import bridge_status as bridge
from bluepilot.ui.lib.modem_info import mask, modem_info
from bluepilot.ui.lib.net_usage import CATEGORIES, fmt_data, month_breakdown, next_reset, usage
from bluepilot.ui.lib.theme import Console
from bluepilot.ui.lib.upload_status import citadel_configured, comma_wifi_only

NEAR_LIMIT = 0.9
STRENGTH_NAMES = {1: "Poor", 2: "Fair", 3: "Good", 4: "Excellent"}


def category_color(key: str) -> rl.Color:
  return {"citadel": Console.ACCENT, "commaConnect": Console.INFO, "live": Console.PURPLE, "link": Console.LIME,
          "other": Console.TEXT_MUTED}.get(key, Console.TEXT_MUTED)


def _text(v) -> str:
  if isinstance(v, bytes):
    v = v.decode(errors="ignore")
  return str(v or "").strip("\x00").strip()


class CellularPage(FormPage):
  def __init__(self, wifi_manager=None):
    super().__init__()
    self._wifi = wifi_manager
    self._keyboard: Keyboard | None = None
    self.on_open_uploads: Callable[[], None] | None = None

  def show_event(self):
    super().show_event()
    modem_info().request(force=True)

  @staticmethod
  def _ds():
    try:
      return ui_state.sm["deviceState"]
    except Exception:
      return None

  # -- data ---------------------------------------------------------------------------------

  def limit_bytes(self) -> int:
    limit = int(bridge.get("usage", "limitBytes", default=0) or 0)
    if not limit and self.p.has("BPCellLimitMB"):
      limit = max(0, self.p.int("BPCellLimitMB")) * 1_000_000
    return limit

  def _period(self) -> tuple[str, str]:
    """('Oct 1', 'Nov 1'): when this count started and when it starts over."""
    today = dt.date.today()
    start = bridge.get("usage", "cell", "monthStart")
    if isinstance(start, str) and bridge.status() is not None:
      try:
        since = dt.date.fromisoformat(start[:10])
      except ValueError:
        since = today.replace(day=1)
      reset = next_reset(today, self.p.int("BPCellResetDay", 1) if self.p.has("BPCellResetDay") else since.day)
    else:  # the UI's own count follows the calendar month
      since, reset = today.replace(day=1), next_reset(today, 1)
    return f"{since:%b} {since.day}", f"{reset:%b} {reset.day}"

  # -- sections -----------------------------------------------------------------------------

  def sections(self) -> list[Section]:
    modem_info().request()
    ds = self._ds()
    if ds is not None:
      usage().tick(ds)
    return [self._usage_section(), self._network_section(ds), self._settings_section()]

  def _usage_section(self) -> Section:
    month, cats = month_breakdown(bridge.get("usage"), usage().month_bytes)
    limit = self.limit_bytes()
    over = bool(limit) and (month >= limit or bool(bridge.get("usage", "overLimit", default=False)))
    near = bool(limit) and not over and month >= NEAR_LIMIT * limit
    since, reset = self._period()

    def total(r: rl.Rectangle):
      v, u = fmt_data(month).split(" ")
      color = Console.WARNING if (over or near) else None
      w = D.value_unit(v, u, r.x, r.y + 8, K.VAL, K.CAP + 4, color)
      if limit:
        cap = f"{limit / 1e9:g} GB" if limit % 100_000_000 == 0 else fmt_data(limit)
        D.text(tr("of") + " " + cap, r.x + w + 20, r.y + 8 + K.VAL * 0.86 - K.CAP * 0.86, K.CAP,
               Console.TEXT_MUTED)
      D.text(tr("Since") + f" {since}", r.x, r.y + 8 + K.VAL + 14, D.LABEL, Console.TEXT_MUTED)
      right = r.x + r.width
      if over:
        label = tr("Limit reached")
      elif limit:
        label = fmt_data(max(0, limit - month)) + " " + tr("left")
      else:
        label = tr("No monthly limit")
      D.text_right(label, right, r.y + 16, D.BODY, Console.WARNING if (over or near) else Console.TEXT_PRIMARY, semi=True)
      D.text_right(tr("Resets") + f" {reset}", right, r.y + 8 + K.VAL + 14, D.LABEL, Console.TEXT_MUTED)
      return None

    rows: list = [Custom(K.VAL + 72, total)]
    scale = max(limit, month) if limit else float(month)
    marker = limit if over and limit else None
    if cats is not None:
      parts = [StackPart(tr(name), fmt_data(cats.get(key, 0)), cats.get(key, 0), category_color(key)) for key, name in CATEGORIES]
      rows.append(Stack(parts, scale=scale, marker=marker, hide_empty=month == 0))
      if month == 0:
        rows.append(Note(tr("No LTE data used yet this period.")))
    else:
      rows.append(Stack([StackPart(tr("All LTE data"), fmt_data(month), month, Console.ACCENT)], scale=scale, marker=marker, cols=1))
      rows.append(Note(tr("Turn on Data export (Connect > Data export) to see what used it: Citadel uploads, comma " +
                          "connect, live data and the remote link.")))
    if over:
      act = self.p.int("BPCellLimitAction") if self.p.has("BPCellLimitAction") else 0
      rows.append(Note(tr("Over the limit: uploads over LTE have stopped until the reset.") if act == 1 else
                       tr("Over the limit: only logs go over LTE until the reset, no video."), Console.WARNING))
    return Section(tr("This month"), "pulse", rows, wide=True)

  def _network_section(self, ds) -> Section:
    snap = modem_info().snapshot
    nt = str(ds.networkType) if ds is not None else "none"
    info = getattr(ds, "networkInfo", None) if ds is not None else None
    operator = _text(getattr(info, "operator", "")) if info is not None else ""
    tech = _text(getattr(info, "technology", "")) if info is not None else ""
    band = _text(getattr(info, "band", "")) if info is not None else ""
    on_cell = nt.startswith("cell")
    level = STRENGTH.get(str(ds.networkStrength), 0) if (ds is not None and on_cell) else 0
    tone = (Console.WARNING if level <= 1 else Console.SUCCESS) if on_cell else Console.TEXT_GHOST
    no_sim = bool(snap.read_at) and not snap.sim_present

    if on_cell:
      status = tr("Connected") + (f" · {tech}" if tech else "")
    elif nt in ("wifi", "ethernet"):
      status = tr("Standby, Wi-Fi is in use")
    elif no_sim:
      status = tr("Insert a SIM card to use LTE")
    else:
      status = tr("No cellular connection")
    if operator:
      carrier = operator
    elif no_sim:
      carrier = tr("No SIM")
    else:
      carrier = tr("On Wi-Fi") if nt in ("wifi", "ethernet") else tr("No carrier")
      if nt in ("wifi", "ethernet"):
        status = tr("LTE is on standby")

    def hero(r: rl.Rectangle):
      bw = K.signal_bars(r.x, r.y + 70, 56, level, tone)
      D.text(D.fit(carrier, D.H2 + 6, r.width - bw - 28, semi=True), r.x + bw + 28, r.y + 12, D.H2 + 6, semi=True)
      D.text(D.fit(status, D.LABEL, r.width - bw - 28), r.x + bw + 28, r.y + 66, D.LABEL, Console.TEXT_MUTED)
      return None

    rows: list = [Custom(116, hero)]
    rows.append(Info(tr("Signal"), tr(STRENGTH_NAMES.get(level, "None")) if on_cell else tr("Not in use"), tone))
    if band and on_cell:
      rows.append(Info(tr("Band"), band.upper().replace("LTE BAND", "").strip() or band, adv=True))
    metered = bool(getattr(ds, "networkMetered", False)) if ds is not None else False
    if on_cell:
      rows.append(Info(tr("Metered"), tr("Yes, video waits for Wi-Fi") if metered else tr("No")))
    temps = list(ds.modemTempC) if ds is not None else []
    if temps:
      rows.append(Info(tr("Modem temperature"), f"{max(temps):.0f} °C", adv=True))
    if snap.read_at:
      rows.append(Info(tr("SIM"), tr("Ready") if snap.sim_present else tr("Not inserted"),
                       None if snap.sim_present else Console.WARNING, adv=True))
      if snap.mcc_mnc:
        rows.append(Info(tr("Carrier code"), f"{snap.mcc_mnc[:3]}-{snap.mcc_mnc[3:]}", adv=True))
      if snap.sim_id:
        rows.append(Info(tr("SIM number"), mask(snap.sim_id), adv=True))
      if snap.imei:
        rows.append(Info(tr("IMEI"), mask(snap.imei), adv=True))
      if snap.modem_version:
        rows.append(Info(tr("Modem firmware"), snap.modem_version, adv=True))
    else:
      rows.append(Info(tr("SIM"), tr("Reading…"), adv=True))
    return Section(tr("Network"), "cell", rows)

  def _settings_section(self) -> Section:
    rows: list = [Toggle(tr("Data roaming"), tr("Other carriers, can cost extra"),
                         self.p.bool("GsmRoaming"), lambda: self._put_gsm(roaming=not self.p.bool("GsmRoaming")))]
    if self._wifi is not None:
      try:
        hot = bool(self._wifi.is_tethering_active())
      except Exception:
        hot = False
      rows.append(Toggle(tr("Personal hotspot"), tr("Share LTE over Wi-Fi"), hot,
                         lambda: self._wifi.set_tethering_active(not hot)))
    apn = _text(self.p.get("GsmApn", ""))
    rows.append(Nav(tr("APN"), tr("Your carrier's access point"), self._edit_apn, value=apn or tr("Automatic"), adv=True))
    if self.p.has("BPCellLimitMB"):
      mb = max(0, self.p.int("BPCellLimitMB"))
      act = self.p.int("BPCellLimitAction") if self.p.has("BPCellLimitAction") else 0
      sub = (tr("At the limit uploads stop") if act == 1 else tr("At the limit only logs upload")) if mb else tr("Not counting against a limit")
      rows.append(Nav(tr("Monthly data limit"), sub, self._open_uploads, value=f"{mb / 1000:g} GB" if mb else tr("Off")))
    rows.append(Nav(tr("Uploads over LTE"), self._uploads_summary(), self._open_uploads))
    rows.append(Action(tr("Restart modem"), tr("Reconnects LTE, takes about a minute") if TICI else tr("Only on the comma"),
                       tr("Restart"), self._restart, enabled=TICI, adv=True))
    return Section(tr("Settings"), "sliders", rows)

  def _uploads_summary(self) -> str:
    parts = [tr("comma connect") + " " + (tr("Wi-Fi only") if comma_wifi_only(self.p._params) else tr("on LTE"))]
    if self.p.has("BPRoadTripMode"):
      on = self.p.bool("BPRoadTripMode") and citadel_configured(self.p._params)
      cell = self.p.bool("BPRoadTripCellular", True) if self.p.has("BPRoadTripCellular") else True
      parts.append(tr("Citadel") + " " + (tr("on LTE") if on and cell else tr("Wi-Fi only") if on else tr("off")))
    return " · ".join(parts)

  # -- actions ------------------------------------------------------------------------------

  def _open_uploads(self):
    if self.on_open_uploads is not None:
      self.on_open_uploads()

  def _put_gsm(self, roaming: bool | None = None):
    if roaming is not None:
      self.p.put("GsmRoaming", roaming)
    # 7.0: WifiManager.update_gsm_settings is gone; the modem daemon (system/hardware/tici/modem.py)
    # applies GsmRoaming / GsmApn / GsmMetered from params itself, as the stock network panel relies on.

  def _edit_apn(self):
    if self._keyboard is None:
      self._keyboard = Keyboard(max_text_size=64, min_text_size=0)

    def done(result: DialogResult):
      if result != DialogResult.CONFIRM or self._keyboard is None:
        return
      apn = self._keyboard.text.strip()
      if apn:
        self.p.put("GsmApn", apn)
      else:
        try:
          self.p._params.remove("GsmApn")
        except Exception:
          pass
        self.p.invalidate()
      self._put_gsm()

    self._keyboard.reset(min_text_size=0)
    self._keyboard.set_title(tr("Enter APN"), tr("Leave blank for automatic"))
    self._keyboard.set_text(_text(self.p.get("GsmApn", "")))
    self._keyboard.set_callback(done)
    gui_app.push_widget(self._keyboard)

  def _restart(self):
    self.confirm(tr("Restart the modem?"), tr("LTE drops for about a minute while the modem restarts. Wi-Fi isn't affected."),
                 tr("Restart"), modem_info().restart_modem)
