"""
Bluetooth for the Console Bluetooth page: adapter check, discovery and pairing through BlueZ's
bluetoothctl when the OS has it.

Status on the comma 3X is not confirmed: the fork has no Bluetooth code, comma's docs don't list it,
and whether AGNOS exposes an adapter needs a check on the device (CONNECTIVITY-AND-ALL-IN-ONE.md §1.1).
So every call first checks /sys/class/bluetooth and bluetoothctl, and the page shows "no adapter"
instead of pretending. All commands run on a worker thread; the page reads snapshots.

Reading OBD data over the paired dongle (RFCOMM serial, ELM327 commands) is not built here; the
"Lightning control and CAN" thread owns that work.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass, field

from openpilot.common.params import Params

SYS_BT = "/sys/class/bluetooth"
SCAN_S = 12
OBD_NAME = re.compile(r"obd|elm|vgate|veepeak|obdlink|vlink|v-link|icar|konnwei|carista|bafx|kiwi", re.I)
DEVICE_LINE = re.compile(r"^Device ([0-9A-F:]{17}) (.+)$", re.I)


@dataclass
class BtDevice:
  mac: str
  name: str
  paired: bool = False
  connected: bool = False

  @property
  def looks_like_obd(self) -> bool:
    return bool(OBD_NAME.search(self.name))


@dataclass
class BtState:
  adapter: bool = False          # an HCI adapter exists
  tool: bool = False             # bluetoothctl is installed
  powered: bool = False
  scanning: bool = False
  devices: list[BtDevice] = field(default_factory=list)
  busy: str = ""                 # what a running command is doing, for the page
  message: str = ""              # result of the last action
  checked_at: float = 0.0


def _run(*args: str, timeout: float = 20.0) -> str:
  try:
    out = subprocess.run(["bluetoothctl", *args], capture_output=True, text=True, timeout=timeout, check=False)
    return out.stdout or ""
  except (OSError, subprocess.TimeoutExpired):
    return ""


def _parse_devices(text: str) -> dict[str, str]:
  found = {}
  for ln in text.splitlines():
    m = DEVICE_LINE.match(ln.strip())
    if m:
      found[m.group(1).upper()] = m.group(2).strip()
  return found


class Bluetooth:
  def __init__(self):
    self._lock = threading.Lock()
    self._state = BtState()
    self._worker: threading.Thread | None = None

  @property
  def state(self) -> BtState:
    with self._lock:
      return self._state

  def _set(self, **kw):
    with self._lock:
      for k, v in kw.items():
        setattr(self._state, k, v)

  def _start(self, label: str, fn):
    if self._worker is not None and self._worker.is_alive():
      return
    self._set(busy=label, message="")

    def run():
      try:
        fn()
      finally:
        self._set(busy="", scanning=False)
    self._worker = threading.Thread(target=run, name="console-bluetooth", daemon=True)
    self._worker.start()

  # -- queries ------------------------------------------------------------------------------

  @staticmethod
  def has_adapter() -> bool:
    try:
      return any(n.startswith("hci") for n in os.listdir(SYS_BT))
    except OSError:
      return False

  def refresh(self):
    """Cheap presence check plus, when possible, the paired list (on a worker)."""
    adapter, tool = self.has_adapter(), shutil.which("bluetoothctl") is not None
    self._set(adapter=adapter, tool=tool, checked_at=time.monotonic())
    if adapter and tool:
      self._start("", self._load)

  def _load(self):
    show = _run("show", timeout=5)
    paired = _parse_devices(_run("devices", "Paired", timeout=5)) or _parse_devices(_run("paired-devices", timeout=5))
    devices = [BtDevice(mac, name, paired=True) for mac, name in paired.items()]
    self._set(powered="Powered: yes" in show, devices=devices)

  # -- actions ------------------------------------------------------------------------------

  def power(self, on: bool):
    self._start(("Turning on" if on else "Turning off"), lambda: (_run("power", "on" if on else "off", timeout=8), self._load()))

  def scan(self):
    def work():
      self._set(scanning=True)
      _run("power", "on", timeout=8)
      _run("--timeout", str(SCAN_S), "scan", "on", timeout=SCAN_S + 5)
      seen = _parse_devices(_run("devices", timeout=5))
      paired = set(_parse_devices(_run("devices", "Paired", timeout=5)) or _parse_devices(_run("paired-devices", timeout=5)))
      devices = [BtDevice(mac, name, paired=mac in paired) for mac, name in seen.items()]
      devices.sort(key=lambda d: (not d.paired, not d.looks_like_obd, d.name.lower()))
      self._set(devices=devices, message=f"{len(devices)} found" if devices else "Nothing found nearby")
    self._start("Searching", work)

  def pair(self, mac: str):
    def work():
      out = _run("pair", mac, timeout=30)
      ok = "Pairing successful" in out or "AlreadyExists" in out
      if ok:
        _run("trust", mac, timeout=8)
      self._set(message="Paired" if ok else "Pairing failed")
      self._load()
    self._start("Pairing", work)

  def forget(self, mac: str):
    self._start("Removing", lambda: (_run("remove", mac, timeout=8), self._load()))


_bt: Bluetooth | None = None


def bluetooth() -> Bluetooth:
  global _bt
  if _bt is None:
    _bt = Bluetooth()
  return _bt


def saved(params: Params, key: str) -> dict | None:
  """BPObdDongle / BPPhoneLink: {"mac": ..., "name": ...} once the user picked a device."""
  try:
    raw = params.get(key)
    data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    return data if isinstance(data, dict) and data.get("mac") else None
  except Exception:
    return None


def save(params: Params, key: str, dev: BtDevice | None):
  try:
    if dev is None:
      params.remove(key)
    else:
      params.put(key, json.dumps({"mac": dev.mac, "name": dev.name}))
  except Exception:
    pass
