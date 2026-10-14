"""
How the charging screen behaves once it is up: how long it stays fully on, what it does after that, and whether
it is the minimal dark view. Depends on whether someone is inside and on AC versus DC.

Someone is inside when the truck is on or in accessory mode; with the truck off, nobody is (Lucas, 2026-10-14:
no door, belt or seat mapping).

  someone inside, AC   BPChargeOnAcMin   (default always on), then BPChargeOnThen   (default dim)
  someone inside, DC   BPChargeOnDcMin   (default always on)
  nobody inside,  AC   BPChargeSleepMin  (default 30 min), then BPChargeOffThen  (default off)
  nobody inside,  DC   BPChargeOffDcMin  (default 60 min)
  BPChargeMinimal (default on): with nobody inside, a dark, sparse screen that moves a little every minute

Minutes count from the later of plug-in and the last tap, so a tap gives the full window again. 0 = always on.
"""

from __future__ import annotations

from dataclasses import dataclass

ON, DIM, OFF = "on", "dim", "off"
THEN = (DIM, OFF)                       # BPCharge*Then: 0 dim, 1 off
MINUTE_STEPS = [1, 2, 5, 10, 15, 30, 60, 120, 0]  # 0 = always on
DIM_BRIGHTNESS = 8                      # %, the display's dimmed backlight
OCCUPIED_IGNITION = ("accessory", "run", "start")  # chargingStateBP.wake.ignition values that mean someone is inside


def occupied(ignition: bool, truck_ignition: str = "") -> bool:
  """Someone is inside: the comma is onroad (ignition on), or the truck reports accessory, run or start."""
  return bool(ignition) or truck_ignition in OCCUPIED_IGNITION


@dataclass
class ChargePolicy:
  on_ac_min: int = 0
  on_dc_min: int = 0
  off_ac_min: int = 30
  off_dc_min: int = 60
  on_then: str = DIM
  off_then: str = OFF
  minimal: bool = True

  KEYS = {  # param -> (attribute, default)
    "BPChargeOnAcMin": ("on_ac_min", 0),
    "BPChargeOnDcMin": ("on_dc_min", 0),
    "BPChargeSleepMin": ("off_ac_min", 30),
    "BPChargeOffDcMin": ("off_dc_min", 60),
    "BPChargeOnThen": ("on_then", 0),
    "BPChargeOffThen": ("off_then", 1),
    "BPChargeMinimal": ("minimal", True),
  }

  @classmethod
  def from_params(cls, params) -> ChargePolicy:
    p = cls()
    for key, (attr, default) in cls.KEYS.items():
      try:
        v = params.get(key, return_default=True)
      except Exception:  # key not in this build: keep the default
        v = None
      if v is None:
        v = default
      if attr == "minimal":
        p.minimal = bool(v)
      elif attr.endswith("_then"):
        try:
          setattr(p, attr, THEN[max(0, min(1, int(v)))])
        except (TypeError, ValueError):
          pass
      else:
        try:
          setattr(p, attr, max(0, int(v)))
        except (TypeError, ValueError):
          pass
    return p

  def minutes(self, inside: bool, dc: bool) -> int:
    if inside:
      return self.on_dc_min if dc else self.on_ac_min
    return self.off_dc_min if dc else self.off_ac_min

  def then(self, inside: bool) -> str:
    return self.on_then if inside else self.off_then

  def mode(self, inside: bool, dc: bool, idle_s: float) -> str:
    """ON while inside the window (or always-on), then DIM or OFF. `inside`: see occupied()."""
    m = self.minutes(inside, dc)
    if m <= 0 or idle_s < m * 60:
      return ON
    return self.then(inside)


def fmt_minutes(m: int) -> str:
  if m <= 0:
    return "Always"
  return f"{m} min" if m < 60 else f"{m // 60} h"


def step_minutes(m: int, d: int) -> int:
  """The next value in MINUTE_STEPS (Always sits after the longest)."""
  i = MINUTE_STEPS.index(m) if m in MINUTE_STEPS else min(range(len(MINUTE_STEPS) - 1), key=lambda k: abs(MINUTE_STEPS[k] - m))
  return MINUTE_STEPS[max(0, min(len(MINUTE_STEPS) - 1, i + d))]
