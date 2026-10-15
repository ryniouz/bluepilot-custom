import time
import threading

from openpilot.common.params import Params
from openpilot.system.hardware import HARDWARE
from openpilot.common.swaglog import cloudlog
from openpilot.system.statsd import statlog
from openpilot.selfdrive.car import lv_power  # Custom: Lightning 12 V management

CAR_VOLTAGE_LOW_PASS_K = 0.011 # LPF gain for 45s tau (dt/tau / (dt/tau + 1))

# While driving, a battery charges completely in about 30-60 minutes
CAR_BATTERY_CAPACITY_uWh = 30e6
CAR_CHARGING_RATE_W = 45

VBATT_PAUSE_CHARGING = 11.8           # Lower limit on the LPF car battery voltage
MAX_TIME_OFFROAD_S = 30*3600
MIN_ON_TIME_S = 3600
DELAY_SHUTDOWN_TIME_S = 300 # Wait at least DELAY_SHUTDOWN_TIME_S seconds after offroad_time to shutdown.
VOLTAGE_SHUTDOWN_MIN_OFFROAD_TIME_S = 60

class PowerMonitoring:
  def __init__(self):
    self.params = Params()
    self.last_measurement_time = None           # Used for integration delta
    self.last_save_time = 0                     # Used for saving current value in a param
    self.power_used_uWh = 0                     # Integrated power usage in uWh since going into offroad
    self.next_pulsed_measurement_time = None
    self.car_voltage_mV = 12e3                  # Low-passed version of peripheralState voltage
    self.car_voltage_instant_mV = 12e3          # Last value of peripheralState voltage
    self.integration_lock = threading.Lock()
    self.top_up_boot = False                    # Custom: this boot came from a Lightning 12 V top-up wake
    self.top_up_last_ts: float | None = None    # Custom: last time that wake was reported

    car_battery_capacity_uWh = self.params.get("CarBatteryCapacity") or 0

    # Reset capacity if it's low
    self.car_battery_capacity_uWh = max((CAR_BATTERY_CAPACITY_uWh / 10), car_battery_capacity_uWh)

  # Calculation tick
  def calculate(self, voltage: int | None, ignition: bool):
    try:
      now = time.monotonic()

      # If peripheralState is None, we're probably not in a car, so we don't care
      if voltage is None:
        with self.integration_lock:
          self.last_measurement_time = None
          self.next_pulsed_measurement_time = None
          self.power_used_uWh = 0
        return

      # Low-pass battery voltage
      self.car_voltage_instant_mV = voltage
      self.car_voltage_mV = ((voltage * CAR_VOLTAGE_LOW_PASS_K) + (self.car_voltage_mV * (1 - CAR_VOLTAGE_LOW_PASS_K)))
      statlog.gauge("car_voltage", self.car_voltage_mV / 1e3)

      # Cap the car battery power and save it in a param every 10-ish seconds
      self.car_battery_capacity_uWh = max(self.car_battery_capacity_uWh, 0)
      self.car_battery_capacity_uWh = min(self.car_battery_capacity_uWh, CAR_BATTERY_CAPACITY_uWh)
      if now - self.last_save_time >= 10:
        self.params.put("CarBatteryCapacity", int(self.car_battery_capacity_uWh))
        self.last_save_time = now

      # First measurement, set integration time
      with self.integration_lock:
        if self.last_measurement_time is None:
          self.last_measurement_time = now
          return

      if ignition:
        # If there is ignition, we integrate the charging rate of the car
        with self.integration_lock:
          self.power_used_uWh = 0
          integration_time_h = (now - self.last_measurement_time) / 3600
          if integration_time_h < 0:
            raise ValueError(f"Negative integration time: {integration_time_h}h")
          self.car_battery_capacity_uWh += (CAR_CHARGING_RATE_W * 1e6 * integration_time_h)
          self.last_measurement_time = now
      else:
        # Get current power draw somehow
        current_power = HARDWARE.get_current_power_draw()

        # Do the integration
        self._perform_integration(now, current_power)
    except Exception:
      cloudlog.exception("Power monitoring calculation failed")

  def _perform_integration(self, t: float, current_power: float) -> None:
    with self.integration_lock:
      try:
        if self.last_measurement_time:
          integration_time_h = (t - self.last_measurement_time) / 3600
          power_used = (current_power * 1000000) * integration_time_h
          if power_used < 0:
            raise ValueError(f"Negative power used! Integration time: {integration_time_h} h Current Power: {power_used} uWh")
          self.power_used_uWh += power_used
          self.car_battery_capacity_uWh -= power_used
          self.last_measurement_time = t
      except Exception:
        cloudlog.exception("Integration failed")

  # Get the power usage
  def get_power_used(self) -> int:
    return int(self.power_used_uWh)

  def get_car_battery_capacity(self) -> int:
    return int(self.car_battery_capacity_uWh)

  # Max Time Offroad
  def max_time_offroad_exceeded(self, offroad_time):
    """
    Check if the max time offroad has been exceeded. If the value is 0, it means no limit.
    :param offroad_time: Time spent offroad in seconds
    :return: True if the max time offroad has been exceeded, False otherwise
    """
    try:
      param = self.params.get("MaxTimeOffroad")
      sp_max_time_val_s = param * 60 if param is not None and param >= 0 else MAX_TIME_OFFROAD_S
    except Exception:
      sp_max_time_val_s = MAX_TIME_OFFROAD_S

    # Custom: 12 V power saver caps the offroad time
    saver_s = lv_power.read_settings(self.params).saver_offroad_s
    if saver_s is not None:
      sp_max_time_val_s = saver_s if sp_max_time_val_s <= 0 else min(sp_max_time_val_s, saver_s)
    # Custom: end
    return 0 < sp_max_time_val_s <= offroad_time

  # Custom: offroad charging keep-awake and post-charge sleep delay
  def charging_shutdown_state(self, now: float, offroad_timestamp: float) -> tuple[bool, bool]:
    try:
      charging = self.params.get_bool("BPChargingActive")
      keep_awake = bool(self.params.get("BPChargeKeepAwake", return_default=True))
      last = self.params.get("BPChargeLastActiveTs")
      delay_s = 60. * float(self.params.get("BPChargeSleepDelayMin", return_default=True))
    except Exception:
      cloudlog.exception("charging shutdown params")
      return False, False
    fresh = last is not None and (now - float(last)) < 60.  # the monitor refreshes it every 10 s while charging
    if charging and fresh:
      return keep_awake, False
    # BPChargeSleepDelayMin = 0: no post-charge rule, MaxTimeOffroad decides
    charged_this_offroad = last is not None and float(last) >= offroad_timestamp
    return False, delay_s > 0 and charged_this_offroad and (now - float(last)) >= delay_s
  # Custom: end

  # Custom: Lightning 12 V top-up wakes (selfdrive/car/lv_power.py)
  def lv_top_up_wake(self, now: float | None = None) -> bool:
    """hardwared: ignition is up because the truck is topping up its 12 V battery, not for a drive."""
    now = time.monotonic() if now is None else now
    try:
      if not lv_power.read_settings(self.params).wake_filter:
        return False
      return lv_power.top_up_active(lv_power.read_state(self.params), now)
    except Exception:
      cloudlog.exception("lv top-up wake check")
      return False

  def top_up_wake_over(self, now: float, started_seen: bool) -> bool:
    """A comma that only booted for a 12 V top-up wake powers down TOP_UP_SLEEP_S after the wake ends."""
    if started_seen:
      self.top_up_boot = False
      return False
    if self.lv_top_up_wake(now):
      self.top_up_boot = True
      self.top_up_last_ts = now
      return False
    return self.top_up_boot and self.top_up_last_ts is not None and now - self.top_up_last_ts >= lv_power.TOP_UP_SLEEP_S
  # Custom: end

  # See if we need to shutdown
  def should_shutdown(self, ignition: bool, in_car: bool, offroad_timestamp: float | None, started_seen: bool):
    if offroad_timestamp is None:
      return False

    now = time.monotonic()
    should_shutdown = False
    offroad_time = (now - offroad_timestamp)
    # Custom: 12 V power saver raises the voltage cutoff; the 12 V SOC cutoff counts as low voltage
    vbatt_cutoff = VBATT_PAUSE_CHARGING
    lv = lv_power.read_settings(self.params)
    vbatt_cutoff = max(vbatt_cutoff, lv.volts_cutoff) if lv.saver else vbatt_cutoff
    low_soc = lv_power.soc_below_cutoff(lv, lv_power.read_state(self.params), now)
    # Custom: end
    low_voltage_shutdown = ((self.car_voltage_mV < (vbatt_cutoff * 1e3) or low_soc) and
                            offroad_time > VOLTAGE_SHUTDOWN_MIN_OFFROAD_TIME_S)
    should_shutdown |= self.max_time_offroad_exceeded(offroad_time)
    should_shutdown |= low_voltage_shutdown
    should_shutdown |= (self.car_battery_capacity_uWh <= 0)
    # Custom: offroad charging (selfdrive/car/charging_monitor.py). Stay on while the truck charges,
    # except for the 12 V cutoff; power down BPChargeSleepDelayMin after a charge in this offroad period ends.
    charge_hold, charge_done = self.charging_shutdown_state(now, offroad_timestamp)
    if charge_hold:
      should_shutdown = low_voltage_shutdown
    should_shutdown |= charge_done
    # A 12 V top-up wake that booted the comma is not a reason to stay on once it ends.
    top_up_over = self.top_up_wake_over(now, started_seen)
    should_shutdown |= top_up_over
    # Custom: end
    should_shutdown &= not ignition
    should_shutdown &= (not self.params.get_bool("DisablePowerDown"))
    should_shutdown &= in_car
    should_shutdown &= offroad_time > DELAY_SHUTDOWN_TIME_S
    should_shutdown |= self.params.get_bool("ForcePowerDown")
    should_shutdown &= started_seen or (now > MIN_ON_TIME_S) or top_up_over  # Custom: top_up_over
    return should_shutdown
