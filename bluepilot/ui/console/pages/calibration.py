"""
Console Calibration page (System > Calibration).

Until the camera is calibrated it is a set-up wizard: three steps (mount the comma, drive, steering learns),
the current one highlighted, with live progress and the mount angle against its limits. Once calibrated it
becomes a status page: the mount angle as meters of the allowed range, how far steering has learned, and
Recalibrate (the reset the stock Device panel offers, behind a confirm, never while engaged).

Camera: CalibrationParams (saved) or liveCalibration (while driving): status, progress, and the
mount angle against the allowed range (4° left or right, 5° up, 9° down).
Steering: LiveDelay (steering lag) and LiveTorqueParameters (torque response, when the car uses them).
"""

from __future__ import annotations

import math
import time

import pyray as rl

from cereal import log
import cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.console import draw as D
from bluepilot.ui.console.form import Action, Custom, FormPage, Info, Meter, Section
from bluepilot.ui.lib.theme import Console

PITCH_UP, PITCH_DOWN, YAW_MAX = 5.0, 9.0, 4.0
STEP_H = 132
READ_EVERY_S = 2.0
Status = log.LiveCalibrationData.Status


def _event(params: Params, key: str):
  try:
    raw = params.get(key)
    return messaging.log_from_bytes(raw, log.Event) if raw else None
  except Exception:
    return None


class CalibrationPage(FormPage):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._read_at = 0.0
    self._cam = None
    self._lag: float | None = None
    self._torque: float | None = None

  def show_event(self):
    super().show_event()
    self._read_at = 0.0

  # -- data ---------------------------------------------------------------------------------

  def _refresh(self):
    now = time.monotonic()
    if now - self._read_at < READ_EVERY_S:
      return
    self._read_at = now
    ev = _event(self._params, "CalibrationParams")
    self._cam = ev.liveCalibration if ev is not None else None
    ev = _event(self._params, "LiveDelay")
    self._lag = float(ev.liveDelay.calPerc) if ev is not None else None
    ev = _event(self._params, "LiveTorqueParameters")
    self._torque = float(ev.liveTorqueParameters.calPerc) if ev is not None and ev.liveTorqueParameters.useParams else None

  def camera(self):
    """(status, percent, pitch°, yaw°) from the live message while driving, else the saved one."""
    cal = None
    try:
      if ui_state.started and ui_state.sm.valid["liveCalibration"]:
        cal = ui_state.sm["liveCalibration"]
    except Exception:
      cal = None
    cal = cal or self._cam
    if cal is None:
      return Status.uncalibrated, 0.0, None, None
    rpy = list(cal.rpyCalib)
    pitch = math.degrees(rpy[1]) if len(rpy) == 3 else None
    yaw = math.degrees(rpy[2]) if len(rpy) == 3 else None
    return cal.calStatus, float(cal.calPerc), pitch, yaw

  # -- sections -----------------------------------------------------------------------------

  def sections(self) -> list[Section]:
    self._refresh()
    status, pct, pitch, yaw = self.camera()
    if status == Status.calibrated:
      return self._status_view(pitch, yaw)
    return self._wizard(status, pct, pitch, yaw)

  def _angle_rows(self, pitch, yaw) -> list:
    if pitch is None or yaw is None:
      return []
    limit = PITCH_DOWN if pitch > 0 else PITCH_UP
    tilt, turn = abs(pitch) / limit, abs(yaw) / YAW_MAX

    def col(f):
      return Console.DANGER if f > 1 else (Console.WARNING if f > 0.8 else Console.SUCCESS)
    return [
      Meter(tr("Tilt") + " (" + tr("limit") + f" {limit:.0f}°)", f"{abs(pitch):.1f}° " + (tr("down") if pitch > 0 else tr("up")),
            min(1.0, tilt), col(tilt)),
      Meter(tr("Turn") + " (" + tr("limit") + f" {YAW_MAX:.0f}°)", f"{abs(yaw):.1f}° " + (tr("left") if yaw > 0 else tr("right")),
            min(1.0, turn), col(turn)),
    ]

  def _wizard(self, status, pct, pitch, yaw) -> list[Section]:
    invalid = status == Status.invalid
    lag = self._lag or 0.0
    if invalid:
      current = 0
    elif pct < 100:
      current = 1
    else:
      current = 2
    steps = [
      (tr("Mount the comma"), tr("Centred high on the windshield, level, behind the mirror") if not invalid
       else tr("It's tilted or turned too far. Adjust the mount, then drive again.")),
      (tr("Drive"), tr("Straight roads above 15 km/h. Usually a few minutes.") + (f"  {pct:.0f} %" if current == 1 and pct > 0 else "")),
      (tr("Steering learns"), tr("Happens while you drive; driver assist works meanwhile.") + (f"  {lag:.0f} %" if current == 2 and lag > 0 else "")),
    ]

    def tracker(r: rl.Rectangle):
      y = r.y
      for i, (title, sub) in enumerate(steps):
        done = i < current
        on = i == current
        cx, cy = r.x + 32, y + 40
        if i < len(steps) - 1:
          rl.draw_rectangle_rec(rl.Rectangle(cx - 2, cy + 32, 4, STEP_H - 64), Console.SUCCESS if done else Console.BG_TRACK)
        fill = Console.DANGER if on and invalid else (Console.SUCCESS if done else (Console.ACCENT if on else Console.BG_RAISED))
        rl.draw_circle(int(cx), int(cy), 30, fill)
        if done:
          D.icon("check", cx - 18, cy - 18, 36, Console.ON_ACCENT)
        else:
          D.text_center(str(i + 1), cx, cy - D.LABEL / 2 - 2, D.LABEL, Console.ON_ACCENT if on else Console.TEXT_MUTED, semi=True)
        D.text(title, r.x + 96, y + 10, D.BODY, Console.TEXT_PRIMARY if on or done else Console.TEXT_MUTED, semi=True)
        for j, ln in enumerate(D.wrap(sub, D.LABEL, r.width - 96, 2)):
          D.text(ln, r.x + 96, y + 56 + j * 36, D.LABEL, Console.DANGER if on and invalid else Console.TEXT_MUTED)
        y += STEP_H
      return None

    setup: list = [Custom(STEP_H * len(steps), tracker)]
    if current >= 1 and not invalid:
      setup.append(Meter(tr("Camera"), f"{pct:.0f} %", pct / 100.0))
    if current == 2:
      setup.append(Meter(tr("Steering"), f"{lag:.0f} %", lag / 100.0))
    title = tr("Recalibrating") if status == Status.recalibrating else tr("Set up calibration")
    sections = [Section(title, "calibrate", setup,
                        note=tr("Calibration runs by itself while you drive. Driver assist turns on once step 2 is done."),
                        wide=True)]
    angles = self._angle_rows(pitch, yaw)
    if angles:
      sections.append(Section(tr("Mount angle"), "eye", angles,
                              note=tr("Allowed: up to 4° left or right, 5° up or 9° down."), wide=True))
    return sections

  def _status_view(self, pitch, yaw) -> list[Section]:
    camera: list = [Info(tr("Status"), tr("Calibrated"), dot=Console.SUCCESS)] + self._angle_rows(pitch, yaw)
    steering: list = []
    if self._lag is not None:
      steering.append(Meter(tr("Steering lag"), tr("Learned") if self._lag >= 100 else f"{self._lag:.0f} %",
                            min(1.0, self._lag / 100.0), Console.SUCCESS if self._lag >= 100 else Console.ACCENT))
    if self._torque is not None:
      steering.append(Meter(tr("Torque response"), tr("Learned") if self._torque >= 100 else f"{self._torque:.0f} %",
                            min(1.0, self._torque / 100.0), Console.SUCCESS if self._torque >= 100 else Console.ACCENT))
    if not steering:
      steering.append(Info(tr("Steering"), tr("Learns on the next drive")))
    engaged = ui_state.engaged
    return [
      Section(tr("Camera"), "calibrate", camera),
      Section(tr("Steering"), "wheel", steering, note=tr("Keeps learning while you drive."), adv=True),
      Section(tr("Recalibrate"), "close", [
        Action(tr("Reset calibration"), tr("Disengage first") if engaged else tr("After moving the comma or the mount"),
               tr("Reset"), self._ask_reset, danger=True, enabled=not engaged),
      ], note=tr("Resetting is rarely needed. The comma calibrates again on the next drive.")),
    ]

  # -- actions ------------------------------------------------------------------------------

  def _ask_reset(self):
    self.confirm(tr("Reset calibration?"),
                 tr("Driver assist stays off until the comma has recalibrated, over the first few minutes of the next drive."),
                 tr("Reset"), self._reset, danger=True)

  def _reset(self):
    if ui_state.engaged:
      return
    for key in ("CalibrationParams", "LiveTorqueParameters", "LiveParameters", "LiveParametersV2", "LiveDelay"):
      try:
        self._params.remove(key)
      except Exception:
        pass
    self._params.put_bool("OnroadCycleRequested", True)
    self._read_at = 0.0
