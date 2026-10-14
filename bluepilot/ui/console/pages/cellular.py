"""
Console Cellular page (Connect > Cellular), laid out like a phone's mobile-data settings.

  Network     carrier, signal, technology and band, SIM and modem identity
  Data usage  this month against the optional limit, today, and what the uploads used
  Settings    only controls the comma really supports:
                Citadel uploads          BPRoadTripMode, BPRoadTripCellular (export bridge; shown once its keys exist)
                comma connect Wi-Fi only BPCommaConnectWifiOnly (bridge) or, without it, stock GsmMetered
                Data roaming             GsmRoaming, applied to the NetworkManager LTE connection
                Personal hotspot         Wi-Fi tethering through the Wi-Fi manager
                APN                      GsmApn, blank means automatic
                Monthly data limit       BPCellLimitMB (export bridge enforces it)
                Restart modem            AT+CFUN cycle, the same call athena uses

Carrier, band and data counters come from deviceState (hardwared). SIM and modem identity are read in the
background through HARDWARE (ModemManager), so nothing here blocks the UI. Network selection, preferred
network type and eSIM profiles have no supported path on AGNOS for a user SIM, so they are not offered.
"""

from __future__ import annotations

from collections.abc import Callable

import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.hardware import TICI
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import DialogResult, Widget
from openpilot.system.ui.widgets.keyboard import Keyboard
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.console.home import STRENGTH, _param, has_param
from bluepilot.ui.lib import bridge_status as bridge
from bluepilot.ui.lib.modem_info import mask, modem_info
from bluepilot.ui.lib.net_usage import usage
from bluepilot.ui.lib.theme import Console
from bluepilot.ui.lib.upload_status import citadel_configured, comma_wifi_only, fmt_bytes

GAP = 32
ROW = 70
SET_ROW = 104


def _text(v) -> str:
  if isinstance(v, bytes):
    v = v.decode(errors="ignore")
  return str(v or "").strip("\x00").strip()


class CellularPage(Widget):
  def __init__(self, wifi_manager=None):
    super().__init__()
    self._params = Params()
    self._wifi = wifi_manager
    self._hits: list[tuple[rl.Rectangle, Callable[[], None]]] = []
    self._keyboard: Keyboard | None = None
    self.on_open_uploads: Callable[[], None] | None = None
    self._restart_armed = 0.0

  def show_event(self):
    super().show_event()
    modem_info().request(force=True)

  @staticmethod
  def _ds():
    try:
      return ui_state.sm["deviceState"]
    except Exception:
      return None

  # -- render -------------------------------------------------------------------------------

  def _render(self, rect: rl.Rectangle):
    self._hits = []
    modem_info().request()
    ds = self._ds()
    if rect.width < 1300:  # UI size Large: two columns, network over data usage
      left, right = K.split_cols(rect, [1.0, 1.0])
      left.width -= GAP / 2
      right.x += GAP / 2
      right.width -= GAP / 2
      top, bottom = K.split_rows(left, [1, 1])
      top.height -= GAP / 2
      bottom.y += GAP / 2
      bottom.height -= GAP / 2
      self._network_card(top, ds)
      self._usage_card(bottom)
      self._settings_card(right)
      return
    cols = K.split_cols(rect, [0.95, 1.0, 1.2])
    for i, c in enumerate(cols):
      if i > 0:
        c.x += GAP / 2
        c.width -= GAP / 2
      if i < 2:
        c.width -= GAP / 2
    self._network_card(cols[0], ds)
    self._usage_card(cols[1])
    self._settings_card(cols[2])

  def _row(self, r: rl.Rectangle, y: float, label: str, value: str, color: rl.Color | None = None) -> float:
    p = D.CARD_PAD
    if y + ROW > r.y + r.height - p + 8:
      return y
    K.hline(r.x + p, r.x + r.width - p, y)
    ty = y + (ROW - D.LABEL) / 2 - 2
    D.text(label, r.x + p, ty, D.LABEL, Console.TEXT_MUTED)
    vmax = r.width - 2 * p - D.text_w(label, D.LABEL) - 24
    D.text_right(D.fit(value, D.LABEL, vmax, semi=True), r.x + r.width - p, ty, D.LABEL, color, semi=True)
    return y + ROW

  def _network_card(self, r: rl.Rectangle, ds):
    D.card(r)
    p = D.CARD_PAD
    x, y = r.x + p, r.y + p
    D.text(tr("Cellular"), x, y, D.H2, semi=True)
    snap = modem_info().snapshot
    nt = str(ds.networkType) if ds is not None else "none"
    info = ds.networkInfo if ds is not None else None
    operator = _text(getattr(info, "operator", "")) if info is not None else ""
    tech = _text(getattr(info, "technology", "")) if info is not None else ""
    band = _text(getattr(info, "band", "")) if info is not None else ""
    on_cell = nt.startswith("cell")
    level = STRENGTH.get(str(ds.networkStrength), 0) if (ds is not None and on_cell) else 0
    color = (Console.WARNING if level <= 1 else Console.SUCCESS) if on_cell else Console.TEXT_GHOST
    y += 84
    bw = K.signal_bars(x, y + 60, 60, level, color)
    D.text(D.fit(operator or (tr("No SIM") if snap.read_at and not snap.sim_present else tr("No carrier")), 52,
                 r.width - 2 * p - bw - 28, semi=True), x + bw + 28, y + 4, 52, semi=True)
    y += 92
    if on_cell:
      status = tr("Connected")
    elif nt == "wifi":
      status = tr("Standby, Wi-Fi is in use")
    elif snap.read_at and not snap.sim_present:
      status = tr("Insert a SIM card to use LTE")
    else:
      status = tr("No cellular connection")
    D.text(D.fit(status + (f" · {tech}" if tech and on_cell else ""), D.LABEL, r.width - 2 * p), x, y, D.LABEL, Console.TEXT_SECONDARY)
    y += 60
    if band and on_cell:
      y = self._row(r, y, tr("Band"), band.upper().replace("LTE BAND", "").strip() or band)
    state = _text(getattr(info, "state", "")) if info is not None else ""
    if state:
      y = self._row(r, y, tr("Modem state"), state.replace("_", " ").capitalize())
    temps = list(ds.modemTempC) if ds is not None else []
    if temps:
      y = self._row(r, y, tr("Modem temp"), f"{max(temps):.0f} °C")
    if snap.read_at:
      y = self._row(r, y, tr("SIM"), tr("Ready") if snap.sim_present else tr("Not inserted"),
                    None if snap.sim_present else Console.WARNING)
      if snap.mcc_mnc:
        y = self._row(r, y, tr("Carrier code"), f"{snap.mcc_mnc[:3]}-{snap.mcc_mnc[3:]}")
      if snap.sim_id:
        y = self._row(r, y, tr("SIM number"), mask(snap.sim_id))
      if snap.imei:
        y = self._row(r, y, tr("IMEI"), mask(snap.imei))
      if snap.modem_version:
        y = self._row(r, y, tr("Firmware"), snap.modem_version)
    else:
      y = self._row(r, y, tr("SIM"), tr("Reading…"), Console.TEXT_GHOST)

  def _usage_card(self, r: rl.Rectangle):
    D.card(r)
    p = D.CARD_PAD
    x, y, right = r.x + p, r.y + p, r.x + r.width - p
    D.text(tr("Data usage"), x, y, D.H2, semi=True)
    y += 84
    cell = bridge.get("usage", "cell")
    own = usage()
    month = int(cell.get("monthBytes") or 0) if isinstance(cell, dict) else own.month_bytes
    v, u = fmt_bytes(month).split(" ")
    D.value_unit(v, u, x, y, 88, 36)
    D.text(tr("used this month"), x, y + 104, D.LABEL, Console.TEXT_MUTED)
    y += 164
    limit = int(bridge.get("usage", "limitBytes", default=0) or 0)
    if not limit and has_param(self._params, "BPCellLimitMB"):
      try:
        limit = int(_text(_param(self._params, "BPCellLimitMB", "0")) or 0) * 1_000_000
      except ValueError:
        limit = 0
    if limit:
      over = month >= limit or bool(bridge.get("usage", "overLimit", default=False))
      K.bar(rl.Rectangle(x, y, r.width - 2 * p, K.BAR_H), min(1.0, month / limit), Console.WARNING if over else Console.ACCENT)
      y += K.BAR_H + 16
      D.text(tr("Limit") + f" {fmt_bytes(limit)}", x, y, D.LABEL, Console.TEXT_MUTED)
      if has_param(self._params, "BPCellResetDay"):
        D.text_right(tr("Resets on day") + f" {_text(_param(self._params, 'BPCellResetDay', '1'))}", right, y, D.LABEL, Console.TEXT_MUTED)
      y += 56
    else:
      D.text(tr("No monthly limit set"), x, y, D.LABEL, Console.TEXT_MUTED)
      y += 56
    if isinstance(cell, dict):
      y = self._row(r, y, tr("Today"), fmt_bytes(int(cell.get("todayBytes") or 0)))
    y = self._row(r, y, tr("Since start-up"), fmt_bytes(own.boot_bytes))
    up = bridge.get("usage", "uploader")
    if isinstance(up, dict):
      cit = int(up.get("cellBytesMonth") or 0)
      y = self._row(r, y, tr("Citadel uploads"), fmt_bytes(cit))
      y = self._row(r, y, tr("Everything else"), fmt_bytes(max(0, month - cit)))
    else:
      y = self._row(r, y, tr("Citadel uploads"), tr("Off"), Console.TEXT_GHOST)
    y = self._row(r, y, tr("comma connect"), tr("Wi-Fi only") if comma_wifi_only(self._params) else tr("Allowed"))
    if not isinstance(cell, dict):
      for i, ln in enumerate(D.wrap(tr("Counted on this device. Your carrier may count differently."),
                                    D.LABEL, r.width - 2 * p, 3)):
        if y + 20 + i * 40 + D.LABEL < r.y + r.height - p:
          D.text(ln, x, y + 20 + i * 40, D.LABEL, Console.TEXT_MUTED)

  def _set_row(self, r: rl.Rectangle, y: float, title: str, sub: str, on: bool | None, fn: Callable[[], None] | None,
               enabled: bool = True, action: str = "Edit") -> float:
    p = D.CARD_PAD
    x, right = r.x + p, r.x + r.width - p
    if y + SET_ROW > r.y + r.height - p - D.CONTROL_H - 16:
      return y
    K.hline(x, right, y)
    D.text(D.fit(title, D.BODY, r.width - 2 * p - 128, semi=True), x, y + 16, D.BODY,
           Console.TEXT_PRIMARY if enabled else Console.TEXT_GHOST, semi=True)
    D.text(D.fit(sub, D.LABEL, r.width - 2 * p - 140), x, y + 58, D.LABEL, Console.TEXT_MUTED)
    if on is not None:
      D.toggle(right - 104, y + (SET_ROW - 60) / 2, on, enabled=enabled)
      if enabled and fn is not None:
        self._hits.append((rl.Rectangle(x, y, right - x, SET_ROW), fn))
    elif fn is not None and enabled:
      lw = D.text_w(tr(action), D.LABEL, semi=True) + 48
      b = rl.Rectangle(right - lw, y + (SET_ROW - 64) / 2, lw, 64)
      D.button(b, tr(action), primary=False, size=D.LABEL)
      self._hits.append((b, fn))
    return y + SET_ROW

  def _settings_card(self, r: rl.Rectangle):
    D.card(r)
    p = D.CARD_PAD
    x, y = r.x + p, r.y + p
    D.text(tr("Settings"), x, y, D.H2, semi=True)
    y += 76

    y = self._set_row(r, y, tr("Uploads over LTE"), self._uploads_summary(), None,
                      lambda: self.on_open_uploads and self.on_open_uploads(), action="Open")
    roaming = bool(_param(self._params, "GsmRoaming", False))
    y = self._set_row(r, y, tr("Data roaming"), tr("Other carriers' networks"), roaming,
                      lambda: self._put_gsm(roaming=not roaming))
    if self._wifi is not None:
      try:
        hot = bool(self._wifi.is_tethering_active())
      except Exception:
        hot = False
      y = self._set_row(r, y, tr("Personal hotspot"), tr("Share LTE over Wi-Fi"), hot,
                        lambda: self._wifi.set_tethering_active(not hot))
    apn = _text(_param(self._params, "GsmApn", ""))
    y = self._set_row(r, y, tr("APN"), apn or tr("Automatic"), None, self._edit_apn)

    if TICI:
      b = rl.Rectangle(x, r.y + r.height - p - D.CONTROL_H, r.width - 2 * p, D.CONTROL_H)
      armed = rl.get_time() < self._restart_armed
      D.button(b, tr("Tap again to restart") if armed else tr("Restart modem"), primary=armed)
      self._hits.append((b, self._restart))

  def _uploads_summary(self) -> str:
    parts = [tr("comma") + " " + (tr("Wi-Fi only") if comma_wifi_only(self._params) else tr("LTE on"))]
    if has_param(self._params, "BPRoadTripMode"):
      on = bool(_param(self._params, "BPRoadTripMode", False)) and citadel_configured(self._params)
      parts.append(tr("Citadel") + " " + (tr("on") if on else tr("off")))
    if has_param(self._params, "BPCellLimitMB"):
      try:
        mb = int(_text(_param(self._params, "BPCellLimitMB", "0")) or 0)
      except ValueError:
        mb = 0
      if mb:
        parts.append(tr("limit") + f" {mb / 1000:g} GB")
    return " · ".join(parts)

  # -- actions ------------------------------------------------------------------------------

  def _put_gsm(self, roaming: bool | None = None, metered: bool | None = None):
    if roaming is not None:
      self._params.put_bool("GsmRoaming", roaming)
    if metered is not None:
      self._params.put_bool("GsmMetered", metered)
    if self._wifi is not None:
      try:
        self._wifi.update_gsm_settings(bool(_param(self._params, "GsmRoaming", False)), _text(_param(self._params, "GsmApn", "")),
                                       bool(_param(self._params, "GsmMetered", True)))
      except Exception:
        pass

  def _edit_apn(self):
    if self._keyboard is None:
      self._keyboard = Keyboard(max_text_size=64, min_text_size=0)

    def done(result: DialogResult):
      if result != DialogResult.CONFIRM or self._keyboard is None:
        return
      apn = self._keyboard.text.strip()
      if apn:
        self._params.put("GsmApn", apn)
      else:
        self._params.remove("GsmApn")
      self._put_gsm()

    self._keyboard.reset(min_text_size=0)
    self._keyboard.set_title(tr("Enter APN"), tr("Leave blank for automatic"))
    self._keyboard.set_text(_text(_param(self._params, "GsmApn", "")))
    self._keyboard.set_callback(done)
    gui_app.push_widget(self._keyboard)

  def _restart(self):
    if rl.get_time() < self._restart_armed:
      self._restart_armed = 0.0
      modem_info().restart_modem()
    else:
      self._restart_armed = rl.get_time() + 4.0

  def _handle_mouse_release(self, pos) -> bool:
    for r, fn in self._hits:
      if D.hit(r, pos):
        fn()
        return True
    return False
