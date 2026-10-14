"""Color definitions for onroad UI."""
from openpilot.selfdrive.ui.ui_state import UIStatus
from openpilot.selfdrive.ui.sunnypilot.onroad.augmented_road_view import BORDER_COLORS_SP

from bluepilot.ui.lib.theme import Onroad  # Custom: Console theme

# BluePilot: Border colors for confidence ball / UI status
# Custom: Console status hues (deepened for the 30 px frame); SP states mapped to info / purple
BORDER_COLORS = {
  **BORDER_COLORS_SP,
  UIStatus.DISENGAGED: Onroad.BORDER_DISENGAGED,
  UIStatus.OVERRIDE: Onroad.BORDER_OVERRIDE,
  UIStatus.ENGAGED: Onroad.BORDER_ENGAGED,
  UIStatus.LAT_ONLY: Onroad.BORDER_LAT_ONLY,
  UIStatus.LONG_ONLY: Onroad.BORDER_LONG_ONLY,
}
