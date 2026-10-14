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

from bluepilot.ui.lib.charge_screen import OCCUPIED_IGNITION

NAN = float("nan")

# Lightning usable pack energy, used only for the estimated range when the truck does not send one.
# Standard Range 98 kWh, Extended Range 131 kWh. Extended is the common build; the estimate is labelled "est."
LIGHTNING_USABLE_KWH = 131.0
DEFAULT_WH_PER_KM = 300.0  # ~2.1 mi/kWh, a typical mixed Lightning figure; replaced by the live value

# Range impact of outside temperature for a large-pack EV (fraction of rated range).
# Interpolated; anchored on published cold- and hot-weather fleet averages.
_TEMP_IMPACT = [(-20.0, 0.60), (-10.0, 0.68), (0.0, 0.78), (10.0, 0.90), (21.0, 1.00), (30.0, 0.97), (38.0, 0.88)]


STALE_S = 2.0  # carStateBP older than this is ignored (offroad, after the reader stops)
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
  # Charging (CarStateBP.ev charge fields from the Lightning CAN stream)
  charging: bool = False
  charge_type: int = 0             # 0 none, 1 AC, 2 DC
  charge_status: str = ""
  charge_power_kw: float = NAN     # kW into the pack
  charge_time_to_full_min: float = NAN
  charge_target_soc: float = NAN
  charge_inhibit_thermal: bool = False
  charge_conditioning: bool = False
  # Battery thermal system: "cooling", "heating", "conditioning", "circulating", "off", or "" (no data)
  thermal_mode: str = ""
  heater_on: bool = False
  pack_delta_temp_c: float = NAN   # spread between the warmest and coolest module
  source: str = ""                 # "car" (carStateBP, ignition on) or "charger" (chargingStateBP, ignition off)
  truck_ignition: str = ""         # chargingStateBP.wake.ignition while offroad: "off", "accessory", ... ("" onroad)
  # Trip integrals (since the UI went onroad)
  trip_used_kwh: float = 0.0
  trip_regen_kwh: float = 0.0
  trip_km: float = 0.0
  wh_per_km: float = NAN           # live efficiency (smoothed, trip-based)


THERMAL_MODES = ("cooling", "heating", "conditioning", "circulating", "off")


def thermal_mode(c) -> str:
  """Battery thermal mode from CarStateBP.Charging.thermalMode (stream B, PR #2).

  Ford sends no single thermal-mode signal; stream B infers it from the PTC heater, the preconditioning
  flag, the coolant pump / flow request and coolant vs pack temperature. "unknown" (no thermal message on
  the bus) becomes "" so the UI shows "No data". Before that field existed, the heater and preconditioning
  flags alone give "heating" or "conditioning".
  """
  raw = str(_f(c, "thermalMode", "") or "")
  if raw in THERMAL_MODES:
    return raw
  if raw == "unknown":
    return ""
  if bool(_f(c, "coolantHeaterOn", False)):
    return "heating"
  if bool(_f(c, "batteryConditioning", False)):
    return "conditioning"
  return ""


def _f(obj, name: str, default=NAN):
  try:
    v = getattr(obj, name)
  except (AttributeError, KeyError, TypeError, ValueError):
    return default
  return v


def _avail(obj, flag: str = "dataAvailable") -> bool:
  return obj is not None and bool(_f(obj, flag, False))


def _fv(obj, name: str, flag: str | None = None):
  """Float field, NaN when the struct (or its availability flag) says it is missing."""
  if obj is None or (flag is not None and not _f(obj, flag, False)):
    return NAN
  v = _f(obj, name)
  try:
    return float(v)
  except (TypeError, ValueError):
    return NAN


SAVE_EVERY_S = 60.0
_SAVED_FIELDS = ("soc", "range_km", "range_estimated", "pack_temp_c", "tire_kpa", "tire_low", "lv_volts", "lv_low", "outside_temp_c")


def _load_last_good() -> EvSnapshot | None:
  """Last known truck data, kept across reboots so the parked screens have something to show."""
  try:
    from openpilot.common.params import Params
    d = Params().get("BPLastEvSnapshot")
    if not isinstance(d, dict):
      return None
    s = EvSnapshot(available=True)
    for k in _SAVED_FIELDS:
      if k in d and d[k] is not None:
        setattr(s, k, list(d[k]) if k == "tire_kpa" else d[k])
    return s
  except Exception:
    return None


def _save_last_good(s: EvSnapshot) -> None:
  try:
    from openpilot.common.params import Params
    d = {k: (None if isinstance(getattr(s, k), float) and not math.isfinite(getattr(s, k)) else getattr(s, k)) for k in _SAVED_FIELDS}
    Params().put_nonblocking("BPLastEvSnapshot", d)
  except Exception:
    pass


class EvDataSource:
  """Collects EV values once per frame and integrates trip energy."""

  LV_LOW_VOLTS = 11.8

  def __init__(self):
    self.snap = EvSnapshot()
    self._last_t: float | None = None
    self._started_frame = -1
    self.last_good: EvSnapshot | None = _load_last_good()   # last snapshot with truck data, for parked screens
    self._saved_t = 0.0

  @staticmethod
  def _read_stream_b(bp, s: EvSnapshot) -> None:
    """CarStateBP fields from the "Lightning control and CAN" stream (PR #2)."""
    b = _f(bp, "evBattery", None)
    if _avail(b):
      s.available = True
      s.soc = _fv(b, "socPercent")
      s.voltage = _fv(b, "packVoltage")
      src = str(_f(b, "packCurrentSource", "none"))
      s.current_a = _fv(b, "packCurrent") if src not in ("none", "battTracActl") else NAN
      s.power_kw = _fv(b, "powerKw") if finite(s.current_a) else NAN
      s.pack_temp_c = _fv(b, "packTempC")
      s.coolant_temp_c = _fv(b, "coolantTempC")
      s.pack_delta_temp_c = _fv(b, "packDeltaTempC")
      s.charge_limit_kw = _fv(b, "chargeLimitKw", "limitsAvailable")
      s.discharge_limit_kw = _fv(b, "dischargeLimitKw", "limitsAvailable")
      s.range_km = _fv(b, "rangeKm", "rangeAvailable")
      s.motor_torque_nm = _fv(b, "motorTorqueNm", "motorTorqueAvailable")

    t = _f(bp, "tirePressure", None)
    if _avail(t):
      s.tire_kpa = [_fv(t, k) for k in ("frontLeftKpa", "frontRightKpa", "rearLeftKpa", "rearRightKpa")]
      s.tire_low = bool(_f(t, "lowPressure", False))

    lv = _f(bp, "lowVoltBattery", None)
    if _avail(lv):
      s.lv_volts = _fv(lv, "voltage")
      s.lv_low = bool(_f(lv, "low", False)) or bool(_f(lv, "fault", False))

    a = _f(bp, "ambient", None)
    if _avail(a):
      s.outside_temp_c = _fv(a, "outsideTempC")

    vm = _f(bp, "vehicleMode", None)
    if vm is not None:
      if _f(vm, "driveModeAvailable", False):
        mode = str(_f(vm, "driveMode", "unknown"))
        s.drive_mode = "" if mode == "unknown" else mode.capitalize()
      s.trailer = bool(_f(vm, "trailerAvailable", False)) and bool(_f(vm, "trailerConnected", False))
      s.one_pedal = bool(_f(vm, "onePedalActive", False))

    al = _f(bp, "evAlerts", None)
    if al is not None:
      s.low_soc = str(_f(al, "lowSoc", "none")) != "none"

    c = _f(bp, "charging", None)
    if _avail(c):
      s.charging = bool(_f(c, "charging", False))
      ct = str(_f(c, "chargeType", "none"))
      s.charge_type = {"ac": 1, "dc": 2, "other": 3}.get(ct, 0)
      s.charge_status = str(_f(c, "state", "unknown"))
      s.charge_power_kw = _fv(c, "powerKw", "powerAvailable")
      hours = _fv(c, "timeToFullHours", "timeToFullAvailable")
      s.charge_time_to_full_min = hours * 60.0 if finite(hours) else NAN
      s.charge_conditioning = bool(_f(c, "batteryConditioning", False))
      s.heater_on = bool(_f(c, "coolantHeaterOn", False))
      s.thermal_mode = thermal_mode(c)
      # Charging floats read 0.0 when unavailable; the EvBattery values above are gated on dataAvailable
      if not finite(s.soc) and _fv(c, "socPercent") > 0:
        s.soc = _fv(c, "socPercent")
      if s.charging or s.charge_status not in ("unknown", "notReady"):
        s.available = True

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
    # Fresh carStateBP: onroad from card, offroad from the Lightning stream's charging reader.
    # Freshness (not started_frame) decides, so the last drive's values never linger offroad.
    has_bp = "carStateBP" in sm.recv_frame and sm.recv_frame["carStateBP"] > 0 and \
      (now - float(getattr(sm, "recv_time", {}).get("carStateBP", now))) < STALE_S
    has_chg = not has_bp and "chargingStateBP" in sm.recv_frame and sm.recv_frame["chargingStateBP"] > 0 and \
      (now - float(getattr(sm, "recv_time", {}).get("chargingStateBP", now))) < STALE_S
    if has_chg:
      # Ignition off: the Lightning stream's charging monitor publishes the same Charging and EvBattery structs
      self._read_stream_b(sm["chargingStateBP"], s)
      s.source = "charger"
      wake = _f(sm["chargingStateBP"], "wake", None)
      s.truck_ignition = str(_f(wake, "ignition", "")) if _avail(wake) else ""
    if has_bp:
      bp = sm["carStateBP"]
      s.source = "car"
      self._read_stream_b(bp, s)
      hb = _f(bp, "hybridBattery", None)
      hb_ok = hb is not None and bool(_f(hb, "dataAvailable", False))

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

    if s.charging and not finite(s.charge_power_kw) and finite(s.power_kw) and s.power_kw < 0:
      s.charge_power_kw = -s.power_kw

    if s.trip_km > 0.5:
      s.wh_per_km = 1000.0 * (s.trip_used_kwh - s.trip_regen_kwh) / s.trip_km

    if not finite(s.range_km) and finite(s.soc):
      whpk = s.wh_per_km if finite(s.wh_per_km) and s.wh_per_km > 80 else DEFAULT_WH_PER_KM
      s.range_km = LIGHTNING_USABLE_KWH * 1000.0 * (s.soc / 100.0) / whpk
      s.range_estimated = True

    if s.available:
      self.last_good = s
      if now - self._saved_t > SAVE_EVERY_S:
        self._saved_t = now
        _save_last_good(s)
    return s


# Charging states that mean the truck is still plugged in, so the screen stays (or comes) up
PLUGGED_STATES = ("chargingAc", "chargingDc", "chargingInductive", "chargingUnknownType", "targetReached",
                  "maintaining", "evsePaused", "scheduled", "fault")


class ChargeSession:
  """Decides when the charging screen replaces the driving view, and tracks the session.

  The screen only takes over at a standstill, after the truck has reported charging for
  ENTER_S, and it lets go after EXIT_S without a charging report or as soon as the truck moves.
  """

  ENTER_S = 2.0
  EXIT_S = 5.0
  HANDOFF_S = 30.0  # no fresh source at all: the ignition just changed and the other publisher is starting
  STANDSTILL_MS = 0.3

  def __init__(self):
    self.active = False
    self.dismissed = False      # driver tapped back to the driving view for this session
    self.reopened = False       # driver reopened the page (shows even with BPChargingScreen off)
    self.start_t = 0.0
    self.window_t = 0.0         # when the screen's on-time window last restarted (see charge_screen.py)
    self._window_key: tuple | None = None
    self.start_soc = NAN
    self.start_range_km = NAN
    self.energy_kwh = 0.0
    self.peak_kw = NAN
    self.last: dict | None = None   # summary of the previous session, for the Energy > Charging page
    self._snap: EvSnapshot | None = None
    self._on_since: float | None = None
    self._off_since: float | None = None
    self._last_t: float | None = None

  def update(self, snap: EvSnapshot, v_ego: float, now: float | None = None) -> bool:
    now = time.monotonic() if now is None else now
    moving = finite(v_ego) and v_ego > self.STANDSTILL_MS

    plugged = snap.charging or snap.charge_status in PLUGGED_STATES
    if plugged and not moving:
      self._off_since = None
      if self._on_since is None:
        self._on_since = now
      if not self.active and now - self._on_since >= self.ENTER_S:
        self._begin(snap, now)
    else:
      self._on_since = None
      if self.active:
        if moving:
          self._end()
        else:
          if self._off_since is None:
            self._off_since = now
          # Ignition on <-> off hands charging over between carStateBP (card) and chargingStateBP
          # (charging_monitor, offroad only); neither is fresh while the processes swap, so wait longer
          # before calling the session over rather than ending it and starting a new one.
          limit = self.HANDOFF_S if not snap.source else self.EXIT_S
          if now - self._off_since >= limit:
            self._end()

    if self.active:
      # The screen window restarts when the situation changes: the truck turned off or on (the publisher
      # switches between carStateBP and chargingStateBP) or went to accessory, AC <-> DC, or charging stopped/started
      # (a re-plug).
      # Without this, a session that began with the truck on spent its truck-off window before the truck was off.
      key = (bool(snap.charging), snap.charge_type, snap.source, snap.truck_ignition in OCCUPIED_IGNITION)
      if snap.source and key != self._window_key:
        if self._window_key is not None:
          self.window_t = now
        self._window_key = key
      if self._last_t is not None and snap.charging and finite(snap.charge_power_kw):
        dt = min(max(now - self._last_t, 0.0), 0.5)
        self.energy_kwh += max(snap.charge_power_kw, 0.0) * dt / 3600.0
      if finite(snap.charge_power_kw):
        self.peak_kw = snap.charge_power_kw if not finite(self.peak_kw) else max(self.peak_kw, snap.charge_power_kw)
      if not finite(self.start_soc) and finite(snap.soc):
        self.start_soc = snap.soc
      if not finite(self.start_range_km) and finite(snap.range_km):
        self.start_range_km = snap.range_km
      self._snap = snap
    self._last_t = now
    return self.active and not self.dismissed

  def elapsed_s(self, now: float | None = None) -> float:
    now = time.monotonic() if now is None else now
    return max(0.0, now - self.start_t) if self.active else 0.0

  def range_added_km(self, snap: EvSnapshot) -> float:
    if finite(snap.range_km) and finite(self.start_range_km):
      return max(0.0, snap.range_km - self.start_range_km)
    return NAN

  def _begin(self, snap: EvSnapshot, now: float):
    self.active = True
    self.dismissed = False
    self.reopened = False
    self.start_t = now
    self.window_t = now
    self._window_key = None
    self.start_soc = snap.soc
    self.start_range_km = snap.range_km
    self.energy_kwh = 0.0
    self.peak_kw = NAN

  def _end(self):
    snap = self._snap
    self.last = {
      "ended": time.strftime("%-I:%M %p").lower(),
      "minutes": self.elapsed_s() / 60.0,
      "energy_kwh": self.energy_kwh,
      "peak_kw": self.peak_kw,
      "start_soc": self.start_soc,
      "end_soc": snap.soc if snap is not None else NAN,
    }
    self.active = False
    self.dismissed = False
    self.reopened = False
    self._off_since = None
