"""
Console driver-monitoring tile (bottom left, bottom right on right-hand drive).

openpilot's pose tracking and active/inactive fade are unchanged (DriverStateRendererSP); only
the drawing is new: a rounded Console tile with camera-style corner brackets, a simple head
that turns and nods with the driver, and an attention bar along the bottom that empties as
openpilot's awareness drops.
"""

import numpy as np
import pyray as rl

from openpilot.selfdrive.ui.sunnypilot.onroad.driver_state import DriverStateRendererSP
from openpilot.selfdrive.ui.ui_state import ui_state
from bluepilot.ui.console import kit as K
from bluepilot.ui.lib.theme import Console, Onroad, roundness, with_alpha

TILE = 176
TILE_R = 32
BRACKET = 26          # corner bracket arm
BRACKET_W = 6
HEAD_R = 30
LOOK = 26             # how far the head moves at full yaw / pitch
BAR_H = 12


def _awareness_color(awareness: float) -> rl.Color:
  if awareness > 0.6:
    return Console.SUCCESS
  if awareness > 0.3:
    return Console.WARNING
  return Console.DANGER


class DriverMonitorBP(DriverStateRendererSP):
  def _render(self, rect):
    cx, cy = self.position_x, self.position_y
    a = 1.0 if self.is_active else 0.45
    t = rl.Rectangle(cx - TILE / 2, cy - TILE / 2, TILE, TILE)
    rl.draw_rectangle_rounded(t, roundness(t, TILE_R), 10, with_alpha(Onroad.PANEL_SOLID, int(0xD0 * a + 0x20)))
    rl.draw_rectangle_rounded_lines_ex(t, roundness(t, TILE_R), 10, 2, Console.BORDER_DEFAULT)

    dm = ui_state.sm["driverMonitoringState"]
    awareness = float(np.clip(getattr(dm, "awarenessStatus", 1.0), 0.0, 1.0))
    color = _awareness_color(awareness) if ui_state.engaged else Console.TEXT_GHOST
    ink = with_alpha(color, int(255 * a))

    # Corner brackets: the "camera sees you" frame
    inset = 22
    x0, y0, x1, y1 = t.x + inset, t.y + inset, t.x + TILE - inset, t.y + TILE - inset - BAR_H - 8
    for (x, y, dx, dy) in ((x0, y0, 1, 1), (x1, y0, -1, 1), (x0, y1, 1, -1), (x1, y1, -1, -1)):
      rl.draw_rectangle_rec(rl.Rectangle(min(x, x + dx * BRACKET), y - (BRACKET_W if dy < 0 else 0), BRACKET, BRACKET_W), ink)
      rl.draw_rectangle_rec(rl.Rectangle(x - (BRACKET_W if dx < 0 else 0), min(y, y + dy * BRACKET), BRACKET_W, BRACKET), ink)

    # Head and shoulders; the head follows the driver's yaw (sins[1]) and pitch (sins[0])
    fx, fy = (x0 + x1) / 2, (y0 + y1) / 2
    hx = fx - self.driver_pose_sins[1] * LOOK
    hy = fy - 10 - self.driver_pose_sins[0] * LOOK * 0.6
    shoulder_y = y1 - 4
    rl.draw_ring(rl.Vector2(fx, shoulder_y + 6), HEAD_R + 6, HEAD_R + 14, 200, 340, 24, with_alpha(Console.TEXT_PRIMARY, int(200 * a)))
    rl.draw_circle_v(rl.Vector2(hx, hy), HEAD_R, with_alpha(Console.TEXT_PRIMARY, int(235 * a)))
    # nose mark shows where the face points
    nx = hx - self.driver_pose_sins[1] * HEAD_R * 0.75
    ny = hy - self.driver_pose_sins[0] * HEAD_R * 0.5 + 4
    rl.draw_circle_v(rl.Vector2(nx, ny), 7, with_alpha(Console.BG_PAGE, int(220 * a)))

    # Attention bar
    K.bar(rl.Rectangle(t.x + inset, t.y + TILE - inset - BAR_H, TILE - 2 * inset, BAR_H), awareness, ink)
