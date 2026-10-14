"""
BluePilot colour scheme for the raylib UI, backed by the Console theme.
"""

import pyray as rl

from bluepilot.ui.lib.theme import Console, Onroad


class BPColors:
  """BluePilot colour names, mapped onto the Console theme tokens (bluepilot/ui/lib/theme.py).

  Custom: every value now comes from Console. Names are kept so existing callers keep working.
  """

  # Background colors
  BACKGROUND = Console.BG_PAGE
  BACKGROUND_DARKER = Console.BG_PAGE
  CARD_BACKGROUND = Console.BG_PANEL
  SIDEBAR_BG = Console.BG_PANEL

  # Accent (follows the Console accent theme)
  ACCENT = Console.ACCENT

  # Status colors
  GOOD = Console.SUCCESS
  WARNING = Console.WARNING
  DANGER = Console.DANGER
  DISABLED = Console.TEXT_GHOST
  PROGRESS = Console.ACCENT

  # Text colors
  WHITE = Console.TEXT_PRIMARY
  WHITE_DIM = Console.TEXT_GHOST
  GRAY = Console.BORDER_DEFAULT
  LIGHT_GRAY = Console.TEXT_SECONDARY
  TEXT_SECONDARY = Console.TEXT_MUTED

  # UI elements
  METRIC_BORDER = Console.BORDER_DEFAULT
  BUTTON_NORMAL = Console.TEXT_PRIMARY
  BUTTON_PRESSED = Console.TEXT_MUTED
  BUTTON_BG = Console.BG_RAISED
  BUTTON_BG_PRESSED = Console.BG_HIGH
  SHADOW = Console.TRANSPARENT

  # Signal bar colors
<<<<<<< ours
  SIGNAL_ACTIVE = rl.Color(24, 144, 255, 255)  # accent_color from Qt
  SIGNAL_INACTIVE = rl.Color(120, 120, 120, 120)  # Gray for inactive

  # Badge colors (for version badges)
  BADGE_BRAND = rl.Color(74, 144, 226, 255)  # Blue - brand/version
  BADGE_BRANCH = rl.Color(155, 89, 182, 255)  # Purple - branch
  BADGE_COMMIT = rl.Color(230, 126, 34, 255)  # Orange - commit
  BADGE_DATE = rl.Color(149, 165, 166, 255)  # Gray - date

  # Recent changes dialog colors (from Qt bp_recent_changes.cc)
  CHANGES_GREEN = rl.Color(80, 211, 50, 255)        # #50d332 - New features
  CHANGES_BLUE = rl.Color(33, 150, 243, 255)        # #2196F3 - Bug fixes / version badge
  CHANGES_ORANGE = rl.Color(255, 124, 48, 255)      # #ff7c30 - Removed features
  CHANGES_RED = rl.Color(234, 70, 70, 255)          # #EA4646 - Known issues
  CHANGES_FRAME_BG = rl.Color(36, 36, 36, 255)      # #242424 - Category frame bg
  CHANGES_HEADER_BG = rl.Color(32, 32, 32, 255)     # #202020 - Header bg
  CHANGES_TEXT = rl.Color(228, 228, 228, 255)        # #E4E4E4 - Item text
  CHANGES_AGNOS = rl.Color(156, 39, 176, 255)       # #9C27B0 - AGNOS badge
  BADGE_C3X = rl.Color(0, 188, 212, 255)             # #00BCD4 - Cyan/teal for C3X
  BADGE_C4 = rl.Color(255, 179, 0, 255)              # #FFB300 - Amber/gold for C4
=======
  SIGNAL_ACTIVE = Console.ACCENT
  SIGNAL_INACTIVE = Console.BG_TRACK

  # Badge colors (version badges): quiet chips, colour only where it means something
  BADGE_BRAND = Console.ACCENT_FILL
  BADGE_BRANCH = Console.BG_HIGH
  BADGE_COMMIT = Console.BG_HIGH
  BADGE_DATE = Console.BG_HIGH

  # Recent changes dialog colors
  CHANGES_GREEN = Console.SUCCESS
  CHANGES_BLUE = Console.ACCENT
  CHANGES_ORANGE = Console.WARNING
  CHANGES_RED = Console.DANGER
  CHANGES_FRAME_BG = Console.BG_PANEL
  CHANGES_HEADER_BG = Console.BG_PAGE
  CHANGES_TEXT = Console.TEXT_SECONDARY
  CHANGES_AGNOS = Console.PURPLE
>>>>>>> theirs

  # Onroad border colors
  BORDER_DISENGAGED = Onroad.BORDER_DISENGAGED
  BORDER_OVERRIDE = Onroad.BORDER_OVERRIDE
  BORDER_ENGAGED = Onroad.BORDER_ENGAGED

  @staticmethod
  def with_alpha(color: rl.Color, alpha: int) -> rl.Color:
    """Create a new color with modified alpha"""
    return rl.Color(color.r, color.g, color.b, alpha)

  @staticmethod
  def darker(color: rl.Color, factor: float = 0.8) -> rl.Color:
    """Create a darker version of the color"""
    return rl.Color(
      int(color.r * factor),
      int(color.g * factor),
      int(color.b * factor),
      color.a
    )

  @staticmethod
  def lighter(color: rl.Color, factor: float = 1.2) -> rl.Color:
    """Create a lighter version of the color"""
    return rl.Color(
      min(255, int(color.r * factor)),
      min(255, int(color.g * factor)),
      min(255, int(color.b * factor)),
      color.a
    )
