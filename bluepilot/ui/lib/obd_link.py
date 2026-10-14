"""
OBD adapter link for the Console Bluetooth page's OBD wizard.

The bp_obdd service (PR #2, selfdrive/car/obd/) talks to an ELM327 adapter over Wi-Fi, USB or Bluetooth
RFCOMM and publishes obdStateBP at 1 Hz. AGNOS is built with CONFIG_BT=n, so on a stock comma the
Wi-Fi and USB adapters are the ones that work (/mnt/project-files/comma/obd-bluetooth.md).

The page needs to run on builds without PR #2 too, so the service and params are looked up at run time:
available() is False until both exist, and snapshot() returns plain data the page can draw.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from openpilot.common.params import Params

SERVICE = "obdStateBP"
DEFAULT_WIFI = "192.168.0.10:35000"
TRANSPORTS = ("wifi", "usb", "bluetooth", "simulated")
STALE_S = 5.0


@dataclass
class ObdValue:
  name: str          # catalog short name, e.g. HvbSoc
  value: float
  unit: str
  age_s: float
  label: str = ""    # catalog long name, e.g. "HV battery state of charge"


@dataclass
class ObdSnapshot:
  received: bool = False         # a message arrived within STALE_S
  enabled: bool = False
  transport: str = "none"
  link: str = "off"              # off, unavailable, connecting, initializing, connected, carAsleep, idle, error
  message: str = ""
  adapter: str = ""
  protocol: str = ""
  bluetooth_available: bool = False
  bluetooth_message: str = ""
  usb_devices: list[str] = field(default_factory=list)
  polling: bool = False
  values: list[ObdValue] = field(default_factory=list)


def _has_param(params: Params, key: str) -> bool:
  try:
    params.get(key, return_default=True)
    return True
  except Exception:
    return False


def _service_exists() -> bool:
  try:
    from cereal.services import SERVICE_LIST
    return SERVICE in SERVICE_LIST
  except Exception:
    return False


class ObdLink:
  def __init__(self):
    self._params = Params()
    self._sm = None
    self._last_rx = 0.0
    self._snap = ObdSnapshot()

  def available(self) -> bool:
    return _service_exists() and _has_param(self._params, "BPObdEnabled")

  def snapshot(self) -> ObdSnapshot:
    if not self.available():
      return ObdSnapshot()
    if self._sm is None:
      try:
        from cereal import messaging
        self._sm = messaging.SubMaster([SERVICE])
      except Exception:
        return ObdSnapshot()
    self._sm.update(0)
    if self._sm.updated[SERVICE]:
      self._last_rx = time.monotonic()
      self._snap = self._read(self._sm[SERVICE])
    self._snap.received = bool(self._last_rx) and time.monotonic() - self._last_rx < STALE_S
    return self._snap

  @staticmethod
  def _read(m) -> ObdSnapshot:
    return ObdSnapshot(
      enabled=bool(m.enabled), transport=str(m.transport), link=str(m.link), message=str(m.message),
      adapter=str(m.adapter), protocol=str(m.protocol), bluetooth_available=bool(m.bluetoothAvailable),
      bluetooth_message=str(m.bluetoothMessage), usb_devices=[str(d) for d in m.usbDevices], polling=bool(m.polling),
      values=[ObdValue(str(v.shortName or v.name), float(v.value), str(v.unit), float(v.ageS), str(v.name or v.shortName))
              for v in m.values],
    )

  # -- settings -----------------------------------------------------------------------------

  def get(self, key: str, default=""):
    try:
      v = self._params.get(key, return_default=True)
    except Exception:
      return default
    if isinstance(v, bytes):
      v = v.decode(errors="ignore")
    return default if v is None else v

  def has(self, key: str) -> bool:
    return _has_param(self._params, key)

  def put_bool(self, key: str, v: bool):
    if self.has(key):
      self._params.put_bool(key, v)

  def configure(self, transport: str, address: str):
    if not self.available():
      return
    self._params.put("BPObdTransport", transport)
    self._params.put("BPObdAddress", address)
    self._params.put_bool("BPObdEnabled", True)

  def disable(self):
    if self.available():
      self._params.put_bool("BPObdEnabled", False)


_link: ObdLink | None = None


def obd_link() -> ObdLink:
  global _link
  if _link is None:
    _link = ObdLink()
  return _link


UNIT = {"degC": "°C", "percent": "%", "kPa": "kPa", "V": "V", "A": "A", "kWh": "kWh"}


def fmt_value(v: ObdValue) -> str:
  """Metric from obdd; tire pressure is shown in PSI (Canadian units, PSI for tires)."""
  if v.unit == "kPa":
    return f"{v.value * 0.145038:.0f} PSI"
  unit = UNIT.get(v.unit, v.unit)
  num = f"{v.value:.0f}" if abs(v.value) >= 100 or v.unit == "percent" else f"{v.value:.1f}"
  return f"{num} {unit}".strip() if unit != "%" else f"{num}%"


LINK_TEXT = {
  "off": "Off", "unavailable": "Not available", "connecting": "Connecting", "initializing": "Setting up adapter",
  "connected": "Connected", "carAsleep": "Truck asleep", "idle": "Paused while truck is off", "error": "Error",
}


# -- connected / not connected ----------------------------------------------------------------

MAX_AGE_S = 120.0  # a value older than this is dropped rather than shown stale


def live_values() -> dict[str, ObdValue]:
  """OBD values by short name, only while the adapter is connected and the truck answers. Anything else
  (off, not set up, connecting, truck asleep, error) returns {}, so callers simply leave OBD items out."""
  link = obd_link()
  if not link.available():
    return {}
  snap = link.snapshot()
  if not snap.received or snap.link != "connected":
    return {}
  return {v.name: v for v in snap.values if 0 <= v.age_s < MAX_AGE_S}


def connected() -> bool:
  return bool(live_values())


def status() -> tuple[str, str]:
  """(state, text) for a small status line: state is connected, waiting, off or setup."""
  link = obd_link()
  if not link.available():
    return "setup", "Not set up"
  snap = link.snapshot()
  if not snap.received:
    return ("waiting", "Starting") if str(link.get("BPObdEnabled", "")) in ("1", "True", "true") else ("off", "Off")
  if not snap.enabled or snap.link == "off":
    return "off", "Off"
  if snap.link == "connected":
    return "connected", "Connected" + (f" · {snap.adapter}" if snap.adapter else "")
  return "waiting", LINK_TEXT.get(snap.link, "Waiting")
