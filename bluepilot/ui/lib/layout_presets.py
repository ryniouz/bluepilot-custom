"""
Console layout presets for the driving screen (BPLayoutPreset param).

  0 Minimal   speed, set speed, alerts, plus the driving cues that matter at a glance
              (speed limit, turn signals, blindspot edges, driver monitoring).
  1 Standard  every element the driver has switched on, plus the compact EV HUD.
  2 Dense     everything in Standard plus the full EV HUD (temperatures, limits, tires, 12 V).

Presets only filter what draws; they never change the user's individual toggles, so moving
back to Standard restores the screen exactly as it was.
"""

from enum import IntEnum


class LayoutPreset(IntEnum):
  MINIMAL = 0
  STANDARD = 1
  DENSE = 2


PRESET_LABELS = ["Minimal", "Standard", "Dense"]
PRESET_DESCRIPTIONS = [
  "Speed, set speed and alerts. Optional overlays are hidden.",
  "Your enabled overlays plus a compact EV panel: charge, power and range.",
  "Everything in Standard plus temperatures, power limits, tire pressure and 12 V.",
]


def current_preset() -> LayoutPreset:
  from openpilot.selfdrive.ui.ui_state import ui_state
  try:
    return LayoutPreset(int(getattr(ui_state, "layout_preset", LayoutPreset.STANDARD)))
  except ValueError:
    return LayoutPreset.STANDARD
