"""
System > More settings: the last three rows of the old BluePilot panel that have no other home yet (preferred
Wi-Fi, the 12 V battery limit and the UI debug log). The Wi-Fi picker is still the BluePilot panel's own dialog,
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
    return [
      Section(tr("Network"), "wifi", [wifi]),
      Section(tr("12 V battery"), "battery", [
        self.stepper("vbatt_pause_charging", tr("Sleep below"), 11.0, 14.0, 0.1, lambda v: f"{v:.1f} V",
                     sub=tr("Protects the battery"), default=11.8, as_float=True),
      ]),
      Section(tr("Diagnostics"), "code", [
        self.toggle("BPUIDebugLog", tr("UI debug log"), tr("Logs screen changes for bug reports")),
      ]),
    ]
