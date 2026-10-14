"""
Console layout presets for the driving screen (BPLayoutPreset param).

  0 Minimal   speed card, alerts, plus the driving cues that matter at a glance
              (speed limit, turn signals, blindspot edges, driver monitoring).
  1 Standard  every element the driver has switched on, plus the bottom dock (charge, power,
              range) and a details card only when something needs attention.
  2 Dense     everything in Standard plus the details card (temperatures, trip energy, tires,
              12 V, outside temperature).

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
  "Your enabled overlays plus the dock along the bottom: charge, power and range.",
  "Everything in Standard plus a details card: temperatures, trip energy, tires and 12 V.",
]


def current_preset() -> LayoutPreset:
  from openpilot.selfdrive.ui.ui_state import ui_state
  try:
    return LayoutPreset(int(getattr(ui_state, "layout_preset", LayoutPreset.STANDARD)))
  except ValueError:
    return LayoutPreset.STANDARD
