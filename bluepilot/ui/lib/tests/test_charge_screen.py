from bluepilot.ui.lib.charge_screen import DIM, OFF, ON, ChargePolicy, fmt_minutes, step_minutes
from bluepilot.ui.lib.ev_data import ChargeSession, EvSnapshot


class FakeParams:
  def __init__(self, vals: dict):
    self.vals = vals

  def get(self, key, return_default=False):
    if key not in self.vals:
      raise KeyError(key)  # a key this build doesn't have
    return self.vals[key]


def test_defaults_when_keys_missing():
  p = ChargePolicy.from_params(FakeParams({}))
  assert (p.on_ac_min, p.on_dc_min, p.off_ac_min, p.off_dc_min) == (15, 0, 30, 60)
  assert (p.on_then, p.off_then, p.minimal) == (DIM, OFF, True)


def test_mode_per_ignition_and_charge_type():
  p = ChargePolicy.from_params(FakeParams({"BPChargeOnAcMin": 5, "BPChargeOnDcMin": 0, "BPChargeSleepMin": 10,
                                           "BPChargeOffDcMin": 2, "BPChargeOnThen": 1, "BPChargeOffThen": 0}))
  assert p.mode(True, False, 4 * 60) == ON
  assert p.mode(True, False, 5 * 60) == OFF           # truck on, AC, then off
  assert p.mode(True, True, 10 * 3600) == ON          # truck on, DC: always
  assert p.mode(False, False, 9 * 60) == ON
  assert p.mode(False, False, 10 * 60) == DIM         # truck off, AC, then dim
  assert p.mode(False, True, 2 * 60) == DIM           # truck off, DC uses its own window


def test_steps():
  assert step_minutes(120, 1) == 0 and fmt_minutes(0) == "Always"
  assert step_minutes(0, -1) == 120
  assert step_minutes(1, -1) == 1
  assert step_minutes(45, 1) == 60  # an old odd value snaps onto the list


def snap(charging: bool, source: str) -> EvSnapshot:
  s = EvSnapshot()
  s.charging = charging
  s.charge_status = "chargingAc" if charging else "unknown"
  s.source = source
  return s


def test_session_survives_ignition_handoff():
  cs = ChargeSession()
  t = 0.0
  for _ in range(30):  # 3 s of AC charging, truck on
    cs.update(snap(True, "car"), 0.0, t)
    t += 0.1
  assert cs.active
  start = cs.start_t
  for _ in range(150):  # 15 s with neither carStateBP nor chargingStateBP fresh: ignition off, monitor starting
    cs.update(snap(False, ""), 0.0, t)
    t += 0.1
  assert cs.active and cs.start_t == start
  cs.update(snap(True, "charger"), 0.0, t)
  assert cs.active and cs.start_t == start


def test_session_ends_when_charging_stops_or_truck_moves():
  cs = ChargeSession()
  t = 0.0
  for _ in range(30):
    cs.update(snap(True, "charger"), 0.0, t)
    t += 0.1
  for _ in range(60):  # 6 s of a fresh source saying "not charging"
    cs.update(snap(False, "charger"), 0.0, t)
    t += 0.1
  assert not cs.active
  for _ in range(30):
    cs.update(snap(True, "car"), 0.0, t)
    t += 0.1
  assert cs.active
  cs.update(snap(True, "car"), 2.0, t)
  assert not cs.active
