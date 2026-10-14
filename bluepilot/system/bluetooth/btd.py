#!/usr/bin/env python3
"""
Bluetooth on the comma 3X: the on/off setting (BPBluetoothEnabled) and everything needed to make it work.

Stock AGNOS has no Bluetooth (CONFIG_BT=n). With the Citadel Bluetooth kernel (boot image built from
agnos-kernel-sdm845 plus the Bluetooth parts of StarPilot's "Bluey" change) the chip shows up as /dev/btpower,
but AGNOS still lacks BlueZ. So when Bluetooth is turned on, this daemon:

  1. checks the kernel (/dev/btpower); without it the setting just reports "needs the Bluetooth OS update"
  2. installs the bundled BlueZ packages (debs/, Ubuntu 24.04 arm64, checked against SHA256SUMS) once,
     only while parked, by remounting / read-write for dpkg and back to read-only after
  3. powers the chip up and attaches it (bt_init.sh), then starts bluetoothd

Turning it off powers the adapter down and blocks it with rfkill. Status goes to BPBluetoothStatus (JSON) for
the Connect > Bluetooth page. An AGNOS update replaces the root filesystem; step 2 then runs again by itself.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time

from openpilot.common.params import Params
from openpilot.common.swaglog import cloudlog
from openpilot.system.hardware import TICI

HERE = os.path.dirname(os.path.abspath(__file__))
DEBS = os.path.join(HERE, "debs")
BTPOWER = "/dev/btpower"
SYS_BT = "/sys/class/bluetooth"
LOOP_S = 5.0
RETRY_S = 60.0


def sh(*cmd: str, timeout: float = 60.0) -> tuple[bool, str]:
  try:
    out = subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout, check=False)
    return out.returncode == 0, (out.stdout + out.stderr).strip()
  except (OSError, subprocess.TimeoutExpired) as e:
    return False, str(e)


def sudo(*cmd: str, timeout: float = 60.0) -> tuple[bool, str]:
  return sh("sudo", "-n", *cmd, timeout=timeout)


def kernel_ready() -> bool:
  return os.path.exists(BTPOWER)


def bluez_installed() -> bool:
  return all(shutil.which(t) for t in ("hciattach", "hciconfig", "bluetoothctl", "rfkill"))


def adapter_up() -> bool:
  try:
    return any(n.startswith("hci") for n in os.listdir(SYS_BT))
  except OSError:
    return False


def debs_ok() -> list[str] | None:
  """The bundled .deb paths when every one matches SHA256SUMS, else None."""
  try:
    sums = dict(reversed(ln.split()) for ln in open(os.path.join(DEBS, "SHA256SUMS")) if ln.strip())
  except (OSError, ValueError):
    return None
  paths = []
  for name, want in sums.items():
    p = os.path.join(DEBS, name)
    try:
      with open(p, "rb") as f:
        if hashlib.sha256(f.read()).hexdigest() != want:
          return None
    except OSError:
      return None
    paths.append(p)
  return paths or None


def install_bluez() -> tuple[bool, str]:
  debs = debs_ok()
  if debs is None:
    return False, "BlueZ packages missing or damaged"
  ok, out = sudo("mount", "-o", "remount,rw", "/")
  if not ok:
    return False, f"couldn't remount / ({out[-120:]})"
  try:
    ok, out = sudo("dpkg", "-i", "--force-confold", *debs, timeout=300)
  finally:
    sudo("mount", "-o", "remount,ro", "/")
  return ok, "" if ok else f"dpkg failed ({out[-200:]})"


class BluetoothDaemon:
  def __init__(self):
    self.params = Params()
    self.state = ""
    self.message = ""
    self.next_try = 0.0

  def publish(self, state: str, message: str = ""):
    if (state, message) == (self.state, self.message):
      return
    self.state, self.message = state, message
    status = {"state": state, "message": message, "kernel": kernel_ready(), "bluez": bluez_installed(),
              "adapter": adapter_up()}
    try:
      self.params.put("BPBluetoothStatus", json.dumps(status))
    except Exception:
      pass
    cloudlog.info(f"btd: {state} {message}")

  def turn_off(self):
    if adapter_up() and shutil.which("bluetoothctl"):
      sh("bluetoothctl", "power", "off", timeout=8)
    if shutil.which("rfkill"):
      sudo("rfkill", "block", "bluetooth", timeout=8)
    self.publish("off")

  def turn_on(self, onroad: bool):
    if self.state == "on" and adapter_up():
      return
    if not kernel_ready():
      self.publish("no_kernel")
      return
    if time.monotonic() < self.next_try:
      return
    if not bluez_installed():
      if onroad:
        self.publish("waiting", "BlueZ installs while parked")
        return
      self.publish("installing")
      ok, msg = install_bluez()
      if not ok:
        self.next_try = time.monotonic() + RETRY_S
        self.publish("error", msg)
        return
    if not adapter_up():
      self.publish("starting")
      ok, out = sudo("bash", os.path.join(HERE, "bt_init.sh"), timeout=60)
      if not ok or not adapter_up():
        self.next_try = time.monotonic() + RETRY_S
        self.publish("error", f"adapter didn't start ({out[-160:]})")
        return
    sudo("rfkill", "unblock", "bluetooth", timeout=8)
    sudo("systemctl", "start", "bluetooth", timeout=30)
    self.publish("on")

  def step(self):
    enabled = self.params.get_bool("BPBluetoothEnabled")
    onroad = self.params.get_bool("IsOnroad")
    if enabled:
      self.turn_on(onroad)
    elif self.state not in ("off", "") or adapter_up():
      self.turn_off()
    elif not self.state:
      self.publish("off" if kernel_ready() else "no_kernel")


def main():
  if not TICI:
    return
  d = BluetoothDaemon()
  while True:
    try:
      d.step()
    except Exception:
      cloudlog.exception("btd: step failed")
    time.sleep(LOOP_S)


if __name__ == "__main__":
  main()
