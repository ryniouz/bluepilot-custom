"""
Copyright (c) 2021-, Haibin Wen, sunnypilot, and a number of other contributors.

This file is part of sunnypilot and is licensed under the MIT License.
See the LICENSE.md file in the root directory for more details.
"""
from dataclasses import dataclass

import pyray as rl  # noqa: F401

from bluepilot.ui.lib.theme import Console, with_alpha  # Custom: Console theme


@dataclass
class Base:
  # Widget/Control Base Dimensions
  # Custom: Console (Citadel form rows) sizes; stock was 170 / 50 / 40 / 150
  ITEM_BASE_HEIGHT = 124
  ITEM_PADDING = 20
  ITEM_TEXT_FONT_SIZE = 34
  ITEM_DESC_FONT_SIZE = 28
  ITEM_DESC_V_OFFSET = 104
  # Custom: end
  ITEM_TEXT_VALUE_COLOR = Console.TEXT_SECONDARY  # Custom: Console
  CLOSE_BTN_SIZE = 160

  TEXT_PADDING = 20

  # Custom: Console sizes; stock toggle 120 high, buttons 120 / 150 high
  # Toggle Control
  TOGGLE_HEIGHT = 64
  TOGGLE_WIDTH = int(TOGGLE_HEIGHT * 1.75)
  TOGGLE_BG_HEIGHT = TOGGLE_HEIGHT - 8

  # Button Control
  BUTTON_ACTION_WIDTH = 260
  BUTTON_HEIGHT = 80

  # Simple Button Control
  SIMPLE_BUTTON_WIDTH = 640
  SIMPLE_BUTTON_HEIGHT = 88
  # Custom: end


@dataclass
class DefaultStyleSP(Base):
  # Custom: every colour comes from the Console theme (bluepilot/ui/lib/theme.py)
  # Base Colors
  BASE_BG_COLOR = Console.BG_RAISED
  ON_BG_COLOR = Console.ACCENT_FILL
  OFF_BG_COLOR = BASE_BG_COLOR
  ON_HOVER_BG_COLOR = Console.ACCENT_FILL_HOVER
  OFF_HOVER_BG_COLOR = Console.BG_HIGH
  DISABLED_ON_BG_COLOR = Console.ACCENT_TINT_STRONG
  DISABLED_OFF_BG_COLOR = Console.BG_PANEL
  ITEM_TEXT_COLOR = Console.TEXT_PRIMARY
  ITEM_DISABLED_TEXT_COLOR = Console.TEXT_GHOST
  ITEM_DESC_TEXT_COLOR = Console.TEXT_MUTED

  # Toggle Control
  TOGGLE_ON_COLOR = ON_BG_COLOR
  TOGGLE_OFF_COLOR = Console.TOGGLE_OFF
  TOGGLE_KNOB_COLOR = Console.TOGGLE_KNOB
  TOGGLE_DISABLED_ON_COLOR = DISABLED_ON_BG_COLOR
  TOGGLE_DISABLED_OFF_COLOR = DISABLED_OFF_BG_COLOR
  TOGGLE_DISABLED_KNOB_COLOR = Console.TEXT_GHOST

  # Multi Button Control
  MBC_TRANSPARENT = Console.TRANSPARENT
  MBC_BG_CHECKED_ENABLED = Console.ACCENT_FILL
  MBC_DISABLED = with_alpha(Console.TEXT_PRIMARY, 0x33)

  # Option Control
  OPTION_CONTROL_CONTAINER_BG = OFF_BG_COLOR
  OPTION_CONTROL_BTN_ENABLED = Console.BG_HIGH
  OPTION_CONTROL_BTN_PRESSED = Console.BORDER_DEFAULT
  OPTION_CONTROL_BTN_DISABLED = DISABLED_OFF_BG_COLOR
  OPTION_CONTROL_TEXT_ENABLED = Console.TEXT_PRIMARY
  OPTION_CONTROL_TEXT_PRESSED = Console.TEXT_PRIMARY
  OPTION_CONTROL_TEXT_DISABLED = ITEM_DISABLED_TEXT_COLOR

  # Tree Button Colors
  BUTTON_PRIMARY_COLOR = Console.ACCENT_FILL
  BUTTON_NEUTRAL_GRAY = Console.BG_RAISED
  BUTTON_DISABLED_BG_COLOR = Console.BG_PANEL
  TREE_DIALOG_TRANSPARENT = Console.TRANSPARENT
  TREE_DIALOG_SEARCH_BUTTON_PRESSED = Console.BG_HIGH
  TREE_DIALOG_SEARCH_BUTTON_BORDER = Console.BORDER_DEFAULT

  # Vehicle Description Colors (status marks)
  GREEN = Console.SUCCESS
  BLUE = Console.INFO
  YELLOW = Console.WARNING

  # Button Colors
  BUTTON_ENABLED_OFF = Console.BG_RAISED
  BUTTON_OFF_PRESSED = Console.BG_HIGH
  BUTTON_DISABLED = Console.BG_PANEL
  BUTTON_TEXT_DISABLED = Console.TEXT_GHOST


style = DefaultStyleSP
