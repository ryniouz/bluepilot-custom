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
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.console.form import FormPage, advanced_mode, set_advanced
from bluepilot.ui.console.search import Hit, SearchPage
from bluepilot.ui.console.home import network_status
from bluepilot.ui.lib.theme import Console, is_day, roundness

RAIL_W = 152
HEADER_H = 128
SUBNAV_W = 480
SUBNAV_STEP = 104      # Custom: page-list row pitch, and the smallest it may shrink to
SUBNAV_MIN_STEP = 72
GUTTER = 32
MODE_H = 76            # Custom: the Basic | Advanced switch under the page list


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
  level: str = "basic"                                  # "advanced": listed only in Advanced mode (search still finds it)


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
    self._search = SearchPage(self._search_index, self.ask_search)
    self._searching = False
    self._search_rect: rl.Rectangle | None = None
    self._mode_rects: list[rl.Rectangle] = []
    self._sub_index: list[int] = []

    self.register_page(Dest.HOME, Page(tr("Overview"), "grid", home, key="overview", framed=False))
    if alerts is not None:
      self.register_page(Dest.HOME, Page(tr("Alerts"), "bell", alerts, key="alerts", subtitle=tr("Home"),
                                         action=lambda: tr("Back"), on_action=lambda: self.go(Dest.HOME, 0)))

    # Drive: Console form pages in place of the Toggles, Steering, Cruise, Models and BluePilot tuning panels. Keys stay
    # the PanelTypes they replace, so open_settings(PanelType.MODELS) etc. still land on the right page.
    from bluepilot.ui.console.pages.drive import AssistPage, SpeedPage, SteeringPage
    from bluepilot.ui.console.pages.drive_model import DrivingModelPage
    for title, icon, widget, name in ((tr("Assist"), "wheel", AssistPage(), "TOGGLES"),
                                      (tr("Speed and cruise"), "pulse", SpeedPage(), "CRUISE"),
                                      (tr("Steering"), "steer", SteeringPage(), "STEERING"),
                                      (tr("Driving model"), "cpu", DrivingModelPage(), "MODELS")):
      self.register_page(Dest.DRIVE, Page(title, icon, widget, key=getattr(PT, name, name.lower()), framed=False,
                                          level="advanced" if name == "MODELS" else "basic"))

    # Energy (stream B): Console pages instead of the BluePilot rows and sunnypilot's Trips panel. sunnypilot's
    # TripsLayout still exists inside the settings layout and keeps ApiCache_DriveStats fresh for TripsPage.
    from bluepilot.ui.console.pages.trips import TripsPage
    from bluepilot.ui.console.pages.charging_settings import ChargingSettingsPage
    self.trips = TripsPage()
    self.register_page(Dest.ENERGY, Page(tr("Trips"), "route", self.trips, key="trips", subtitle=self.trips.subtitle,
                                         sub_dot=self.trips.sub_dot, framed=False,
                                         aliases=tuple(k for k in (getattr(PT, "TRIPS", None),) if k is not None)))
    charge_settings = ChargingSettingsPage()
    charge_settings.on_open_power = self.open_vehicle_power
    self.register_page(Dest.ENERGY, Page(tr("Charging settings"), "sliders", charge_settings, key="charging",
                                         subtitle=tr("Energy"), framed=False))

    from bluepilot.ui.console.pages.drives import DrivesPage
    drives = DrivesPage()
    self.register_page(Dest.DRIVES, Page(tr("Previous drives"), "list", drives, key="drives", framed=False))
    # Uploads: the old Offloading and Upload settings pages merged; their keys still open it
    from bluepilot.ui.console.pages.uploads import UploadsPage
    wifi = self._panels.get(PT.NETWORK) if hasattr(PT, "NETWORK") else None
    self.register_page(Dest.DRIVES, Page(tr("Uploads"), "cloud",
                                         UploadsPage(getattr(wifi.instance, "_wifi_manager", None) if wifi is not None else None),
                                         key="uploads", framed=False, aliases=("drives_offload", "upload_settings")))

    from bluepilot.ui.console.pages.theme import ThemePage
    self.register_page(Dest.SCREEN, Page(tr("Theme and layout"), "palette", ThemePage(), key="theme",
                                         subtitle=tr("Screen") + " | " + tr("Applies right away"), framed=False))
    from bluepilot.ui.console.pages.onroad_display import OnroadDisplayPage
    from bluepilot.ui.console.pages.display import DisplayPage
    old_keys = lambda *names: tuple(k for k in (getattr(PT, n, None) for n in names) if k is not None)  # noqa: E731
    self.register_page(Dest.SCREEN, Page(tr("Onroad display"), "eye", OnroadDisplayPage(), key="onroad_display",
                                         subtitle=tr("Screen"), framed=False, aliases=old_keys("VISUALS"),
                                         level="advanced"))
    self.register_page(Dest.SCREEN, Page(tr("Display"), "sun", DisplayPage(), key="display",
                                         subtitle=tr("Screen"), framed=False, aliases=old_keys("DISPLAY")))
    # Road view and the BluePilot driving-view rows (Onroad display has the sunnypilot ones)
    from bluepilot.ui.console.pages.driving_screen import DrivingScreenPage
    self.register_page(Dest.SCREEN, Page(tr("Road view"), "car", DrivingScreenPage(), key="road_view", framed=False), index=2)

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
    # Wi-Fi: a Console page on the stock panel's WifiManager; keeps the NETWORK key, and System > More settings'
    # old key (its preferred network moved here)
    from bluepilot.ui.console.pages.wifi import WifiPage
    self.wifi = WifiPage(self.connectivity._wifi)
    self.wifi.on_open_cellular = lambda: self.open_panel("cellular")
    self._wifi_key = self._wifi_key if self._wifi_key is not None else "wifi"
    self.register_page(Dest.CONNECT, Page(tr("Wi-Fi"), "wifi", self.wifi, key=self._wifi_key, framed=False,
                                          aliases=("wifi", "bp_misc")))
    from bluepilot.ui.console.pages.automations import AutomationsPage
    autos = AutomationsPage()
    autos.on_open_wifi = lambda: self.open_panel(self._wifi_key)
    self.register_page(Dest.CONNECT, Page(tr("Home automations"), "home", autos, key="automations", framed=False))
    self.connectivity.on_open_automations = lambda: self.open_panel("automations")
    from bluepilot.ui.console.pages.bluetooth import BluetoothPage
    self.bluetooth = BluetoothPage()
    self.register_page(Dest.CONNECT, Page(tr("Bluetooth"), "bluetooth", self.bluetooth, key="bluetooth", framed=False))
    # sunnylink is gone (Citadel has its own link); the web portal is a section of Data export
    from bluepilot.ui.console.pages.export import ExportPage
    self.register_page(Dest.CONNECT, Page(tr("Data export"), "export", ExportPage(), key="export", framed=False))
    from bluepilot.ui.console.pages.firehose import FirehosePage
    fh = self._panels.get(getattr(PT, "FIREHOSE", None))
    self.register_page(Dest.CONNECT, Page(tr("Firehose"), "flame", FirehosePage(getattr(fh, "instance", None)),
                                          key=getattr(PT, "FIREHOSE", "firehose"), framed=False, level="advanced"))
    # Custom: 7.0 Connect Backend selector (comma connect / Konik / Offline) and dongle ID recovery
    from bluepilot.ui.console.pages.backend import ConnectBackendPage
    self.register_page(Dest.CONNECT, Page(tr("Connect backend"), "cloud", ConnectBackendPage(), key="backend", framed=False,
                                          level="advanced"))

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
                                         framed=False, level="advanced"))
    from bluepilot.ui.console.pages.about import AboutPage
    self.register_page(Dest.SYSTEM, Page(tr("About"), "info", AboutPage(), key="about", subtitle=tr("System"), framed=False))

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
    self._searching = False
    if sub is not None:
      self._sub[dest] = max(0, min(sub, len(self._pages[dest]) - 1))
    self._dest = dest
    p = self.current_page()
    self._switch_to(p.widget if p else None)

  def open_vehicle_power(self):
    """System > Vehicle on its Power tab (charging keep-awake and power-down)."""
    if self.open_panel("vehicle"):
      page = self.current_page()
      if page is not None and hasattr(page.widget, "_tab"):
        page.widget._tab = 3

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

  # -- Basic / Advanced and search ---------------------------------------------------

  def listed(self, dest: Dest) -> list[int]:
    """Indices of the pages the page list shows: all in Advanced mode; in Basic the basic ones and the open one."""
    pages = self._pages[dest]
    if advanced_mode():
      return list(range(len(pages)))
    cur = min(self._sub[dest], len(pages) - 1)
    return [i for i, p in enumerate(pages) if p.level != "advanced" or i == cur]

  def set_mode(self, advanced: bool):
    set_advanced(advanced)
    page = self.current_page()
    if not advanced and page is not None and page.level == "advanced" and self._dest != Dest.HOME:
      first = next((i for i, p in enumerate(self._pages[self._dest]) if p.level != "advanced"), 0)
      self.go(self._dest, first)

  def ask_search(self):
    try:
      from openpilot.system.ui.sunnypilot.widgets.input_dialog import InputDialogSP
      from openpilot.system.ui.widgets import DialogResult
    except Exception:
      return

    def done(result, text):
      if result == DialogResult.CONFIRM and (text or "").strip():
        self.search(text)
    InputDialogSP(tr("Search settings"), tr("A setting, a page or a word in its description"),
                  current_text=self._search.query if self._searching else "", callback=done).show()

  def search(self, query: str):
    self._search.run(query)
    self._searching = True
    self._switch_to(self._search)

  def close_search(self):
    self._searching = False
    p = self.current_page()
    self._switch_to(p.widget if p else None)

  def _search_index(self) -> list[Hit]:
    hits = []
    for dest, label, icon in SECTIONS:
      if dest == Dest.HOME:
        continue
      for i, page in enumerate(self._pages[dest]):
        def opener(dest=dest, i=i, reveal=False):
          def fn():
            self.go(dest, i)
            if reveal and isinstance(self._pages[dest][i].widget, FormPage):
              self._pages[dest][i].widget.reveal = True
          return fn
        page_adv = page.level == "advanced"
        hits.append(Hit(tr(label), icon, page.title, "", page.title, tr(label), page_adv, opener()))
        entries = page.widget.search_entries() if hasattr(page.widget, "search_entries") else []
        for card, title, sub, adv in entries:
          hits.append(Hit(tr(label), icon, page.title, card, title, sub, adv or page_adv, opener(reveal=adv)))
    return hits

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
    self._sub_rects = []
    self._sub_index = []
    self._mode_rects = []
    if self._searching:
      self._switch_to(self._search)
      self._search.render(content)
      return
    if page is None:
      return
    self._switch_to(page.widget)
    pages = self._pages[self._dest]

    if len(pages) > 1 and self._dest != Dest.HOME:
      y = content.y
      listed = self.listed(self._dest)
      # Custom: Connect has nine or more pages; rows shrink (down to 64 px) so the last one stays on screen
      # at every UI size instead of running off the bottom. The Basic | Advanced switch sits under the list.
      list_h = content.height - MODE_H - 24
      step = max(SUBNAV_MIN_STEP, min(SUBNAV_STEP, list_h / max(1, len(listed))))
      for i in listed:
        p = pages[i]
        r = rl.Rectangle(content.x, y, SUBNAV_W - GUTTER, step - 8)
        self._sub_rects.append(r)
        self._sub_index.append(i)
        on = i == self._sub[self._dest]
        if on:
          rl.draw_rectangle_rounded(r, roundness(r, 16), 8, Console.ACCENT_TINT)
        color = Console.ACCENT_TEXT if on else Console.TEXT_SECONDARY
        D.icon(p.icon, r.x + 24, r.y + (r.height - 40) / 2, 40, Console.ACCENT if on else Console.TEXT_MUTED)
        D.text(D.fit(p.title, D.BODY, r.width - 112, semi=on), r.x + 88, r.y + (r.height - D.BODY) / 2 - 2, D.BODY, color, semi=on)
        y += step
      adv = advanced_mode()
      mode = rl.Rectangle(content.x, content.y + content.height - MODE_H, SUBNAV_W - GUTTER, MODE_H)
      self._mode_rects = D.segmented(mode, [tr("Basic"), tr("Advanced")], 1 if adv else 0)
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
    if self._searching:
      title = tr("Search")
    elif self._dest == Dest.HOME and page is not None and page.key == "alerts":
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
    if self._searching:
      action = tr("Close")
    if action:
      w = D.text_w(action, D.LABEL, semi=True) + 64
      b = rl.Rectangle(right - w, r.y + (r.height - 72) / 2, w, 72)
      D.button(b, action, primary=False, size=D.LABEL)
      self._action_rect = b
      right = b.x - 16
    # Custom: settings search, on every settings section
    self._search_rect = None
    if self._dest != Dest.HOME or self._searching:
      b = rl.Rectangle(right - 72, r.y + (r.height - 72) / 2, 72, 72)
      rl.draw_rectangle_rounded(b, roundness(b, 16), 8, Console.ACCENT_TINT if self._searching else Console.BG_RAISED)
      D.icon("search", b.x + 16, b.y + 16, 40, Console.ACCENT if self._searching else Console.TEXT_SECONDARY)
      self._search_rect = b
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
    for i, r in zip(self._sub_index, self._sub_rects, strict=True):
      if D.hit(r, mouse_pos):
        self.go(self._dest, i)
        return True
    for i, r in enumerate(self._mode_rects):
      if D.hit(r, mouse_pos):
        self.set_mode(i == 1)
        return True
    if self._search_rect is not None and D.hit(self._search_rect, mouse_pos):
      self.ask_search()
      return True
    if self._searching and self._action_rect is not None and D.hit(self._action_rect, mouse_pos):
      self.close_search()
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
