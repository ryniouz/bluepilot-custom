"""
Console Bluetooth page (Connect > Bluetooth).

  Left    the adapter: present or not, on/off, what is paired
  Right   three tabs
            Devices      search nearby, pair, forget
            OBD scanner  a four-step wizard: plug in, connect (Wi-Fi, USB or Bluetooth), test, live data
            Phone        the planned Android link (pair now; live data later)

Stock AGNOS is built with CONFIG_BT=n, so there is no adapter and the page says so. With the Citadel Bluetooth
boot image, the on/off switch (BPBluetoothEnabled) has bp_btd install BlueZ and bring the adapter up. The OBD
wizard therefore leads with Wi-Fi and USB ELM327 adapters, which PR #2's bp_obdd reads (obdStateBP).

Built:     adapter check, search, pair and forget through bluetoothctl (when the OS has an adapter),
           OBD setup over Wi-Fi/USB (BPObdTransport, BPObdAddress, BPObdEnabled) with live link status and values.
Not built: any data link to the phone. Those carry an "In development" tag.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import pyray as rl

from openpilot.common.params import Params
from openpilot.system.hardware import TICI
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import DialogResult, Widget
from openpilot.system.ui.widgets.keyboard import Keyboard
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.lib.bluetooth import BtDevice, bluetooth, save, saved
from bluepilot.ui.lib.obd_link import DEFAULT_WIFI, LINK_TEXT, fmt_value, obd_link
from bluepilot.ui.lib.theme import Console, roundness, with_alpha

GAP = 32
DEV_ROW = 104
TABS = ["Devices", "OBD scanner", "Phone"]
OBD_STEPS = ["Plug in", "Connect", "Test", "Live data"]


TRANSPORT_IDX = {"wifi": 0, "usb": 1, "bluetooth": 2, "simulated": 3}


def _text(v) -> str:
  if isinstance(v, bytes):
    v = v.decode(errors="ignore")
  return str(v or "").strip()


BTD_TEXT = {
  "off": ("Off", lambda: Console.TEXT_GHOST),
  "installing": ("Installing Bluetooth tools", lambda: Console.ACCENT),
  "starting": ("Starting", lambda: Console.ACCENT),
  "waiting": ("Finishes setting up when parked", lambda: Console.WARNING),
  "error": ("Couldn't start", lambda: Console.DANGER),
}


def btd_status(params: Params) -> dict:
  """BPBluetoothStatus from bp_btd: state, message, kernel, bluez, adapter."""
  try:
    raw = params.get("BPBluetoothStatus")
    data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    return data if isinstance(data, dict) else {}
  except Exception:
    return {}


def dev_tag(x: float, y: float, label: str, color: rl.Color) -> float:
  w = D.text_w(label, 24, semi=True) + 28
  r = rl.Rectangle(x, y, w, 40)
  rl.draw_rectangle_rounded(r, roundness(r, 10), 8, with_alpha(color, 0x2E))
  D.text(label, x + 14, y + 7, 24, color, semi=True)
  return w


def in_dev(x: float, y: float) -> float:
  return dev_tag(x, y, tr("In development"), Console.WARNING)


class BluetoothPage(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._tab = 0
    self._obd_step = 0
    self._obd_kind = 0
    self._addr_draft = ""
    self._keyboard: Keyboard | None = None
    self._hits: list[tuple[rl.Rectangle, Callable[[], None]]] = []

  def show_event(self):
    super().show_event()
    bluetooth().refresh()
    link = obd_link()
    on = link.available() and bool(link.get("BPObdEnabled", False))
    self._obd_step = 2 if on else 0
    self._obd_kind = max(0, TRANSPORT_IDX.get(_text(link.get("BPObdTransport", "wifi")), 0))

  # -- render -------------------------------------------------------------------------------

  def _render(self, rect: rl.Rectangle):
    self._hits = []
    left, right = K.split_cols(rect, [0.82, 1.6])
    left.width -= GAP / 2
    right.x += GAP / 2
    right.width -= GAP / 2
    st = bluetooth().state
    self._adapter_card(left, st)
    seg = rl.Rectangle(right.x, right.y, right.width, 80)
    for i, sr in enumerate(D.segmented(seg, [tr(t) for t in TABS], self._tab, size=D.BODY - 2)):
      self._hits.append((sr, lambda i=i: self._set_tab(i)))
    body = rl.Rectangle(right.x, right.y + 80 + 24, right.width, right.height - 80 - 24)
    [self._devices_tab, self._obd_tab, self._phone_tab][self._tab](body, st)

  def _adapter_card(self, r: rl.Rectangle, st):
    D.card(r)
    p = D.CARD_PAD
    x, y, right = r.x + p, r.y + p, r.x + r.width - p
    D.text(tr("Bluetooth"), x, y, D.H2, semi=True)
    usable = st.adapter and st.tool
    # Custom: the on/off setting; bp_btd installs BlueZ and brings the adapter up (bluepilot/system/bluetooth)
    btd = btd_status(self._params)
    enabled = self._params.get_bool("BPBluetoothEnabled")
    if btd.get("kernel") or usable:
      tg = D.toggle(right - 104, y - 8, enabled)
      self._hits.append((tg, lambda: self._set_enabled(not enabled)))
    y += 84
    state = str(btd.get("state") or "")
    if not st.checked_at and not state:
      status, color = tr("Checking…"), Console.TEXT_GHOST
    elif state == "no_kernel" or (not btd and not st.adapter):
      status, color = tr("Needs the Bluetooth OS update"), Console.WARNING
    elif state in BTD_TEXT:
      status, color = tr(BTD_TEXT[state][0]), BTD_TEXT[state][1]()
    elif not st.adapter:
      status, color = tr("No Bluetooth adapter"), Console.WARNING
    elif not st.tool:
      status, color = tr("Bluetooth tools missing"), Console.WARNING
    else:
      status, color = (tr("On") if st.powered else tr("Off")), (Console.SUCCESS if st.powered else Console.TEXT_GHOST)
    D.dot(x + 10, y + D.BODY / 2 + 2, 10, color)
    D.text(D.fit(status, D.BODY, r.width - 2 * p - 36, semi=True), x + 36, y, D.BODY, semi=True)
    y += 72
    rows = [(tr("Adapter"), tr("Found") if st.adapter else tr("Not found")),
            (tr("Paired devices"), str(sum(1 for d in st.devices if d.paired)))]
    obd, phone = saved(self._params, "BPObdDongle"), saved(self._params, "BPPhoneLink")
    link = obd_link()
    if link.available() and link.get("BPObdEnabled", False):
      kind = _text(link.get("BPObdTransport", "wifi"))
      obd_txt = {"wifi": tr("Wi-Fi adapter"), "usb": tr("USB adapter")}.get(kind, obd["name"] if obd else kind)
    else:
      obd_txt = tr("None")
    rows.append((tr("OBD adapter"), obd_txt))
    rows.append((tr("Phone"), phone["name"] if phone else tr("None")))
    for label, value in rows:
      K.hline(x, right, y)
      D.text(label, x, y + 20, D.LABEL, Console.TEXT_MUTED)
      D.text_right(D.fit(value, D.LABEL, r.width * 0.55, semi=True), right, y + 20, D.LABEL, semi=True)
      y += 70
    if state == "error" and btd.get("message"):
      note = str(btd["message"])
    elif state == "waiting":
      note = tr("Bluetooth finishes setting up the next time the truck is parked.")
    elif state in ("installing", "starting"):
      note = tr("Setting up Bluetooth. The first time takes about a minute.")
    elif btd.get("kernel") and not usable and not enabled:
      note = tr("Turn Bluetooth on to finish setting it up. The first time takes about a minute and only runs while parked.")
    else:
      note = tr("This comma's OS doesn't have Bluetooth yet. It needs the Citadel Bluetooth OS update (a new boot image).")
    if st.checked_at and not usable and (state != "on"):
      y += 16
      for ln in D.wrap(note, D.LABEL, r.width - 2 * p, 6):
        D.text(ln, x, y, D.LABEL, Console.TEXT_SECONDARY)
        y += 40

  def _set_enabled(self, on: bool):
    try:
      self._params.put_bool("BPBluetoothEnabled", on)
    except Exception:
      pass
    if bluetooth().state.adapter and bluetooth().state.tool:
      bluetooth().power(on)

  # -- tabs ---------------------------------------------------------------------------------

  def _device_list(self, r: rl.Rectangle, y: float, st, devices: list[BtDevice], action: str,
                   on_pick: Callable[[BtDevice], None]) -> float:
    p = D.CARD_PAD
    x, right = r.x + p, r.x + r.width - p
    if not devices:
      usable = st.adapter and st.tool
      msg = st.message or (tr("Search to find devices nearby.") if usable else
                           tr("Turn Bluetooth on to search for devices.") if btd_status(self._params).get("kernel") else
                           tr("The comma's OS is built without Bluetooth, so there is nothing to search with yet."))
      return self._para(r, x, y + 8, msg, D.BODY, Console.TEXT_MUTED, 3) + 14
    for d in devices:
      if y + DEV_ROW > r.y + r.height - p - D.CONTROL_H - 16:
        break
      K.hline(x, right, y)
      D.icon("plug" if d.looks_like_obd else "phone", x, y + 28, 44, Console.TEXT_SECONDARY)
      D.text(D.fit(d.name, D.BODY, r.width * 0.5, semi=True), x + 68, y + 16, D.BODY, semi=True)
      tx = x + 68
      D.text(d.mac[-8:], tx, y + 60, D.LABEL, Console.TEXT_MUTED)
      if d.paired:
        dev_tag(tx + D.text_w(d.mac[-8:], D.LABEL) + 16, y + 56, tr("Paired"), Console.SUCCESS)
      lw = D.text_w(action, D.LABEL, semi=True) + 56
      b = rl.Rectangle(right - lw, y + (DEV_ROW - 64) / 2, lw, 64)
      D.button(b, action, primary=False, size=D.LABEL)
      self._hits.append((b, lambda d=d: on_pick(d)))
      y += DEV_ROW
    return y

  def _search_button(self, r: rl.Rectangle, st):
    p = D.CARD_PAD
    b = rl.Rectangle(r.x + p, r.y + r.height - p - D.CONTROL_H, r.width - 2 * p, D.CONTROL_H)
    usable = st.adapter and st.tool
    if st.busy:
      D.button(b, tr(st.busy) + "…", primary=False)
    elif usable:
      D.button(b, tr("Search for devices"), primary=True)
      self._hits.append((b, bluetooth().scan))
    else:
      in_dev(b.x, b.y + (D.CONTROL_H - 40) / 2)
      D.text(tr("Needs Bluetooth in the comma's OS"), b.x + 220, b.y + (D.CONTROL_H - D.LABEL) / 2, D.LABEL, Console.TEXT_MUTED)

  def _devices_tab(self, r: rl.Rectangle, st):
    D.card(r)
    p = D.CARD_PAD
    D.text(tr("Devices"), r.x + p, r.y + p, D.H2, semi=True)
    self._device_list(r, r.y + p + 76, st, st.devices, tr("Forget"),
                      lambda d: bluetooth().forget(d.mac) if d.paired else bluetooth().pair(d.mac))
    self._search_button(r, st)

  def _stepper(self, r: rl.Rectangle, y: float, steps: list[str], current: int) -> float:
    p = D.CARD_PAD
    n = len(steps)
    w = (r.width - 2 * p - 16 * (n - 1)) / n
    for i, s in enumerate(steps):
      x = r.x + p + i * (w + 16)
      bar = rl.Rectangle(x, y, w, 12)
      rl.draw_rectangle_rounded(bar, roundness(bar, 3), 4, Console.ACCENT_FILL if i <= current else Console.BG_TRACK)
      D.text(D.fit(f"{i + 1}  {tr(s)}", D.LABEL, w, semi=i == current), x, y + 24, D.LABEL,
             Console.TEXT_PRIMARY if i == current else Console.TEXT_MUTED, semi=i == current)
    return y + 84

  def _obd_tab(self, r: rl.Rectangle, st):
    D.card(r)
    p = D.CARD_PAD
    x, right = r.x + p, r.x + r.width - p
    D.text(tr("OBD scanner"), x, r.y + p, D.H2, semi=True)
    y = self._stepper(r, r.y + p + 76, OBD_STEPS, self._obd_step)
    link = obd_link()
    snap = link.snapshot()
    [self._obd_plug, self._obd_connect, self._obd_test, self._obd_live][self._obd_step](r, x, right, y, st, link, snap)

  def _para(self, r: rl.Rectangle, x: float, y: float, text: str, size: int = D.BODY, color=None, lines: int = 4) -> float:
    lh = 50 if size == D.BODY else 40
    for ln in D.wrap(text, size, r.width - 2 * D.CARD_PAD, lines):
      D.text(ln, x, y, size, color or Console.TEXT_SECONDARY)
      y += lh
    return y

  def _obd_plug(self, r, x, right, y, st, link, snap):
    y = self._para(r, x, y, tr("Plug a Wi-Fi or USB OBD adapter (ELM327 type) into the diagnostic port under the dash, " +
                               "left of the steering column. Its light comes on."))
    y += 24
    self._para(r, x, y, tr("The comma's operating system (AGNOS) is built without Bluetooth, so a Bluetooth-only dongle " +
                           "can't connect to it directly."), D.LABEL, Console.TEXT_MUTED, 3)
    self._next_button(r, tr("It's plugged in"), lambda: self._go_obd(1))

  def _obd_connect(self, r, x, right, y, st, link, snap):
    seg = rl.Rectangle(x, y, right - x, 72)
    kinds = [tr("Wi-Fi"), tr("USB"), tr("Bluetooth")] + ([] if TICI else [tr("Simulated")])
    for i, sr in enumerate(D.segmented(seg, kinds, self._obd_kind, size=D.LABEL)):
      self._hits.append((sr, lambda i=i: self._set_obd_kind(i)))
    y += 72 + 28
    ready = link.available()
    go: Callable[[], None] | None = None
    if self._obd_kind == 0:
      addr = self._wifi_addr(link)
      K.hline(x, right, y)
      D.text(tr("Adapter address"), x, y + 20, D.BODY, Console.TEXT_MUTED)
      bw = D.text_w(tr("Edit"), D.LABEL, semi=True) + 56
      b = rl.Rectangle(right - bw, y + 12, bw, 64)
      D.button(b, tr("Edit"), primary=False, size=D.LABEL)
      self._hits.append((b, lambda: self._edit_addr(link)))
      D.text_right(D.fit(addr, D.BODY, right - x - bw - 320, semi=True), right - bw - 24, y + 20, D.BODY, semi=True)
      y += 96
      self._para(r, x, y, tr("Most Wi-Fi adapters make their own network (often WiFi_OBDII). Join it in Wi-Fi first. " +
                             "The comma leaves your home Wi-Fi while it's on the adapter's network."), D.LABEL, Console.TEXT_MUTED, 3)
      go = lambda: self._connect(link, "wifi", addr)  # noqa: E731
    elif self._obd_kind == 1:
      devs = snap.usb_devices
      K.hline(x, right, y)
      D.text(tr("USB adapter"), x, y + 20, D.BODY, Console.TEXT_MUTED)
      D.text_right(D.fit(devs[0] if devs else tr("Not found"), D.BODY, r.width * 0.45, semi=True), right, y + 20, D.BODY,
                   Console.TEXT_PRIMARY if devs else Console.TEXT_GHOST, semi=True)
      y += 96
      self._para(r, x, y, tr("Plug the adapter's USB cable into the comma. It shows here a few seconds later. " +
                             "If several are found, the first one is used."), D.LABEL, Console.TEXT_MUTED, 3)
      go = lambda: self._connect(link, "usb", devs[0] if devs else "")  # noqa: E731
    elif self._obd_kind == 3:
      y = self._para(r, x, y, tr("A pretend adapter that answers like a parked, charging Lightning. For the PC simulator only."),
                     D.LABEL, Console.TEXT_MUTED, 3)
      go = lambda: self._connect(link, "simulated", "")  # noqa: E731
    else:
      if st.adapter and st.tool:
        obd = [d for d in st.devices if d.looks_like_obd] or st.devices
        self._device_list(r, y, st, obd, tr("Choose"), self._choose_dongle)
        dongle = saved(self._params, "BPObdDongle")
        if dongle:
          go = lambda: self._connect(link, "bluetooth", dongle["mac"])  # noqa: E731
      else:
        D.text(tr("Not available on this comma"), x, y, D.BODY, Console.WARNING, semi=True)
        y += 64
        y = self._para(r, x, y, tr("AGNOS, the comma's OS, is built without Bluetooth. Using a Bluetooth dongle needs a custom AGNOS " +
                                   "build, which is being looked into."), D.LABEL, Console.TEXT_MUTED, 3)
        in_dev(x, y + 12)
        return
    if not ready:
      in_dev(x, r.y + r.height - D.CARD_PAD - D.CONTROL_H - 64)
      D.text(tr("OBD service not in this build"), x + 220, r.y + r.height - D.CARD_PAD - D.CONTROL_H - 58, D.LABEL, Console.TEXT_MUTED)
      go = None
    self._next_button(r, tr("Connect"), go)

  def _obd_test(self, r, x, right, y, st, link, snap):
    state = snap.link if snap.received else ("connecting" if link.get("BPObdEnabled", False) else "off")
    color = {"connected": Console.SUCCESS, "error": Console.DANGER, "unavailable": Console.WARNING,
             "carAsleep": Console.WARNING}.get(state, Console.TEXT_GHOST)
    D.dot(x + 10, y + D.H2 / 2, 12, color)
    D.text(tr(LINK_TEXT.get(state, state)), x + 40, y - 4, D.H2, semi=True)
    y += 72
    if snap.message:
      y = self._para(r, x, y, snap.message, D.LABEL, Console.TEXT_MUTED, 2) + 8
    kind = _text(link.get("BPObdTransport", "wifi"))
    rows = [(tr("Connection"), {"wifi": tr("Wi-Fi"), "usb": tr("USB"), "bluetooth": tr("Bluetooth"), "simulated": tr("Simulated")}.get(kind, kind)),
            (tr("Address"), _text(link.get("BPObdAddress", "")) or tr("Automatic")),
            (tr("Adapter"), snap.adapter or "–"),
            (tr("Protocol"), snap.protocol or "–")]
    for label, value in rows:
      K.hline(x, right, y)
      D.text(label, x, y + 20, D.LABEL, Console.TEXT_MUTED)
      D.text_right(D.fit(value, D.LABEL, r.width * 0.6, semi=True), right, y + 20, D.LABEL, semi=True)
      y += 70
    if state in ("connected", "idle"):
      self._next_button(r, tr("Show live data"), lambda: self._go_obd(3))
    else:
      self._next_button(r, tr("Back"), lambda: self._go_obd(1), primary=False)

  def _obd_live(self, r, x, right, y, st, link, snap):
    bottom = r.y + r.height - D.CARD_PAD - D.CONTROL_H - 24
    if link.has("BPObdPollWhenOff"):
      bottom -= 96
      when_off = bool(link.get("BPObdPollWhenOff", False))
      K.hline(x, right, bottom + 8)
      D.text(tr("Read while the truck is off"), x, bottom + 20, D.LABEL, semi=True)
      D.text(tr("May drain the 12 V battery"), x, bottom + 56, D.LABEL - 4, Console.TEXT_MUTED)
      tg = D.toggle(right - 104, bottom + 26, when_off)
      self._hits.append((tg, lambda: link.put_bool("BPObdPollWhenOff", not when_off)))
    if not snap.polling and snap.received:
      y = self._para(r, x, y, tr("Paused while the truck is off and not charging, to spare the 12 V battery."),
                     D.LABEL, Console.TEXT_MUTED, 2) + 8
    if not snap.values:
      D.text(tr("No answers from the truck yet"), x, y + 8, D.BODY, Console.TEXT_MUTED)
    for v in snap.values:
      if y + 64 > bottom:
        break
      K.hline(x, right, y)
      D.text(D.fit(v.label or v.name, D.LABEL, r.width * 0.55), x, y + 16, D.LABEL, Console.TEXT_MUTED)
      D.text_right(fmt_value(v), right, y + 16, D.LABEL, Console.TEXT_GHOST if v.age_s > 30 else Console.TEXT_PRIMARY, semi=True)
      y += 64
    self._next_button(r, tr("Turn off OBD"), self._obd_off, primary=False)

  def _phone_tab(self, r: rl.Rectangle, st):
    D.card(r)
    p = D.CARD_PAD
    x, right = r.x + p, r.x + r.width - p
    D.text(tr("Phone"), x, r.y + p, D.H2, semi=True)
    in_dev(right - 200, r.y + p + 2)
    y = r.y + p + 84
    phone = saved(self._params, "BPPhoneLink")
    pick = tr("Choose it below") if st.adapter and st.tool else tr("Needs Bluetooth in the comma's OS")
    steps = [(tr("Pair your Android phone"), tr("Paired with") + f" {phone['name']}" if phone else pick, bool(phone)),
             (tr("Open the EV app on the phone"), tr("The app side is still to be built"), False),
             (tr("Live truck data on the phone"), tr("Charge, range, tires and trips while you drive"), False)]
    for i, (title, sub, done) in enumerate(steps):
      K.hline(x, right, y)
      c = rl.Rectangle(x, y + 26, 52, 52)
      rl.draw_rectangle_rounded(c, 1.0, 16, Console.SUCCESS if done else Console.BG_RAISED)
      if done:
        D.icon("check", c.x + 10, c.y + 10, 32, Console.ON_ACCENT)
      else:
        D.text_center(str(i + 1), c.x + 26, c.y + 10, 30, Console.TEXT_SECONDARY, semi=True)
      D.text(title, x + 76, y + 16, D.BODY, semi=True)
      D.text(D.fit(sub, D.LABEL, r.width - 2 * p - 76), x + 76, y + 58, D.LABEL, Console.TEXT_MUTED)
      y += 104
    y += 8
    others = [d for d in st.devices if not d.looks_like_obd]
    if not phone:
      self._device_list(r, y, st, others, tr("Choose"), lambda d: save(self._params, "BPPhoneLink", d))
      self._search_button(r, st)
    else:
      self._next_button(r, tr("Forget phone"), lambda: save(self._params, "BPPhoneLink", None), primary=False)

  # -- actions ------------------------------------------------------------------------------

  def _next_button(self, r: rl.Rectangle, label: str, fn: Callable[[], None] | None, primary: bool = True):
    p = D.CARD_PAD
    b = rl.Rectangle(r.x + p, r.y + r.height - p - D.CONTROL_H, r.width - 2 * p, D.CONTROL_H)
    D.button(b, label, primary=primary and fn is not None)
    if fn is not None:
      self._hits.append((b, fn))

  def _set_tab(self, i: int):
    self._tab = i

  def _go_obd(self, step: int):
    self._obd_step = step

  def _choose_dongle(self, d: BtDevice):
    save(self._params, "BPObdDongle", d)
    if not d.paired:
      bluetooth().pair(d.mac)

  def _set_obd_kind(self, i: int):
    self._obd_kind = i

  @staticmethod
  def _wifi_addr(link) -> str:
    addr = _text(link.get("BPObdAddress", ""))
    return addr if addr and not addr.startswith("/dev") and ":" in addr and addr.count(":") == 1 else DEFAULT_WIFI

  def _connect(self, link, transport: str, address: str):
    link.configure(transport, address)
    self._obd_step = 2

  def _obd_off(self):
    obd_link().disable()
    self._obd_step = 0

  def _edit_addr(self, link):
    if self._keyboard is None:
      self._keyboard = Keyboard(max_text_size=64, min_text_size=0)

    def done(result: DialogResult):
      if result != DialogResult.CONFIRM or self._keyboard is None:
        return
      addr = self._keyboard.text.strip() or DEFAULT_WIFI
      if link.available():
        self._params.put("BPObdAddress", addr)
      self._addr_draft = addr

    self._keyboard.reset(min_text_size=0)
    self._keyboard.set_title(tr("Adapter address"), tr("IP and port, for example") + " " + DEFAULT_WIFI)
    self._keyboard.set_text(self._wifi_addr(link))
    self._keyboard.set_callback(done)
    gui_app.push_widget(self._keyboard)

  def _handle_mouse_release(self, pos) -> bool:
    for r, fn in self._hits:
      if D.hit(r, pos):
        fn()
        return True
    return False
