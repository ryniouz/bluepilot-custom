"""
Console Wi-Fi page (Connect > Wi-Fi), built from the Console form components. It replaces the stock network panel
(NetworkUISP) and System > More settings, and runs on the same WifiManager the stock panel used.

  Wi-Fi              the connected network (signal, address), Wi-Fi on/off
  Networks           every network in range: signal, lock, connected / saved state; tap to join (a password
                     prompt on the existing keyboard when it needs one), Forget for saved ones, Scan
  Preferred network  WifiFavoriteSSID: the saved network the comma joins first when it is in range
                     (WifiFavoriteManager acts on it; this page only picks it, as the BluePilot panel did)
  This network       metered or not, and its IP address (Advanced mode)
  Hotspot            on/off lives on Cellular (linked); its name and password here (Advanced mode)
  Other networks     joining a hidden network (Advanced mode)

Wi-Fi on/off is NetworkManager's WirelessEnabled switch, read and written in the background; the row is left out
when NetworkManager doesn't answer. Passwords go straight from the keyboard to WifiManager and are never logged.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import DialogResult
from openpilot.system.ui.widgets.keyboard import Keyboard
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.console.form import ROW_SET, Action, Choice, Custom, FormPage, Info, Nav, Note, Section, Toggle
from bluepilot.ui.lib import wifi_settings as ws
from bluepilot.ui.lib.theme import Console

SCAN_TIMEOUT_S = 10.0
METERED = ("Default", "Metered", "Unmetered")   # MeteredType UNKNOWN, YES, NO: the index is the value


class WifiRadio:
  """NetworkManager's WirelessEnabled, read and written off the UI thread. `enabled` is None until it answers."""

  def __init__(self, wifi_manager):
    self._wifi = wifi_manager
    self.enabled: bool | None = None
    self._busy = False

  def _call(self, fn):
    if self._busy or self._wifi is None or getattr(self._wifi, "_router_main", None) is None:
      return
    self._busy = True

    def worker():
      try:
        fn()
      except Exception:
        pass
      finally:
        self._busy = False
    threading.Thread(target=worker, daemon=True).start()

  def refresh(self):
    def read():
      from jeepney.wrappers import Properties
      reply = self._wifi._router_main.send_and_get_reply(Properties(self._wifi._nm).get("WirelessEnabled"))
      self.enabled = bool(reply.body[0][1])
    self._call(read)

  def set(self, on: bool):
    def write():
      from jeepney.wrappers import Properties
      self._wifi._router_main.send_and_get_reply(Properties(self._wifi._nm).set("WirelessEnabled", "b", on))
      self.enabled = on
    self.enabled = on  # the switch moves at once; a failed write is corrected by the next refresh
    self._call(write)


class WifiPage(FormPage):
  def __init__(self, wifi_manager=None):
    super().__init__()
    self._wifi = wifi_manager
    self.radio = WifiRadio(wifi_manager)
    self.on_open_cellular: Callable[[], None] | None = None
    self._keyboard: Keyboard | None = None
    self._networks: list = []
    self._state = ""             # "connecting" / "forgetting" while WifiManager works on _state_ssid
    self._state_ssid = ""
    self._scan_at = 0.0
    if wifi_manager is not None:
      wifi_manager.add_callbacks(need_auth=self._on_need_auth, activated=self._idle, forgotten=self._on_forgotten,
                                 networks_updated=self._on_networks, disconnected=self._idle)

  # -- lifecycle ------------------------------------------------------------------------------

  def show_event(self):
    super().show_event()
    self._idle()   # WifiManager's own connecting state still shows a join that is under way
    if self._wifi is not None:
      self._wifi.set_active(True)   # scan while the page is open, like the stock panel
      self._networks = list(self._wifi.networks)
    self.radio.refresh()

  def hide_event(self):
    super().hide_event()
    if self._wifi is not None:
      self._wifi.set_active(False)

  def _update_state(self):
    if self._wifi is None:
      return
    self._wifi.process_callbacks()
    try:  # stock: the hotspot shares LTE only off a comma prime SIM
      self._wifi.set_ipv4_forward(ws.forwarding_allowed(ui_state.prime_state.get_type()))
    except Exception:
      pass
    if self._scan_at and time.monotonic() - self._scan_at > SCAN_TIMEOUT_S:
      self._scan_at = 0.0

  # -- WifiManager callbacks ------------------------------------------------------------------

  def _idle(self, *_):
    self._state, self._state_ssid = "", ""

  def _on_forgotten(self, ssid=None):
    if ssid and ssid == self.favorite():
      self.p.put("WifiFavoriteSSID", "")
    self._idle()

  def _on_networks(self, networks):
    self._networks = list(networks)
    self._scan_at = 0.0
    fav = self.favorite()
    if ws.stale_favorite(fav, getattr(self._wifi, "_connections", {}).keys()):
      self.p.put("WifiFavoriteSSID", "")

  def _on_need_auth(self, ssid):
    net = next((n for n in self._networks if n.ssid == ssid), None)
    if net is not None:
      self._ask_password(ssid, retry=True)

  # -- data -----------------------------------------------------------------------------------

  def favorite(self) -> str:
    return ws.text(self.p.get("WifiFavoriteSSID", ""))

  def _tether_ssid(self) -> str:
    return getattr(self._wifi, "_tethering_ssid", "")

  def _saved(self) -> list[str]:
    return ws.saved_ssids(getattr(self._wifi, "_connections", {}).keys(), self._tether_ssid())

  def _hotspot_on(self) -> bool:
    try:
      return bool(self._wifi.is_tethering_active())
    except Exception:
      return False

  def _connected(self) -> str:
    return (getattr(self._wifi, "connected_ssid", None) or "") if self._wifi is not None else ""

  # -- sections -------------------------------------------------------------------------------

  def sections(self) -> list[Section]:
    if self._wifi is None:
      return [Section(tr("Wi-Fi"), "wifi", [Note(tr("Wi-Fi isn't available on this device."))])]
    return [self._status_section(), self._networks_section(), self._preferred_section(), *self._advanced_sections()]

  def _status_section(self) -> Section:
    off = self.radio.enabled is False
    ssid = self._connected()
    hotspot = self._hotspot_on()
    net = next((n for n in self._networks if n.ssid == ssid), None)
    if off:
      name, status, level, tone = tr("Wi-Fi is off"), tr("LTE carries everything while it's off"), 0, Console.TEXT_GHOST
    elif hotspot:
      name, status, level, tone = tr("Personal hotspot"), tr("Sharing LTE as") + f" {self._tether_ssid()}", 4, Console.ACCENT
    elif ssid:
      level = ws.signal_level(net.strength) if net is not None else 4
      name, status, tone = ssid, tr("Connected"), Console.WARNING if level <= 1 else Console.SUCCESS
      if ssid == self.favorite():
        status += " · " + tr("Preferred")
    else:
      connecting = getattr(self._wifi, "connecting_to_ssid", None)
      name = tr("Not connected")
      status = (tr("Joining") + f" {connecting}…") if connecting else tr("Pick a network to join")
      level, tone = 0, Console.TEXT_GHOST

    def hero(r: rl.Rectangle):
      bw = K.signal_bars(r.x, r.y + 70, 56, level, tone)
      D.text(D.fit(name, D.H2 + 6, r.width - bw - 28, semi=True), r.x + bw + 28, r.y + 12, D.H2 + 6, semi=True)
      D.text(D.fit(status, D.LABEL, r.width - bw - 28), r.x + bw + 28, r.y + 66, D.LABEL, Console.TEXT_MUTED)
      return None

    rows: list = [Custom(116, hero)]
    if self.radio.enabled is not None:
      rows.append(Toggle(tr("Wi-Fi"), tr("Turn off to stay on LTE only") if not off else tr("Off, nothing joins or scans"),
                         not off, self._toggle_radio))
    ip = self._wifi.ipv4_address
    if ip and not off:
      rows.append(Info(tr("IP address"), ip, adv=True))
    return Section(tr("Wi-Fi"), "wifi", rows)

  def _networks_section(self) -> Section:
    if self.radio.enabled is False:
      return Section(tr("Networks"), "list", [Note(tr("Turn Wi-Fi on to see the networks around you."))])
    scanning = bool(self._scan_at)
    nets = [n for n in self._networks if not n.is_tethering]
    count = (tr("1 network nearby") if len(nets) == 1 else f"{len(nets)} " + tr("networks nearby")) if nets else tr("Looking…")
    rows: list = [Action(count, tr("Tap one to join it"), tr("Scanning…") if scanning else tr("Scan"), self._scan,
                         enabled=not scanning)]
    if not nets:
      rows.append(Note(tr("No networks found yet. They show up here as the comma finds them.")))
    rows += [Custom(ROW_SET, lambda r, n=n: self._network_row(r, n)) for n in nets]
    return Section(tr("Networks"), "list", rows)

  def _network_row(self, r: rl.Rectangle, n) -> list:
    from openpilot.system.ui.lib.wifi_manager import SecurityType, normalize_ssid
    connecting = (self._state == "connecting" and self._state_ssid == n.ssid) or \
                 getattr(self._wifi, "connecting_to_ssid", None) == n.ssid
    connected = n.ssid == self._connected() and not connecting
    forgetting = self._state == "forgetting" and self._state_ssid == n.ssid
    saved = self._wifi.is_connection_saved(n.ssid)
    secured = n.security_type != SecurityType.OPEN
    supported = n.security_type != SecurityType.UNSUPPORTED
    status = tr(ws.network_status(connected=connected, connecting=connecting, forgetting=forgetting, saved=saved,
                                  secured=secured, supported=supported))
    if saved and n.ssid == self.favorite() and not (connecting or forgetting):
      status += " · " + tr("Preferred")
    hits = []
    right = r.x + r.width
    if saved and not (connecting or forgetting):
      bw = D.text_w(tr("Forget"), D.LABEL, semi=True) + 56
      b = rl.Rectangle(right - bw, r.y + (ROW_SET - 64) / 2, bw, 64)
      D.button(b, tr("Forget"), primary=False, size=D.LABEL)
      hits.append((b, lambda: self._ask_forget(n.ssid)))
      right = b.x - 24
    if secured:
      D.icon("lock", right - 36, r.y + (ROW_SET - 36) / 2, 36, Console.TEXT_MUTED)
      right -= 36 + 16
    tone = Console.SUCCESS if connected else (Console.ACCENT if connecting else Console.TEXT_SECONDARY)
    bars_w = K.signal_bars(r.x, r.y + ROW_SET / 2 + 18, 36, ws.signal_level(n.strength), tone)
    tx = r.x + bars_w + 28
    D.text(D.fit(normalize_ssid(n.ssid), D.BODY, right - tx - 16, semi=True), tx, r.y + 14, D.BODY,
           Console.TEXT_PRIMARY if supported else Console.TEXT_GHOST, semi=True)
    D.text(D.fit(status, D.LABEL, right - tx - 16), tx, r.y + 58, D.LABEL,
           Console.SUCCESS if connected else (Console.ACCENT_TEXT if connecting else Console.TEXT_MUTED))
    act = ws.tap_action(connected=connected, saved=saved, secured=secured, supported=supported,
                        busy=connecting or forgetting)
    if act == "password":
      hits.append((r, lambda: self._ask_password(n.ssid)))
    elif act == "connect":
      hits.append((r, lambda: self._connect(n.ssid)))
    return hits

  def _preferred_section(self) -> Section:
    saved = self._saved()
    fav = self.favorite()
    if not saved and not fav:
      return Section(tr("Preferred network"), "bookmark",
                     [Note(tr("Join a network once and it can be picked here. The comma then switches to it " +
                              "whenever it's in range."))])
    options, sel = ws.preferred_choices(saved, fav)
    labels = [tr("None")] + options[1:]
    return Section(tr("Preferred network"), "bookmark", [
      Choice(tr("Join first when in range"), labels, sel, lambda i: self._set_favorite(options[i] if i else ""),
             radio=True),
    ], note=tr("Checked every 30 seconds. When it's in range with a usable signal, the comma moves to it from any " +
                       "other network."))

  def _advanced_sections(self) -> list[Section]:
    hotspot = self._hotspot_on()
    ip = self._wifi.ipv4_address
    can_meter = bool(ip) and not hotspot
    metered = int(self._wifi.current_network_metered) if can_meter else 0
    this = [Choice(tr("Metered network"), [tr(m) for m in METERED], metered if metered in (0, 1, 2) else 0,
                   self._set_metered, enabled=can_meter)]
    note = tr("Large uploads wait for an unmetered network. Default lets the network say so itself.") if can_meter else \
      (tr("Not while the hotspot is on.") if hotspot else tr("Join a network to change this."))
    hot = [Nav(tr("Personal hotspot"), tr("Turn it on or off on the Cellular page"), self._open_cellular,
               value=tr("On") if hotspot else tr("Off")),
           Info(tr("Hotspot name"), self._tether_ssid() or "–", adv=True),
           Action(tr("Hotspot password"), tr("At least 8 characters"), tr("Change"), self._edit_hotspot_password,
                  adv=True)]
    hidden = [Action(tr("Hidden network"), tr("Join one that doesn't show its name"), tr("Join"), self._join_hidden,
                     enabled=self.radio.enabled is not False)]
    return [Section(tr("This network"), "wifi", this, note=note, adv=True),
            Section(tr("Hotspot"), "phone", hot,
                    note=tr("Phones join it to share the comma's LTE.")),
            Section(tr("Other networks"), "search", hidden, adv=True)]

  # -- actions --------------------------------------------------------------------------------

  def _open_cellular(self):
    if self.on_open_cellular is not None:
      self.on_open_cellular()

  def _toggle_radio(self):
    if self.radio.enabled is False:
      self.radio.set(True)
      return
    self.confirm(tr("Turn off Wi-Fi?"),
                 tr("The comma stays online over LTE. Uploads that wait for Wi-Fi, the preferred network and the " +
                    "hotspot pause until Wi-Fi is back on."), tr("Turn off"), lambda: self.radio.set(False))

  def _scan(self):
    self._scan_at = time.monotonic()
    try:  # the stock panel's Scan: refresh the list now and ask the radio for a fresh scan
      threading.Thread(target=self._wifi._update_networks, daemon=True).start()
      self._wifi._request_scan()
      self._wifi._last_network_update = time.monotonic()
    except Exception:
      pass

  def _connect(self, ssid: str, password: str = ""):
    self._state, self._state_ssid = "connecting", ssid
    if self._wifi.is_connection_saved(ssid) and not password:
      self._wifi.activate_connection(ssid)
    else:
      self._wifi.connect_to_network(ssid, password)

  def _ask_forget(self, ssid: str):
    from openpilot.system.ui.lib.wifi_manager import normalize_ssid

    def forget():
      self._state, self._state_ssid = "forgetting", ssid
      self._wifi.forget_connection(ssid)
    extra = " " + tr("It's also your preferred network, so that's cleared too.") if ssid == self.favorite() else ""
    self.confirm(tr("Forget") + f" {normalize_ssid(ssid)}?",
                 tr("The comma stops joining it and drops its password. Join it again any time.") + extra,
                 tr("Forget"), forget, danger=True)

  def _set_favorite(self, ssid: str):
    self.p.put("WifiFavoriteSSID", ssid)

  def _set_metered(self, i: int):
    from openpilot.system.ui.lib.wifi_manager import MeteredType
    metered = {0: MeteredType.UNKNOWN, 1: MeteredType.YES, 2: MeteredType.NO}.get(i, MeteredType.UNKNOWN)
    self._wifi.set_current_network_metered(metered)
    # shown at once; WifiManager re-reads the real value from NetworkManager on its next network update
    self._wifi._current_network_metered = metered

  # -- keyboard prompts -----------------------------------------------------------------------

  def _kb(self) -> Keyboard:
    if self._keyboard is None:
      self._keyboard = Keyboard(max_text_size=ws.MAX_PASSWORD_LENGTH, min_text_size=ws.MIN_PASSWORD_LENGTH,
                                show_password_toggle=True)
    return self._keyboard

  def _ask_password(self, ssid: str, retry: bool = False):
    from openpilot.system.ui.lib.wifi_manager import normalize_ssid
    kb = self._kb()

    def done(result: DialogResult):
      if result == DialogResult.CONFIRM:
        password = kb.text
        kb.clear()
        if len(password) >= ws.MIN_PASSWORD_LENGTH:
          self._connect(ssid, password)
      else:
        kb.clear()
        self._idle()

    kb.reset(min_text_size=ws.MIN_PASSWORD_LENGTH)
    kb.set_title(tr("Wrong password") if retry else tr("Enter password"), tr("for \"{}\"").format(normalize_ssid(ssid)))
    kb.set_callback(done)
    gui_app.push_widget(kb)

  def _edit_hotspot_password(self):
    kb = self._kb()

    def done(result: DialogResult):
      if result == DialogResult.CONFIRM:
        self._wifi.set_tethering_password(kb.text)
      kb.clear()

    kb.reset(min_text_size=ws.MIN_PASSWORD_LENGTH)
    kb.set_title(tr("New hotspot password"), tr("At least 8 characters"))
    kb.set_text(self._wifi.tethering_password)
    kb.set_callback(done)
    gui_app.push_widget(kb)

  def _join_hidden(self):
    kb = self._kb()

    def got_ssid(result: DialogResult):
      ssid = kb.text if result == DialogResult.CONFIRM else ""
      kb.clear()
      if not ssid:
        return

      def got_password(result: DialogResult):
        password = kb.text if result == DialogResult.CONFIRM else None
        kb.clear()
        if password is not None:  # blank: an open hidden network, as the stock panel allows
          self._state, self._state_ssid = "connecting", ssid
          self._wifi.connect_to_network(ssid, password, hidden=True)

      kb.reset(min_text_size=0)
      kb.set_title(tr("Enter password"), tr("for \"{}\", blank if it's open").format(ssid))
      kb.set_callback(got_password)
      gui_app.push_widget(kb)

    kb.reset(min_text_size=1)
    kb.set_title(tr("Network name"), tr("Exactly as the router has it"))
    kb.set_callback(got_ssid)
    gui_app.push_widget(kb)
