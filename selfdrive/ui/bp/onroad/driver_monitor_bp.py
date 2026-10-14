"""
Console driver-monitoring status (bottom left, bottom right on right-hand drive).

openpilot's pose tracking and active/inactive fade are unchanged (DriverStateRendererSP); the
drawing is reduced to a quiet status chip, Console style: a dot and a word.

  Attentive   success   awareness above 0.6
  Look ahead  warning   awareness above 0.3
  Distracted  danger    below that
  Monitoring  ghost     not engaged

Model confidence sits in the same chip, after a hairline: a short squared bar in the confidence
zone colour, so everything about "is this going well" is read in one place.
"""

from collections.abc import Callable

import numpy as np
import pyray as rl

from openpilot.selfdrive.ui.sunnypilot.onroad.driver_state import DriverStateRendererSP
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.lib.theme import Console, Onroad, roundness, with_alpha

CHIP_H = 72
CHIP_PAD = 26
DOT_R = 10
LABEL = 30
DIVIDER_GAP = 22
CONF_W = 96                # confidence bar
CONF_H = 20


def _status(awareness: float) -> tuple[str, rl.Color]:
  if not ui_state.engaged:
    return tr("Monitoring"), Console.TEXT_GHOST
  if awareness > 0.6:
    return tr("Attentive"), Console.SUCCESS
  if awareness > 0.3:
    return tr("Look ahead"), Console.WARNING
  return tr("Distracted"), Console.DANGER


class DriverMonitorBP(DriverStateRendererSP):
  def __init__(self):
    super().__init__()
    # () -> (fraction 0..1, zone colour or None); set by the road view when confidence is shown
    self.confidence: Callable[[], tuple[float, rl.Color | None]] | None = None

  def _render(self, rect):
    dm = ui_state.sm["driverMonitoringState"]
    awareness = float(np.clip(getattr(dm, "awarenessStatus", 1.0), 0.0, 1.0))
    word, color = _status(awareness)

    word_w = D.text_w(word, LABEL, semi=True)
    w = CHIP_PAD * 2 + DOT_R * 2 + 16 + word_w
    conf = self.confidence() if self.confidence is not None else None
    if conf is not None:
      w += DIVIDER_GAP * 2 + 2 + CONF_W
    # Anchored to the corner openpilot uses for the face icon, sitting on its bottom edge
    left = self.position_x - 96 if not self.is_rhd else self.position_x + 96 - w
    chip = rl.Rectangle(left, self.position_y + 96 - CHIP_H, w, CHIP_H)
    rl.draw_rectangle_rounded(chip, roundness(chip, CHIP_H / 2), 12, Onroad.PANEL)
    rl.draw_rectangle_rounded_lines_ex(chip, roundness(chip, CHIP_H / 2), 12, 2, Console.BORDER_DEFAULT)

    a = 1.0 if self.is_active else 0.5
    D.dot(chip.x + CHIP_PAD + DOT_R, chip.y + CHIP_H / 2, DOT_R, with_alpha(color, int(255 * a)))
    D.text(word, chip.x + CHIP_PAD + DOT_R * 2 + 16, chip.y + (CHIP_H - LABEL) / 2 - 2, LABEL,
           Console.TEXT_PRIMARY if ui_state.engaged else Console.TEXT_MUTED, semi=True)

    if conf is not None:
      frac, fill = conf
      dx = chip.x + CHIP_PAD + DOT_R * 2 + 16 + word_w + DIVIDER_GAP
      rl.draw_rectangle_rec(rl.Rectangle(dx, chip.y + 20, 2, CHIP_H - 40), Console.BORDER_DEFAULT)
      bar = rl.Rectangle(dx + 2 + DIVIDER_GAP, chip.y + (CHIP_H - CONF_H) / 2, CONF_W, CONF_H)
      K.bar(bar, frac if fill is not None else 0.0, fill or Console.TEXT_GHOST)
