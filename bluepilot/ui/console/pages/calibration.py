"""
Console Calibration page (System > Calibration): how the comma is mounted and how far the
camera and steering calibrations have got, with the reset the stock Device panel offers.

Camera: CalibrationParams (saved) or liveCalibration (while driving): status, progress, and the
mount angle against the allowed range (4° left or right, 5° up, 9° down).
Steering: LiveDelay (steering lag) and LiveTorqueParameters (torque response, when the car uses them).
"""

from __future__ import annotations

import math
import time
from collections.abc import Callable

import pyray as rl

from cereal import log
import cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.lib.theme import Console

GAP = 32
ROW = 84
PITCH_UP, PITCH_DOWN, YAW_MAX = 5.0, 9.0, 4.0
CONFIRM_S = 4.0
READ_EVERY_S = 2.0
Status = log.LiveCalibrationData.Status


def _event(params: Params, key: str):
  try:
    raw = params.get(key)
    return messaging.log_from_bytes(raw, log.Event) if raw else None
  except Exception:
    return None


class CalibrationPage(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._hits: list[tuple[rl.Rectangle, Callable[[], None]]] = []
    self._confirm_until = 0.0
    self._read_at = 0.0
    self._cam = None
    self._lag: float | None = None
    self._torque: float | None = None

  def show_event(self):
    super().show_event()
    self._read_at = 0.0
    self._confirm_until = 0.0

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

  # -- render -------------------------------------------------------------------------------

  def _render(self, rect: rl.Rectangle):
    self._hits = []
    self._refresh()
    left, right = K.split_cols(rect, [1, 1])
    left.width -= GAP / 2
    right.x += GAP / 2
    right.width -= GAP / 2
    self._camera_card(left)
    self._steering_card(right)

  def _title(self, r: rl.Rectangle, ic: str, title: str) -> tuple[float, float, float]:
    D.card(r)
    p = D.CARD_PAD
    x, y = r.x + p, r.y + p
    D.icon(ic, x, y - 2, 44, Console.TEXT_SECONDARY)
    D.text(title, x + 64, y, D.H2, semi=True)
    return x, y + 92, r.x + r.width - p

  def _progress(self, x: float, y: float, w: float, label: str, pct: float | None) -> float:
    D.text(label, x, y, D.BODY, Console.TEXT_MUTED)
    if pct is None:
      D.text_right(tr("Not started"), x + w, y, D.BODY, Console.TEXT_GHOST, semi=True)
      pct = 0.0
    else:
      D.text_right(tr("Done") if pct >= 100 else f"{pct:.0f} %", x + w, y, D.BODY, semi=True)
    y += 56
    K.bar(rl.Rectangle(x, y, w, K.BAR_H), min(1.0, pct / 100.0), Console.SUCCESS if pct >= 100 else Console.ACCENT)
    return y + K.BAR_H + 40

  def _camera_card(self, r: rl.Rectangle):
    x, y, right = self._title(r, "calibrate", tr("Camera"))
    status, pct, pitch, yaw = self.camera()
    if status == Status.calibrated:
      text, color = tr("Calibrated"), Console.SUCCESS
    elif status == Status.invalid:
      text, color = tr("Mount is off: adjust the comma"), Console.DANGER
    elif status == Status.recalibrating:
      text, color = tr("Recalibrating"), Console.ACCENT
    else:
      text, color = tr("Calibrates on the first drive"), Console.TEXT_GHOST
    D.dot(x + 10, y + D.BODY / 2 + 2, 10, color)
    D.text(D.fit(text, D.BODY, r.width - 2 * D.CARD_PAD - 36, semi=True), x + 36, y, D.BODY, semi=True)
    y += 76
    w = right - x
    if status != Status.calibrated:
      y = self._progress(x, y, w, tr("Progress"), pct)
    rows = []
    if pitch is not None and status != Status.uncalibrated:
      limit = PITCH_DOWN if pitch > 0 else PITCH_UP
      rows.append((tr("Tilt"), f"{abs(pitch):.1f}° " + (tr("down") if pitch > 0 else tr("up")), abs(pitch) / limit))
      rows.append((tr("Turn"), f"{abs(yaw):.1f}° " + (tr("left") if yaw > 0 else tr("right")), abs(yaw) / YAW_MAX))
    for label, value, frac in rows:
      K.hline(x, right, y)
      D.text(label, x, y + 24, D.BODY, Console.TEXT_MUTED)
      D.text_right(value, right, y + 24, D.BODY, Console.WARNING if frac > 0.8 else None, semi=True)
      y += ROW
    note = tr("Allowed: up to 4° left or right, 5° up or 9° down.")
    for i, ln in enumerate(D.wrap(note, D.LABEL, w, 2)):
      if y + 24 + i * 40 + D.LABEL < r.y + r.height - D.CARD_PAD:
        D.text(ln, x, y + 24 + i * 40, D.LABEL, Console.TEXT_MUTED)

  def _steering_card(self, r: rl.Rectangle):
    x, y, right = self._title(r, "wheel", tr("Steering"))
    w = right - x
    y = self._progress(x, y, w, tr("Steering lag"), self._lag)
    if self._torque is not None:
      y = self._progress(x, y, w, tr("Torque response"), self._torque)
    for i, ln in enumerate(D.wrap(tr("Calibration keeps learning while you drive. Resetting is rarely needed."), D.LABEL, w, 2)):
      D.text(ln, x, y + i * 40, D.LABEL, Console.TEXT_MUTED)

    b = rl.Rectangle(x, r.y + r.height - D.CARD_PAD - D.CONTROL_H, w, D.CONTROL_H)
    if ui_state.engaged:
      D.button(b, tr("Disengage to reset"), primary=False)
      return
    confirming = time.monotonic() < self._confirm_until
    if confirming:
      rl.draw_rectangle_rounded(b, 0.3, 8, Console.DANGER_FILL)
      D.text_center(tr("Tap again to reset"), b.x + b.width / 2, b.y + (b.height - D.BODY) / 2 - 2, D.BODY,
                    Console.ON_ACCENT, semi=True)
    else:
      D.button(b, tr("Reset calibration"), primary=False)
    self._hits.append((b, self._reset))

  # -- actions ------------------------------------------------------------------------------

  def _reset(self):
    if ui_state.engaged:
      return
    if time.monotonic() >= self._confirm_until:
      self._confirm_until = time.monotonic() + CONFIRM_S
      return
    self._confirm_until = 0.0
    for key in ("CalibrationParams", "LiveTorqueParameters", "LiveParameters", "LiveParametersV2", "LiveDelay"):
      try:
        self._params.remove(key)
      except Exception:
        pass
    self._params.put_bool("OnroadCycleRequested", True)
    self._read_at = 0.0

  def _handle_mouse_release(self, pos) -> bool:
    for r, fn in self._hits:
      if D.hit(r, pos):
        fn()
        return True
    return False
