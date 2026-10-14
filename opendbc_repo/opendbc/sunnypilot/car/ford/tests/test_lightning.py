"""Custom: tests for Lightning EV parsing, alerts and tune profiles (stream B)."""
from dataclasses import fields

import pytest

from opendbc.can import CANPacker, CANParser
from opendbc.car.ford.values import CAR
from opendbc.sunnypilot.car.ford.lightning import (
  EV_PT_MESSAGES, HEV_BATTERY_MESSAGES, LIGHTNING_TUNE, PROFILE_TUNES, STOCK_TUNE, EvSettings, LightningState,
  OnePedalEstimator, TuneBlender, TuneSettings, TuneValues, range_impact_percent, sanitize, select_profile, thermal_mode,
)

DBC = "ford_lincoln_base_pt"
BUS = 0
DT = 0.01
NS = 10_000_000  # 10 ms


class Feed:
  """Packs DBC messages and feeds them to a real CANParser, 100 Hz."""
  def __init__(self):
    self.packer = CANPacker(DBC)
    msgs = [(m, float('nan')) for m in EV_PT_MESSAGES + HEV_BATTERY_MESSAGES]
    self.cp = CANParser(DBC, msgs, BUS)
    self.t = 0
    self.frames: dict[str, dict] = {}

  def set(self, name, **values):
    self.frames[name] = values

  def drop(self, name):
    self.frames.pop(name, None)

  def step(self, n=1):
    for _ in range(n):
      self.t += NS
      frames = [self.packer.make_can_msg(name, BUS, vals) for name, vals in self.frames.items()]
      self.cp.update([(self.t, frames)])


def run(feed, state, settings=None, n=1, v_ego=20., a_ego=0., gas=False, brake=False, cruise=False):
  settings = settings or EvSettings()
  values = {}
  for _ in range(n):
    feed.step()
    values = state.update(feed.cp, settings, v_ego, a_ego, gas, brake, cruise, DT)
  return values


def lightning_feed():
  f = Feed()
  # BattTrac_I_Actl left at raw 0 (= -750 A), as seen on the truck
  f.set("Battery_Traction_1_FD1", BattTrac_U_Actl=400., BattTrac_I_Actl=-750.)
  f.set("Battery_Traction_3_FD1", BattTracClnt_Te_Actl=25.)
  f.set("Battery_Traction_4_FD1", BattTracSoc2_Pc_Actl=55.5, BattTrac_Te_Actl=30.)
  f.set("Battery_Traction_5_FD1", BattTrac2_Pw_LimChrg=150000., BattTrac2_Pw_LimDchrg=300000.)
  f.set("MtrTracData_1_FD1", MtrTrac2_I_Actl=50.)
  f.set("MtrTrac_Data2_FD1", VehElRnge_L_Dsply=300.)
  f.set("Tire_Pressure_Data_FD1", Tire_Press_LF_Data=290, Tire_Press_RF_Data=290, Tire_Press_LR_OLR_Data=290,
        Tire_Press_RR_ORR_Data=290)
  f.set("Battery_Mgmt_4_FD1", BattULoAux_U_Actl=13.5, BattULoAuxSoc_Pc_Actl=85, BattULoAux_I_Actl=5.)
  f.set("SmartChargingData_ECG_3", AirAmb_Te_ActlCld=-5.)
  f.set("SelectDriveModeData", SelDrvMdePt_D_Rq=0)
  f.set("TrailerInfo_FD1", TrlrLampCnnct_B_Actl=0)
  return f


class TestLightningState:
  def test_nothing_on_bus(self):
    values = run(Feed(), LightningState())
    assert not values["evBattery.dataAvailable"]
    assert values["evBattery.packCurrentSource"] == "none"
    assert values["evBattery.powerKw"] == 0.
    assert not values["tirePressure.dataAvailable"]
    assert not values["ambient.dataAvailable"]
    assert values["vehicleMode.driveMode"] == "unknown"
    assert values["evAlerts.lowSoc"] == "none"
    assert values["evAlerts.alertText"] == ""

  def test_battery_and_current_fallback(self):
    values = run(lightning_feed(), LightningState())
    assert values["evBattery.dataAvailable"]
    assert values["evBattery.socPercent"] == pytest.approx(55.5, abs=0.01)
    assert values["evBattery.packVoltage"] == pytest.approx(400.)
    # stuck BattTrac_I_Actl is skipped in favour of MtrTrac2_I_Actl
    assert values["evBattery.packCurrentSource"] == "mtrTrac2Actl"
    assert values["evBattery.packCurrent"] == pytest.approx(50., abs=0.1)
    assert values["evBattery.powerKw"] == pytest.approx(20., abs=0.1)
    assert values["evBattery.regenKw"] == 0.
    assert values["evBattery.packTempC"] == pytest.approx(30.)
    assert values["evBattery.coolantTempC"] == pytest.approx(25.)
    assert values["evBattery.limitsAvailable"]
    assert values["evBattery.chargeLimitKw"] == pytest.approx(150.)
    assert values["evBattery.dischargeLimitKw"] == pytest.approx(300.)
    assert values["evBattery.rangeAvailable"]
    assert values["evBattery.rangeKm"] == pytest.approx(300., abs=0.1)

  def test_est_vsc_preferred_over_motor_current(self):
    f = lightning_feed()
    f.set("MtrTracData_1_FD1", MtrTrac2_I_Actl=50., MtrTrac2_U_Actl=400.)
    f.set("PreCond_Hev_Data2_FD1", BattTrac_I_EstVsc=60.)
    values = run(f, LightningState())
    assert values["evBattery.packCurrentSource"] == "battTracEstVsc"
    assert values["evBattery.powerKw"] == pytest.approx(24., abs=0.1)
    # motor-only power is published separately
    assert values["evBattery.motorPowerAvailable"]
    assert values["evBattery.motorPowerKw"] == pytest.approx(20., abs=0.1)

  def test_ambient_source_order(self):
    f = lightning_feed()
    f.set("EngineClimateData", AirAmb_Te_Actl=12.)
    assert run(f, LightningState())["ambient.outsideTempC"] == pytest.approx(12.)
    f.set("Climate_Control_Data_FD1", Outside_Air_Temp_Stat=87.)  # raw 254 = unknown, skipped
    assert run(f, LightningState())["ambient.outsideTempC"] == pytest.approx(12.)
    f.set("Climate_Control_Data_FD1", Outside_Air_Temp_Stat=8.5)
    assert run(f, LightningState())["ambient.outsideTempC"] == pytest.approx(8.5)

  def test_working_batt_trac_current_preferred(self):
    f = lightning_feed()
    f.set("Battery_Traction_1_FD1", BattTrac_U_Actl=400., BattTrac_I_Actl=-100.)
    values = run(f, LightningState())
    assert values["evBattery.packCurrentSource"] == "battTracActl"
    assert values["evBattery.powerKw"] == pytest.approx(-40., abs=0.1)
    assert values["evBattery.regenKw"] == pytest.approx(40., abs=0.1)

  def test_range_no_data_falls_back(self):
    f = lightning_feed()
    f.set("MtrTrac_Data2_FD1", VehElRnge_L_Dsply=409.4)  # raw 4094 = NoDataExists
    f.set("HEV_ChargeStat_FD1", VehElRngeNut_L_Dsply=250.)
    values = run(f, LightningState())
    assert values["evBattery.rangeKm"] == pytest.approx(250., abs=0.1)

  def test_trip_energy_and_efficiency(self):
    state = LightningState()
    values = run(lightning_feed(), state, n=1000, v_ego=20.)  # 10 s at 20 kW, 72 km/h
    assert values["evBattery.tripEnergyUsedKwh"] == pytest.approx(20. * 10 / 3600, rel=0.02)
    assert values["evBattery.tripDistanceKm"] == pytest.approx(0.2, rel=0.01)
    assert values["evBattery.efficiencyWhPerKm"] == pytest.approx(20000 / 72., rel=0.02)
    assert run(lightning_feed(), state, v_ego=0.)["evBattery.efficiencyWhPerKm"] == 0.

  def test_stale_message_unavailable(self):
    f = lightning_feed()
    state = LightningState()
    assert run(f, state)["ambient.dataAvailable"]
    f.drop("SmartChargingData_ECG_3")
    assert run(f, state, n=400)["ambient.dataAvailable"]  # 4 s: still fresh
    assert not run(f, state, n=200)["ambient.dataAvailable"]

  def test_tires(self):
    f = lightning_feed()
    state = LightningState()
    values = run(f, state)
    assert values["tirePressure.dataAvailable"]
    assert values["tirePressure.frontLeftKpa"] == 290.
    assert not values["tirePressure.lowPressure"]
    f.set("Tire_Pressure_Data_FD1", Tire_Press_LF_Data=290, Tire_Press_RF_Data=200, Tire_Press_LR_OLR_Data=290,
          Tire_Press_RR_ORR_Data=65534)
    assert not run(f, state, n=100)["tirePressure.lowPressure"]  # debounced
    values = run(f, state, n=300)
    assert values["tirePressure.lowPressure"]
    assert values["tirePressure.rearRightKpa"] == 0.  # invalid
    assert values["evAlerts.tirePressureLow"]
    assert values["evAlerts.alertText"] == "Tire pressure low"

  def test_low_volt(self):
    f = lightning_feed()
    state = LightningState()
    values = run(f, state)
    assert values["lowVoltBattery.dataAvailable"]
    assert values["lowVoltBattery.voltage"] == pytest.approx(13.5)
    assert values["lowVoltBattery.socPercent"] == 85.
    f.set("Battery_Mgmt_4_FD1", BattULoAux_U_Actl=11.5, BattULoAuxSoc_Pc_Actl=40)
    values = run(f, state, n=600)
    assert values["lowVoltBattery.low"]
    assert values["evAlerts.alertText"] == "12V battery low"

  def test_ambient(self):
    values = run(lightning_feed(), LightningState())
    assert values["ambient.outsideTempC"] == pytest.approx(-5.)
    assert values["ambient.rangeImpactPercent"] == pytest.approx(-25.)
    assert range_impact_percent(25.) == 0.

  def test_drive_mode_and_trailer(self):
    f = lightning_feed()
    state = LightningState()
    assert run(f, state)["vehicleMode.driveMode"] == "normal"
    for raw, mode in ((1, "sport"), (3, "tow"), (5, "slippery"), (8, "offroad"), (6, "eco"), (2, "unknown")):
      f.set("SelectDriveModeData", SelDrvMdePt_D_Rq=raw)
      values = run(f, state)
      assert values["vehicleMode.driveMode"] == mode
      assert values["vehicleMode.driveModeRaw"] == raw

    f.set("TrailerInfo_FD1", TrlrLampCnnct_B_Actl=1)
    assert not run(f, state, n=150)["vehicleMode.trailerConnected"]
    assert run(f, state, n=100)["vehicleMode.trailerConnected"]
    f.set("TrailerInfo_FD1", TrlrLampCnnct_B_Actl=0)
    assert run(f, state, n=400)["vehicleMode.trailerConnected"]  # 5 s release
    assert not run(f, state, n=200)["vehicleMode.trailerConnected"]

  def test_low_soc_hysteresis(self):
    f = lightning_feed()
    state = LightningState()
    s = EvSettings(low_soc_pct=20., critical_soc_pct=10.)

    def level(soc):
      f.set("Battery_Traction_4_FD1", BattTracSoc2_Pc_Actl=soc, BattTrac_Te_Actl=30.)
      return run(f, state, s)["evAlerts.lowSoc"]

    assert level(25.) == "none"
    assert level(20.) == "low"
    assert level(21.) == "low"       # inside hysteresis
    assert level(22.5) == "none"
    assert level(9.5) == "critical"
    values = run(f, state, s)
    assert values["evAlerts.alertText"].startswith("Battery critical 10%")
    assert level(11.) == "critical"  # inside hysteresis
    assert level(12.5) == "low"
    assert level(30.) == "none"

  def test_charging_dc(self):
    f = lightning_feed()
    state = LightningState()
    values = run(f, state)
    assert not values["charging.dataAvailable"] and not values["charging.charging"]
    f.set("Battery_Traction_4_FD1", BattTracSoc2_Pc_Actl=15., BattTrac_Te_Actl=35.)
    f.set("PreCond_Hev_Data1_FD1", ChrgStat_D2_Dsply=8)  # ChargingDCFastChange
    f.set("PreCond_Hev_Data2_FD1", BattTrac_I_EstVsc=-300., PreCondActv_B_Actl=0)
    f.set("HEV_ChargeStat_FD1", ChargeNowDuration_St=0.7)
    f.set("MHT_EV_Wakeup_FD1", PreCondBatt_B_Actl=1, PtcHtr_D_Stat=0)
    values = run(f, state, v_ego=0., n=100)
    assert values["charging.dataAvailable"] and values["charging.state"] == "chargingDc"
    assert not values["charging.charging"]  # debounced 2 s
    values = run(f, state, v_ego=0., n=150)
    assert values["charging.charging"]
    assert values["charging.chargeType"] == "dc"
    assert values["charging.powerAvailable"]
    assert values["charging.powerKw"] == pytest.approx(120., abs=0.1)
    assert values["charging.socPercent"] == pytest.approx(15.)
    assert values["charging.batteryTempC"] == pytest.approx(35.)
    assert values["charging.timeToFullHours"] == pytest.approx(0.7)
    assert values["charging.batteryConditioning"]
    assert not values["charging.coolantHeaterOn"]
    assert values["charging.thermalMode"] == "conditioning"
    # DC fast charge: pump on, cold coolant -> cooling
    f.set("MHT_EV_Wakeup_FD1", PreCondBatt_B_Actl=0, PtcHtr_D_Stat=0)
    f.set("PreCond_Hev_Data2_FD1", BattTrac_I_EstVsc=-300., PreCondActv_B_Actl=0, BattTracClntFlw_Pc_Rq=60.)
    f.set("Battery_Traction_3_FD1", BattTracClnt_Te_Actl=22.)
    f.set("Battery_Traction_6_FD1", BattTracClntPmp_D_Stat=1)
    values = run(f, state, v_ego=0., n=10)
    assert values["charging.coolantPumpOn"] and values["charging.coolantFlowAvailable"]
    assert values["charging.coolantFlowPercent"] == pytest.approx(60.)
    assert values["charging.thermalMode"] == "cooling"
    # low SOC alert is suppressed while charging
    assert values["evAlerts.lowSoc"] == "none"

  def test_charging_ac_and_cluster_fallback(self):
    f = lightning_feed()
    state = LightningState()
    f.set("Cluster_HEV_Data1_FD1", ChrgStat_D_Dsply=4)  # In_Progress, no AC/DC detail
    values = run(f, state, v_ego=0., n=250)
    assert values["charging.charging"] and values["charging.state"] == "chargingUnknownType"
    assert values["charging.chargeType"] == "other"
    # only MtrTrac2 current: no charge power (it excludes the charger path)
    assert not values["charging.powerAvailable"]
    f.set("PreCond_Hev_Data1_FD1", ChrgStat_D2_Dsply=7)
    assert run(f, state, v_ego=0.)["charging.chargeType"] == "ac"
    f.set("PreCond_Hev_Data1_FD1", ChrgStat_D2_Dsply=13)  # target reached
    values = run(f, state, v_ego=0., n=250)
    assert not values["charging.charging"] and values["charging.state"] == "targetReached"

  def test_thermal_mode(self):
    assert thermal_mode(False, False, False, False, None) == "unknown"
    assert thermal_mode(False, False, False, True, -10.) == "off"
    assert thermal_mode(True, True, True, True, -10.) == "heating"
    assert thermal_mode(False, True, True, True, -10.) == "conditioning"
    assert thermal_mode(False, False, True, True, -5.) == "cooling"
    assert thermal_mode(False, False, True, True, 5.) == "heating"
    assert thermal_mode(False, False, True, True, 1.) == "circulating"
    assert thermal_mode(False, False, True, True, None) == "circulating"

  def test_one_pedal_estimator(self):
    est = OnePedalEstimator()
    for _ in range(100):
      est.update(15., -1.8, False, False, False, DT)
    assert not est.active
    for _ in range(60):
      est.update(15., -1.8, False, False, False, DT)
    assert est.active
    # braking, gas or cruise never change the estimate
    for _ in range(500):
      est.update(15., -0.1, False, True, False, DT)
      est.update(15., -0.1, True, False, False, DT)
      est.update(15., -0.1, False, False, True, DT)
    assert est.active
    for _ in range(260):
      est.update(15., -0.2, False, False, False, DT)
    assert not est.active

  def test_one_pedal_setting(self):
    f = lightning_feed()
    assert run(f, LightningState(), EvSettings(one_pedal_mode=1))["vehicleMode.onePedalSource"] == "setting"
    assert run(f, LightningState(), EvSettings(one_pedal_mode=1))["vehicleMode.onePedalActive"]
    assert not run(f, LightningState(), EvSettings(one_pedal_mode=0))["vehicleMode.onePedalActive"]


class TestTuneProfiles:
  def test_select(self):
    s = TuneSettings()
    lightning = CAR.FORD_F_150_LIGHTNING_MK1
    assert select_profile(CAR.FORD_F_150_MK14, s, "tow", True) == "stock"
    assert select_profile(lightning, s, "normal", False) == "lightning"
    assert select_profile(lightning, s, "unknown", True) == "tow"
    assert select_profile(lightning, s, "tow", False) == "tow"
    assert select_profile(lightning, s, "sport", False) == "sport"
    assert select_profile(lightning, s, "slippery", False) == "slippery"
    assert select_profile(lightning, s, "offroad", False) == "offroad"
    assert select_profile(lightning, s, "eco", False) == "lightning"
    assert select_profile(lightning, TuneSettings(lightning_tune=False), "tow", True) == "stock"
    assert select_profile(lightning, TuneSettings(tow_profile=1), "normal", True) == "lightning"
    assert select_profile(lightning, TuneSettings(tow_profile=2), "normal", False) == "tow"
    assert select_profile(lightning, TuneSettings(drive_mode_tune=False), "sport", False) == "lightning"
    assert select_profile(lightning, TuneSettings(drive_mode_tune=False), "tow", True) == "tow"

  @pytest.mark.parametrize("name", list(PROFILE_TUNES))
  def test_profiles_never_looser_than_stock(self, name):
    t = sanitize(PROFILE_TUNES[name])
    for f in ("accel_max_scale", "lat_accel_scale", "lane_change_factor_scale", "path_angle_roc_scale"):
      assert 0. < getattr(t, f) <= 1.0, f
    # hysteresis order kept: engage below target, release above it
    assert t.brake_actuate_target < t.brake_actuate_release < 0
    assert t.precharge_actuate_target < t.precharge_actuate_release < 0
    assert t.lead_gas_cut_s >= STOCK_TUNE.lead_gas_cut_s
    assert 0 < t.following_accel_roc
    assert 0 <= t.creep_comp_max <= STOCK_TUNE.creep_comp_max

  def test_sanitize_clamps(self):
    t = sanitize(TuneValues(accel_max_scale=1.5, lat_accel_scale=2.0, lane_change_factor_scale=1.2, path_angle_roc_scale=0.))
    assert t.accel_max_scale == 1.0 and t.lat_accel_scale == 1.0 and t.lane_change_factor_scale == 1.0
    assert t.path_angle_roc_scale == 0.1

  def test_blend_ramps(self):
    b = TuneBlender(ramp_s=3.0)
    assert b.update("lightning", DT) != LIGHTNING_TUNE  # does not jump
    for _ in range(300):
      t = b.update("lightning", DT)
    assert t == sanitize(LIGHTNING_TUNE)
    tow = sanitize(PROFILE_TUNES["tow"])
    mid = None
    for i in range(300):
      t = b.update("tow", DT)
      if i == 149:
        mid = t
    assert mid.accel_max_scale == pytest.approx((1.0 + tow.accel_max_scale) / 2, abs=0.01)
    assert t == tow
    for f in fields(TuneValues):
      assert getattr(t, f.name) == getattr(tow, f.name)


class TestLightningCarInterface:
  """Runs the real Ford CarState and CarController with Lightning CAN frames."""

  @staticmethod
  def _setup(alpha_long=True):
    from opendbc.car import Bus
    from opendbc.car.ford.carcontroller import CarController
    from opendbc.car.ford.carstate import CarState
    from opendbc.car.ford.interface import CarInterface
    candidate = CAR.FORD_F_150_LIGHTNING_MK1
    CP = CarInterface.get_non_essential_params(candidate)
    CP.openpilotLongitudinalControl = alpha_long
    CP_SP = CarInterface.get_non_essential_params_sp(CP, candidate)
    CS = CarState(CP, CP_SP)
    can_parsers = CarState.get_can_parsers(CP, CP_SP)
    CC = CarController({Bus.pt: DBC}, CP, CP_SP)
    return CP, CS, CC, can_parsers

  @staticmethod
  def _model():
    from cereal import log
    from selfdrive.modeld.constants import ModelConstants
    n = len(ModelConstants.T_IDXS)
    model = log.Event.new_message().init('modelV2')
    model.orientation.x = [0.] * n
    model.orientationRate.z = [0.01] * n
    model.position.y = [0.] * n
    lines = model.init('laneLines', 4)
    for line in lines:
      line.y = [0.] * n
    lines[1].y = [-1.8] * n
    lines[2].y = [1.8] * n
    model.laneLineProbs = [0.9] * 4
    return model

  def _frames(self, packer, soc=55., drive_mode=0, trailer=0):
    return [
      packer.make_can_msg("Battery_Traction_1_FD1", BUS, {"BattTrac_U_Actl": 400., "BattTrac_I_Actl": -750.}),
      packer.make_can_msg("Battery_Traction_3_FD1", BUS, {}),
      packer.make_can_msg("Battery_Traction_4_FD1", BUS, {"BattTracSoc2_Pc_Actl": soc}),
      packer.make_can_msg("MtrTracData_1_FD1", BUS, {"MtrTrac2_I_Actl": -25.}),
      packer.make_can_msg("SelectDriveModeData", BUS, {"SelDrvMdePt_D_Rq": drive_mode}),
      packer.make_can_msg("TrailerInfo_FD1", BUS, {"TrlrLampCnnct_B_Actl": trailer}),
    ]

  def test_car_state_bp_and_profiles(self):
    from opendbc.car import structs
    CP, CS, CC, can_parsers = self._setup()
    packer = CANPacker(DBC)
    CC.model = self._model()

    cc_msg = structs.CarControl.new_message()
    cc_msg.latActive = True
    cc_msg.longActive = True
    cc_msg.actuators.accel = 1.9
    cc_msg.actuators.curvature = 0.005
    cc_sp = structs.CarControlSP()

    t = 0
    accels, gases, n_sends = [], [], 0
    # trailer plugged in at 1 s, debounced 2 s, then the tow profile blends in over 3 s
    for i in range(700):
      t += NS
      trailer = 1 if i >= 100 else 0
      frames = self._frames(packer, soc=15., trailer=trailer)
      for cp in can_parsers.values():
        cp.update([(t, frames)])
      CS.out, _ = CS.update(can_parsers)
      actuators, can_sends = CC.update(cc_msg.as_reader(), cc_sp, CS, t)
      accels.append(actuators.accel)
      gases.append(actuators.gas)
      n_sends += len(can_sends)

    assert n_sends > 600
    bp = CS.car_state_bp_msg.carStateBP
    assert bp.evBattery.dataAvailable
    assert bp.evBattery.packCurrentSource == "mtrTrac2Actl"
    assert bp.evBattery.powerKw == pytest.approx(-10., abs=0.1)
    assert bp.evBattery.regenKw == pytest.approx(10., abs=0.1)
    assert bp.evAlerts.lowSoc == "low"
    assert bp.vehicleMode.trailerConnected
    assert bp.tune.platformTuneActive
    assert bp.tune.profile == "tow"
    assert bp.tune.accelMaxScale == pytest.approx(0.6)
    # tow profile caps acceleration at 0.6 * ACCEL_MAX once blended in
    assert max(accels[-50:]) <= 1.2 + 1e-6
    assert max(gases[-50:]) <= 1.2 + 1e-6
    # before the trailer, the Lightning profile kept the stock ACCEL_MAX cap
    assert max(accels[:100]) <= 2.0 + 1e-6

  def test_other_ford_stays_stock(self):
    from opendbc.car import Bus
    from opendbc.car.ford.carcontroller import CarController
    from opendbc.car.ford.carstate import CarState
    from opendbc.car.ford.interface import CarInterface
    CP = CarInterface.get_non_essential_params(CAR.FORD_F_150_MK14)
    CP_SP = CarInterface.get_non_essential_params_sp(CP, CAR.FORD_F_150_MK14)
    CS = CarState(CP, CP_SP)
    CS.bp_trailer_connected = True
    CS.bp_drive_mode = "tow"
    CC = CarController({Bus.pt: DBC}, CP, CP_SP)
    for _ in range(400):
      CC._update_tune(CS)
    assert CC.tune == STOCK_TUNE
    assert CS.bp_tune_state[1] == "stock"

  def test_lateral_accel_scale_only_lowers_cap(self):
    from opendbc.car.ford.carcontroller import apply_ford_curvature_limits
    CP, _, _, _ = self._setup()
    v = 20.
    _, cap = apply_ford_curvature_limits(0.02, 0.02, 0.02, v, 0, True, CP)
    _, cap_tow = apply_ford_curvature_limits(0.02, 0.02, 0.02, v, 0, True, CP, 0.8)
    _, cap_hi = apply_ford_curvature_limits(0.02, 0.02, 0.02, v, 0, True, CP, 1.5)
    assert cap_tow == pytest.approx(cap * 0.8)
    assert cap_hi == pytest.approx(cap)
