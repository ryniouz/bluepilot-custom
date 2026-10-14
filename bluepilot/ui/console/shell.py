"""
Console shell for the comma 3X: the parked-mode interface.

A slim navigation rail on the left (Home, Drive, Energy, Screen, Connect, System), a header
band with the page title and status chips, and the page. Section pages show a sub-page list
beside a card that hosts the existing openpilot / sunnypilot / BluePilot settings panels, so
every feature keeps working while the 18 flat panels fold into six sections.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import IntEnum

import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.scroller_tici import Scroller
from bluepilot.ui.console import draw as D
from bluepilot.ui.lib.theme import Console, roundness

RAIL_W = 152
HEADER_H = 112
SUBNAV_W = 440
GUTTER = 32


class Dest(IntEnum):
  HOME = 0
  DRIVE = 1
  ENERGY = 2
  SCREEN = 3
  CONNECT = 4
  SYSTEM = 5


RAIL = [
  (Dest.HOME, "Home", "home"),
  (Dest.DRIVE, "Drive", "wheel"),
  (Dest.ENERGY, "Energy", "bolt"),
  (Dest.SCREEN, "Screen", "screen"),
  (Dest.CONNECT, "Connect", "wifi"),
  (Dest.SYSTEM, "System", "sliders"),
]


@dataclass
class SubPage:
  title: str
  key: object          # a settings PanelType, or a string naming a shell page
  widget: Widget | None = None


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
  def __init__(self, settings_layout, home: Widget):
    super().__init__()
    from openpilot.selfdrive.ui.layouts.settings import settings as _settings_mod
    PT = _settings_mod.PanelType
    self._settings = settings_layout
    self._panels = settings_layout._panels
    self._home = home
    self._dest = Dest.HOME
    self._sub_index: dict[Dest, int] = dict.fromkeys(Dest, 0)
    self._rail_rects: list[tuple[Dest, rl.Rectangle]] = []
    self._sub_rects: list[rl.Rectangle] = []
    self._params = Params()

    bp_items = {}
    bp = self._panels.get(PT.BLUEPILOT) if hasattr(PT, "BLUEPILOT") else None
    if bp is not None and hasattr(bp.instance, "console_page_items"):
      bp_items = bp.instance.console_page_items()
    pages = {k: ItemsPage(v) for k, v in bp_items.items()}

    def p(title, key):
      if isinstance(key, str):
        return SubPage(title, key, pages.get(key))
      info = self._panels.get(key)
      return SubPage(title, key, info.instance if info else None)

    def pt(name):
      return getattr(PT, name, None)

    sections = {
      Dest.DRIVE: [p("Assist", pt("TOGGLES")), p("Steering", pt("STEERING")), p("Speed and cruise", pt("CRUISE")),
                   p("Driving model", pt("MODELS")), p("BluePilot tuning", pt("BLUEPILOT"))],
      Dest.ENERGY: [p("Charging", "charging"), p("Trips", pt("TRIPS"))],
      Dest.SCREEN: [p("Theme and layout", "theme"), p("Visuals", pt("VISUALS")), p("Display", pt("DISPLAY"))],
      Dest.CONNECT: [p("Wi-Fi", pt("NETWORK")), p("sunnylink", pt("SUNNYLINK")), p("Firehose", pt("FIREHOSE")),
                     p("BluePilot Portal", pt("BP_PORTAL")), p("Data export", "export")],
      Dest.SYSTEM: [p("Device", pt("DEVICE")), p("Software", pt("SOFTWARE")), p("Vehicle", pt("VEHICLE")),
                    p("Maps", pt("OSM")), p("Developer", pt("DEVELOPER"))],
    }
    self._sections = {d: [s for s in subs if s.widget is not None] for d, subs in sections.items()}
    self._current: Widget | None = None

  # -- navigation --------------------------------------------------------------

  @property
  def dest(self) -> Dest:
    return self._dest

  def go(self, dest: Dest, sub: int | None = None):
    if sub is not None:
      self._sub_index[dest] = max(0, min(sub, len(self._sections.get(dest, [])) - 1))
    self._dest = dest
    self._switch_to(self._page_widget())

  def open_panel(self, key) -> bool:
    """Open the sub-page that hosts a settings PanelType (or shell page key)."""
    for dest, subs in self._sections.items():
      for i, sp in enumerate(subs):
        if sp.key == key:
          self.go(dest, i)
          return True
    return False

  def _page_widget(self) -> Widget | None:
    if self._dest == Dest.HOME:
      return self._home
    subs = self._sections.get(self._dest, [])
    if not subs:
      return None
    return subs[self._sub_index[self._dest]].widget

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
    self._switch_to(self._page_widget())

  def hide_event(self):
    super().hide_event()
    if self._current is not None:
      self._current.hide_event()
    self._current = None

  # -- render --------------------------------------------------------------------

  def _render(self, rect: rl.Rectangle):
    rl.draw_rectangle_rec(rect, Console.BG_PAGE)
    self._draw_rail(rl.Rectangle(rect.x, rect.y, RAIL_W, rect.height))
    body = rl.Rectangle(rect.x + RAIL_W, rect.y, rect.width - RAIL_W, rect.height)
    self._draw_header(rl.Rectangle(body.x, body.y, body.width, HEADER_H))
    content = rl.Rectangle(body.x, body.y + HEADER_H, body.width, body.height - HEADER_H)

    if self._dest == Dest.HOME:
      self._switch_to(self._home)
      self._home.render(rl.Rectangle(content.x + GUTTER, content.y, content.width - GUTTER * 2, content.height - GUTTER))
      return

    subs = self._sections.get(self._dest, [])
    self._sub_rects = []
    y = content.y + 8
    for i, sp in enumerate(subs):
      r = rl.Rectangle(content.x + GUTTER, y, SUBNAV_W - GUTTER, 88)
      self._sub_rects.append(r)
      on = i == self._sub_index[self._dest]
      if on:
        rl.draw_rectangle_rounded(r, roundness(r, 12), 8, Console.ACCENT_TINT)
      D.text(D.fit(tr(sp.title), D.BODY, r.width - 56, semi=on), r.x + 28, r.y + (r.height - D.BODY) / 2 - 2, D.BODY,
             Console.ACCENT_TEXT if on else Console.TEXT_SECONDARY, semi=on)
      y += 96

    panel = rl.Rectangle(content.x + SUBNAV_W + 8, content.y + 8, content.width - SUBNAV_W - 8 - GUTTER, content.height - 8 - GUTTER)
    D.card(panel)
    w = self._page_widget()
    self._switch_to(w)
    if w is not None:
      w.render(rl.Rectangle(panel.x + 24, panel.y + 12, panel.width - 48, panel.height - 24))

  def _draw_rail(self, r: rl.Rectangle):
    rl.draw_rectangle_rec(r, Console.BG_PANEL)
    from bluepilot.ui.lib.theme import is_day
    if is_day():
      rl.draw_rectangle_rec(rl.Rectangle(r.x + r.width - 2, r.y, 2, r.height), Console.BORDER_DEFAULT)
    brand = rl.Rectangle(r.x + (r.width - 80) / 2, r.y + 28, 80, 80)
    rl.draw_rectangle_rounded(brand, roundness(brand, 16), 8, Console.ACCENT_FILL)
    D.text_center("BP", brand.x + 40, brand.y + 22, 32, Console.ON_ACCENT, semi=True)

    self._rail_rects = []
    y = r.y + 140
    for dest, label, ic in RAIL:
      item = rl.Rectangle(r.x + 16, y, r.width - 32, 116)
      self._rail_rects.append((dest, item))
      on = dest == self._dest
      if on:
        rl.draw_rectangle_rounded(item, roundness(item, 16), 8, Console.ACCENT_TINT)
      color = Console.ACCENT_TEXT if on else Console.TEXT_MUTED
      D.icon(ic, item.x + (item.width - 44) / 2, item.y + 18, 44, color)
      D.text_center(tr(label), item.x + item.width / 2, item.y + 72, D.CAPTION, color, semi=True)
      y += 124

    ready = ui_state.panda_type is not None and str(ui_state.panda_type) != "unknown"
    D.dot(r.x + r.width / 2, r.y + r.height - 86, 10, Console.SUCCESS if ready else Console.TEXT_GHOST)
    D.text_center(tr("Ready") if ready else tr("No car"), r.x + r.width / 2, r.y + r.height - 62, D.CAPTION,
                  Console.TEXT_MUTED, semi=True)

  def _header_title(self) -> str:
    return {Dest.HOME: tr("F-150 Lightning"), Dest.DRIVE: tr("Drive"), Dest.ENERGY: tr("Energy"),
            Dest.SCREEN: tr("Screen"), Dest.CONNECT: tr("Connect"), Dest.SYSTEM: tr("System")}[self._dest]

  def _draw_header(self, r: rl.Rectangle):
    D.text(self._header_title(), r.x + GUTTER + 16, r.y + (r.height - D.H1) / 2 - 2, D.H1, semi=True)
    right = r.x + r.width - GUTTER
    clock = time.strftime("%-I:%M %p") if hasattr(time, "strftime") else ""
    w = D.text_w(clock, D.BODY, semi=True)
    D.text(clock, right - w, r.y + (r.height - D.BODY) / 2 - 2, D.BODY, semi=True)
    right -= w + 28
    chips = []
    try:
      if self._params.get_bool("UpdateAvailable"):
        chips.append((tr("Update ready"), Console.ACCENT))
    except Exception:
      pass
    net = self._network_label()
    if net:
      chips.append(net)
    for label, color in chips:
      cw = D.text_w(label, D.LABEL, semi=True) + 24 * 2 + 28
      D.chip(right - cw, r.y + (r.height - 60) / 2, label, color)
      right -= cw + 16

  @staticmethod
  def _network_label():
    try:
      ds = ui_state.sm["deviceState"]
      nt = str(ds.networkType)
    except Exception:
      return None
    names = {"wifi": "Wi-Fi", "cell2G": "2G", "cell3G": "3G", "cell4G": "LTE", "cell5G": "5G", "ethernet": "Ethernet"}
    if nt in ("none", ""):
      return (tr("Offline"), Console.TEXT_GHOST)
    return (names.get(nt, nt), Console.SUCCESS)

  # -- input ---------------------------------------------------------------------

  def _handle_mouse_release(self, mouse_pos) -> bool:
    for dest, r in self._rail_rects:
      if D.hit(r, mouse_pos):
        self.go(dest)
        return True
    if self._dest != Dest.HOME:
      for i, r in enumerate(self._sub_rects):
        if D.hit(r, mouse_pos):
          self.go(self._dest, i)
          return True
    return False
