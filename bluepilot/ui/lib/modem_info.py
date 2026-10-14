"""
Cellular modem details for the Cellular page, read through the same HARDWARE calls hardwared and athena
use (ModemManager over D-Bus). The calls can take seconds, so a background thread refreshes them while the
page is open; the page only reads the last snapshot. Live signal, carrier, band and data counters come from
deviceState instead, which hardwared already publishes.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from openpilot.system.hardware import HARDWARE

REFRESH_S = 15.0


@dataclass
class ModemSnapshot:
  sim_present: bool = False
  sim_id: str = ""            # ICCID
  mcc_mnc: str = ""
  data_connected: bool = False
  imei: str = ""
  modem_version: str = ""
  read_at: float = 0.0        # monotonic; 0 = never read
  error: str = ""


class ModemInfo:
  def __init__(self):
    self._lock = threading.Lock()
    self._snap = ModemSnapshot()
    self._busy = False

  @property
  def snapshot(self) -> ModemSnapshot:
    with self._lock:
      return self._snap

  def request(self, force: bool = False):
    snap = self.snapshot
    if self._busy or (not force and snap.read_at and time.monotonic() - snap.read_at < REFRESH_S):
      return
    self._busy = True
    threading.Thread(target=self._run, name="console-modem-info", daemon=True).start()

  def _run(self):
    snap = ModemSnapshot()
    try:
      sim = HARDWARE.get_sim_info() or {}
      snap.sim_present = "ABSENT" not in (sim.get("sim_state") or ["ABSENT"])
      snap.sim_id = str(sim.get("sim_id") or "")
      snap.mcc_mnc = str(sim.get("mcc_mnc") or "")
      snap.data_connected = bool(sim.get("data_connected"))
      try:
        snap.imei = str(HARDWARE.get_imei(0) or "")
      except Exception:
        snap.imei = ""
      try:
        snap.modem_version = str(HARDWARE.get_modem_version() or "")
      except Exception:
        snap.modem_version = ""
    except Exception as e:
      snap.error = str(e)
    snap.read_at = time.monotonic()
    with self._lock:
      self._snap = snap
    self._busy = False

  def restart_modem(self):
    threading.Thread(target=self._restart, name="console-modem-restart", daemon=True).start()

  @staticmethod
  def _restart():
    try:
      HARDWARE.reboot_modem()
    except Exception:
      pass


_info: ModemInfo | None = None


def modem_info() -> ModemInfo:
  global _info
  if _info is None:
    _info = ModemInfo()
  return _info


def mask(s: str, keep: int = 4) -> str:
  """Show only the last digits of an identifier (ICCID, IMEI)."""
  s = s.strip()
  return s if len(s) <= keep else "•••• " + s[-keep:]
