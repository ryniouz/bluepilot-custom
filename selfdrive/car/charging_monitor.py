#!/usr/bin/env python3
"""
Custom: offroad charging monitor (stream B).

card stops when the truck turns off, so nothing decodes CAN while it charges with the
ignition off. This process runs offroad only, passively parses the battery and charge-status
messages from pandad's `can` stream, and:
  - publishes `chargingStateBP` at 2 Hz for the UI's charging screen
  - writes BPChargingActive / BPChargeLastActiveTs, which power monitoring uses to stay awake
    while charging and power down BPChargeSleepDelayMin after the charge ends.

Read-only on the bus: no diagnostic requests, nothing is sent.
"""
import math
import time

import cereal.messaging as messaging
from cereal import car
from opendbc.can import CANParser
from opendbc.car import Bus
from opendbc.car.ford.fordcan import CanBus
from opendbc.car.ford.values import DBC, FordFlags
from opendbc.sunnypilot.car.ford.lightning import CHARGING_PT_MESSAGES, LightningState, fill_car_state_bp
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.pandad import can_capnp_to_list

RATE_HZ = 2.
CAN_ALIVE_NS = 2_000_000_000
PARAM_REFRESH_S = 10.


def load_car_params(params: Params):
  raw = params.get("CarParamsPersistent")
  if raw is None:
    return None
  with car.CarParams.from_bytes(raw) as cp:
    return cp.as_builder()


def supported(CP) -> bool:
  return CP is not None and CP.brand == "ford" and bool(CP.flags & FordFlags.CANFD)


def sleep_in_seconds(params: Params, charging: bool, now: float) -> float:
  if charging:
    return -1.
  last = params.get("BPChargeLastActiveTs")
  if last is None:
    return -1.
  delay_s = 60. * float(params.get("BPChargeSleepDelayMin", return_default=True) or 0)
  if delay_s <= 0:  # 0 = no post-charge rule, MaxTimeOffroad decides
    return -1.
  return max(0., delay_s - (now - float(last)))


class ChargingMonitor:
  def __init__(self, CP, params: Params):
    self.params = params
    self.cp = CANParser(DBC[CP.carFingerprint][Bus.pt], [(m, math.nan) for m in CHARGING_PT_MESSAGES], CanBus(CP).main)
    self.state = LightningState()
    self.charging_last: bool | None = None
    self.last_param_write = -math.inf

  def step(self, can_strings: list[bytes], now: float):
    """One 2 Hz tick: parse new CAN, update params for power monitoring, return a chargingStateBP message."""
    if can_strings:
      self.cp.update(can_capnp_to_list(can_strings))
    values = self.state.update_charging_only(self.cp, 1. / RATE_HZ)
    charging = bool(values["charging.charging"])

    # power monitoring reads these; write on change and refresh the timestamp while charging
    if charging != self.charging_last:
      self.params.put_bool_nonblocking("BPChargingActive", charging)
      self.charging_last = charging
    if charging and now - self.last_param_write >= PARAM_REFRESH_S:
      self.params.put_nonblocking("BPChargeLastActiveTs", now)
      self.last_param_write = now

    dat = messaging.new_message('chargingStateBP')
    dat.valid = True
    msg = dat.chargingStateBP
    fill_car_state_bp(msg, {k: v for k, v in values.items() if k.startswith(("charging.", "evBattery."))})
    cp = self.cp
    msg.canAlive = bool(can_strings) and cp.last_nonempty_nanos > 0 and \
                   (cp._last_update_nanos - cp.last_nonempty_nanos) < CAN_ALIVE_NS
    msg.keepAwake = charging and bool(self.params.get("BPChargeKeepAwake", return_default=True))
    msg.sleepInSeconds = sleep_in_seconds(self.params, charging, now)
    return dat


def main():
  params = Params()
  CP = load_car_params(params)
  if not supported(CP):
    cloudlog.info("charging_monitor: not a CAN FD Ford, idling")
    while True:
      time.sleep(60.)

  monitor = ChargingMonitor(CP, params)
  can_sock = messaging.sub_sock('can', conflate=False, timeout=0)
  pm = messaging.PubMaster(['chargingStateBP'])
  rk = Ratekeeper(RATE_HZ, print_delay_threshold=None)
  while True:
    pm.send('chargingStateBP', monitor.step(messaging.drain_sock_raw(can_sock), time.monotonic()))
    rk.keep_time()


if __name__ == "__main__":
  main()
