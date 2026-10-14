"""
Custom: F-150 Lightning EV state, vehicle mode and tune profiles (stream B).

Everything here is pure Python with no cereal or Params dependency, so it can be unit tested
with a fake CAN parser. carstate.py fills carStateBP from LightningState; carcontroller.py
reads the active TuneValues.

Safety: tune values may only make control gentler than stock. Scales are clamped to <= 1.0
and nothing here touches CarControllerParams or the panda safety limits in ford.h.
"""
from dataclasses import dataclass, fields, replace

import numpy as np

from opendbc.car.ford.values import CAR

LIGHTNING_PLATFORMS = (CAR.FORD_F_150_LIGHTNING_MK1,)

STALE_NS = 5_000_000_000  # a message not seen for 5 s counts as unavailable

# Non-critical (nan frequency) PT messages added to the parser on CAN FD Fords.
# They may or may not reach the comma's bus; availability is decided at runtime.
EV_PT_MESSAGES = (
  "Battery_Traction_5_FD1",   # 0x24D charge/discharge power limits
  "Battery_Traction_6_FD1",   # 0x458 pack delta temperature
  "MtrTracData_1_FD1",        # 0x441 motor current (pack current on Lightning)
  "PreCond_Hev_Data2_FD1",    # 0x185 BattTrac_I_EstVsc
  "MtrTrac_Data2_FD1",        # 0x442 range
  "HEV_ChargeStat_FD1",       # 0x352 range fallback
  "Cluster_HEV_Data9_FD1",    # 0x475 motor torque
  "Tire_Pressure_Data_FD1",   # 0x3B5
  "Battery_Mgmt_3_FD1",       # 0x43C 12 V SOC and temperature
  "Battery_Mgmt_4_FD1",       # 0x42B 12 V voltage and current
  "Climate_Control_Data_FD1", # 0x41A outside air temperature (display value)
  "EngineClimateData",        # 0x178 outside air temperature fallback
  "SmartChargingData_ECG_3",  # 0x308 outside air temperature fallback
  "SelectDriveModeData",      # 0x420 drive mode
  "TrailerInfo_FD1",          # 0x443 trailer lamp connection
  "TrailerBrakeInfo_FD1",     # 0x445 trailer brake connection
  "PreCond_Hev_Data1_FD1",    # 0x440 charge status (AC / DC / scheduled / paused ...)
  "Cluster_HEV_Data1_FD1",    # 0x312 cluster charge status fallback
  "MHT_EV_Wakeup_FD1",        # 0x478 battery preconditioning, coolant heater, wake alarm
  "HEV_Powertrain_Data6",     # 0x480 DC/DC and 12 V support requests
)

# ChrgStat_D2_Dsply (0x440)
CHARGE_STATE_D2 = {
  0: "notReady", 1: "fault", 2: "fault", 3: "evseNotCompatible", 4: "evseNotDetected", 5: "evsePaused",
  6: "scheduled", 7: "chargingAc", 8: "chargingDc", 9: "chargingInductive", 10: "maintaining",
  11: "cabinPreconditioning", 12: "driveConditioning", 13: "targetReached",
}
# ChrgStat_D_Dsply (0x312)
CHARGE_STATE_CLUSTER = {
  0: "notReady", 1: "fault", 2: "fault", 3: "fault", 4: "chargingUnknownType", 5: "scheduled", 6: "targetReached",
}
CHARGE_TYPE = {"chargingAc": "ac", "chargingDc": "dc", "chargingInductive": "other", "chargingUnknownType": "other"}
# What the offroad charging monitor parses: battery, current and charge status only
CHARGING_PT_MESSAGES = (
  "Battery_Traction_1_FD1", "Battery_Traction_3_FD1", "Battery_Traction_4_FD1", "Battery_Traction_5_FD1",
  "Battery_Traction_6_FD1", "MtrTracData_1_FD1", "PreCond_Hev_Data2_FD1", "MtrTrac_Data2_FD1", "HEV_ChargeStat_FD1",
  "Cluster_HEV_Data9_FD1", "PreCond_Hev_Data1_FD1", "Cluster_HEV_Data1_FD1", "MHT_EV_Wakeup_FD1",
  "Battery_Mgmt_3_FD1", "Battery_Mgmt_4_FD1", "HEV_Powertrain_Data6", "BodyInfo_3_FD1",
)
# Ignition_Status (0x3B3)
IGNITION_STATUS = {1: "off", 2: "accessory", 4: "run", 8: "start"}
# Already parsed by BluePilot when FordFlags.HEV_BATTERY_DATA is set; added here otherwise.
HEV_BATTERY_MESSAGES = ("Battery_Traction_1_FD1", "Battery_Traction_3_FD1", "Battery_Traction_4_FD1")

# SelDrvMdePt_D_Rq values from the DBC
DRIVE_MODE_MAP = {
  0: "normal",
  1: "sport", 14: "sport", 16: "sport",
  3: "tow",
  5: "slippery",
  6: "eco",
  7: "offroad", 8: "offroad", 9: "offroad", 15: "offroad",
}

CURRENT_SOURCES = ("none", "battTracActl", "mtrTrac2Actl", "battTracEstVsc")


def msg_age_ns(cp, name: str) -> int | None:
  """Nanoseconds since the message was last parsed, or None if never seen."""
  ts = cp.ts_nanos.get(name)
  if not ts:
    return None
  last = max(ts.values())
  if last == 0:
    return None
  return max(getattr(cp, "_last_update_nanos", last) - last, 0)


def msg_fresh(cp, name: str) -> bool:
  age = msg_age_ns(cp, name)
  return age is not None and age < STALE_NS


def range_impact_percent(outside_temp_c: float) -> float:
  """Rough range change vs. mild weather. Estimate from published EV fleet data, not Lightning-measured."""
  return float(np.interp(outside_temp_c, [-20., -10., 0., 10., 20., 30., 40.], [-40., -30., -20., -10., 0., 0., -8.]))


class Debounce:
  """Boolean that only flips after the input holds for on_s / off_s seconds."""
  def __init__(self, on_s: float, off_s: float):
    self.on_s, self.off_s = on_s, off_s
    self.state = False
    self._t = 0.0

  def update(self, value: bool, dt: float) -> bool:
    if value != self.state:
      self._t += dt
      if self._t >= (self.on_s if value else self.off_s):
        self.state = value
        self._t = 0.0
    else:
      self._t = 0.0
    return self.state


class OnePedalEstimator:
  """Infers One-Pedal Drive from lift-off deceleration while the driver is driving.

  No One-Pedal signal is known in the Ford DBC. Lightning One-Pedal regen reaches about 0.2 g,
  while normal lift-off regen is well under 0.1 g, so sustained deceleration past ACTIVE_ACCEL
  with no pedal pressed and cruise off means One-Pedal is on. Steep uphill grades can fool it,
  which is why the result is published as `estimated` and only softens creep handling.
  """
  ACTIVE_ACCEL = -1.4   # m/s^2
  INACTIVE_ACCEL = -0.4
  ACTIVE_S = 1.5
  INACTIVE_S = 2.5
  V_MIN, V_MAX = 4.0, 30.0

  def __init__(self):
    self.active = False
    self._t_on = 0.0
    self._t_off = 0.0

  def update(self, v_ego: float, a_ego: float, gas: bool, brake: bool, cruise: bool, dt: float) -> bool:
    if gas or brake or cruise or not (self.V_MIN < v_ego < self.V_MAX):
      self._t_on = self._t_off = 0.0
      return self.active
    self._t_on = self._t_on + dt if a_ego < self.ACTIVE_ACCEL else 0.0
    self._t_off = self._t_off + dt if a_ego > self.INACTIVE_ACCEL else 0.0
    if self._t_on >= self.ACTIVE_S:
      self.active = True
    elif self._t_off >= self.INACTIVE_S:
      self.active = False
    return self.active


@dataclass
class EvSettings:
  low_soc_pct: float = 20.
  critical_soc_pct: float = 10.
  tire_low_kpa: float = 240.
  low_volt_v: float = 11.8
  one_pedal_mode: int = 2  # 0 off, 1 on, 2 estimate


class LightningState:
  """Parses EV, tire, 12 V, ambient, drive-mode and trailer data and runs the alert logic.

  `values` is a flat dict keyed like the carStateBP fields, so the capnp fill is mechanical.
  """
  SOC_HYSTERESIS = 2.0

  def __init__(self):
    self.trip_used_wh = 0.0
    self.trip_regen_wh = 0.0
    self.trip_m = 0.0
    self.efficiency = 0.0
    self.soc_level = "none"
    self.trailer = Debounce(2.0, 5.0)
    self.tire_low = Debounce(3.0, 3.0)
    self.low_volt = Debounce(5.0, 5.0)
    self.one_pedal = OnePedalEstimator()
    self.charging = Debounce(2.0, 2.0)
    self.top_up = Debounce(2.0, 2.0)
    self.top_up_prev = False
    self.top_up_count = 0
    self.values: dict = {}

  # *** traction battery ***
  @staticmethod
  def _motor_current(cp) -> float | None:
    if msg_fresh(cp, "MtrTracData_1_FD1"):
      i = cp.vl["MtrTracData_1_FD1"]["MtrTrac2_I_Actl"]
      if -999.9 < i < 5553.0:  # raw 0 / 65535 = unset / faulty
        return i
    return None

  def _pack_current(self, cp) -> tuple[float, str]:
    # Order matters: whole-pack values first. Seen on the truck (TELEMETRY-FEASIBILITY.md): BattTrac_I_Actl is a
    # constant -750 A (raw 0); BattTrac_I_EstVsc and MtrTrac2_I_Actl both move, but MtrTrac2 is one motor only.
    if msg_fresh(cp, "Battery_Traction_1_FD1"):
      i = cp.vl["Battery_Traction_1_FD1"]["BattTrac_I_Actl"]
      if -749.9 < i < 888.0:
        return i, "battTracActl"
    if msg_fresh(cp, "PreCond_Hev_Data2_FD1"):
      i = cp.vl["PreCond_Hev_Data2_FD1"]["BattTrac_I_EstVsc"]
      if -749.9 < i < 888.0:
        return i, "battTracEstVsc"
    i = self._motor_current(cp)
    if i is not None:
      return i, "mtrTrac2Actl"
    return 0.0, "none"

  def _update_battery(self, cp, v_ego: float, dt: float) -> None:
    v = self.values
    soc_ok = msg_fresh(cp, "Battery_Traction_4_FD1")
    volt_ok = msg_fresh(cp, "Battery_Traction_1_FD1")
    soc = cp.vl["Battery_Traction_4_FD1"]["BattTracSoc2_Pc_Actl"] if soc_ok else 0.0
    soc_ok = soc_ok and soc <= 100.5
    volts = cp.vl["Battery_Traction_1_FD1"]["BattTrac_U_Actl"] if volt_ok else 0.0
    volt_ok = volt_ok and 0. < volts < 511.
    current, source = self._pack_current(cp)
    power_kw = volts * current / 1000. if (volt_ok and source != "none") else 0.0

    v["evBattery.dataAvailable"] = bool(soc_ok)
    v["evBattery.socPercent"] = float(soc) if soc_ok else 0.0
    v["evBattery.packVoltage"] = float(volts) if volt_ok else 0.0
    v["evBattery.packCurrent"] = float(current)
    v["evBattery.packCurrentSource"] = source
    v["evBattery.powerKw"] = float(power_kw)
    v["evBattery.regenKw"] = float(max(0.0, -power_kw))

    t4 = cp.vl["Battery_Traction_4_FD1"]["BattTrac_Te_Actl"] if soc_ok else 0.0
    v["evBattery.packTempC"] = float(t4) if t4 < 460. else 0.0
    v["evBattery.coolantTempC"] = float(cp.vl["Battery_Traction_3_FD1"]["BattTracClnt_Te_Actl"]) \
      if msg_fresh(cp, "Battery_Traction_3_FD1") else 0.0
    v["evBattery.packDeltaTempC"] = float(cp.vl["Battery_Traction_6_FD1"]["BattTracDelta_Te_Actl"]) \
      if msg_fresh(cp, "Battery_Traction_6_FD1") else 0.0

    limits_ok = msg_fresh(cp, "Battery_Traction_5_FD1")
    v["evBattery.limitsAvailable"] = limits_ok
    v["evBattery.chargeLimitKw"] = float(cp.vl["Battery_Traction_5_FD1"]["BattTrac2_Pw_LimChrg"] / 1000.) if limits_ok else 0.0
    v["evBattery.dischargeLimitKw"] = float(cp.vl["Battery_Traction_5_FD1"]["BattTrac2_Pw_LimDchrg"] / 1000.) if limits_ok else 0.0

    rng, rng_ok = 0.0, False
    for msg, sig in (("MtrTrac_Data2_FD1", "VehElRnge_L_Dsply"), ("HEV_ChargeStat_FD1", "VehElRngeNut_L_Dsply")):
      if msg_fresh(cp, msg):
        r = cp.vl[msg][sig]
        if 0. < r < 409.35:  # raw 4094/4095 = no data / fault
          rng, rng_ok = r, True
          break
    v["evBattery.rangeKm"] = float(rng)
    v["evBattery.rangeAvailable"] = rng_ok

    motor_i = self._motor_current(cp)
    motor_u = cp.vl["MtrTracData_1_FD1"]["MtrTrac2_U_Actl"] if motor_i is not None else 0.0
    v["evBattery.motorPowerAvailable"] = motor_i is not None and motor_u > 0.
    v["evBattery.motorPowerKw"] = float(motor_u * motor_i / 1000.) if v["evBattery.motorPowerAvailable"] else 0.0

    tq_ok = msg_fresh(cp, "Cluster_HEV_Data9_FD1")
    v["evBattery.motorTorqueAvailable"] = tq_ok
    v["evBattery.motorTorqueNm"] = float(cp.vl["Cluster_HEV_Data9_FD1"]["MtrTrac2_Tq_Actl"]) if tq_ok else 0.0

    # trip energy and live efficiency
    if power_kw != 0.0:
      wh = power_kw * 1000. * dt / 3600.
      if wh > 0:
        self.trip_used_wh += wh
      else:
        self.trip_regen_wh -= wh
    self.trip_m += max(v_ego, 0.) * dt
    if v_ego > 2.0 and power_kw != 0.0:
      inst = power_kw * 1000. / (v_ego * 3.6)  # W / (km/h) = Wh/km
      alpha = min(dt / 30., 1.)
      self.efficiency = inst if self.efficiency == 0.0 else self.efficiency + alpha * (inst - self.efficiency)
    v["evBattery.efficiencyWhPerKm"] = float(self.efficiency) if v_ego > 2.0 else 0.0
    v["evBattery.tripEnergyUsedKwh"] = float(self.trip_used_wh / 1000.)
    v["evBattery.tripEnergyRegenKwh"] = float(self.trip_regen_wh / 1000.)
    v["evBattery.tripDistanceKm"] = float(self.trip_m / 1000.)

  # *** body and environment ***
  def _update_tires(self, cp, s: EvSettings, dt: float) -> None:
    v = self.values
    ok = msg_fresh(cp, "Tire_Pressure_Data_FD1")
    msg = cp.vl["Tire_Pressure_Data_FD1"] if ok else {}
    sigs = (("frontLeftKpa", "Tire_Press_LF_Data"), ("frontRightKpa", "Tire_Press_RF_Data"),
            ("rearLeftKpa", "Tire_Press_LR_OLR_Data"), ("rearRightKpa", "Tire_Press_RR_ORR_Data"))
    pressures = []
    for field, sig in sigs:
      p = msg[sig] if ok else 0.0
      p = p if 0. < p < 65533. else 0.0  # 65533-65535 = unknown / invalid / not supported
      v[f"tirePressure.{field}"] = float(p)
      if p > 0:
        pressures.append(p)
    ok = ok and len(pressures) > 0
    v["tirePressure.dataAvailable"] = ok
    v["tirePressure.lowThresholdKpa"] = float(s.tire_low_kpa)
    v["tirePressure.lowPressure"] = self.tire_low.update(ok and min(pressures) < s.tire_low_kpa, dt)

  def _update_low_volt(self, cp, s: EvSettings, dt: float) -> None:
    v = self.values
    m4 = msg_fresh(cp, "Battery_Mgmt_4_FD1")
    m3 = msg_fresh(cp, "Battery_Mgmt_3_FD1")
    volts = cp.vl["Battery_Mgmt_4_FD1"]["BattULoAux_U_Actl"] if m4 else 0.0
    volts = volts if volts < 15.85 else 0.0  # raw 255 = faulty
    soc = cp.vl["Battery_Mgmt_4_FD1"]["BattULoAuxSoc_Pc_Actl"] if m4 else 0.0
    if (soc <= 0 or soc > 100) and m3:
      soc = cp.vl["Battery_Mgmt_3_FD1"]["BSBattSOC"]
    fault = bool(cp.vl["Battery_Mgmt_4_FD1"]["BattULoAux_B_Falt"]) if m4 else False
    v["lowVoltBattery.dataAvailable"] = bool(volts > 0 or m3)
    v["lowVoltBattery.voltage"] = float(volts)
    current = cp.vl["Battery_Mgmt_4_FD1"]["BattULoAux_I_Actl"] if m4 else 0.0
    v["lowVoltBattery.current"] = float(current) if current < 127.8 else 0.0
    v["lowVoltBattery.socPercent"] = float(soc) if 0 < soc <= 100 else 0.0
    v["lowVoltBattery.tempC"] = float(cp.vl["Battery_Mgmt_3_FD1"]["BattULo2_Te_Actl"]) if m3 else 0.0
    v["lowVoltBattery.fault"] = fault
    v["lowVoltBattery.low"] = self.low_volt.update(fault or (0 < volts < s.low_volt_v), dt)

  def _update_ambient(self, cp) -> None:
    v = self.values
    t, ok = 0.0, False
    for msg, sig, hi in (("Climate_Control_Data_FD1", "Outside_Air_Temp_Stat", 86.4),  # raw 254/255 = unknown/invalid
                         ("EngineClimateData", "AirAmb_Te_Actl", 127.7),
                         ("SmartChargingData_ECG_3", "AirAmb_Te_ActlCld", 127.7)):
      if msg_fresh(cp, msg):
        t = cp.vl[msg][sig]
        if -39.9 < t < min(hi, 70.):
          ok = True
          break
    v["ambient.dataAvailable"] = ok
    v["ambient.outsideTempC"] = float(t) if ok else 0.0
    v["ambient.rangeImpactPercent"] = range_impact_percent(t) if ok else 0.0

  def _update_vehicle_mode(self, cp, s: EvSettings, v_ego, a_ego, gas, brake, cruise, dt) -> None:
    v = self.values
    dm_ok = msg_fresh(cp, "SelectDriveModeData")
    raw = int(cp.vl["SelectDriveModeData"]["SelDrvMdePt_D_Rq"]) if dm_ok else 31
    v["vehicleMode.driveModeAvailable"] = dm_ok and raw != 31
    v["vehicleMode.driveModeRaw"] = raw if dm_ok else 0
    v["vehicleMode.driveMode"] = DRIVE_MODE_MAP.get(raw, "unknown") if dm_ok else "unknown"

    lamp_ok = msg_fresh(cp, "TrailerInfo_FD1")
    brk_ok = msg_fresh(cp, "TrailerBrakeInfo_FD1")
    connected = (lamp_ok and cp.vl["TrailerInfo_FD1"]["TrlrLampCnnct_B_Actl"] == 1) or \
                (brk_ok and cp.vl["TrailerBrakeInfo_FD1"]["TrlrBrkActCnnct_B_Actl"] == 1)
    v["vehicleMode.trailerAvailable"] = lamp_ok or brk_ok
    v["vehicleMode.trailerConnected"] = self.trailer.update(bool(connected), dt)

    est = self.one_pedal.update(v_ego, a_ego, gas, brake, cruise, dt)
    if s.one_pedal_mode == 1:
      v["vehicleMode.onePedalActive"], v["vehicleMode.onePedalSource"] = True, "setting"
    elif s.one_pedal_mode == 2:
      v["vehicleMode.onePedalActive"], v["vehicleMode.onePedalSource"] = est, "estimated"
    else:
      v["vehicleMode.onePedalActive"], v["vehicleMode.onePedalSource"] = False, "off"

  # *** charging ***
  def _update_charging(self, cp, dt: float) -> None:
    v = self.values
    state, raw, ok = "unknown", 0, False
    if msg_fresh(cp, "PreCond_Hev_Data1_FD1"):
      raw = int(cp.vl["PreCond_Hev_Data1_FD1"]["ChrgStat_D2_Dsply"])
      state, ok = CHARGE_STATE_D2.get(raw, "unknown"), True
    elif msg_fresh(cp, "Cluster_HEV_Data1_FD1"):
      raw = int(cp.vl["Cluster_HEV_Data1_FD1"]["ChrgStat_D_Dsply"])
      state, ok = CHARGE_STATE_CLUSTER.get(raw, "unknown"), True
    ctype = CHARGE_TYPE.get(state, "none")
    charging = self.charging.update(ctype != "none", dt)

    pack_kw = v["evBattery.powerKw"]
    power_ok = charging and v["evBattery.packCurrentSource"] in ("battTracActl", "battTracEstVsc")
    v["charging.dataAvailable"] = ok
    v["charging.charging"] = charging
    v["charging.state"] = state
    v["charging.stateRaw"] = raw
    v["charging.chargeType"] = ctype if charging else "none"
    v["charging.powerAvailable"] = power_ok
    v["charging.powerKw"] = float(max(0.0, -pack_kw)) if power_ok else 0.0
    v["charging.socPercent"] = v["evBattery.socPercent"]
    v["charging.batteryTempC"] = v["evBattery.packTempC"]

    ttf = cp.vl["HEV_ChargeStat_FD1"]["ChargeNowDuration_St"] if msg_fresh(cp, "HEV_ChargeStat_FD1") else 0.0
    v["charging.timeToFullAvailable"] = charging and 0. < ttf < 25.45  # raw 255 = invalid
    v["charging.timeToFullHours"] = float(ttf) if v["charging.timeToFullAvailable"] else 0.0

    wake_ok = msg_fresh(cp, "MHT_EV_Wakeup_FD1")
    precond = (wake_ok and cp.vl["MHT_EV_Wakeup_FD1"]["PreCondBatt_B_Actl"] == 1) or \
              (msg_fresh(cp, "PreCond_Hev_Data2_FD1") and cp.vl["PreCond_Hev_Data2_FD1"]["PreCondActv_B_Actl"] == 1)
    v["charging.batteryConditioning"] = bool(precond)
    heater = bool(wake_ok and cp.vl["MHT_EV_Wakeup_FD1"]["PtcHtr_D_Stat"] == 1)
    v["charging.coolantHeaterOn"] = heater

    pump_ok = msg_fresh(cp, "Battery_Traction_6_FD1")
    pump = bool(pump_ok and cp.vl["Battery_Traction_6_FD1"]["BattTracClntPmp_D_Stat"] == 1)
    flow_ok = msg_fresh(cp, "PreCond_Hev_Data2_FD1")
    flow = float(cp.vl["PreCond_Hev_Data2_FD1"]["BattTracClntFlw_Pc_Rq"]) if flow_ok else 0.0
    flow = flow if flow <= 100. else 0.0  # 101-127 unused
    v["charging.coolantPumpOn"] = pump
    v["charging.coolantFlowPercent"] = flow
    v["charging.coolantFlowAvailable"] = flow_ok
    v["charging.thermalMode"] = thermal_mode(heater, bool(precond), pump or flow > 0.,
                                             wake_ok or pump_ok or flow_ok, self._coolant_minus_pack(cp))

  @staticmethod
  def _coolant_minus_pack(cp) -> float | None:
    if not (msg_fresh(cp, "Battery_Traction_3_FD1") and msg_fresh(cp, "Battery_Traction_4_FD1")):
      return None
    pack = cp.vl["Battery_Traction_4_FD1"]["BattTrac_Te_Actl"]
    if pack >= 460.:  # Fault / Unknown
      return None
    return float(cp.vl["Battery_Traction_3_FD1"]["BattTracClnt_Te_Actl"] - pack)

  # *** alerts ***
  def _update_alerts(self, s: EvSettings) -> None:
    v = self.values
    low = max(s.low_soc_pct, s.critical_soc_pct)
    crit = min(s.low_soc_pct, s.critical_soc_pct)
    prev, h = self.soc_level, self.SOC_HYSTERESIS
    soc = v["evBattery.socPercent"]
    if not v["evBattery.dataAvailable"] or v["charging.charging"]:  # no "plan a charging stop" while charging
      level = "none"
    elif soc <= crit or (prev == "critical" and soc <= crit + h):
      level = "critical"
    elif soc <= low or (prev != "none" and soc <= low + h):
      level = "low"
    else:
      level = "none"
    self.soc_level = level

    v["evAlerts.lowSoc"] = level
    v["evAlerts.lowSocThresholdPercent"] = float(low)
    v["evAlerts.criticalSocThresholdPercent"] = float(crit)
    v["evAlerts.tirePressureLow"] = v["tirePressure.lowPressure"]
    v["evAlerts.lowVoltBatteryLow"] = v["lowVoltBattery.low"]

    soc_txt = f"{v['evBattery.socPercent']:.0f}%"
    if level == "critical":
      text = f"Battery critical {soc_txt}: charge now"
    elif level == "low":
      text = f"Battery low {soc_txt}: plan a charging stop"
    elif v["tirePressure.lowPressure"]:
      text = "Tire pressure low"
    elif v["lowVoltBattery.low"]:
      text = "12V battery low"
    else:
      text = ""
    v["evAlerts.alertText"] = text

  # *** offroad wake (why the truck's network is up) ***
  def _update_wake(self, cp, can_alive: bool, dt: float) -> None:
    v = self.values
    body_ok = msg_fresh(cp, "BodyInfo_3_FD1")
    pt6_ok = msg_fresh(cp, "HEV_Powertrain_Data6")
    wake_ok = msg_fresh(cp, "MHT_EV_Wakeup_FD1")
    ignition = IGNITION_STATUS.get(int(cp.vl["BodyInfo_3_FD1"]["Ignition_Status"]), "unknown") if body_ok else "unknown"
    remote = body_ok and cp.vl["BodyInfo_3_FD1"]["Remote_Start_Status"] != 0
    dcdc = pt6_ok and cp.vl["HEV_Powertrain_Data6"]["DcdcOn_B_Rq"] == 1
    lv_support = pt6_ok and cp.vl["HEV_Powertrain_Data6"]["ULoBattSpprtSustn_B_Rq"] == 1
    alarm = int(cp.vl["MHT_EV_Wakeup_FD1"]["WakeAlarm0_T_Rq"]) if wake_ok else -1
    cabin = wake_ok and (cp.vl["MHT_EV_Wakeup_FD1"]["CabinDrvSustn_B_Rq"] == 1 or cp.vl["MHT_EV_Wakeup_FD1"]["BattTracDrvSustn_B_Rq"] == 1)

    if not can_alive:
      reason = "asleep"
    elif ignition in ("run", "start"):
      reason = "ignitionOn"
    elif v.get("charging.charging"):
      reason = "charging"
    elif remote:
      reason = "remoteStart"
    elif ignition == "off" and lv_support:
      reason = "lowVoltTopUp"
    elif v.get("charging.batteryConditioning") or cabin:
      reason = "conditioning"
    elif ignition == "accessory":
      reason = "accessory"
    else:
      reason = "unknown"
    top_up = self.top_up.update(reason == "lowVoltTopUp", dt)
    if top_up and not self.top_up_prev:
      self.top_up_count += 1
    self.top_up_prev = top_up

    v["wake.dataAvailable"] = bool(body_ok or pt6_ok)
    v["wake.reason"] = reason
    v["wake.ignition"] = ignition
    v["wake.remoteStart"] = bool(remote)
    v["wake.dcdcOn"] = bool(dcdc)
    v["wake.lowVoltSupport"] = bool(lv_support)
    v["wake.nextWakeMinutes"] = alarm if 0 < alarm < 32767 else -1
    v["wake.lowVoltTopUps"] = min(self.top_up_count, 65535)

  def update_charging_only(self, cp, dt: float, can_alive: bool = True, s: EvSettings | None = None) -> dict:
    """Offroad (charging_monitor): battery, charging, 12 V and wake fields."""
    self._update_battery(cp, 0.0, dt)
    self._update_low_volt(cp, s or EvSettings(), dt)
    self._update_charging(cp, dt)
    self._update_wake(cp, can_alive, dt)
    return self.values

  @property
  def low_volt_top_up(self) -> bool:
    """A debounced 12 V top-up wake is in progress (ignition off, 12 V support requested, not charging)."""
    return self.top_up_prev

  def update(self, cp, s: EvSettings, v_ego: float, a_ego: float, gas: bool, brake: bool, cruise: bool, dt: float) -> dict:
    self._update_battery(cp, v_ego, dt)
    self._update_tires(cp, s, dt)
    self._update_low_volt(cp, s, dt)
    self._update_ambient(cp)
    self._update_vehicle_mode(cp, s, v_ego, a_ego, gas, brake, cruise, dt)
    self._update_charging(cp, dt)
    self._update_alerts(s)
    return self.values


THERMAL_DIRECTION_C = 2.0  # coolant must differ from the pack by this much to call cooling vs heating


def thermal_mode(heater_on: bool, conditioning: bool, flowing: bool, data_ok: bool, coolant_minus_pack: float | None) -> str:
  """Battery thermal mode for the charging screen. Inferred: Ford broadcasts no single mode signal."""
  if not data_ok:
    return "unknown"
  if heater_on:
    return "heating"
  if conditioning:
    return "conditioning"
  if not flowing:
    return "off"
  if coolant_minus_pack is not None and coolant_minus_pack <= -THERMAL_DIRECTION_C:
    return "cooling"
  if coolant_minus_pack is not None and coolant_minus_pack >= THERMAL_DIRECTION_C:
    return "heating"
  return "circulating"


def fill_car_state_bp(car_state_bp, values: dict) -> None:
  """Copy LightningState.values into a carStateBP builder ("struct.field" keys)."""
  structs = {}
  for key, val in values.items():
    struct_name, field = key.split(".", 1)
    if struct_name not in structs:
      structs[struct_name] = getattr(car_state_bp, struct_name)
    setattr(structs[struct_name], field, val)


# *** tune profiles ***

@dataclass(frozen=True)
class TuneValues:
  # longitudinal (openpilot longitudinal / alpha long only)
  accel_max_scale: float = 1.0          # <= 1: caps gas and accel below CarControllerParams.ACCEL_MAX
  following_accel_roc: float = 0.002    # BP long brake-onset rate limit per 50 Hz frame
  brake_actuate_target: float = -0.14
  brake_actuate_release: float = -0.06
  precharge_actuate_target: float = -0.12
  precharge_actuate_release: float = -0.06
  creep_comp_max: float = 0.6           # m/s^2 creep compensation at 1 m/s (stock openpilot value)
  lead_gas_cut_s: float = 1.5           # gaining on a lead closer than this many seconds: no gas
  # lateral
  lat_accel_scale: float = 1.0          # <= 1: scales the CAN FD max lateral accel cap
  lane_change_factor_scale: float = 1.0 # <= 1: extra curvature reduction during lane changes
  path_angle_roc_scale: float = 1.0     # <= 1: slower lane-positioning path angle changes


STOCK_TUNE = TuneValues()

# Starting points for A/B testing (BPLightningTune), not values measured on the truck.
# 2948 kg BEV with strong regen: leave light decel to regen (deeper friction-brake thresholds),
# softer brake onset, weaker creep, slightly gentler lane changes for the 3.7 m wheelbase.
LIGHTNING_TUNE = replace(
  STOCK_TUNE,
  following_accel_roc=0.0015,
  brake_actuate_target=-0.20,
  brake_actuate_release=-0.08,
  precharge_actuate_target=-0.16,
  precharge_actuate_release=-0.08,
  creep_comp_max=0.4,
  lane_change_factor_scale=0.97,
  path_angle_roc_scale=0.85,
)

PROFILE_TUNES = {
  "stock": STOCK_TUNE,
  "lightning": LIGHTNING_TUNE,
  # trailer: softer acceleration, earlier friction braking (feeds the trailer brake controller),
  # a longer gap before cutting gas on a lead, and gentler lateral rates
  "tow": replace(
    LIGHTNING_TUNE,
    accel_max_scale=0.6,
    following_accel_roc=0.001,
    brake_actuate_target=-0.12,
    brake_actuate_release=-0.05,
    precharge_actuate_target=-0.10,
    precharge_actuate_release=-0.05,
    lead_gas_cut_s=2.5,
    lat_accel_scale=0.8,
    lane_change_factor_scale=0.9,
    path_angle_roc_scale=0.7,
  ),
  "sport": replace(LIGHTNING_TUNE, following_accel_roc=0.0025, path_angle_roc_scale=1.0),
  "offroad": replace(LIGHTNING_TUNE, accel_max_scale=0.6, lat_accel_scale=0.85, path_angle_roc_scale=0.8),
  "slippery": replace(
    LIGHTNING_TUNE,
    accel_max_scale=0.5,
    following_accel_roc=0.001,
    lat_accel_scale=0.75,
    lane_change_factor_scale=0.9,
    path_angle_roc_scale=0.7,
  ),
}

# fields that must never exceed 1.0
_SCALE_FIELDS = ("accel_max_scale", "lat_accel_scale", "lane_change_factor_scale", "path_angle_roc_scale")


@dataclass
class TuneSettings:
  lightning_tune: bool = True
  tow_profile: int = 0       # 0 auto (trailer or Tow/Haul mode), 1 off, 2 always on
  drive_mode_tune: bool = True


def select_profile(car_fingerprint, settings: TuneSettings, drive_mode: str, trailer_connected: bool) -> str:
  if car_fingerprint not in LIGHTNING_PLATFORMS or not settings.lightning_tune:
    return "stock"
  if settings.tow_profile == 2:
    return "tow"
  if settings.tow_profile == 0 and (trailer_connected or (settings.drive_mode_tune and drive_mode == "tow")):
    return "tow"
  if settings.drive_mode_tune and drive_mode in ("slippery", "offroad", "sport"):
    return drive_mode
  return "lightning"


def sanitize(t: TuneValues) -> TuneValues:
  """Clamp so a tune can only be gentler than stock where it matters for safety."""
  vals = {f: min(getattr(t, f), 1.0) for f in _SCALE_FIELDS}
  vals = {k: max(v, 0.1) for k, v in vals.items()}
  return replace(t, **vals)


class TuneBlender:
  """Moves the active tune toward the selected profile over `ramp_s` so a mode change mid-drive
  (drive-mode knob, trailer plugged in) never steps the control limits."""
  def __init__(self, ramp_s: float = 3.0):
    self.ramp_s = ramp_s
    self.profile = "stock"
    self.current = STOCK_TUNE
    self._target = STOCK_TUNE
    self._steps: dict[str, float] = {}

  def update(self, profile: str, dt: float) -> TuneValues:
    target = sanitize(PROFILE_TUNES.get(profile, STOCK_TUNE))
    if target != self._target:
      self.profile = profile
      self._target = target
      self._steps = {f.name: abs(getattr(target, f.name) - getattr(self.current, f.name)) * dt / self.ramp_s
                     for f in fields(TuneValues)}
    if self.current != target:
      new = {}
      for f in fields(TuneValues):
        cur, tgt, step = getattr(self.current, f.name), getattr(target, f.name), self._steps[f.name]
        new[f.name] = tgt if abs(tgt - cur) <= step + 1e-12 else cur + np.sign(tgt - cur) * step
      self.current = replace(self.current, **new)
    return self.current
