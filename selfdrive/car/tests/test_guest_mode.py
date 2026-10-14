"""Custom: Guest Mode (stream B)."""
import pytest

from cereal import car
from opendbc.car.ford.interface import CarInterface
from opendbc.car.ford.radar_interface import RadarInterface
from opendbc.car.ford.values import CAR
from openpilot.common.params import Params
from openpilot.selfdrive.car.guest_mode import offroad_reset

KEYS = ("BPGuestMode", "BPGuestModeOneTrip", "BPGuestModeActive", "BPGuestModeUsed", "OpenpilotEnabledToggle",
        "BPLockedPlatform", "BPPlatformMismatch")
NO_OUTPUT = car.CarParams.SafetyModel.noOutput


@pytest.fixture
def params():
  p = Params()
  for k in KEYS:
    p.remove(k)
  p.put_bool("OpenpilotEnabledToggle", True)
  return p


def make_car(platform=CAR.FORD_F_150_LIGHTNING_MK1):
  from openpilot.selfdrive.car.card import Car
  CP = CarInterface.get_non_essential_params(platform)
  CI = CarInterface(CP, CarInterface.get_non_essential_params_sp(CP, platform))
  return Car(CI, RadarInterface(CI.CP, CI.CP_SP))


class TestGuestMode:
  def test_normal_drive_controls(self, params):
    c = make_car()
    assert not c.CP.passive
    assert all(cfg.safetyModel != NO_OUTPUT for cfg in c.CP.safetyConfigs)
    assert not params.get_bool("BPGuestModeActive") and not params.get_bool("BPGuestModeUsed")

  def test_guest_drive_is_passive(self, params):
    params.put_bool("BPGuestMode", True)
    c = make_car()
    assert c.CP.passive
    assert [cfg.safetyModel for cfg in c.CP.safetyConfigs] == [NO_OUTPUT]  # relay open, no TX
    assert params.get_bool("BPGuestModeActive") and params.get_bool("BPGuestModeUsed")

  def test_one_trip_reset(self, params):
    params.put_bool("BPGuestMode", True)
    assert not offroad_reset(params)  # enabled offroad, no guest drive yet: stays on
    assert params.get_bool("BPGuestMode")
    make_car()
    assert offroad_reset(params)
    assert not params.get_bool("BPGuestMode") and not params.get_bool("BPGuestModeUsed")
    assert not make_car().CP.passive

  def test_sticky(self, params):
    params.put_bool("BPGuestMode", True)
    params.put_bool("BPGuestModeOneTrip", False)
    make_car()
    assert not offroad_reset(params)
    assert params.get_bool("BPGuestMode") and not params.get_bool("BPGuestModeUsed")
    assert make_car().CP.passive


class TestPlatformLock:
  def test_lightning_controls(self, params):
    assert not make_car().CP.passive
    assert params.get("BPPlatformMismatch") is None

  def test_other_car_stays_passive(self, params):
    c = make_car(CAR.FORD_F_150_MK14)  # e.g. the comma moved to a gas F-150
    assert c.CP.passive
    assert [cfg.safetyModel for cfg in c.CP.safetyConfigs] == [NO_OUTPUT]
    assert params.get("BPPlatformMismatch") == "FORD_F_150_MK14"

  def test_lock_off(self, params):
    params.put("BPLockedPlatform", "")
    assert not make_car(CAR.FORD_F_150_MK14).CP.passive
