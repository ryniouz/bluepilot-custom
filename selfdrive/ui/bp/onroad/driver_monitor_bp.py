"""
Console driver-monitoring status (bottom left, bottom right on right-hand drive).

openpilot's pose tracking and active/inactive fade are unchanged (DriverStateRendererSP); the
drawing is reduced to a quiet status chip, Console style: a dot and a word.

  Attentive   success   awareness above 0.6
  Look ahead  warning   awareness above 0.3
  Distracted  danger    below that
  Monitoring  ghost     not engaged
"""

import numpy as np
import pyray as rl

from openpilot.selfdrive.ui.sunnypilot.onroad.driver_state import DriverStateRendererSP
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.console import draw as D
from bluepilot.ui.lib.theme import Console, Onroad, roundness, with_alpha

CHIP_H = 72
CHIP_PAD = 26
DOT_R = 10
LABEL = 30


def _status(awareness: float) -> tuple[str, rl.Color]:
  if not ui_state.engaged:
    return tr("Monitoring"), Console.TEXT_GHOST
  if awareness > 0.6:
    return tr("Attentive"), Console.SUCCESS
  if awareness > 0.3:
    return tr("Look ahead"), Console.WARNING
  return tr("Distracted"), Console.DANGER


class DriverMonitorBP(DriverStateRendererSP):
  def _render(self, rect):
    dm = ui_state.sm["driverMonitoringState"]
    awareness = float(np.clip(getattr(dm, "awarenessStatus", 1.0), 0.0, 1.0))
    word, color = _status(awareness)

    w = CHIP_PAD * 2 + DOT_R * 2 + 16 + D.text_w(word, LABEL, semi=True)
    # Anchored to the corner openpilot uses for the face icon, sitting on its bottom edge
    left = self.position_x - 96 if not self.is_rhd else self.position_x + 96 - w
    chip = rl.Rectangle(left, self.position_y + 96 - CHIP_H, w, CHIP_H)
    rl.draw_rectangle_rounded(chip, roundness(chip, CHIP_H / 2), 12, Onroad.PANEL)
    rl.draw_rectangle_rounded_lines_ex(chip, roundness(chip, CHIP_H / 2), 12, 2, Console.BORDER_DEFAULT)

    a = 1.0 if self.is_active else 0.5
    D.dot(chip.x + CHIP_PAD + DOT_R, chip.y + CHIP_H / 2, DOT_R, with_alpha(color, int(255 * a)))
    D.text(word, chip.x + CHIP_PAD + DOT_R * 2 + 16, chip.y + (CHIP_H - LABEL) / 2 - 2, LABEL,
           Console.TEXT_PRIMARY if ui_state.engaged else Console.TEXT_MUTED, semi=True)
