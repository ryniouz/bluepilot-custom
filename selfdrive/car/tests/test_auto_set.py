from cereal import car, custom
from openpilot.common.constants import CV
from openpilot.selfdrive.car.auto_set import ADJUSTING, HOLDING, IDLE, AutoSetSpeed, parse_table, target_kph

ButtonType = car.CarState.ButtonEvent.Type
Send = custom.IntelligentCruiseButtonManagement.SendButtonState
TABLE = '{"50":65,"60":75,"80":90,"90":110,"100":120}'


class FakeParams:
  def __init__(self, on=True, table=TABLE):
    self.vals = {"BPAutoSetSpeed": on, "BPAutoSetTable": table}
    self.puts = []

  def get_bool(self, k):
    return bool(self.vals[k])

  def get(self, k, return_default=False):
    return self.vals[k]

  def put(self, k, v):
    self.puts.append((k, v))


def cs(enabled=False, set_kph=0., buttons=(), brake=False, gas=False):
  c = car.CarState.new_message()
  c.cruiseState.available = True
  c.cruiseState.enabled = enabled
  c.cruiseState.speedCluster = set_kph * CV.KPH_TO_MS
  c.brakePressed, c.gasPressed = brake, gas
  c.buttonEvents = [car.CarState.ButtonEvent(type=b, pressed=True) for b in buttons]
  return c


LIMIT_90 = 90 * CV.KPH_TO_MS


def engage(a: AutoSetSpeed, set_kph: float, limit=LIMIT_90, valid=True):
  a.update(cs(buttons=(ButtonType.resumeCruise,)), False, limit, valid, True)
  for _ in range(100):
    a.update(cs(True, set_kph), True, limit, valid, True)


def test_table_and_bounds():
  t = parse_table(TABLE)
  assert target_kph(t, 90) == 110 and target_kph(t, 100) == 120
  assert target_kph(t, 70) == 70                     # not in the table: the limit itself
  assert target_kph({50: 200}, 50) == 90             # never more than limit + 40
  assert target_kph({50: 0}, 50) == 30               # never less than limit - 20
  assert target_kph({140: 180}, 140) == 145          # never over 145
  assert parse_table("not json") == parse_table("")  # bad table -> defaults


def test_resume_moves_to_preferred_speed_then_holds():
  p = FakeParams()
  a = AutoSetSpeed(p)
  engage(a, 92)
  assert a.state == ADJUSTING and a.button == Send.increase
  a.update(cs(True, 110), True, LIMIT_90, True, True)
  assert a.state == HOLDING and a.button == Send.none
  assert p.puts[-1] == ("BPAutoSetActive", 110)
  a.update(cs(True, 111), True, LIMIT_90, True, True)  # the driver nudged it: done, no fighting back
  assert a.state == IDLE and a.button == Send.none and p.puts[-1] == ("BPAutoSetActive", 0)


def test_decreases_too():
  a = AutoSetSpeed(FakeParams())
  engage(a, 130)
  assert a.button == Send.decrease


def test_off_or_no_limit_does_nothing():
  a = AutoSetSpeed(FakeParams(on=False))
  engage(a, 92)
  assert a.state == IDLE and a.button == Send.none
  a = AutoSetSpeed(FakeParams())
  engage(a, 92, valid=False)
  assert a.state == IDLE and a.button == Send.none


def test_driver_inputs_cancel_it():
  for kw in ({"brake": True}, {"gas": True}, {"buttons": (ButtonType.decelCruise,)}):
    a = AutoSetSpeed(FakeParams())
    engage(a, 92)
    a.update(cs(True, 95, **kw), True, LIMIT_90, True, True)
    assert a.state == IDLE and a.button == Send.none, kw


def test_limit_change_alone_never_starts_it():
  a = AutoSetSpeed(FakeParams())
  for _ in range(300):  # cruising, no button press, limit appears and changes
    a.update(cs(True, 92), True, LIMIT_90, True, True)
  assert a.state == IDLE and a.button == Send.none
