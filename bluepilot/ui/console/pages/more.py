"""
System > More settings: preferred Wi-Fi, the last row of the old BluePilot panel with no other home yet (the 12 V
battery limit moved to System > Truck > 12 V, the UI debug log to System > Developer). The Wi-Fi picker is still the BluePilot panel's own dialog,
fed by that panel's Wi-Fi scan, which runs while this page is open.
"""

from __future__ import annotations

from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.console.form import Nav, Section
from bluepilot.ui.console.pages.drive import DrivePage


class MorePage(DrivePage):
  def __init__(self, bp_panel=None):
    super().__init__()
    self._bp = bp_panel

  def _wifi(self):
    return getattr(self._bp, "_wifi_manager", None)

  def show_event(self):
    super().show_event()
    if self._wifi() is not None:
      self._wifi().set_active(True)

  def hide_event(self):
    super().hide_event()
    if self._wifi() is not None:
      self._wifi().set_active(False)

  def _render(self, rect):
    if self._wifi() is not None:
      self._wifi().process_callbacks()
    super()._render(rect)

  def sections(self):
    bp = self._bp
    saved = len(getattr(bp, "_saved_networks", []) or [])
    fav = ""
    if bp is not None and hasattr(bp, "_get_preferred_network_display"):
      try:
        fav = bp._get_preferred_network_display()
      except Exception:
        fav = ""
    wifi = Nav(tr("Preferred Wi-Fi"), tr("Joined first when in range") if saved else tr("No saved networks yet"),
               bp._select_preferred_network, value=fav) if bp is not None and hasattr(bp, "_select_preferred_network") else None
    return [Section(tr("Network"), "wifi", [wifi])]
