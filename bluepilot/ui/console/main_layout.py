"""
Console main layout for the comma 3X.

  STANDBY   parked splash (clock, charge, readiness); any tap opens the shell
  SHELL     Citadel layout: section tabs across the top, page rail on the left
  ONROAD    full-camera driving view; a tap opens the quick-controls sheet
  CHARGING  charging page; takes over while the truck is plugged in

Replaces the stock sidebar + home + settings arrangement. Every settings panel is still the
original widget, hosted inside the shell's sections.
"""

from __future__ import annotations

from enum import IntEnum

import pyray as rl

import cereal.messaging as messaging
from openpilot.selfdrive.ui.ui_state import device, ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget

from openpilot.selfdrive.ui.bp.onroad.augmented_road_view_bp import AugmentedRoadViewBP
from bluepilot.ui.widgets.debug import ControlsDebugPanel
from bluepilot.ui.console.onboarding import ConsoleOnboarding
from bluepilot.ui.console.home import AlertsPage, ConsoleHome, active_alerts
from bluepilot.ui.console.pages.charging import ChargingPage, ChargingScreen
from bluepilot.ui.console.pages.stats import StatsPage
from bluepilot.ui.console.quick_controls import QuickControls
from bluepilot.ui.console.shell import ConsoleShell, Dest, Page
from bluepilot.ui.console.standby import ConsoleStandby
from bluepilot.ui.lib import ui_scale
from bluepilot.ui.lib.automations import automations
from bluepilot.ui.lib.home_location import home_location
from bluepilot.ui.lib.net_usage import usage

if gui_app.sunnypilot_ui():
  from openpilot.selfdrive.ui.sunnypilot.layouts.settings.settings import SettingsLayoutSP as SettingsLayout
else:
  from openpilot.selfdrive.ui.layouts.settings.settings import SettingsLayout


def _apply_canadian_units():
  """Lucas drives in Canada: switch to km and km/h once; the Units toggle still works afterwards."""
  from openpilot.common.params import Params
  params = Params()
  try:
    if not params.get_bool("BPCanadianUnitsSet"):
      params.put_bool("IsMetric", True)
      params.put_bool("BPCanadianUnitsSet", True)
      ui_state.is_metric = True
  except Exception:
    pass


class MainState(IntEnum):
  STANDBY = 0
  SHELL = 1
  ONROAD = 2
  CHARGING = 3
  # Older names, kept for tools that drive the UI
  HOME = 1
  SETTINGS = 1


class ConsoleMainLayout(Widget):
  def __init__(self):
    super().__init__()
    self._pm = messaging.PubMaster(['bookmarkButton'])

    _apply_canadian_units()
    self._settings = SettingsLayout()
    self._home = ConsoleHome()
    self._shell = ConsoleShell(self._settings, self._home, AlertsPage())
    home_page = self._shell.pages(Dest.HOME)[0]
    home_page.subtitle = self._home.subtitle
    home_page.sub_dot = self._home.sub_dot
    self._shell.alert_count = lambda: len(active_alerts(self._home._params))
    # Energy pages (thread C): Charging and Statistics lead the Energy section
    self._charging_page = ChargingPage()
    self._charging_page.on_open_full = self.open_charging
    self._stats_page = StatsPage()
    self._shell.register_page(Dest.ENERGY, Page(tr("Charging"), "plug", self._charging_page, key="charging_page",
                                                subtitle=self._charging_page.subtitle, sub_dot=self._charging_page.sub_dot,
                                                action=self._charging_page.action, on_action=self.open_charging,
                                                framed=False), index=0)
    self._shell.register_page(Dest.ENERGY, Page(tr("Statistics"), "pulse", self._stats_page, key="statistics",
                                                subtitle=self._stats_page.subtitle, sub_dot=self._stats_page.sub_dot,
                                                action=self._stats_page.action, on_action=self._stats_page.on_action,
                                                framed=False), index=1)
    from bluepilot.ui.console.pages.truck_data import TruckDataPage
    self._truck_data = TruckDataPage()
    self._truck_data.on_open_setup = self._shell.open_obd
    self._shell.register_page(Dest.ENERGY, Page(tr("Truck data"), "gauge", self._truck_data, key="truck_data",
                                                subtitle=self._truck_data.subtitle, sub_dot=self._truck_data.sub_dot,
                                                framed=False), index=2)
    self._layouts = {
      MainState.STANDBY: ConsoleStandby(),
      MainState.SHELL: self._shell,
      MainState.ONROAD: AugmentedRoadViewBP(),
      MainState.CHARGING: ChargingScreen(),
    }
    self._current_mode = MainState.STANDBY
    self._prev_onroad = False
    self._prev_charging = False

    self._debug_panel = ControlsDebugPanel()
    self._quick = QuickControls()
    self._quick.on_bookmark = self._on_bookmark_clicked
    self._quick.on_diagnostics = self._debug_panel.toggle_visibility

    self._home.on_open_drive = lambda: self._shell.go(Dest.DRIVE, 0)
    self._home.on_open_assist = lambda: self._shell.go(Dest.DRIVE, 0)
    self._home.on_open_software = lambda: self._shell.open_panel("updates")
    self._home.on_open_connectivity = lambda: self._shell.open_panel("connectivity")
    self._home.on_open_storage = lambda: self._shell.open_panel("drives_storage")
    self._home.wifi_ssid = self._shell.connectivity._connected_ssid
    self._home.on_open_charging = self.open_charging
    self._home.on_open_alerts = lambda: self._shell.open_panel("alerts")

    self._layouts[MainState.STANDBY].set_click_callback(lambda: self._open_shell(Dest.HOME, 0))  # Home overview, not the last sub-page
    self._layouts[MainState.ONROAD].set_click_callback(self._on_onroad_clicked)
    self._layouts[MainState.CHARGING].set_click_callback(self._on_charging_clicked)
    device.add_interactive_timeout_callback(self._on_interactive_timeout)
    automations().attach(self._shell.connectivity._wifi)

    gui_app.push_widget(self)

    self._onboarding_window = ConsoleOnboarding()
    if not self._onboarding_window.completed:
      gui_app.push_widget(self._onboarding_window)

    self._set_mode_for_state()

  # -- state ----------------------------------------------------------------------

  def _render(self, rect):
    self._handle_transitions()
    home_location().tick(ui_state.sm)
    automations().tick(ui_state.started)
    if ui_state.sm.updated["deviceState"]:
      usage().tick(ui_state.sm["deviceState"])
    if self._current_mode == MainState.SHELL:
      z = ui_scale.current()  # Screen > UI size
      with ui_scale.zoomed(z):
        self._shell.render(ui_scale.logical(rect, z))
    else:
      self._layouts[self._current_mode].render(rect)
    if self._current_mode == MainState.ONROAD:
      self._quick.render(rect)
      if self._debug_panel.is_panel_visible:
        self._debug_panel.render(rect)

  def _handle_transitions(self):
    charging = bool(getattr(ui_state, "charging_screen", False))
    if ui_state.started != self._prev_onroad or charging != self._prev_charging:
      self._prev_onroad = ui_state.started
      self._prev_charging = charging
      if charging or not (self._current_mode == MainState.SHELL and not ui_state.started):
        self._set_mode_for_state()

  def _set_mode_for_state(self):
    if getattr(ui_state, "charging_screen", False):
      self._set_current_layout(MainState.CHARGING)
    elif ui_state.started:
      self._quick.close()
      self._set_current_layout(MainState.ONROAD)
    else:
      self._set_current_layout(MainState.STANDBY)

  def _set_current_layout(self, mode: MainState):
    if mode != self._current_mode:
      self._layouts[self._current_mode].hide_event()
      self._current_mode = mode
      self._layouts[self._current_mode].show_event()

  def _on_interactive_timeout(self):
    # Parked and idle: back to the standby splash (driving and charging keep their screens)
    if not ui_state.started and not getattr(ui_state, "charging_screen", False):
      self._shell.go(Dest.HOME, 0)
      self._set_current_layout(MainState.STANDBY)

  # -- navigation -----------------------------------------------------------------

  def _open_shell(self, dest: Dest = Dest.HOME, sub: int | None = None):
    self._shell.go(dest, sub)
    self._set_current_layout(MainState.SHELL)

  def open_settings(self, panel_type):
    self._set_current_layout(MainState.SHELL)
    if not self._shell.open_panel(panel_type):
      self._shell.go(Dest.SYSTEM, 0)

  def _on_onroad_clicked(self):
    if self._debug_panel.is_panel_visible:
      return
    if self._quick.in_gesture:  # the release of a drag on the dock or handle is not a tap
      return
    pos = rl.get_mouse_position()
    if self._quick.visible:
      self._quick.handle_tap(pos)
    else:
      self._quick.open()

  def open_charging(self):
    """Home's Charging card and Energy > Charging: bring the charging page back."""
    session = getattr(ui_state, "charge_session", None)
    if session is not None and session.active:
      session.dismissed = False
      session.reopened = True
      ui_state.charging_screen = True
      self._prev_charging = True
      self._set_current_layout(MainState.CHARGING)
    else:
      self._open_shell(Dest.ENERGY)
      self._shell.open_panel("charging_page")

  def _on_charging_clicked(self):
    session = getattr(ui_state, "charge_session", None)
    if session is not None:
      session.dismissed = True
      session.reopened = False
    ui_state.charging_screen = False
    self._prev_charging = False
    if ui_state.started:
      self._set_current_layout(MainState.ONROAD)
    else:
      self._open_shell(Dest.HOME)

  def _on_bookmark_clicked(self):
    msg = messaging.new_message('bookmarkButton')
    msg.valid = True
    self._pm.send('bookmarkButton', msg)
