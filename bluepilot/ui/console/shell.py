"""
Console shell for the comma 3X: roomy, phone-like navigation in the Console theme.

  rail        Home, Drive, Energy, Screen, Connect, System (icon and label)
  header      section title, alert / update / network chips, one page action, clock
  page        Home's cards, or a section's page list beside one big card

Settings sections host the existing openpilot / sunnypilot / BluePilot panel widgets, so every
feature keeps working. Other modules add pages with register_page().
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum

import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.scroller_tici import Scroller
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.console.home import network_status
from bluepilot.ui.lib.theme import Console, is_day, roundness

RAIL_W = 152
HEADER_H = 128
SUBNAV_W = 480
GUTTER = 32


class Dest(IntEnum):
  HOME = 0
  DRIVE = 1
  ENERGY = 2
  SCREEN = 3
  CONNECT = 4
  SYSTEM = 5
  DRIVES = 6


SECTIONS = [
  (Dest.HOME, "Home", "home"),
  (Dest.DRIVE, "Drive", "wheel"),
  (Dest.ENERGY, "Energy", "bolt"),
  (Dest.DRIVES, "Drives", "route"),
  (Dest.SCREEN, "Screen", "screen"),
  (Dest.CONNECT, "Connect", "wifi"),
  (Dest.SYSTEM, "System", "sliders"),
]


@dataclass
class Page:
  title: str
  icon: str
  widget: Widget
  key: object = None                                    # a settings PanelType or a page name, for open_panel()
  subtitle: str | Callable[[], str] = ""                # "Section | status": text after | follows the dot
  sub_dot: Callable[[], rl.Color | None] | None = None
  action: Callable[[], str | None] | None = None        # header button label, or None for no button
  on_action: Callable[[], None] | None = None
  framed: bool = True                                   # draw the page body inside one panel
  aliases: tuple = ()                                   # older keys that open this page (merged pages)


class ItemsPage(Widget):
  """A list page made of existing list items (rows moved off the BluePilot panel)."""

  def __init__(self, items: list, on_show: Callable[[], None] | None = None):
    super().__init__()
    self._scroller = Scroller(items, line_separator=True, spacing=0)
    self._on_show = on_show

  def show_event(self):
    super().show_event()
    if self._on_show is not None:  # rows whose param can change elsewhere (quick controls) re-read it
      self._on_show()
    self._scroller.show_event()

  def _render(self, rect):
    self._scroller.render(rect)


class ConsoleShell(Widget):
  def __init__(self, settings_layout, home: Widget, alerts: Widget | None = None):
    super().__init__()
    from openpilot.selfdrive.ui.layouts.settings import settings as _settings_mod
    PT = _settings_mod.PanelType
    self._panels = settings_layout._panels
    self._dest = Dest.HOME
    self._sub: dict[Dest, int] = dict.fromkeys(Dest, 0)
    self._pages: dict[Dest, list[Page]] = {d: [] for d in Dest}
    self._tab_rects: list[rl.Rectangle] = []
    self._sub_rects: list[rl.Rectangle] = []
    self._chip_rects: list[tuple[rl.Rectangle, str]] = []
    self._params = Params()
    self._wifi_key = getattr(PT, "NETWORK", None)
    self._software_key = "updates"
    self._action_rect: rl.Rectangle | None = None
    self._current: Widget | None = None
    self.alert_count: Callable[[], int] = lambda: 0

    bp_items = {}
    bp = self._panels.get(PT.BLUEPILOT) if hasattr(PT, "BLUEPILOT") else None
    if bp is not None and hasattr(bp.instance, "console_page_items"):
      bp_items = bp.instance.console_page_items()
    refresh = getattr(bp.instance, "console_page_refresh", None) if bp is not None else None
    items = {k: ItemsPage(v, refresh) for k, v in bp_items.items()}

    def panel(dest, title, icon, name, sub=""):
      pt = getattr(PT, name, None)
      info = self._panels.get(pt) if pt is not None else None
      if info is not None:
        self.register_page(dest, Page(title, icon, info.instance, key=pt, subtitle=sub))

    def item_page(dest, title, icon, name, sub=""):
      if name in items:
        self.register_page(dest, Page(title, icon, items[name], key=name, subtitle=sub))

    self.register_page(Dest.HOME, Page(tr("Overview"), "grid", home, key="overview", framed=False))
    if alerts is not None:
      self.register_page(Dest.HOME, Page(tr("Alerts"), "bell", alerts, key="alerts", subtitle=tr("Home"),
                                         action=lambda: tr("Back"), on_action=lambda: self.go(Dest.HOME, 0)))

    drive = tr("Drive") + " | " + tr("Changes apply on the next drive")
    panel(Dest.DRIVE, tr("Assist"), "gauge", "TOGGLES", drive)
    panel(Dest.DRIVE, tr("Steering"), "steer", "STEERING", drive)
    self._hide_torque_rows(PT)
    panel(Dest.DRIVE, tr("Speed and cruise"), "pulse", "CRUISE", drive)
    panel(Dest.DRIVE, tr("Driving model"), "cpu", "MODELS", tr("Drive"))
    panel(Dest.DRIVE, tr("BluePilot tuning"), "tune", "BLUEPILOT", drive)

    item_page(Dest.ENERGY, tr("Charging settings"), "sliders", "charging", tr("Energy"))
    panel(Dest.ENERGY, tr("Trips"), "route", "TRIPS", tr("Energy"))

    from bluepilot.ui.console.pages.drives import DrivesPage
    drives = DrivesPage()
    self.register_page(Dest.DRIVES, Page(tr("Previous drives"), "list", drives, key="drives", framed=False))
    # Uploads: the old Offloading and Upload settings pages merged; their keys still open it
    from bluepilot.ui.console.pages.uploads import UploadsPage
    wifi = self._panels.get(PT.NETWORK) if hasattr(PT, "NETWORK") else None
    self.register_page(Dest.DRIVES, Page(tr("Uploads"), "cloud",
                                         UploadsPage(getattr(wifi.instance, "_wifi_manager", None) if wifi is not None else None),
                                         key="uploads", framed=False, aliases=("drives_offload", "upload_settings")))

    item_page(Dest.SCREEN, tr("Theme and layout"), "palette", "theme", tr("Screen") + " | " + tr("Applies right away"))
    panel(Dest.SCREEN, tr("Visuals"), "eye", "VISUALS", tr("Screen"))
    panel(Dest.SCREEN, tr("Display"), "screen", "DISPLAY", tr("Screen"))

    from bluepilot.ui.console.pages.connectivity import ConnectivityPage
    net = self._panels.get(PT.NETWORK) if hasattr(PT, "NETWORK") else None
    self.connectivity = ConnectivityPage(getattr(net.instance, "_wifi_manager", None) if net is not None else None)
    self.connectivity.on_open_wifi = lambda: self.open_panel(self._wifi_key)
    self.connectivity.on_open_export = lambda: self.open_panel("export")
    self.connectivity.on_open_uploads = lambda: self.open_panel("uploads")
    self.connectivity.on_open_cellular = lambda: self.open_panel("cellular")
    self.register_page(Dest.CONNECT, Page(tr("Status"), "pulse", self.connectivity, key="connectivity", framed=False))
    from bluepilot.ui.console.pages.cellular import CellularPage
    cellular = CellularPage(self.connectivity._wifi)
    cellular.on_open_uploads = lambda: self.open_panel("uploads")
    self.register_page(Dest.CONNECT, Page(tr("Cellular"), "cell", cellular, key="cellular", framed=False))
    panel(Dest.CONNECT, tr("Wi-Fi"), "wifi", "NETWORK", tr("Connect"))
    from bluepilot.ui.console.pages.automations import AutomationsPage
    autos = AutomationsPage()
    autos.on_open_wifi = lambda: self.open_panel(self._wifi_key)
    self.register_page(Dest.CONNECT, Page(tr("Home automations"), "home", autos, key="automations", framed=False))
    self.connectivity.on_open_automations = lambda: self.open_panel("automations")
    from bluepilot.ui.console.pages.bluetooth import BluetoothPage
    self.bluetooth = BluetoothPage()
    self.register_page(Dest.CONNECT, Page(tr("Bluetooth"), "bluetooth", self.bluetooth, key="bluetooth", framed=False))
    panel(Dest.CONNECT, tr("sunnylink"), "cloud", "SUNNYLINK", tr("Connect"))
    panel(Dest.CONNECT, tr("Firehose"), "flame", "FIREHOSE", tr("Connect"))
    panel(Dest.CONNECT, tr("BluePilot Portal"), "phone", "BP_PORTAL", tr("Connect"))
    item_page(Dest.CONNECT, tr("Data export"), "export", "export", tr("Connect"))

    # System: Updates (the old Software page merged in), Truck, Device, Calibration, Storage, Maps, Developer, About
    from bluepilot.ui.console.pages.updates import UpdatesPage
    self.register_page(Dest.SYSTEM, Page(tr("Updates"), "download", UpdatesPage(), key="updates", framed=False,
                                         aliases=tuple(k for k in (getattr(PT, "SOFTWARE", None),) if k is not None)))
    # This build only drives the F-150 Lightning: its own page instead of sunnypilot's all-makes vehicle panel
    from bluepilot.ui.console.pages.vehicle import VehiclePage
    vehicle = VehiclePage()
    vehicle.on_open_obd = self.open_obd
    self.register_page(Dest.SYSTEM, Page(tr("Truck"), "car", vehicle, key="vehicle", framed=False))
    from bluepilot.ui.console.pages.device import DevicePage
    self.register_page(Dest.SYSTEM, Page(tr("Device"), "cpu", DevicePage(), key=getattr(PT, "DEVICE", "device"), framed=False))
    from bluepilot.ui.console.pages.calibration import CalibrationPage
    self.register_page(Dest.SYSTEM, Page(tr("Calibration"), "calibrate", CalibrationPage(), key="calibration", framed=False))
    from bluepilot.ui.console.pages.storage import StoragePage
    self.register_page(Dest.SYSTEM, Page(tr("Storage"), "storage", StoragePage(), key="drives_storage", framed=False))
    from bluepilot.ui.console.pages.maps import MapsPage
    self.register_page(Dest.SYSTEM, Page(tr("Maps"), "map", MapsPage(), key=getattr(PT, "OSM", "maps"), framed=False))
    from bluepilot.ui.console.pages.developer import DeveloperPage
    self.register_page(Dest.SYSTEM, Page(tr("Developer"), "code", DeveloperPage(), key=getattr(PT, "DEVELOPER", "developer"),
                                         framed=False))
    from bluepilot.ui.console.pages.about import AboutPage
    self.register_page(Dest.SYSTEM, Page(tr("About"), "info", AboutPage(), key="about", subtitle=tr("System"), framed=False))

  def _hide_torque_rows(self, PT):
    """The Lightning steers by curvature: torque control, torque tuning and NNLC never apply, so hide them
    (and the separators above them) instead of showing them greyed out."""
    info = self._panels.get(getattr(PT, "STEERING", None))
    inst = getattr(info, "instance", None)
    scroller = getattr(inst, "_scroller", None)
    hide = [getattr(inst, n, None) for n in ("_torque_control_toggle", "_torque_customization_button", "_nnlc_toggle")]
    items = getattr(scroller, "_items", [])
    for i, item in enumerate(items):
      if item in hide or (i + 1 < len(items) and items[i + 1] in hide and type(item).__name__.startswith("LineSeparator")):
        item.set_visible(False)

  # -- pages ------------------------------------------------------------------------

  def register_page(self, dest: Dest, page: Page, index: int | None = None):
    pages = self._pages[dest]
    pages.insert(len(pages) if index is None else index, page)

  def pages(self, dest: Dest) -> list[Page]:
    return self._pages[dest]

  @property
  def dest(self) -> Dest:
    return self._dest

  def current_page(self) -> Page | None:
    pages = self._pages.get(self._dest) or []
    if not pages:
      return None
    return pages[min(self._sub[self._dest], len(pages) - 1)]

  def go(self, dest: Dest, sub: int | None = None):
    if sub is not None:
      self._sub[dest] = max(0, min(sub, len(self._pages[dest]) - 1))
    self._dest = dest
    p = self.current_page()
    self._switch_to(p.widget if p else None)

  def open_obd(self):
    """Connect > Bluetooth on its OBD scanner tab (OBD adapters work over Wi-Fi and USB too)."""
    if self.open_panel("bluetooth"):
      self.bluetooth._set_tab(1)

  def open_panel(self, key) -> bool:
    """Open the page that hosts a settings PanelType (or a page key)."""
    for dest, pages in self._pages.items():
      for i, p in enumerate(pages):
        if p.key == key or key in p.aliases:
          self.go(dest, i)
          return True
    return False

  def _switch_to(self, w: Widget | None):
    if w is self._current:
      return
    if self._current is not None:
      self._current.hide_event()
    self._current = w
    if w is not None:
      w.show_event()

  def show_event(self):
    super().show_event()
    self._current = None
    p = self.current_page()
    self._switch_to(p.widget if p else None)

  def hide_event(self):
    super().hide_event()
    if self._current is not None:
      self._current.hide_event()
    self._current = None

  # -- render ---------------------------------------------------------------------

  def _render(self, rect: rl.Rectangle):
    rl.draw_rectangle_rec(rect, Console.BG_PAGE)
    self._draw_rail(rl.Rectangle(rect.x, rect.y, RAIL_W, rect.height))
    body = rl.Rectangle(rect.x + RAIL_W, rect.y, rect.width - RAIL_W, rect.height)
    page = self.current_page()
    self._draw_header(rl.Rectangle(body.x, body.y, body.width, HEADER_H), page)
    content = rl.Rectangle(body.x + GUTTER, body.y + HEADER_H, body.width - GUTTER * 2, body.height - HEADER_H - GUTTER)
    if page is None:
      return
    self._switch_to(page.widget)
    pages = self._pages[self._dest]
    self._sub_rects = []

    if len(pages) > 1 and self._dest != Dest.HOME:
      y = content.y
      for i, p in enumerate(pages):
        r = rl.Rectangle(content.x, y, SUBNAV_W - GUTTER, 96)
        self._sub_rects.append(r)
        on = i == self._sub[self._dest]
        if on:
          rl.draw_rectangle_rounded(r, roundness(r, 16), 8, Console.ACCENT_TINT)
        color = Console.ACCENT_TEXT if on else Console.TEXT_SECONDARY
        D.icon(p.icon, r.x + 24, r.y + 28, 40, Console.ACCENT if on else Console.TEXT_MUTED)
        D.text(D.fit(p.title, D.BODY, r.width - 112, semi=on), r.x + 88, r.y + (r.height - D.BODY) / 2 - 2, D.BODY, color, semi=on)
        y += 104
      content = rl.Rectangle(content.x + SUBNAV_W, content.y, content.width - SUBNAV_W, content.height)

    if page.framed:
      D.card(content)
      page.widget.render(rl.Rectangle(content.x + 32, content.y + 12, content.width - 64, content.height - 24))
    else:
      page.widget.render(content)

  def _draw_rail(self, r: rl.Rectangle):
    rl.draw_rectangle_rec(r, Console.BG_PANEL)
    if is_day():
      rl.draw_rectangle_rec(rl.Rectangle(r.x + r.width - 2, r.y, 2, r.height), Console.BORDER_DEFAULT)
    self._tab_rects = []
    y = r.y + 32
    for dest, label, ic in SECTIONS:
      item = rl.Rectangle(r.x + 16, y, r.width - 32, 108)
      self._tab_rects.append(item)
      on = dest == self._dest
      if on:
        rl.draw_rectangle_rounded(item, roundness(item, 16), 8, Console.ACCENT_TINT)
      color = Console.ACCENT_TEXT if on else Console.TEXT_MUTED
      D.icon(ic, item.x + (item.width - 44) / 2, item.y + 14, 44, Console.ACCENT if on else Console.TEXT_MUTED)
      D.text_center(tr(label), item.x + item.width / 2, item.y + 66, D.CAPTION, color, semi=True)
      y += 114

    ready = ui_state.panda_type is not None and str(ui_state.panda_type) != "unknown"
    D.dot(r.x + r.width / 2, r.y + r.height - 86, 10, Console.SUCCESS if ready else Console.TEXT_GHOST)
    D.text_center(tr("Ready") if ready else tr("No car"), r.x + r.width / 2, r.y + r.height - 62, D.CAPTION,
                  Console.TEXT_MUTED, semi=True)

  def _draw_header(self, r: rl.Rectangle, page: Page | None):
    if self._dest == Dest.HOME and page is not None and page.key == "alerts":
      title = tr("Alerts")
    elif self._dest == Dest.HOME:
      title = tr("F-150 Lightning")
    else:
      title = {d: n for d, n, _ in SECTIONS}[self._dest]
      title = tr(title)
    D.text(title, r.x + GUTTER + 16, r.y + (r.height - D.H1) / 2 - 2, D.H1, semi=True)
    right = r.x + r.width - GUTTER
    clock = time.strftime("%-I:%M %p")
    right -= D.text_right(clock, right, r.y + (r.height - D.BODY) / 2 - 2, D.BODY, semi=True) + 28
    self._action_rect = None
    action = page.action() if page is not None and page.action else None
    if action:
      w = D.text_w(action, D.LABEL, semi=True) + 64
      b = rl.Rectangle(right - w, r.y + (r.height - 72) / 2, w, 72)
      D.button(b, action, primary=False, size=D.LABEL)
      self._action_rect = b
      right = b.x - 16
    self._chip_rects = []
    cy = r.y + (r.height - 60) / 2
    net = network_status()
    if net is not None:
      c = K.signal_chip(right, cy, net[0], net[1], net[2])
      self._chip_rects.append((c, self._wifi_key))
      right = c.x - 16
    chips = []
    alerts = self.alert_count()
    if alerts:
      chips.append((tr("1 alert") if alerts == 1 else f"{alerts} " + tr("alerts"), Console.WARNING, "alerts"))
    try:
      if self._params.get_bool("UpdateAvailable"):
        chips.append((tr("Update ready"), Console.ACCENT, self._software_key))
    except Exception:
      pass
    for label, color, key in chips:
      cw = D.text_w(label, D.LABEL, semi=True) + 24 * 2 + 28
      c = D.chip(right - cw, cy, label, color)
      if key is not None:
        self._chip_rects.append((c, key))
      right -= cw + 16

  # -- input ------------------------------------------------------------------------

  def _handle_mouse_release(self, mouse_pos) -> bool:
    for i, r in enumerate(self._tab_rects):
      if D.hit(r, mouse_pos):
        dest = SECTIONS[i][0]
        self.go(dest, 0 if dest == Dest.HOME else None)
        return True
    for i, r in enumerate(self._sub_rects):
      if D.hit(r, mouse_pos):
        self.go(self._dest, i)
        return True
    for r, key in self._chip_rects:
      if D.hit(r, mouse_pos):
        self.open_panel(key)
        return True
    page = self.current_page()
    if page is not None and page.on_action and D.hit(self._action_rect, mouse_pos):
      page.on_action()
      return True
    return False
