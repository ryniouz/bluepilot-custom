"""Custom: offroad charging monitor (stream B)."""
from cereal import log
from opendbc.can import CANPacker
from opendbc.car.ford.interface import CarInterface
from opendbc.car.ford.values import CAR
from openpilot.common.params import Params
from openpilot.selfdrive.car.charging_monitor import ChargingMonitor, supported
from openpilot.selfdrive.pandad import can_list_to_can_capnp

DBC = "ford_lincoln_base_pt"


def frames(packer, charge_state, ignition=1, lv_support=0, lv_soc=None):
  extra = [
    packer.make_can_msg("BodyInfo_3_FD1", 0, {"Ignition_Status": ignition}),
    packer.make_can_msg("HEV_Powertrain_Data6", 0, {"ULoBattSpprtSustn_B_Rq": lv_support, "DcdcOn_B_Rq": lv_support}),
  ]
  if lv_soc is not None:
    extra.append(packer.make_can_msg("Battery_Mgmt_4_FD1", 0, {"BattULoAux_U_Actl": 12.6, "BattULoAuxSoc_Pc_Actl": lv_soc}))
  return extra + [
    packer.make_can_msg("Battery_Traction_1_FD1", 0, {"BattTrac_U_Actl": 350.}),
    packer.make_can_msg("Battery_Traction_4_FD1", 0, {"BattTracSoc2_Pc_Actl": 42., "BattTrac_Te_Actl": 28.}),
    packer.make_can_msg("PreCond_Hev_Data2_FD1", 0, {"BattTrac_I_EstVsc": -200.}),
    packer.make_can_msg("PreCond_Hev_Data1_FD1", 0, {"ChrgStat_D2_Dsply": charge_state}),
  ]


class TestChargingMonitor:
  def setup_method(self):
    self.params = Params()
    for k in ("BPChargingActive", "BPChargeLastActiveTs", "BPChargeKeepAwake", "BPChargeSleepDelayMin", "BPLvState", "BPLvSaver"):
      self.params.remove(k)
    self.CP = CarInterface.get_non_essential_params(CAR.FORD_F_150_LIGHTNING_MK1)
    self.packer = CANPacker(DBC)

  def _step(self, monitor, t, charge_state, obd=None, **kw):
    with log.Event.from_bytes(can_list_to_can_capnp(frames(self.packer, charge_state, **kw))) as evt:
      dat = evt.as_builder()
    dat.logMonoTime = int(t * 1e9)
    return monitor.step([dat.to_bytes()], t, obd, 12400.)

  def test_supported(self):
    assert supported(self.CP)
    assert not supported(None)
    assert not supported(CarInterface.get_non_essential_params(CAR.FORD_BRONCO_SPORT_MK1))

  def test_ac_charge_then_stop(self):
    monitor = ChargingMonitor(self.CP, self.params)
    t = 1000.
    dat = None
    for _ in range(6):  # 3 s at 2 Hz: past the 2 s debounce
      t += 0.5
      dat = self._step(monitor, t, 7)  # ChargingAC
    msg = dat.chargingStateBP
    assert msg.canAlive
    assert msg.charging.charging
    assert msg.charging.chargeType == "ac"
    assert abs(msg.charging.powerKw - 70.) < 0.1
    assert abs(msg.charging.socPercent - 42.) < 0.01
    assert msg.evBattery.dataAvailable
    assert msg.keepAwake
    assert msg.sleepInSeconds == -1.
    assert self.params.get_bool("BPChargingActive")
    last = self.params.get("BPChargeLastActiveTs")
    assert last is not None and t - 3 <= last <= t

    for _ in range(6):
      t += 0.5
      dat = self._step(monitor, t, 13)  # ChargeTargetReached
    msg = dat.chargingStateBP
    assert not msg.charging.charging
    assert msg.charging.state == "targetReached"
    assert not msg.keepAwake
    assert not self.params.get_bool("BPChargingActive")
    assert 0. < msg.sleepInSeconds <= 30 * 60

  def test_no_can(self):
    monitor = ChargingMonitor(self.CP, self.params)
    msg = monitor.step([], 1.).chargingStateBP
    assert not msg.canAlive
    assert not msg.charging.dataAvailable
    assert not msg.charging.charging

  def test_low_volt_top_up_wake(self):
    monitor = ChargingMonitor(self.CP, self.params)
    t, dat = 1000., None
    for _ in range(6):  # ignition off, 12 V support requested, not charging
      t += 0.5
      dat = self._step(monitor, t, 0, lv_support=1, lv_soc=81)
    msg = dat.chargingStateBP
    assert msg.wake.dataAvailable
    assert msg.wake.ignition == "off"
    assert msg.wake.reason == "lowVoltTopUp"
    assert msg.wake.lowVoltSupport and msg.wake.dcdcOn
    assert msg.wake.lowVoltTopUps == 1
    assert not msg.keepAwake
    assert "not a drive" in msg.shutdownReason
    state = self.params.get("BPLvState")
    assert state["topUp"] and abs(state["topUpTs"] - t) <= 2.
    assert msg.lowVoltSource == "can" and abs(msg.lowVoltBattery.socPercent - 81.) < 0.01
    assert abs(msg.lowVoltBattery.voltage - 12.6) < 0.07
    assert abs(msg.harnessVoltage - 12.4) < 0.01

    # the driver starts the truck: the flag clears on the very next tick, no debounce
    t += 0.5
    dat = self._step(monitor, t, 0, ignition=4, lv_support=1, lv_soc=81)
    assert dat.chargingStateBP.wake.reason == "ignitionOn"
    assert not self.params.get("BPLvState")["topUp"]

  def test_charging_is_not_a_top_up(self):
    monitor = ChargingMonitor(self.CP, self.params)
    t, dat = 1000., None
    for _ in range(6):
      t += 0.5
      dat = self._step(monitor, t, 8, lv_support=1)  # DC charging also supports the 12 V
    assert dat.chargingStateBP.wake.reason == "charging"
    assert not self.params.get("BPLvState")["topUp"]

  def test_obd_low_volt_fallback(self):
    obd = log.Event.new_message(obdStateBP={"values": [
      {"shortName": "LvSoc", "value": 74., "unit": "%", "ageS": 3.},
      {"shortName": "LvV", "value": 12.5, "unit": "V", "ageS": 3.},
    ]}).obdStateBP
    monitor = ChargingMonitor(self.CP, self.params)
    msg = self._step(monitor, 1000.5, 0, obd=obd).chargingStateBP
    assert msg.lowVoltSource == "obd"
    assert msg.lowVoltBattery.dataAvailable
    assert abs(msg.lowVoltBattery.socPercent - 74.) < 0.01
    assert self.params.get("BPLvState")["src"] == "obd"

  def test_power_saver_reason(self):
    self.params.put_bool("BPLvSaver", True)
    monitor = ChargingMonitor(self.CP, self.params)
    msg = self._step(monitor, 1000.5, 0).chargingStateBP
    assert msg.powerSaver
    assert "10 min" in msg.shutdownReason
