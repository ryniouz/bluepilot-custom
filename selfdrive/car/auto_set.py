"""
Custom: Auto set speed (Lucas 2026-10-14 22:42, section 4). Optional, off by default (BPAutoSetSpeed).

When the driver engages cruise with Resume or Set, the set speed moves to the driver's own preferred speed for the
detected limit (BPAutoSetTable: limit km/h -> set km/h, a limit missing from the table keeps the limit itself).
It moves the truck's set speed the same way the driver would: Set+ / Set- presses through the existing ICBM
button path (selfdriveStateSP.intelligentCruiseButtonManagement.sendButton -> carcontroller). Panda safety is
unchanged: ford.h already allows Set+/- from the comma, and only lets Resume through while controls are allowed.

Safeguards:
  - only on the driver's own Resume/Set press that engages cruise; a new limit never changes the speed by itself
  - only with a valid limit right now (not the last one remembered)
  - the target stays within limit - 20 .. limit + 40 km/h (the table editor's range) and within 8..145 km/h
  - stops for good on brake, gas, cancel, disengage, the driver's own Set+/- press, or after GIVE_UP_S
  - the driver can change the speed with the buttons at any time

BPAutoSetActive (runtime): the km/h Auto set put the cruise on, 0 when it isn't holding one, for the speed card.
"""
from __future__ import annotations

import json

from cereal import car, custom
from openpilot.common.constants import CV
from openpilot.common.realtime import DT_CTRL

ButtonType = car.CarState.ButtonEvent.Type
SendButtonState = custom.IntelligentCruiseButtonManagement.SendButtonState

DEFAULT_TABLE = {50: 65, 60: 75, 80: 90, 90: 110, 100: 120}
BELOW_LIMIT_KPH, ABOVE_LIMIT_KPH = 20, 40   # same range as the table editor (Speed and cruise page)
V_MIN_KPH, V_MAX_KPH = 8, 145               # selfdrive/car/cruise.py V_CRUISE_MIN / V_CRUISE_MAX
ENGAGE_WAIT_S = 1.0                         # Resume/Set press -> cruise reports enabled
SETTLE_S = 0.6                              # start pressing after the truck has taken its own set speed
GIVE_UP_S = 15.0
PARAM_REFRESH_S = 2.0
ENGAGE_BUTTONS = (ButtonType.setCruise, ButtonType.resumeCruise)
DRIVER_CHANGE_BUTTONS = (ButtonType.accelCruise, ButtonType.decelCruise, ButtonType.cancel)

IDLE, WAITING, ADJUSTING, HOLDING = "idle", "waiting", "adjusting", "holding"


def parse_table(raw) -> dict[int, int]:
  try:
    data = json.loads(raw) if isinstance(raw, (str, bytes)) and raw.strip() else raw
    table = {int(k): int(v) for k, v in dict(data).items()}
    return table or dict(DEFAULT_TABLE)
  except (TypeError, ValueError, AttributeError):
    return dict(DEFAULT_TABLE)


def target_kph(table: dict[int, int], limit_kph: float) -> int:
  """The preferred set speed for a detected limit, bounded by the safeguards above."""
  limit = int(round(limit_kph))
  want = table.get(limit, limit)
  want = max(limit - BELOW_LIMIT_KPH, min(limit + ABOVE_LIMIT_KPH, want))
  return int(max(V_MIN_KPH, min(V_MAX_KPH, want)))


class AutoSetSpeed:
  def __init__(self, params=None):
    self.params = params
    self.enabled = False
    self.table = dict(DEFAULT_TABLE)
    self.state = IDLE
    self.target = 0             # in the cluster's unit (km/h or mph)
    self.target_kph = 0
    self.t = 0.0
    self.button = SendButtonState.none
    self._param_t = PARAM_REFRESH_S
    self._published = None

  def _refresh_params(self):
    self._param_t += DT_CTRL
    if self.params is None or self._param_t < PARAM_REFRESH_S:
      return
    self._param_t = 0.0
    try:
      self.enabled = bool(self.params.get_bool("BPAutoSetSpeed"))
      self.table = parse_table(self.params.get("BPAutoSetTable", return_default=True))
    except Exception:  # keys missing in this build: stay off
      self.enabled = False

  def _publish(self):
    value = self.target_kph if self.state in (ADJUSTING, HOLDING) else 0
    if value != self._published and self.params is not None:
      try:
        self.params.put_nonblocking("BPAutoSetActive", value)
      except Exception:
        pass
    self._published = value

  def _stop(self):
    self.state, self.target, self.target_kph, self.t = IDLE, 0, 0, 0.0

  def update(self, CS: car.CarState, enabled: bool, limit_ms: float, limit_valid: bool, is_metric: bool) -> int:
    """One selfdrived step (DT_CTRL). Returns the button to send (SendButtonState), none most of the time."""
    self._refresh_params()
    self.button = SendButtonState.none
    pressed = {b.type.raw for b in CS.buttonEvents if b.pressed}
    cruise_on = CS.cruiseState.enabled and enabled
    driver_out = CS.brakePressed or CS.gasPressed or not CS.cruiseState.available

    if not self.enabled:
      self._stop()
    elif self.state == IDLE:
      # the driver's own Resume/Set press while cruise is off, with a limit detected right now
      if not CS.cruiseState.enabled and pressed & set(ENGAGE_BUTTONS) and limit_valid and limit_ms > 0:
        self.target_kph = target_kph(self.table, limit_ms * CV.MS_TO_KPH)
        self.target = self.target_kph if is_metric else int(round(self.target_kph * CV.KPH_TO_MPH))
        self.state, self.t = WAITING, 0.0
    else:
      self.t += DT_CTRL
      if driver_out or (self.state != WAITING and not cruise_on) or pressed & set(DRIVER_CHANGE_BUTTONS):
        self._stop()
      elif self.state == WAITING:
        if cruise_on and self.t >= SETTLE_S:
          self.state, self.t = ADJUSTING, 0.0
        elif self.t >= ENGAGE_WAIT_S + SETTLE_S:
          self._stop()  # the press didn't engage cruise
      elif self.state in (ADJUSTING, HOLDING):
        conv = CV.MS_TO_KPH if is_metric else CV.MS_TO_MPH
        cluster = int(round(CS.cruiseState.speedCluster * conv))
        if cluster <= 0:
          pass
        elif self.state == HOLDING and cluster != self.target:
          self._stop()  # the set speed moved after it got there: the driver's call from here on
        elif cluster < self.target:
          self.state, self.button = ADJUSTING, SendButtonState.increase
        elif cluster > self.target:
          self.state, self.button = ADJUSTING, SendButtonState.decrease
        else:
          self.state, self.t = HOLDING, 0.0
        if self.state == ADJUSTING and self.t >= GIVE_UP_S:  # e.g. the truck won't take that speed
          self._stop()
    self._publish()
    return self.button
