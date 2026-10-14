"""
Console Bluetooth page (Connect > Bluetooth).

  Left    the adapter: present or not, on/off, what is paired
  Right   three tabs
            Devices      search nearby, pair, forget
            OBD scanner  a four-step wizard: plug in, choose the dongle, pair, read data
            Phone        the planned Android link (pair now; live data later)

Built:     adapter check, search, pair and forget through bluetoothctl (when the OS has an adapter),
           saving the chosen OBD dongle (BPObdDongle) and phone (BPPhoneLink).
Not built: reading OBD data from the dongle and any data link to the phone. Those steps carry an
           "In development" tag and do nothing.
"""

from __future__ import annotations

from collections.abc import Callable

import pyray as rl

from openpilot.common.params import Params
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.lib.bluetooth import BtDevice, bluetooth, save, saved
from bluepilot.ui.lib.theme import Console, roundness, with_alpha

GAP = 32
DEV_ROW = 104
TABS = ["Devices", "OBD scanner", "Phone"]
OBD_STEPS = ["Plug in", "Choose", "Pair", "Read data"]


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
    self._hits: list[tuple[rl.Rectangle, Callable[[], None]]] = []

  def show_event(self):
    super().show_event()
    bluetooth().refresh()
    self._obd_step = 3 if saved(self._params, "BPObdDongle") else 0

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
    if usable:
      tg = D.toggle(right - 104, y - 8, st.powered)
      self._hits.append((tg, lambda: bluetooth().power(not st.powered)))
    y += 84
    if not st.checked_at:
      status, color = tr("Checking…"), Console.TEXT_GHOST
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
    rows.append((tr("OBD dongle"), obd["name"] if obd else tr("None")))
    rows.append((tr("Phone"), phone["name"] if phone else tr("None")))
    for label, value in rows:
      K.hline(x, right, y)
      D.text(label, x, y + 20, D.LABEL, Console.TEXT_MUTED)
      D.text_right(D.fit(value, D.LABEL, r.width * 0.55, semi=True), right, y + 20, D.LABEL, semi=True)
      y += 70
    if st.checked_at and not usable:
      note = tr("This comma's system image doesn't offer Bluetooth. Turning it on needs a change to AGNOS, the comma's OS.") \
        if not st.adapter else tr("The OS has an adapter but not the BlueZ tools needed to pair.")
      y += 16
      for ln in D.wrap(note, D.LABEL, r.width - 2 * p, 6):
        D.text(ln, x, y, D.LABEL, Console.TEXT_SECONDARY)
        y += 40

  # -- tabs ---------------------------------------------------------------------------------

  def _device_list(self, r: rl.Rectangle, y: float, st, devices: list[BtDevice], action: str,
                   on_pick: Callable[[BtDevice], None]) -> float:
    p = D.CARD_PAD
    x, right = r.x + p, r.x + r.width - p
    if not devices:
      msg = st.message or (tr("Search to find devices nearby.") if st.adapter and st.tool else tr("Nothing to show without Bluetooth."))
      D.text(msg, x, y + 8, D.BODY, Console.TEXT_MUTED)
      return y + 64
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
      D.button(b, tr("Search for devices"), primary=False)

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
    dongle = saved(self._params, "BPObdDongle")
    if self._obd_step == 0:
      for i, ln in enumerate(D.wrap(tr("Plug the OBD dongle into the diagnostic port under the dash, left of the steering column. Its light comes on."),
                                    D.BODY, r.width - 2 * p, 4)):
        D.text(ln, x, y + i * 50, D.BODY, Console.TEXT_SECONDARY)
      self._next_button(r, tr("It's plugged in"), lambda: self._go_obd(1))
    elif self._obd_step == 1:
      obd = [d for d in st.devices if d.looks_like_obd] or st.devices
      self._device_list(r, y, st, obd, tr("Choose"), self._choose_dongle)
      self._search_button(r, st)
    elif self._obd_step == 2:
      name = dongle["name"] if dongle else "–"
      D.text(D.fit(name, D.H2, r.width - 2 * p, semi=True), x, y, D.H2, semi=True)
      paired = any(d.paired and dongle and d.mac == dongle["mac"] for d in st.devices)
      msg = tr("Paired. The comma will reconnect to it on its own.") if paired else \
        tr("Most dongles pair without a code. If one asks, the code is usually 1234 or 0000.")
      for i, ln in enumerate(D.wrap(msg, D.BODY, r.width - 2 * p, 3)):
        D.text(ln, x, y + 72 + i * 50, D.BODY, Console.TEXT_SECONDARY)
      if paired:
        self._next_button(r, tr("Next"), lambda: self._go_obd(3))
      elif st.busy:
        self._next_button(r, tr(st.busy) + "…", None)
      elif dongle:
        self._next_button(r, tr("Pair"), lambda: bluetooth().pair(dongle["mac"]))
    else:
      D.text(D.fit(dongle["name"] if dongle else tr("No dongle chosen"), D.H2, r.width - 2 * p - 220, semi=True), x, y, D.H2, semi=True)
      in_dev(right - 200, y + 2)
      y += 76
      rows = [(tr("Link"), tr("Paired") if dongle else "–"),
              (tr("Battery health and capacity"), tr("Not read yet")),
              (tr("Heater power, charger details"), tr("Not read yet"))]
      for label, value in rows:
        K.hline(x, right, y)
        D.text(label, x, y + 22, D.BODY, Console.TEXT_MUTED)
        D.text_right(value, right, y + 22, D.BODY, Console.TEXT_GHOST, semi=True)
        y += 84
      for i, ln in enumerate(D.wrap(tr("Reading data from the dongle is being built. Until then, what the truck shares on its own still shows everywhere."),
                                    D.LABEL, r.width - 2 * p, 3)):
        D.text(ln, x, y + 16 + i * 40, D.LABEL, Console.TEXT_MUTED)
      self._next_button(r, tr("Change dongle"), lambda: self._go_obd(1), primary=False)

  def _phone_tab(self, r: rl.Rectangle, st):
    D.card(r)
    p = D.CARD_PAD
    x, right = r.x + p, r.x + r.width - p
    D.text(tr("Phone"), x, r.y + p, D.H2, semi=True)
    in_dev(right - 200, r.y + p + 2)
    y = r.y + p + 84
    phone = saved(self._params, "BPPhoneLink")
    steps = [(tr("Pair your Android phone"), tr("Paired with") + f" {phone['name']}" if phone else tr("Choose it below"), bool(phone)),
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
    self._obd_step = 3 if d.paired else 2

  def _handle_mouse_release(self, pos) -> bool:
    for r, fn in self._hits:
      if D.hit(r, pos):
        fn()
        return True
    return False
