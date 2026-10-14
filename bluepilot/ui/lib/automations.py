"""
Home automations (Connect > Home): small rules that act on the comma's own Wi-Fi, run from the UI loop.

  Join home Wi-Fi       parked at home and not on Wi-Fi: connect to a saved home network that is in range.
                        NetworkManager already reconnects saved networks on its own; this covers the
                        cases it doesn't (the hotspot was on, or another saved network was preferred).
  Hotspot off at home   parked at home with the hotspot on: turn it off, so the comma can join home Wi-Fi.
  Hotspot when leaving  driving away from home with the hotspot off: turn it on (uses LTE data).

"At home" is the last GPS fix within HOME_RADIUS_M of the saved home position, or being connected to (or
seeing) a network marked as home. Each rule acts once per arrival or departure, so turning something back
on by hand sticks until the next one.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass

from openpilot.common.params import Params
from bluepilot.ui.lib.home_location import home_location

TICK_S = 5.0
SCAN_S = 30.0
SETTLE_S = 20.0      # wait after start-up / arrival before acting, so Wi-Fi scans have results


@dataclass
class Rule:
  key: str
  title: str
  sub: str
  default: bool


RULES = [
  Rule("BPAutoHomeWifi", "Join home Wi-Fi", "When parked at home and a saved home network is in range", True),
  Rule("BPAutoHotspotHome", "Hotspot off at home", "So the comma can join your home network", True),
  Rule("BPAutoHotspotAway", "Hotspot when leaving", "Turn the hotspot on when you drive away from home. Uses LTE data.", False),
]


def _bool(params: Params, key: str, default: bool) -> bool:
  try:
    v = params.get(key, return_default=True)
    return default if v is None else bool(v)
  except Exception:
    return default


def has_keys(params: Params) -> bool:
  try:
    params.get(RULES[0].key, return_default=True)
    return True
  except Exception:
    return False


def home_ssids(params: Params) -> list[str]:
  try:
    raw = params.get("BPHomeWifi")
    data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    return [str(s) for s in data] if isinstance(data, list) else []
  except Exception:
    return []


class Automations:
  def __init__(self):
    self._params = Params()
    self._wifi = None
    self._next = time.monotonic() + SETTLE_S
    self._was_home: bool | None = None
    self._arrived_at = 0.0
    self._scanned_at = 0.0
    self._done: set[str] = set()      # rules that already acted for the current arrival/departure
    self.last_action = ""
    self.last_action_at = ""
    self.at_home: bool | None = None
    self.reason = ""

  def attach(self, wifi_manager):
    self._wifi = wifi_manager

  def enabled(self, rule: Rule) -> bool:
    return _bool(self._params, rule.key, rule.default)

  def set_enabled(self, rule: Rule, on: bool):
    try:
      self._params.put_bool(rule.key, on)
    except Exception:
      pass

  # -- state --------------------------------------------------------------------------------

  def _visible(self) -> set[str]:
    try:
      return {n.ssid for n in self._wifi.networks} if self._wifi is not None else set()
    except Exception:
      return set()

  def _connected(self) -> str:
    try:
      return str(self._wifi.connected_ssid or "") if self._wifi is not None else ""
    except Exception:
      return ""

  def _home_state(self, homes: list[str]) -> tuple[bool | None, str]:
    connected = self._connected()
    if connected and connected in homes:
      return True, "home Wi-Fi"
    at = home_location().at_home()
    if at is not None:
      return at, "GPS"
    if homes and self._visible() & set(homes):
      return True, "home Wi-Fi in range"
    return None, ""

  def _log(self, text: str):
    self.last_action = text
    self.last_action_at = time.strftime("%H:%M")

  # -- loop ---------------------------------------------------------------------------------

  def tick(self, onroad: bool):
    now = time.monotonic()
    if now < self._next or self._wifi is None or not has_keys(self._params):
      return
    self._next = now + TICK_S
    homes = home_ssids(self._params)
    if homes and not self._connected() and now - self._scanned_at > SCAN_S:
      self._scanned_at = now
      threading.Thread(target=self._scan, name="console-auto-scan", daemon=True).start()
    at, self.reason = self._home_state(homes)
    self.at_home = at
    if at is not None and at != self._was_home:
      self._was_home = at
      self._arrived_at = now
      self._done.clear()
    if at is None or now - self._arrived_at < SETTLE_S:
      return

    try:
      tethering = bool(self._wifi.is_tethering_active())
    except Exception:
      tethering = False

    if at and not onroad:
      if tethering and "hotspot_off" not in self._done and _bool(self._params, "BPAutoHotspotHome", True):
        self._done.add("hotspot_off")
        self._wifi.set_tethering_active(False)
        self._log("Turned the hotspot off at home")
        return
      if not tethering and "join" not in self._done and _bool(self._params, "BPAutoHomeWifi", True):
        if self._connected() in homes:
          self._done.add("join")
          return
        in_range = [s for s in homes if s in self._visible() and self._saved(s)]
        if in_range:
          self._done.add("join")
          self._wifi.activate_connection(in_range[0])
          self._log(f"Joined {in_range[0]}")
    elif not at and onroad:
      if not tethering and "hotspot_on" not in self._done and _bool(self._params, "BPAutoHotspotAway", False):
        self._done.add("hotspot_on")
        self._wifi.set_tethering_active(True)
        self._log("Turned the hotspot on when leaving home")

  def _scan(self):
    """The Wi-Fi manager only scans while its settings page is open; ask it for a fresh list."""
    try:
      self._wifi._request_scan()
      self._wifi._update_networks(block=False, force=True)
    except Exception:
      pass

  def _saved(self, ssid: str) -> bool:
    try:
      return bool(self._wifi.is_connection_saved(ssid))
    except Exception:
      return False


_auto: Automations | None = None


def automations() -> Automations:
  global _auto
  if _auto is None:
    _auto = Automations()
  return _auto
