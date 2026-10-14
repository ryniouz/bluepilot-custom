"""
Console shell for the comma 3X, laid out like Citadel's own apps.

  top bar     section tabs: Home, Drive, Energy, Screen, Connect, System
  page rail   the section's pages as icons, down the left edge
  page        a header (icon, title, status line, one action) above the page body

Settings sections host the existing openpilot / sunnypilot / BluePilot panel widgets, so every
feature keeps working. Other modules add pages with register_page().
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum

import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.scroller_tici import Scroller
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.lib.theme import Console


class Dest(IntEnum):
  HOME = 0
  DRIVE = 1
  ENERGY = 2
  SCREEN = 3
  CONNECT = 4
  SYSTEM = 5


SECTIONS = [
  (Dest.HOME, "Home", "home"),
  (Dest.DRIVE, "Drive", "wheel"),
  (Dest.ENERGY, "Energy", "bolt"),
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


class ItemsPage(Widget):
  """A list page made of existing list items (rows moved off the BluePilot panel)."""

  def __init__(self, items: list):
    super().__init__()
    self._scroller = Scroller(items, line_separator=True, spacing=0)

  def show_event(self):
    super().show_event()
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
    self._rail_rects: list[rl.Rectangle] = []
    self._action_rect: rl.Rectangle | None = None
    self._current: Widget | None = None
    self.alert_count: Callable[[], int] = lambda: 0

    bp_items = {}
    bp = self._panels.get(PT.BLUEPILOT) if hasattr(PT, "BLUEPILOT") else None
    if bp is not None and hasattr(bp.instance, "console_page_items"):
      bp_items = bp.instance.console_page_items()
    items = {k: ItemsPage(v) for k, v in bp_items.items()}

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
      self.register_page(Dest.HOME, Page(tr("Alerts"), "bell", alerts, key="alerts", subtitle=tr("Home")))

    drive = tr("Drive") + " | " + tr("Changes apply on the next drive")
    panel(Dest.DRIVE, tr("Assist"), "gauge", "TOGGLES", drive)
    panel(Dest.DRIVE, tr("Steering"), "steer", "STEERING", drive)
    panel(Dest.DRIVE, tr("Speed and cruise"), "pulse", "CRUISE", drive)
    panel(Dest.DRIVE, tr("Driving model"), "cpu", "MODELS", tr("Drive"))
    panel(Dest.DRIVE, tr("BluePilot tuning"), "tune", "BLUEPILOT", drive)

    item_page(Dest.ENERGY, tr("Charging settings"), "sliders", "charging", tr("Energy"))
    panel(Dest.ENERGY, tr("Trips"), "route", "TRIPS", tr("Energy"))

    item_page(Dest.SCREEN, tr("Theme and layout"), "palette", "theme", tr("Screen") + " | " + tr("Applies right away"))
    panel(Dest.SCREEN, tr("Visuals"), "eye", "VISUALS", tr("Screen"))
    panel(Dest.SCREEN, tr("Display"), "screen", "DISPLAY", tr("Screen"))

    panel(Dest.CONNECT, tr("Wi-Fi"), "wifi", "NETWORK", tr("Connect"))
    panel(Dest.CONNECT, tr("sunnylink"), "cloud", "SUNNYLINK", tr("Connect"))
    panel(Dest.CONNECT, tr("Firehose"), "flame", "FIREHOSE", tr("Connect"))
    panel(Dest.CONNECT, tr("BluePilot Portal"), "phone", "BP_PORTAL", tr("Connect"))
    item_page(Dest.CONNECT, tr("Data export"), "export", "export", tr("Connect"))

    panel(Dest.SYSTEM, tr("Device"), "cpu", "DEVICE", tr("System"))
    panel(Dest.SYSTEM, tr("Software"), "download", "SOFTWARE", tr("System"))
    panel(Dest.SYSTEM, tr("Vehicle"), "car", "VEHICLE", tr("System"))
    panel(Dest.SYSTEM, tr("Maps"), "map", "OSM", tr("System"))
    panel(Dest.SYSTEM, tr("Developer"), "code", "DEVELOPER", tr("System"))

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

  def open_panel(self, key) -> bool:
    """Open the page that hosts a settings PanelType (or a page key)."""
    for dest, pages in self._pages.items():
      for i, p in enumerate(pages):
        if p.key == key:
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
    net = self._network()
    self._tab_rects, _ = K.top_bar(rl.Rectangle(rect.x, rect.y, rect.width, K.TOP_H), [(tr(n), i) for _, n, i in SECTIONS],
                                   int(self._dest), [net] if net else [], alerts=self.alert_count())
    pages = self._pages[self._dest]
    body_y = rect.y + K.TOP_H
    self._rail_rects = K.page_rail(rl.Rectangle(rect.x, body_y, K.RAIL_W, rect.height - K.TOP_H),
                                   [p.icon for p in pages], self._sub[self._dest])
    page = self.current_page()
    if page is None:
      return
    self._switch_to(page.widget)

    area = rl.Rectangle(rect.x + K.RAIL_W + K.PAD_L, body_y + K.PAD_T, rect.width - K.RAIL_W - K.PAD_L - K.PAD_R,
                        rect.height - K.TOP_H - K.PAD_T - 28)
    sub = page.subtitle() if callable(page.subtitle) else page.subtitle
    dot = page.sub_dot() if page.sub_dot else None
    action = page.action() if page.action else None
    self._action_rect = K.page_header(rl.Rectangle(area.x, area.y, area.width, K.HEADER_H), page.icon, page.title, sub,
                                      dot, action=action)
    body = rl.Rectangle(area.x, area.y + K.HEADER_H + K.GAP, area.width, area.height - K.HEADER_H - K.GAP)
    if page.framed:
      K.panel(body)
      page.widget.render(rl.Rectangle(body.x + 32, body.y + 8, body.width - 64, body.height - 16))
    else:
      page.widget.render(body)

  @staticmethod
  def _network():
    try:
      nt = str(ui_state.sm["deviceState"].networkType)
    except Exception:
      return None
    names = {"wifi": "Wi-Fi", "cell2G": "2G", "cell3G": "3G", "cell4G": "LTE", "cell5G": "5G", "ethernet": "Ethernet"}
    if nt in ("none", ""):
      return (tr("Offline"), Console.TEXT_GHOST)
    return (names.get(nt, nt), Console.SUCCESS)

  # -- input ------------------------------------------------------------------------

  def _handle_mouse_release(self, mouse_pos) -> bool:
    for i, r in enumerate(self._tab_rects):
      if D.hit(r, mouse_pos):
        self.go(SECTIONS[i][0])
        return True
    for i, r in enumerate(self._rail_rects):
      if D.hit(r, mouse_pos):
        self.go(self._dest, i)
        return True
    page = self.current_page()
    if page is not None and page.on_action and D.hit(self._action_rect, mouse_pos):
      page.on_action()
      return True
    return False
