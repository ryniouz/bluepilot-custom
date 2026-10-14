"""
Drive settings: Assist, Speed and cruise, and Steering, built from the Console form components (form.py).

They replace the openpilot Toggles panel, sunnypilot's Steering and Cruise panels (with their MADS, lane change,
speed limit and source sub-pages) and the driving rows of the BluePilot tuning panel. Every row writes the same
param as the panel it replaces, with the same availability rules (offroad only, needs openpilot longitudinal
or ICBM, restart when the truck is on). The Lightning steers by curvature, so sunnypilot's torque and NNLC rows
are left out, as before.

7.0 renamed the BluePilot lateral tuning keys with a _curv suffix; DrivePage.key() picks whichever this build has,
and rows whose key exists in neither form are left out.
"""

from __future__ import annotations

from collections.abc import Callable

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.console.form import Choice, FormPage, Note, Section, Stepper, Toggle

MPH_TO_KPH = 1.609344

PERSONALITY_LABELS = ["Relaxed", "Standard", "Close"]  # same labels and order as Home and quick controls
PERSONALITY_VALUES = [2, 1, 0]                         # LongitudinalPersonality: 0 aggressive, 1 standard, 2 relaxed


def speed_unit() -> str:
  return tr("km/h") if ui_state.is_metric else tr("mph")


class DrivePage(FormPage):
  def __init__(self, params: Params | None = None):
    super().__init__(params)
    self._known: dict[str, bool] = {}

  # -- params --
  def has(self, key: str) -> bool:
    if key not in self._known:
      self._known[key] = self.p.has(key)
    return self._known[key]

  def key(self, *names: str) -> str | None:
    """The first of names (or name + "_curv", the 7.0 spelling) that exists in this build."""
    for n in names:
      for k in (n, n + "_curv"):
        if self.has(k):
          return k
    return None

  def remove(self, key: str) -> None:
    try:
      if self.has(key) and self.p.get(key) not in (None, False, "0", 0):
        Params().remove(key)
        self.p.invalidate()
    except Exception:
      pass

  # -- row builders; None when the param is missing, which FormPage skips --
  def toggle(self, key: str | None, title: str, sub: str, enabled: bool = True, invert: bool = False,
             restart: bool = False, after: Callable[[bool], None] | None = None) -> Toggle | None:
    if key is None or not self.has(key):
      return None
    try:
      locked = self.has(key + "Lock") and self.p.bool(key + "Lock")
    except Exception:
      locked = False
    on = self.p.bool(key) != invert

    def flip():
      new = not self.p.bool(key)
      self.p.put(key, new)
      if restart:
        self.p.put("OnroadCycleRequested", True)
      if after is not None:
        after(new != invert)
    return Toggle(title, sub, on, flip, enabled=enabled and not locked)

  def stepper(self, key: str | None, title: str, lo: float, hi: float, step: float, fmt: Callable[[float], str],
              sub: str = "", default: float = 0.0, as_float: bool = False, enabled: bool = True) -> Stepper | None:
    if key is None or not self.has(key):
      return None
    v = self.p.float(key, default)

    def put(d: float):
      nv = max(lo, min(hi, round((self.p.float(key, default) + d) / step) * step))
      self.p.put(key, round(nv, 4) if as_float else int(round(nv)))
    return Stepper(title, fmt(v), lambda: put(-step), lambda: put(step), sub=sub, enabled=enabled)


# -- Assist ---------------------------------------------------------------------------------------

class AssistPage(DrivePage):
  def sections(self):
    cp = ui_state.CP
    long = ui_state.has_longitudinal_control
    engaged = ui_state.engaged
    exp_ok = cp is None or long
    if cp is not None and not long:
      self.remove("ExperimentalMode")

    if exp_ok:
      exp_sub = tr("Model drives the gas and brakes")
    elif cp.alphaLongitudinalAvailable:
      exp_sub = tr("Turn on longitudinal control first")
    else:
      exp_sub = tr("Not with the truck's own cruise")

    exp = self.toggle("ExperimentalMode", tr("Experimental mode"), exp_sub, enabled=exp_ok)
    if exp is not None and exp_ok:
      exp.fn = self._experimental

    restart_note = tr("Changing these restarts assist if the truck is on, so they're locked while engaged.")
    return [
      Section(tr("Main switches"), "wheel", [
        self.toggle("OpenpilotEnabledToggle", tr("Driver assistance"), tr("Steering and cruise help"),
                    enabled=not engaged, restart=True),
        exp,
        self.toggle("DisengageOnAccelerator", tr("Gas pedal turns assist off"), tr("Otherwise it pauses")),
      ], note=tr("Keep your eyes on the road and hands ready at all times.")),
      Section(tr("Warnings"), "bell", [
        self.toggle("IsLdwEnabled", tr("Lane departure warning"), tr("Drifting over a line above 50 km/h")),
        self.toggle("send_hands_free_cluster_msg", tr("Hands-free icon on the dash"), tr("Shown in the gauge cluster")),
      ]),
      Section(tr("Driver camera and microphone"), "eye", [
        self.toggle("AlwaysOnDM", tr("Always watch the driver"), tr("Even when assist is off")),
        self.toggle("RecordFront", tr("Record the driver camera"), tr("Uploaded with your drives"),
                    enabled=not engaged, restart=True),
        self.toggle("RecordAudio", tr("Record the microphone"), tr("Added to the dashcam video"),
                    enabled=not engaged, restart=True),
      ], note=restart_note),
    ]

  def _experimental(self):
    p = self.p
    if p.bool("ExperimentalMode"):
      p.put("ExperimentalMode", False)
    elif p.bool("ExperimentalModeConfirmed"):
      p.put("ExperimentalMode", True)
    else:
      def ok():
        p.put("ExperimentalMode", True)
        p.put("ExperimentalModeConfirmed", True)
      self.confirm(tr("Turn on experimental mode?"),
                   tr("The driving model controls the gas and brakes and can stop for red lights and stop signs. " +
                      "Your set speed becomes the upper limit. This is alpha quality, so expect mistakes and be ready " +
                      "to take over. At low speed the view switches to the wide camera."),
                   tr("Turn on"), ok)


# -- Speed and cruise -----------------------------------------------------------------------------

LIMIT_MODES = ["Off", "Show", "Warn", "Assist"]
LIMIT_MODE_NOTES = [
  "Speed limits are not used.",
  "Shows the current road's speed limit.",
  "Shows the limit and warns when you're over it.",
  "Cruise +/- jumps to the speed limit (plus your offset).",
]
LIMIT_SOURCES = ["Car only", "Map only", "Car first", "Map first", "Combined"]
LIMIT_SOURCE_SUBS = [
  "Signs the truck's camera reads",
  "From OpenStreetMap",
  "Map when the truck has no limit",
  "Truck when the map has no limit",
  "Both together",
]


class SpeedPage(DrivePage):
  def sections(self):
    p = self.p
    cp = ui_state.CP
    csp = getattr(ui_state, "CP_SP", None)
    known = cp is not None and csp is not None
    long = ui_state.has_longitudinal_control
    icbm = bool(getattr(ui_state, "has_icbm", False))
    offroad = ui_state.is_offroad()
    unit = speed_unit()

    # same availability rules as sunnypilot's cruise and speed limit panels
    icbm_ok = known and csp.intelligentCruiseButtonManagementAvailable and not long
    if known and not icbm_ok:
      self.remove("IntelligentCruiseButtonManagement")
    if known and not (long or icbm):
      for k in ("CustomAccIncrementsEnabled", "DynamicExperimentalControl", "SmartCruiseControlVision", "SmartCruiseControlMap"):
        self.remove(k)
    dec_ok = long if known else True
    scc_ok = (long or icbm) if known else True
    acc_ok = known and ((long and not cp.pcmCruise) or icbm) and offroad
    sla_ok = known and (long or icbm) and cp.brand != "rivian" and not (cp.brand == "tesla" and getattr(ui_state, "is_sp_release", False))
    mode = p.int("SpeedLimitMode", 1)
    if known and not sla_ok and mode == 3:
      p.put("SpeedLimitMode", 2)
      mode = 2

    if not known:
      icbm_sub = tr("Start the truck to check")
    elif icbm_ok:
      icbm_sub = tr("Presses the cruise buttons (alpha)") if offroad else tr("Change it with the truck off")
    else:
      icbm_sub = tr("Not with longitudinal control on")

    pers = p.int("LongitudinalPersonality", 1)
    pers_i = PERSONALITY_VALUES.index(pers) if pers in PERSONALITY_VALUES else 1
    following = Section(tr("Following"), "gauge", [
      Choice(tr("Distance to the car ahead"), [tr(x) for x in PERSONALITY_LABELS], pers_i,
             lambda i: p.put("LongitudinalPersonality", PERSONALITY_VALUES[i]), enabled=cp is None or long),
    ], note=tr("The distance button on the wheel cycles this too.") if cp is None or long
       else tr("Needs openpilot longitudinal control."))

    acc_on = p.bool("CustomAccIncrementsEnabled")
    cruise = Section(tr("Cruise control"), "pulse", [
      self.toggle("IntelligentCruiseButtonManagement", tr("Cruise button control"), icbm_sub, enabled=icbm_ok and offroad),
      self.toggle("DynamicExperimentalControl", tr("Auto experimental mode"), tr("The model decides when"),
                  enabled=dec_ok),
      self.toggle("SmartCruiseControlVision", tr("Slow down for curves"), tr("From the camera's view ahead"), enabled=scc_ok),
      self.toggle("SmartCruiseControlMap", tr("Slow down for map curves"), tr("From map data ahead"), enabled=scc_ok),
      self.toggle("CustomAccIncrementsEnabled", tr("Custom set-speed steps"),
                  tr("Change it with the truck off") if known and not offroad else
                  tr("Start the truck to check") if not known else tr("For the cruise +/- buttons"), enabled=acc_ok),
      self.stepper("CustomAccShortPressIncrement", tr("Short press"), 1, 10, 1, lambda v: f"{int(v)} {unit}",
                   default=1, enabled=acc_ok) if acc_on else None,
      Choice(tr("Long press"), [f"1 {unit}", f"5 {unit}", f"10 {unit}"],
             {1: 0, 5: 1, 10: 2}.get(p.int("CustomAccLongPressIncrement", 5), 1),
             p.setter("CustomAccLongPressIncrement", [1, 5, 10]), enabled=acc_ok)
      if acc_on and self.has("CustomAccLongPressIncrement") else None,
      Choice(tr("Speed shown in"), [tr("km/h"), tr("mph")], 0 if p.bool("IsMetric") else 1,
             lambda i: p.put("IsMetric", i == 0)) if self.has("IsMetric") else None,
    ])

    offset_type = p.int("SpeedLimitOffsetType", 0)
    src = p.int("SpeedLimitPolicy", 3)
    limits = Section(tr("Speed limits"), "warning", [
      Choice(tr("Speed limit"), [tr(x) for x in LIMIT_MODES], mode,
             lambda i: (i != 3 or sla_ok) and p.put("SpeedLimitMode", i)) if self.has("SpeedLimitMode") else None,
      Note(tr(LIMIT_MODE_NOTES[max(0, min(3, mode))]) + ("" if sla_ok else " " + tr("Assist needs longitudinal control or cruise button control."))),
      Choice(tr("Offset"), [tr("None"), tr("Fixed"), tr("Percent")], max(0, min(2, offset_type)),
             p.setter("SpeedLimitOffsetType"), enabled=mode != 0) if self.has("SpeedLimitOffsetType") else None,
      self.stepper("SpeedLimitValueOffset", tr("Offset amount"), -30, 30, 1,
                   lambda v: f"{int(v):+d} %" if offset_type == 2 else f"{int(v):+d} {unit}",
                   enabled=mode != 0) if offset_type != 0 else None,
    ])
    source = Section(tr("Where limits come from"), "map", [
      Choice(tr("Source"), [tr(x) for x in LIMIT_SOURCES], max(0, min(4, src)), p.setter("SpeedLimitPolicy"),
             subs=[tr(x) for x in LIMIT_SOURCE_SUBS], enabled=mode != 0) if self.has("SpeedLimitPolicy") else None,
    ])
    tuning = Section(tr("Speed control tuning"), "tune", [
      self.toggle("disable_BP_long_UI", tr("Smooth speed control"), tr("Gentle coasting and braking"), invert=True),
      self.toggle("disable_downhill_comp_UI", tr("Downhill compensation"), tr("Adjusts for the slope"), invert=True),
    ], note=tr("Turning smooth speed control off uses the stock openpilot longitudinal logic."))
    return [following, limits, cruise, source, tuning]


# -- Steering -------------------------------------------------------------------------------------

BRAKE_MODES = ["Keep steering", "Pause", "Turn off"]   # MadsSteeringMode 0 remain active, 1 pause, 2 disengage
LC_DELAYS = ["None", "0.5 s", "1 s", "2 s", "3 s"]     # AutoLaneChangeTimer 1..5 (nudgeless, 0.5, 1, 2, 3 s)


class SteeringPage(DrivePage):
  def sections(self):
    p = self.p
    cp = ui_state.CP
    offroad = ui_state.is_offroad()
    unit = speed_unit()

    mads_on = p.bool("Mads")
    mads = Section(tr("Lane centring"), "steer", [
      self.toggle("Mads", tr("Steering without cruise"), tr("Lane centring on its own (MADS)") if offroad
                  else tr("Change it with the truck off"), enabled=offroad),
      self.toggle("MadsMainCruiseAllowed", tr("Main cruise button toggles it"), tr("Besides the lane keeping button"),
                  enabled=offroad) if mads_on else None,
      self.toggle("MadsUnifiedEngagementMode", tr("Engage it with cruise"), tr("Setting cruise turns steering on"),
                  enabled=offroad) if mads_on else None,
      Choice(tr("When you brake"), [tr(x) for x in BRAKE_MODES], max(0, min(2, p.int("MadsSteeringMode", 0))),
             p.setter("MadsSteeringMode"), enabled=offroad) if mads_on and self.has("MadsSteeringMode") else None,
    ], note=tr("Once on with cruise, steering stays on until you press the lane keeping button or turn the truck off.")
       if mads_on else "")

    timer = p.int("AutoLaneChangeTimer", 0)
    bsm = bool(cp is not None and cp.enableBsm)
    if cp is not None and not bsm:
      self.remove("AutoLaneChangeBsmDelay")

    def set_lc(i: int):
      p.put("AutoLaneChangeTimer", (-1, 0, max(1, timer))[i])

    lc = Section(tr("Lane changes"), "route", [
      Choice(tr("Change lanes when you signal"), [tr("Off"), tr("Nudge wheel"), tr("Automatic")],
             0 if timer < 0 else 1 if timer == 0 else 2, set_lc) if self.has("AutoLaneChangeTimer") else None,
      Choice(tr("Wait after signalling"), [tr(x) for x in LC_DELAYS], max(0, min(4, timer - 1)),
             lambda i: p.put("AutoLaneChangeTimer", i + 1), radio=False) if timer >= 1 else None,
      self.toggle("AutoLaneChangeBsmDelay", tr("Wait for a clear blind spot"),
                  tr("Needs automatic lane change") if bsm else tr("Needs blind spot monitoring"), enabled=bsm and timer > 0),
      self.stepper(self.key("lane_change_factor_high"), tr("Lane change pace"), 0.5, 1.0, 0.05,
                   lambda v: f"{int(round(v * 100))} %", sub=tr("At highway speed"), default=0.85, as_float=True),
    ], note=tr("Only signal when traffic and the road allow it."))

    pause_lat = p.bool("BlinkerPauseLateralControl")
    pause_lc = p.bool("BlinkerPauseLaneChange")
    turn = p.bool("LaneTurnDesire")
    lt_v = p.float("LaneTurnValue", 19.0)
    signal = Section(tr("Turn signal at low speed"), "car", [
      self.toggle("BlinkerPauseLateralControl", tr("Pause steering"), tr("Lets you make the turn yourself")),
      self.toggle("BlinkerPauseLaneChange", tr("No lane change"), tr("The signal means a turn, not a lane change")),
      self.stepper("BlinkerMinLateralControlSpeed", tr("Below"), 0, 255, 5, lambda v: f"{int(v)} {unit}", default=20)
      if pause_lat or pause_lc else None,
      self.stepper("BlinkerLateralReengageDelay", tr("Resume after the signal"), 0, 10, 1, lambda v: f"{int(v)} s")
      if pause_lat or pause_lc else None,
      self.toggle("LaneTurnDesire", tr("Plan the turn you signal"), tr("At a stop or crawling, e.g. red lights")),
      Stepper(tr("Plan turns up to"), self._lane_turn_label(lt_v), lambda: self._lane_turn_step(-1), lambda: self._lane_turn_step(1))
      if turn and self.has("LaneTurnValue") else None,
    ])

    lp_key = self.key("enable_lane_positioning")
    lp_on = lp_key is not None and p.bool(lp_key)
    position = Section(tr("Position in the lane"), "layout", [
      self.toggle(lp_key, tr("Offset in the lane"), tr("Sit off-centre on purpose")),
      self.stepper(self.key("custom_path_offset"), tr("Offset"), -0.5, 0.5, 0.05, lambda v: f"{v:+.2f} m",
                   as_float=True) if lp_on else None,
      self.toggle(self.key("enable_lane_full_mode"), tr("Follow lane lines"), tr("Blend the lines into the offset"))
      if lp_on else None,
    ])

    custom = p.bool(self.key("custom_profile") or "custom_profile")
    gain_key = self.key("LC_PID_gain_UI")
    gain_hi, gain_step = (50.0, 0.5) if gain_key and gain_key.endswith("_curv") else (5.0, 0.1)
    live = p.bool("LagdToggle")
    tuning = Section(tr("Steering tuning"), "tune", [
      self.toggle(self.key("disable_BP_lat_UI"), tr("Smooth steering control"), tr("Off uses stock curvature control"),
                  invert=True),
      self.toggle(self.key("enable_human_turn_detection"), tr("Notice your own turns"), tr("Eases off while you steer")),
      self.toggle("LagdToggle", tr("Learn the steering delay"), self._delay_sub(live)),
      self.stepper("LagdToggleDelay", tr("Software delay"), 0.05, 0.5, 0.01, lambda v: f"{v:.2f} s", default=0.2,
                   as_float=True) if not live else None,
      self.toggle(self.key("custom_profile"), tr("Custom tuning"), tr("Use the values below")),
      self.stepper(self.key("pc_blend_ratio_high_C_UI"), tr("Curve blend, sharp"), 0, 1, 0.05, lambda v: f"{v:.2f}",
                   default=0.4, as_float=True) if custom else None,
      self.stepper(self.key("pc_blend_ratio_low_C_UI"), tr("Curve blend, gentle"), 0, 1, 0.05, lambda v: f"{v:.2f}",
                   default=0.4, as_float=True) if custom else None,
      self.stepper(gain_key, tr("Gentle curve gain"), 0, gain_hi, gain_step, lambda v: f"{v:.1f}", default=3.0,
                   as_float=True) if custom else None,
    ])
    return [mads, lc, signal, position, tuning]

  def _delay_sub(self, live: bool) -> str:
    try:
      d = ui_state.sm['liveDelay'].lateralDelay if live else 0.0
      if live and d > 0:
        return tr("Now") + f" {d:.3f} s"
      if not live and ui_state.CP is not None:
        return tr("Fixed") + f" {ui_state.CP.steerActuatorDelay + self.p.float('LagdToggleDelay', 0.2):.2f} s"
    except Exception:
      pass
    return tr("Adapts to the truck's response")

  # LaneTurnValue is stored in mph (5 - 20); shown and stepped in km/h when metric
  def _lane_turn_label(self, mph: float) -> str:
    return f"{int(round(mph * MPH_TO_KPH))} km/h" if ui_state.is_metric else f"{int(round(mph))} mph"

  def _lane_turn_step(self, d: int):
    mph = self.p.float("LaneTurnValue", 19.0)
    if ui_state.is_metric:
      mph = (round(mph * MPH_TO_KPH) + d) / MPH_TO_KPH
    else:
      mph = round(mph) + d
    self.p.put("LaneTurnValue", round(max(5.0, min(20.0, mph)), 3))
