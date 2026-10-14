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

It also reports the 12 V battery (CAN first, then the OBD adapter) and why the truck is awake, and writes
BPLvState, which hardwared and power monitoring use to ignore the Lightning's 12 V top-up wakes and to apply
the 12 V cutoffs and power saver (see lv_power.py).

It also clears a one-trip Guest Mode at the start of each offroad period (see guest_mode.py).
"""
import math
import time

import cereal.messaging as messaging
from cereal import car
from opendbc.can import CANParser
from opendbc.car import Bus
from opendbc.car.ford.fordcan import CanBus
from opendbc.car.ford.values import DBC, FordFlags
from opendbc.sunnypilot.car.ford.lightning import CHARGING_PT_MESSAGES, EvSettings, LightningState, fill_car_state_bp
from openpilot.common.params import Params
from openpilot.common.realtime import Ratekeeper
from openpilot.common.swaglog import cloudlog
from openpilot.selfdrive.car import lv_power
from openpilot.selfdrive.car.guest_mode import offroad_reset
from openpilot.selfdrive.pandad import can_capnp_to_list

RATE_HZ = 2.
CAN_ALIVE_NS = 2_000_000_000
PARAM_REFRESH_S = 10.
LV_REFRESH_S = 30.
TOP_UP_REFRESH_S = 2.
OBD_FRESH_S = 30.


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


def obd_low_volt(obd) -> tuple[float, float]:
  """12 V SOC and voltage from obdStateBP (built-in LvSoc / LvV), 0 when absent or stale."""
  soc = volts = 0.
  if obd is None:
    return soc, volts
  for val in obd.values:
    if val.ageS > OBD_FRESH_S:
      continue
    if val.shortName == "LvSoc" and 0. < val.value <= 100.:
      soc = float(val.value)
    elif val.shortName == "LvV" and 0. < val.value < 20.:
      volts = float(val.value)
  return soc, volts


def shutdown_reason(settings: lv_power.LvSettings, keep_awake: bool, low_soc: bool, top_up: bool, soc: float) -> str:
  if low_soc:
    return f"12V battery at {soc:.0f}%: powering down to protect it"
  if keep_awake:
    return "Staying on while the truck charges"
  if top_up:
    return "Truck is topping up its 12V battery: not a drive"
  if settings.saver:
    return f"12V power saver: powers down after {max(1, settings.saver_offroad_min)} min offroad"
  return ""


class ChargingMonitor:
  def __init__(self, CP, params: Params):
    self.params = params
    self.cp = CANParser(DBC[CP.carFingerprint][Bus.pt], [(m, math.nan) for m in CHARGING_PT_MESSAGES], CanBus(CP).main)
    self.state = LightningState()
    self.charging_last: bool | None = None
    self.last_param_write = -math.inf
    self.top_up_last: bool | None = None
    self.last_lv_write = -math.inf

  def step(self, can_strings: list[bytes], now: float, obd=None, harness_mv: float = 0.):
    """One 2 Hz tick: parse new CAN, update params for power monitoring, return a chargingStateBP message."""
    if can_strings:
      self.cp.update(can_capnp_to_list(can_strings))
    cp = self.cp
    can_alive = bool(can_strings) and cp.last_nonempty_nanos > 0 and \
                (cp._last_update_nanos - cp.last_nonempty_nanos) < CAN_ALIVE_NS
    settings = lv_power.read_settings(self.params)
    alert_v = float(self.params.get("BPLowVoltAlertV", return_default=True) or EvSettings.low_volt_v)
    values = self.state.update_charging_only(cp, 1. / RATE_HZ, can_alive, EvSettings(low_volt_v=alert_v))
    charging = bool(values["charging.charging"])

    # power monitoring reads these; write on change and refresh the timestamp while charging
    if charging != self.charging_last:
      self.params.put_bool_nonblocking("BPChargingActive", charging)
      self.charging_last = charging
    if charging and now - self.last_param_write >= PARAM_REFRESH_S:
      self.params.put_nonblocking("BPChargeLastActiveTs", now)
      self.last_param_write = now

    # 12 V battery: CAN, else the OBD adapter's LvSoc / LvV
    lv = {k: v for k, v in values.items() if k.startswith("lowVoltBattery.")}
    source = "can" if lv["lowVoltBattery.dataAvailable"] and lv["lowVoltBattery.socPercent"] > 0 else "none"
    obd_soc, obd_volts = obd_low_volt(obd)
    if source == "none" and (obd_soc > 0 or obd_volts > 0):
      source = "obd"
      lv.update({"lowVoltBattery.dataAvailable": True, "lowVoltBattery.socPercent": obd_soc, "lowVoltBattery.voltage": obd_volts,
                 "lowVoltBattery.current": 0., "lowVoltBattery.tempC": 0., "lowVoltBattery.fault": False,
                 "lowVoltBattery.low": 0. < obd_volts < alert_v})
    elif source == "none" and lv["lowVoltBattery.voltage"] > 0:
      source = "can"  # voltage without SOC
    soc = lv["lowVoltBattery.socPercent"]
    volts = lv["lowVoltBattery.voltage"]

    # BPLvState for hardwared / power monitoring. The top-up flag clears the moment the reason changes,
    # so a real drive start is never held back by the debounce.
    top_up = self.state.low_volt_top_up and values["wake.reason"] == "lowVoltTopUp"
    if top_up != self.top_up_last or (top_up and now - self.last_lv_write >= TOP_UP_REFRESH_S) or \
       now - self.last_lv_write >= LV_REFRESH_S:
      self.params.put_nonblocking(lv_power.LV_STATE_KEY, {
        "ts": now, "soc": soc if soc > 0 else None, "volts": volts if volts > 0 else None, "src": source,
        "topUp": top_up, "topUpTs": now, "topUps": values["wake.lowVoltTopUps"],
      })
      if top_up != self.top_up_last:
        cloudlog.info(f"charging_monitor: 12 V top-up wake {'started' if top_up else 'ended'}")
      self.top_up_last = top_up
      self.last_lv_write = now

    dat = messaging.new_message('chargingStateBP')
    dat.valid = True
    msg = dat.chargingStateBP
    fill_car_state_bp(msg, {k: v for k, v in values.items() if k.startswith(("charging.", "evBattery.", "wake."))})
    fill_car_state_bp(msg, lv)
    msg.lowVoltSource = source
    msg.harnessVoltage = harness_mv / 1000. if harness_mv > 0 else 0.
    msg.canAlive = can_alive
    msg.keepAwake = charging and bool(self.params.get("BPChargeKeepAwake", return_default=True))
    msg.sleepInSeconds = sleep_in_seconds(self.params, charging, now)
    msg.powerSaver = settings.saver
    low_soc = settings.soc_cutoff > 0 and 0 < soc < settings.soc_cutoff
    msg.shutdownReason = shutdown_reason(settings, msg.keepAwake, low_soc, top_up, soc)
    return dat


def main():
  params = Params()
  if offroad_reset(params):  # one process per offroad period, so this runs once after every drive
    cloudlog.info("guest mode: one-trip guest drive ended, back to BluePilot")
  CP = load_car_params(params)
  if not supported(CP):
    cloudlog.info("charging_monitor: not a CAN FD Ford, idling")
    while True:
      time.sleep(60.)

  monitor = ChargingMonitor(CP, params)
  can_sock = messaging.sub_sock('can', conflate=False, timeout=0)
  sm = messaging.SubMaster(['obdStateBP', 'peripheralState'])
  pm = messaging.PubMaster(['chargingStateBP'])
  rk = Ratekeeper(RATE_HZ, print_delay_threshold=None)
  while True:
    sm.update(0)
    obd = sm['obdStateBP'] if sm.recv_frame['obdStateBP'] > 0 else None
    harness_mv = sm['peripheralState'].voltage if sm.recv_frame['peripheralState'] > 0 else 0.
    pm.send('chargingStateBP', monitor.step(messaging.drain_sock_raw(can_sock), time.monotonic(), obd, harness_mv))
    rk.keep_time()


if __name__ == "__main__":
  main()
