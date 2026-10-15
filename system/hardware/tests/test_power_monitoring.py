import pytest

from openpilot.common.params import Params
from openpilot.system.hardware.power_monitoring import PowerMonitoring, CAR_BATTERY_CAPACITY_uWh, \
  CAR_CHARGING_RATE_W, VBATT_PAUSE_CHARGING, DELAY_SHUTDOWN_TIME_S, MAX_TIME_OFFROAD_S

# Create fake time
ssb = 0.
def mock_time_monotonic():
  global ssb
  ssb += 1.
  return ssb

TEST_DURATION_S = 50
GOOD_VOLTAGE = 12 * 1e3
VOLTAGE_BELOW_PAUSE_CHARGING = (VBATT_PAUSE_CHARGING - 1) * 1e3

def pm_patch(mocker, name, value, constant=False):
  if constant:
    mocker.patch(f"openpilot.system.hardware.power_monitoring.{name}", value)
  else:
    mocker.patch(f"openpilot.system.hardware.power_monitoring.{name}", return_value=value)


@pytest.fixture(autouse=True)
def mock_time(mocker):
  mocker.patch("time.monotonic", mock_time_monotonic)


class TestPowerMonitoring:
  def setup_method(self):
    self.params = Params()

  # Test to see that it doesn't do anything when pandaState is None
  def test_panda_state_present(self):
    pm = PowerMonitoring()
    for _ in range(10):
      pm.calculate(None, None)
    assert pm.get_power_used() == 0
    assert pm.get_car_battery_capacity() == (CAR_BATTERY_CAPACITY_uWh / 10)

  # Test to see that it doesn't integrate offroad when ignition is True
  def test_offroad_ignition(self):
    pm = PowerMonitoring()
    for _ in range(10):
      pm.calculate(GOOD_VOLTAGE, True)
    assert pm.get_power_used() == 0

  # Test to see that it integrates with discharging battery
  def test_offroad_integration_discharging(self, mocker):
    POWER_DRAW = 4
    pm_patch(mocker, "HARDWARE.get_current_power_draw", POWER_DRAW)
    pm = PowerMonitoring()
    for _ in range(TEST_DURATION_S + 1):
      pm.calculate(GOOD_VOLTAGE, False)
    expected_power_usage = ((TEST_DURATION_S/3600) * POWER_DRAW * 1e6)
    assert abs(pm.get_power_used() - expected_power_usage) < 10

  # Test to check positive integration of car_battery_capacity
  def test_car_battery_integration_onroad(self, mocker):
    POWER_DRAW = 4
    pm_patch(mocker, "HARDWARE.get_current_power_draw", POWER_DRAW)
    pm = PowerMonitoring()
    pm.car_battery_capacity_uWh = 0
    for _ in range(TEST_DURATION_S + 1):
      pm.calculate(GOOD_VOLTAGE, True)
    expected_capacity = ((TEST_DURATION_S/3600) * CAR_CHARGING_RATE_W * 1e6)
    assert abs(pm.get_car_battery_capacity() - expected_capacity) < 10

  # Test to check positive integration upper limit
  def test_car_battery_integration_upper_limit(self, mocker):
    POWER_DRAW = 4
    pm_patch(mocker, "HARDWARE.get_current_power_draw", POWER_DRAW)
    pm = PowerMonitoring()
    pm.car_battery_capacity_uWh = CAR_BATTERY_CAPACITY_uWh - 1000
    for _ in range(TEST_DURATION_S + 1):
      pm.calculate(GOOD_VOLTAGE, True)
    estimated_capacity = CAR_BATTERY_CAPACITY_uWh + (CAR_CHARGING_RATE_W / 3600 * 1e6)
    assert abs(pm.get_car_battery_capacity() - estimated_capacity) < 10

  # Test to check negative integration of car_battery_capacity
  def test_car_battery_integration_offroad(self, mocker):
    POWER_DRAW = 4
    pm_patch(mocker, "HARDWARE.get_current_power_draw", POWER_DRAW)
    pm = PowerMonitoring()
    pm.car_battery_capacity_uWh = CAR_BATTERY_CAPACITY_uWh
    for _ in range(TEST_DURATION_S + 1):
      pm.calculate(GOOD_VOLTAGE, False)
    expected_capacity = CAR_BATTERY_CAPACITY_uWh - ((TEST_DURATION_S/3600) * POWER_DRAW * 1e6)
    assert abs(pm.get_car_battery_capacity() - expected_capacity) < 10

  # Test to check negative integration lower limit
  def test_car_battery_integration_lower_limit(self, mocker):
    POWER_DRAW = 4
    pm_patch(mocker, "HARDWARE.get_current_power_draw", POWER_DRAW)
    pm = PowerMonitoring()
    pm.car_battery_capacity_uWh = 1000
    for _ in range(TEST_DURATION_S + 1):
      pm.calculate(GOOD_VOLTAGE, False)
    estimated_capacity = 0 - ((1/3600) * POWER_DRAW * 1e6)
    assert abs(pm.get_car_battery_capacity() - estimated_capacity) < 10

  # Test to check policy of stopping charging after MAX_TIME_OFFROAD_S
  def test_max_time_offroad(self, mocker):
    MOCKED_MAX_OFFROAD_TIME = 3600
    POWER_DRAW = 0 # To stop shutting down for other reasons
    pm_patch(mocker, "MAX_TIME_OFFROAD_S", MOCKED_MAX_OFFROAD_TIME, constant=True)
    pm_patch(mocker, "HARDWARE.get_current_power_draw", POWER_DRAW)
    pm = PowerMonitoring()
    pm.car_battery_capacity_uWh = CAR_BATTERY_CAPACITY_uWh
    start_time = ssb
    ignition = False
    while ssb <= start_time + MOCKED_MAX_OFFROAD_TIME:
      pm.calculate(GOOD_VOLTAGE, ignition)
      if (ssb - start_time) % 1000 == 0 and ssb < start_time + MOCKED_MAX_OFFROAD_TIME:
        assert not pm.should_shutdown(ignition, True, start_time, False)
    assert pm.should_shutdown(ignition, True, start_time, False)

  def test_car_voltage(self, mocker):
    POWER_DRAW = 0 # To stop shutting down for other reasons
    TEST_TIME = 350
    VOLTAGE_SHUTDOWN_MIN_OFFROAD_TIME_S = 50
    pm_patch(mocker, "VOLTAGE_SHUTDOWN_MIN_OFFROAD_TIME_S", VOLTAGE_SHUTDOWN_MIN_OFFROAD_TIME_S, constant=True)
    pm_patch(mocker, "HARDWARE.get_current_power_draw", POWER_DRAW)
    pm = PowerMonitoring()
    pm.car_battery_capacity_uWh = CAR_BATTERY_CAPACITY_uWh
    ignition = False
    start_time = ssb
    for i in range(TEST_TIME):
      pm.calculate(VOLTAGE_BELOW_PAUSE_CHARGING, ignition)
      if i % 10 == 0:
        assert pm.should_shutdown(ignition, True, start_time, True) == \
                          (pm.car_voltage_mV < VBATT_PAUSE_CHARGING * 1e3 and \
                          (ssb - start_time) > VOLTAGE_SHUTDOWN_MIN_OFFROAD_TIME_S and \
                            (ssb - start_time) > DELAY_SHUTDOWN_TIME_S)
    assert pm.should_shutdown(ignition, True, start_time, True)

  # Test to check policy of not stopping charging when DisablePowerDown is set
  def test_disable_power_down(self, mocker):
    POWER_DRAW = 0 # To stop shutting down for other reasons
    TEST_TIME = 100
    self.params.put_bool("DisablePowerDown", True, block=True)
    pm_patch(mocker, "HARDWARE.get_current_power_draw", POWER_DRAW)
    pm = PowerMonitoring()
    pm.car_battery_capacity_uWh = CAR_BATTERY_CAPACITY_uWh
    ignition = False
    for i in range(TEST_TIME):
      pm.calculate(VOLTAGE_BELOW_PAUSE_CHARGING, ignition)
      if i % 10 == 0:
        assert not pm.should_shutdown(ignition, True, ssb, False)
    assert not pm.should_shutdown(ignition, True, ssb, False)

  # Test to check policy of not stopping charging when ignition
  def test_ignition(self, mocker):
    POWER_DRAW = 0 # To stop shutting down for other reasons
    TEST_TIME = 100
    pm_patch(mocker, "HARDWARE.get_current_power_draw", POWER_DRAW)
    pm = PowerMonitoring()
    pm.car_battery_capacity_uWh = CAR_BATTERY_CAPACITY_uWh
    ignition = True
    for i in range(TEST_TIME):
      pm.calculate(VOLTAGE_BELOW_PAUSE_CHARGING, ignition)
      if i % 10 == 0:
        assert not pm.should_shutdown(ignition, True, ssb, False)
    assert not pm.should_shutdown(ignition, True, ssb, False)

  # Test to check policy of not stopping charging when harness is not connected
  def test_harness_connection(self, mocker):
    POWER_DRAW = 0 # To stop shutting down for other reasons
    TEST_TIME = 100
    pm_patch(mocker, "HARDWARE.get_current_power_draw", POWER_DRAW)
    pm = PowerMonitoring()
    pm.car_battery_capacity_uWh = CAR_BATTERY_CAPACITY_uWh

    ignition = False
    for i in range(TEST_TIME):
      pm.calculate(VOLTAGE_BELOW_PAUSE_CHARGING, ignition)
      if i % 10 == 0:
        assert not pm.should_shutdown(ignition, False, ssb, False)
    assert not pm.should_shutdown(ignition, False, ssb, False)

  def test_delay_shutdown_time(self):
    pm = PowerMonitoring()
    pm.car_battery_capacity_uWh = 0
    ignition = False
    in_car = True
    offroad_timestamp = ssb
    started_seen = True
    pm.calculate(VOLTAGE_BELOW_PAUSE_CHARGING, ignition)

    while ssb < offroad_timestamp + DELAY_SHUTDOWN_TIME_S:
      assert not pm.should_shutdown(ignition, in_car,
                                          offroad_timestamp,
                                          started_seen), \
                       f"Should not shutdown before {DELAY_SHUTDOWN_TIME_S} seconds offroad time"
    assert pm.should_shutdown(ignition, in_car,
                                       offroad_timestamp,
                                       started_seen), \
                    f"Should shutdown after {DELAY_SHUTDOWN_TIME_S} seconds offroad time"

  @pytest.mark.parametrize(
    "max_time_offroad, offroad_time_min, expected_result",
    [
      # No max time set – fallback to default (30 hours)
      (None, 0, False),
      (None, MAX_TIME_OFFROAD_S + 1, True),  # exceeds 30h (1800+ mins)

      # Valid max time values (in minutes)
      (60, 59, False),  # under limit
      (60, 120, True),  # over limit
      (10, 8, False),  # under limit
      (10, 11, True),  # over limit

      # Edge case: max time is zero → no limit enforced
      (0, 0, False),
      (0, 400, False),

      # Invalid max time formats or negative values → fallback to 30 hours
      (-100, 100, False),  # should fallback to 30h
      (-1, MAX_TIME_OFFROAD_S + 1, True),  # should fallback to 30h, and exceed it
    ]
  )
  def test_max_time_offroad_exceeded(self, max_time_offroad, offroad_time_min, expected_result):
    # Set the parameter if provided
    if max_time_offroad is not None:
      self.params.put("MaxTimeOffroad", max_time_offroad, block=True)

    # Convert offroad time from minutes to seconds
    offroad_time_s = offroad_time_min * 60

    pm = PowerMonitoring()
    result = pm.max_time_offroad_exceeded(offroad_time_s)

    assert result == expected_result

  # Custom: offroad charging keep-awake and post-charge sleep delay
  @pytest.mark.parametrize(
    "active, last_age_s, keep_awake, delay_min, charged_after_offroad, expected",
    [
      (True, 5, True, 30, True, (True, False)),      # charging: hold
      (True, 5, False, 30, True, (False, False)),    # keep-awake off: normal rules
      (True, 120, True, 30, True, (False, False)),   # stale (monitor gone): no hold
      (False, 60, True, 30, True, (False, False)),   # charge ended 1 min ago: still waiting
      (False, 1801, True, 30, True, (False, True)),  # 30 min after the charge: power down
      (False, 1801, True, 0, True, (False, False)),  # delay 0: MaxTimeOffroad decides
      (False, 1801, True, 30, False, (False, False)),  # charge was before this offroad period
    ]
  )
  def test_charging_shutdown_state(self, active, last_age_s, keep_awake, delay_min, charged_after_offroad, expected):
    now = 100_000.
    last = now - last_age_s
    offroad_ts = last - 10 if charged_after_offroad else last + 1
    self.params.put_bool("BPChargingActive", active)
    self.params.put("BPChargeLastActiveTs", last)
    self.params.put_bool("BPChargeKeepAwake", keep_awake)
    self.params.put("BPChargeSleepDelayMin", delay_min)
    try:
      assert PowerMonitoring().charging_shutdown_state(now, offroad_ts) == expected
    finally:
      for k in ("BPChargingActive", "BPChargeLastActiveTs", "BPChargeKeepAwake", "BPChargeSleepDelayMin"):
        self.params.remove(k)

  def test_charging_holds_against_max_time_offroad(self, mocker):
    pm = PowerMonitoring()
    pm.car_voltage_mV = GOOD_VOLTAGE
    self.params.put("MaxTimeOffroad", 10)
    self.params.put_bool("BPChargingActive", True)
    offroad_ts = ssb
    try:
      mocker.patch("time.monotonic", return_value=offroad_ts + 3600)
      self.params.put("BPChargeLastActiveTs", offroad_ts + 3595)
      assert not pm.should_shutdown(False, True, offroad_ts, True)
      self.params.put_bool("BPChargingActive", False)
      assert pm.should_shutdown(False, True, offroad_ts, True)
    finally:
      for k in ("MaxTimeOffroad", "BPChargingActive", "BPChargeLastActiveTs"):
        self.params.remove(k)

  # Custom: Lightning 12 V management (selfdrive/car/lv_power.py)
  LV_KEYS = ("BPLvState", "BPLvSaver", "BPLvSaverOffroadMin", "BPLvShutdownSoc", "BPLvWakeFilter", "MaxTimeOffroad")

  def _clear_lv(self):
    for k in self.LV_KEYS:
      self.params.remove(k)

  def test_lv_top_up_wake(self):
    pm = PowerMonitoring()
    try:
      self.params.put("BPLvState", {"ts": 100., "topUp": True, "topUpTs": 100.})
      assert pm.lv_top_up_wake(102.)
      assert not pm.lv_top_up_wake(110.)  # stale: a dead monitor never blocks a drive
      self.params.put_bool("BPLvWakeFilter", False)
      assert not pm.lv_top_up_wake(102.)
      self.params.put_bool("BPLvWakeFilter", True)
      self.params.put("BPLvState", {"ts": 100., "topUp": False, "topUpTs": 100.})
      assert not pm.lv_top_up_wake(101.)
    finally:
      self._clear_lv()

  def test_top_up_boot_powers_down_after_wake(self, mocker):
    pm = PowerMonitoring()
    pm.car_voltage_mV = GOOD_VOLTAGE
    offroad_ts = 0.
    try:
      # booted by a top-up wake, never started: during the wake it stays on
      mocker.patch("time.monotonic", return_value=400.)
      self.params.put("BPLvState", {"ts": 400., "topUp": True, "topUpTs": 400.})
      assert not pm.should_shutdown(False, True, offroad_ts, False)
      # wake over, but not for long enough yet
      mocker.patch("time.monotonic", return_value=460.)
      self.params.put("BPLvState", {"ts": 460., "topUp": False, "topUpTs": 460.})
      assert not pm.should_shutdown(False, True, offroad_ts, False)
      # TOP_UP_SLEEP_S after the wake ended it powers down, well inside MIN_ON_TIME_S
      mocker.patch("time.monotonic", return_value=530.)
      assert pm.should_shutdown(False, True, offroad_ts, False)
      # never while the ignition line is still up (keeps the next real ignition edge)
      assert not pm.should_shutdown(True, True, offroad_ts, False)
    finally:
      self._clear_lv()

  def test_no_top_up_boot_keeps_min_on_time(self, mocker):
    pm = PowerMonitoring()
    pm.car_voltage_mV = GOOD_VOLTAGE
    mocker.patch("time.monotonic", return_value=530.)
    assert not pm.should_shutdown(False, True, 0., False)

  def test_lv_soc_cutoff(self, mocker):
    pm = PowerMonitoring()
    pm.car_voltage_mV = GOOD_VOLTAGE
    try:
      mocker.patch("time.monotonic", return_value=4000.)
      self.params.put("BPLvState", {"ts": 3990., "soc": 48.})
      assert not pm.should_shutdown(False, True, 3000., True)  # cutoff off by default
      self.params.put("BPLvShutdownSoc", 50)
      assert pm.should_shutdown(False, True, 3000., True)
      self.params.put("BPLvState", {"ts": 3990., "soc": 55.})
      assert not pm.should_shutdown(False, True, 3000., True)
      self.params.put("BPLvState", {"ts": 3000., "soc": 40.})  # stale reading is ignored
      assert not pm.should_shutdown(False, True, 3000., True)
    finally:
      self._clear_lv()

  def test_lv_power_saver(self, mocker):
    pm = PowerMonitoring()
    try:
      assert not pm.max_time_offroad_exceeded(11 * 60)
      self.params.put_bool("BPLvSaver", True)
      assert pm.max_time_offroad_exceeded(11 * 60)  # default 10 min
      assert not pm.max_time_offroad_exceeded(9 * 60)
      self.params.put("BPLvSaverOffroadMin", 5)
      self.params.put("MaxTimeOffroad", 3)  # a shorter MaxTimeOffroad still wins
      assert pm.max_time_offroad_exceeded(4 * 60)
      # saver raises the 12 V cutoff to 12.2 V and the SOC cutoff to 60 %
      self.params.put("MaxTimeOffroad", 0)
      self.params.put("BPLvSaverOffroadMin", 600)
      mocker.patch("time.monotonic", return_value=4000.)
      pm.car_voltage_mV = 12.1e3
      assert pm.should_shutdown(False, True, 3000., True)
      pm.car_voltage_mV = 12.6e3
      assert not pm.should_shutdown(False, True, 3000., True)
      self.params.put("BPLvState", {"ts": 3990., "soc": 58.})
      assert pm.should_shutdown(False, True, 3000., True)
    finally:
      self._clear_lv()
