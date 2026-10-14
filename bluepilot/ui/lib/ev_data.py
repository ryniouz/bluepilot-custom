"""
EV data for the Console driving-screen HUD (F-150 Lightning).

Reads carStateBP from the UI SubMaster. The "Lightning control and CAN" stream adds a
CarStateBP.ev struct; until that lands (or when a signal is missing on the truck) every value
falls back to what bp-6.0 already publishes, or to NaN so the widget hides that row.

Sign conventions used by the HUD:
  power_kw   > 0 driving (pack discharging), < 0 regen or charging
  current_a  > 0 discharging (the hybridBattery field is the opposite: > 0 charging)
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field

NAN = float("nan")

# Lightning usable pack energy, used only for the estimated range when the truck does not send one.
# Standard Range 98 kWh, Extended Range 131 kWh. Extended is the common build; the estimate is labelled "est."
LIGHTNING_USABLE_KWH = 131.0
DEFAULT_WH_PER_KM = 300.0  # ~2.1 mi/kWh, a typical mixed Lightning figure; replaced by the live value

# Range impact of outside temperature for a large-pack EV (fraction of rated range).
# Interpolated; anchored on published cold- and hot-weather fleet averages.
_TEMP_IMPACT = [(-20.0, 0.60), (-10.0, 0.68), (0.0, 0.78), (10.0, 0.90), (21.0, 1.00), (30.0, 0.97), (38.0, 0.88)]


HB_CURRENT_INVALID_A = 745.0  # BattTrac_I_Actl offset is -750 A; anything this large is the broken mapping

# Pack temperature window outside which the HUD surfaces temperatures in the Standard layout
PACK_TEMP_LOW_C = 0.0
PACK_TEMP_HIGH_C = 45.0


def finite(v) -> bool:
  return isinstance(v, (int, float)) and math.isfinite(v)


def temp_range_factor(temp_c: float) -> float:
  if not finite(temp_c):
    return NAN
  pts = _TEMP_IMPACT
  if temp_c <= pts[0][0]:
    return pts[0][1]
  if temp_c >= pts[-1][0]:
    return pts[-1][1]
  for (t0, f0), (t1, f1) in zip(pts, pts[1:], strict=False):
    if t0 <= temp_c <= t1:
      return f0 + (f1 - f0) * (temp_c - t0) / (t1 - t0)
  return 1.0


@dataclass
class EvSnapshot:
  available: bool = False
  soc: float = NAN                 # %
  voltage: float = NAN             # V
  current_a: float = NAN           # A, + discharge
  power_kw: float = NAN            # kW, + drive, - regen
  pack_temp_c: float = NAN
  coolant_temp_c: float = NAN
  charge_limit_kw: float = NAN
  discharge_limit_kw: float = NAN
  range_km: float = NAN
  range_estimated: bool = False
  motor_torque_nm: float = NAN
  tire_kpa: list[float] = field(default_factory=list)
  tire_low: bool = False
  lv_volts: float = NAN            # 12 V battery
  lv_low: bool = False
  outside_temp_c: float = NAN
  drive_mode: str = ""
  trailer: bool = False
  one_pedal: bool = False
  low_soc: bool = False
  # Trip integrals (since the UI went onroad)
  trip_used_kwh: float = 0.0
  trip_regen_kwh: float = 0.0
  trip_km: float = 0.0
  wh_per_km: float = NAN           # live efficiency (smoothed, trip-based)


def _f(obj, name: str, default=NAN):
  try:
    v = getattr(obj, name)
  except (AttributeError, KeyError, TypeError, ValueError):
    return default
  return v


class EvDataSource:
  """Collects EV values once per frame and integrates trip energy."""

  LV_LOW_VOLTS = 11.8

  def __init__(self):
    self.snap = EvSnapshot()
    self._last_t: float | None = None
    self._started_frame = -1

  def reset_trip(self):
    self.snap.trip_used_kwh = 0.0
    self.snap.trip_regen_kwh = 0.0
    self.snap.trip_km = 0.0
    self.snap.wh_per_km = NAN
    self._last_t = None

  def update(self, sm, started_frame: int, now: float | None = None) -> EvSnapshot:
    now = time.monotonic() if now is None else now
    if started_frame != self._started_frame:
      self._started_frame = started_frame
      self.reset_trip()

    prev = self.snap
    s = EvSnapshot(trip_used_kwh=prev.trip_used_kwh, trip_regen_kwh=prev.trip_regen_kwh,
                   trip_km=prev.trip_km, wh_per_km=prev.wh_per_km)
    self.snap = s
    has_bp = "carStateBP" in sm.recv_frame and sm.recv_frame["carStateBP"] >= started_frame
    if has_bp:
      bp = sm["carStateBP"]
      ev = _f(bp, "ev", None)
      ev_ok = ev is not None and bool(_f(ev, "dataAvailable", False))
      hb = _f(bp, "hybridBattery", None)
      hb_ok = hb is not None and bool(_f(hb, "dataAvailable", False))

      if ev_ok:
        s.available = True
        s.soc = _f(ev, "socDisplay")
        s.voltage = _f(ev, "packVoltage")
        s.current_a = _f(ev, "packCurrent")
        s.power_kw = _f(ev, "packPowerKw")
        s.pack_temp_c = _f(ev, "packTempC")
        s.coolant_temp_c = _f(ev, "coolantTempC")
        s.charge_limit_kw = _f(ev, "chargeLimitKw")
        s.discharge_limit_kw = _f(ev, "dischargeLimitKw")
        s.range_km = _f(ev, "rangeKm")
        s.motor_torque_nm = _f(ev, "motorTorqueNm")
        tires = _f(ev, "tirePressureKpa", [])
        s.tire_kpa = [float(t) for t in tires] if tires is not None else []
        s.tire_low = bool(_f(ev, "tirePressureLow", False))
        s.lv_volts = _f(ev, "lowVoltageBatteryV")
        s.lv_low = bool(_f(ev, "lowVoltageBatteryLow", False))
        s.outside_temp_c = _f(ev, "outsideTempC")
        s.drive_mode = str(_f(ev, "driveModeText", "") or "")
        s.trailer = bool(_f(ev, "trailerConnected", False))
        s.one_pedal = bool(_f(ev, "onePedalActive", False))
        s.low_soc = bool(_f(ev, "lowSocAlert", False))

      if hb_ok:
        s.available = True
        if not finite(s.soc):
          s.soc = _f(hb, "socActual")
        if not finite(s.voltage):
          s.voltage = _f(hb, "voltActual")
        if not finite(s.current_a):
          amps = _f(hb, "ampsActual")
          # hybridBattery: + is charging. On the Lightning BattTrac_I_Actl decodes to a constant
          # -750 A (the raw offset), so a value pinned at the offset is treated as missing.
          s.current_a = -amps if finite(amps) and abs(amps) < HB_CURRENT_INVALID_A else NAN
      if not finite(s.power_kw) and finite(s.voltage) and finite(s.current_a):
        s.power_kw = s.voltage * s.current_a / 1000.0

    # 12 V from the panda's harness reading when the car does not send it
    if not finite(s.lv_volts) and "peripheralState" in sm.recv_frame and sm.recv_frame["peripheralState"] >= started_frame:
      mv = _f(sm["peripheralState"], "voltage", 0)
      if finite(mv) and mv > 0:
        s.lv_volts = mv / 1000.0
    if finite(s.lv_volts) and s.lv_volts < self.LV_LOW_VOLTS:
      s.lv_low = True

    # Trip integration
    v_ego = 0.0
    try:
      v_ego = max(0.0, float(sm["carState"].vEgo))
    except (KeyError, AttributeError, TypeError, ValueError):
      pass
    if self._last_t is not None:
      dt = min(max(now - self._last_t, 0.0), 0.5)
      s.trip_km += v_ego * dt / 1000.0
      if finite(s.power_kw):
        kwh = s.power_kw * dt / 3600.0
        if kwh >= 0:
          s.trip_used_kwh += kwh
        else:
          s.trip_regen_kwh += -kwh
    self._last_t = now

    if s.trip_km > 0.5:
      s.wh_per_km = 1000.0 * (s.trip_used_kwh - s.trip_regen_kwh) / s.trip_km

    if not finite(s.range_km) and finite(s.soc):
      whpk = s.wh_per_km if finite(s.wh_per_km) and s.wh_per_km > 80 else DEFAULT_WH_PER_KM
      s.range_km = LIGHTNING_USABLE_KWH * 1000.0 * (s.soc / 100.0) / whpk
      s.range_estimated = True

    return s
