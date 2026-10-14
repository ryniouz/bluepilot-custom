"""
Custom: 12 V power management for the F-150 Lightning (stream B).

Shared by the offroad charging monitor (which reads the truck's CAN and writes BPLvState) and
system/hardware/power_monitoring.py + hardwared.py (which decide when to go onroad and when to power down).

The Lightning has no engine to charge its 12 V battery. While it sleeps it wakes on its own every so often,
turns on the HV-to-12 V converter for a while to top the 12 V battery up, and goes back to sleep. On CAN that
looks like: Ignition_Status = Off, ULoBattSpprtSustn_B_Rq = 1, not charging. Such a wake is not a drive, so:
  - it must not start onroad mode (hardwared), even if the comma's ignition line comes up with it
  - it must not keep the comma awake: a comma booted by a top-up wake powers down soon after the wake ends

Nothing here sends anything on the bus.
"""
from dataclasses import dataclass

LV_STATE_KEY = "BPLvState"
TOP_UP_FRESH_S = 5.       # the monitor refreshes topUpTs every 2 s while a top-up wake lasts
SOC_FRESH_S = 180.        # the monitor refreshes the 12 V reading every 30 s
TOP_UP_SLEEP_S = 120.     # a comma booted by a top-up wake powers down this long after the wake ends
SAVER_MIN_VOLTS = 12.2    # power saver raises the 12 V cutoff to at least this (about half charge at rest)
SAVER_MIN_SOC = 60        # and the 12 V SOC cutoff to at least this


@dataclass(frozen=True)
class LvSettings:
  saver: bool = False
  saver_offroad_min: int = 10
  shutdown_soc: int = 0       # 0 = no SOC cutoff
  wake_filter: bool = True
  vbatt_cutoff: float = 11.8  # vbatt_pause_charging

  @property
  def volts_cutoff(self) -> float:
    return max(self.vbatt_cutoff, SAVER_MIN_VOLTS) if self.saver else self.vbatt_cutoff

  @property
  def soc_cutoff(self) -> int:
    return max(self.shutdown_soc, SAVER_MIN_SOC) if self.saver else self.shutdown_soc

  @property
  def saver_offroad_s(self) -> float | None:
    """Offroad time limit from power saver, or None when power saver is off."""
    return 60. * max(1, self.saver_offroad_min) if self.saver else None


def _num(params, key, default):
  try:
    val = params.get(key, return_default=True)
    return default if val is None else type(default)(val)
  except Exception:
    return default


def read_settings(params) -> LvSettings:
  return LvSettings(
    saver=bool(_num(params, "BPLvSaver", False)),
    saver_offroad_min=_num(params, "BPLvSaverOffroadMin", 10),
    shutdown_soc=_num(params, "BPLvShutdownSoc", 0),
    wake_filter=bool(_num(params, "BPLvWakeFilter", True)),
    vbatt_cutoff=_num(params, "vbatt_pause_charging", 11.8),
  )


def read_state(params) -> dict:
  try:
    state = params.get(LV_STATE_KEY)
  except Exception:
    return {}
  return state if isinstance(state, dict) else {}


def top_up_active(state: dict, now: float) -> bool:
  """A 12 V top-up wake was reported within the last TOP_UP_FRESH_S. A dead monitor never blocks: the flag goes stale."""
  ts = state.get("topUpTs")
  return bool(state.get("topUp")) and ts is not None and 0. <= now - float(ts) < TOP_UP_FRESH_S


def fresh_soc(state: dict, now: float) -> float | None:
  ts, soc = state.get("ts"), state.get("soc")
  if ts is None or soc is None or not (0. <= now - float(ts) < SOC_FRESH_S):
    return None
  soc = float(soc)
  return soc if 0. < soc <= 100. else None


def soc_below_cutoff(settings: LvSettings, state: dict, now: float) -> bool:
  soc = fresh_soc(state, now)
  return settings.soc_cutoff > 0 and soc is not None and soc < settings.soc_cutoff
