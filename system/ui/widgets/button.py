from collections.abc import Callable
from enum import IntEnum

import pyray as rl

from openpilot.system.ui.lib.application import gui_app, FontWeight, MousePos
from openpilot.system.ui.widgets import Widget
from openpilot.system.ui.widgets.label import Label
from openpilot.common.filter_simple import FirstOrderFilter
from bluepilot.ui.lib.theme import with_alpha, Console  # Custom: Console theme


class ButtonStyle(IntEnum):
  NORMAL = 0  # Most common, neutral buttons
  PRIMARY = 1  # For main actions
  DANGER = 2  # For critical actions, like reboot or delete
  TRANSPARENT = 3  # For buttons with transparent background and border
  TRANSPARENT_WHITE_TEXT = 9  # For buttons with transparent background and border and white text
  TRANSPARENT_WHITE_BORDER = 10  # For buttons with transparent background and white border and text
  ACTION = 4
  LIST_ACTION = 5  # For list items with action buttons
  NO_EFFECT = 6
  KEYBOARD = 7
  FORGET_WIFI = 8


ICON_PADDING = 15
DEFAULT_BUTTON_FONT_SIZE = 60
ACTION_BUTTON_FONT_SIZE = 48

# Custom: Console button palette. Neutral buttons sit on bg-raised, the primary action uses
# accent-fill under on-accent, destructive uses danger-fill; pressed steps one tone up.
BUTTON_TEXT_COLOR = {
  ButtonStyle.NORMAL: Console.TEXT_PRIMARY,
  ButtonStyle.PRIMARY: Console.ON_ACCENT,
  ButtonStyle.DANGER: Console.ON_ACCENT,
  ButtonStyle.TRANSPARENT: Console.BG_PAGE,
  ButtonStyle.TRANSPARENT_WHITE_TEXT: Console.TEXT_PRIMARY,
  ButtonStyle.TRANSPARENT_WHITE_BORDER: Console.TEXT_PRIMARY,
  ButtonStyle.ACTION: Console.TEXT_PRIMARY,
  ButtonStyle.LIST_ACTION: Console.TEXT_PRIMARY,
  ButtonStyle.NO_EFFECT: Console.TEXT_PRIMARY,
  ButtonStyle.KEYBOARD: Console.TEXT_PRIMARY,
  ButtonStyle.FORGET_WIFI: Console.TEXT_PRIMARY,
}

BUTTON_DISABLED_TEXT_COLORS = {
  ButtonStyle.TRANSPARENT_WHITE_TEXT: Console.TEXT_GHOST,
}

BUTTON_BACKGROUND_COLORS = {
  ButtonStyle.NORMAL: Console.BG_RAISED,
  ButtonStyle.PRIMARY: Console.ACCENT_FILL,
  ButtonStyle.DANGER: Console.DANGER_FILL,
  ButtonStyle.TRANSPARENT: Console.BG_PAGE,
  ButtonStyle.TRANSPARENT_WHITE_TEXT: rl.BLANK,
  ButtonStyle.TRANSPARENT_WHITE_BORDER: Console.BG_PAGE,
  ButtonStyle.ACTION: Console.BG_HIGH,
  ButtonStyle.LIST_ACTION: Console.BG_RAISED,
  ButtonStyle.NO_EFFECT: Console.BG_RAISED,
  ButtonStyle.KEYBOARD: Console.BG_RAISED,
  ButtonStyle.FORGET_WIFI: Console.BG_HIGH,
}

BUTTON_PRESSED_BACKGROUND_COLORS = {
  ButtonStyle.NORMAL: Console.BG_HIGH,
  ButtonStyle.PRIMARY: Console.ACCENT_FILL_HOVER,
  ButtonStyle.DANGER: Console.DANGER,
  ButtonStyle.TRANSPARENT: Console.BG_PAGE,
  ButtonStyle.TRANSPARENT_WHITE_TEXT: rl.BLANK,
  ButtonStyle.TRANSPARENT_WHITE_BORDER: rl.BLANK,
  ButtonStyle.ACTION: Console.BORDER_DEFAULT,
  ButtonStyle.LIST_ACTION: Console.BG_HIGH,
  ButtonStyle.NO_EFFECT: Console.BG_RAISED,
  ButtonStyle.KEYBOARD: Console.BG_HIGH,
  ButtonStyle.FORGET_WIFI: Console.BORDER_DEFAULT,
}

BUTTON_DISABLED_BACKGROUND_COLORS = {
  ButtonStyle.TRANSPARENT_WHITE_TEXT: rl.BLANK,
}
# Custom: end


class Button(Widget):
  def __init__(self,
               text: str | Callable[[], str],
               click_callback: Callable[[], None] | None = None,
               font_size: int = DEFAULT_BUTTON_FONT_SIZE,
               font_weight: FontWeight = FontWeight.MEDIUM,
               button_style: ButtonStyle = ButtonStyle.NORMAL,
               border_radius: int = 10,
               text_alignment: int = rl.GuiTextAlignment.TEXT_ALIGN_CENTER,
               text_padding: int = 20,
               icon=None,
               elide_right: bool = False,
               multi_touch: bool = False,
               ):

    super().__init__()
    self._button_style = button_style
    self._border_radius = border_radius
    self._background_color = BUTTON_BACKGROUND_COLORS[self._button_style]

    self._label = Label(text, font_size, font_weight, text_alignment, text_padding=text_padding,
                        text_color=BUTTON_TEXT_COLOR[self._button_style], icon=icon, elide_right=elide_right)

    self._click_callback = click_callback
    self._multi_touch = multi_touch

  def set_text(self, text):
    self._label.set_text(text)

  def set_button_style(self, button_style: ButtonStyle):
    self._button_style = button_style
    self._background_color = BUTTON_BACKGROUND_COLORS[self._button_style]
    self._label.set_text_color(BUTTON_TEXT_COLOR[self._button_style])

  def _update_state(self):
    if self.enabled:
      self._label.set_text_color(BUTTON_TEXT_COLOR[self._button_style])
      if self.is_pressed:
        self._background_color = BUTTON_PRESSED_BACKGROUND_COLORS[self._button_style]
      else:
        self._background_color = BUTTON_BACKGROUND_COLORS[self._button_style]
    elif self._button_style != ButtonStyle.NO_EFFECT:
      self._background_color = BUTTON_DISABLED_BACKGROUND_COLORS.get(self._button_style, Console.BG_PANEL)
      self._label.set_text_color(BUTTON_DISABLED_TEXT_COLORS.get(self._button_style, Console.TEXT_GHOST))

  def _render(self, _):
    roundness = self._border_radius / (min(self._rect.width, self._rect.height) / 2)
    if self._button_style == ButtonStyle.TRANSPARENT_WHITE_BORDER:
      rl.draw_rectangle_rounded(self._rect, roundness, 10, Console.BG_PAGE)
      rl.draw_rectangle_rounded_lines_ex(self._rect, roundness, 10, 2, Console.BORDER_DEFAULT)
    else:
      rl.draw_rectangle_rounded(self._rect, roundness, 10, self._background_color)
    self._label.render(self._rect)


class ButtonRadio(Button):
  def __init__(self,
               text: str,
               icon,
               click_callback: Callable[[], None] | None = None,
               font_size: int = DEFAULT_BUTTON_FONT_SIZE,
               text_alignment: int = rl.GuiTextAlignment.TEXT_ALIGN_LEFT,
               border_radius: int = 10,
               text_padding: int = 20,
               ):

    super().__init__(text, click_callback=click_callback, font_size=font_size,
                     border_radius=border_radius, text_padding=text_padding,
                     text_alignment=text_alignment)
    self._text_padding = text_padding
    self._icon = icon
    self.selected = False

  def _handle_mouse_release(self, mouse_pos: MousePos):
    super()._handle_mouse_release(mouse_pos)
    self.selected = not self.selected

  def _update_state(self):
    if self.selected:
      self._background_color = BUTTON_BACKGROUND_COLORS[ButtonStyle.PRIMARY]
    else:
      self._background_color = BUTTON_BACKGROUND_COLORS[ButtonStyle.NORMAL]

  def _render(self, _):
    roundness = self._border_radius / (min(self._rect.width, self._rect.height) / 2)
    rl.draw_rectangle_rounded(self._rect, roundness, 10, self._background_color)
    self._label.render(self._rect)

    if self._icon and self.selected:
      icon_y = self._rect.y + (self._rect.height - self._icon.height) / 2
      icon_x = self._rect.x + self._rect.width - self._icon.width - self._text_padding - ICON_PADDING
      rl.draw_texture_v(self._icon, rl.Vector2(icon_x, icon_y), Console.TEXT_PRIMARY if self.enabled else with_alpha(Console.TEXT_PRIMARY, 100))


class IconButton(Widget):
  def __init__(self, texture: rl.Texture):
    super().__init__()
    self._texture = texture
    self._opacity_filter = FirstOrderFilter(1.0, 0.1, 1 / gui_app.target_fps)
    self.set_rect(rl.Rectangle(0, 0, self._texture.width, self._texture.height))

  def set_opacity(self, opacity: float, smooth: bool = False):
    if smooth:
      self._opacity_filter.update(opacity)
    else:
      self._opacity_filter.x = opacity

  def _render(self, rect: rl.Rectangle):
    color = with_alpha(Console.TEXT_MUTED, int(150 * self._opacity_filter.x)) if self.is_pressed else Console.TEXT_PRIMARY
    if not self.enabled:
      color = with_alpha(Console.TEXT_PRIMARY, int(255 * 0.9 * 0.35 * self._opacity_filter.x))
    draw_x = rect.x + (rect.width - self._texture.width) / 2
    draw_y = rect.y + (rect.height - self._texture.height) / 2
    rl.draw_texture_ex(self._texture, rl.Vector2(draw_x, draw_y), 0.0, 1.0, color)


class SmallCircleIconButton(Widget):
  def __init__(self, icon_txt: rl.Texture):
    super().__init__()
    self.set_rect(rl.Rectangle(0, 0, 100, 100))
    self._opacity_filter = FirstOrderFilter(1.0, 0.1, 1 / gui_app.target_fps)
    self._icon_bg_txt = gui_app.texture("icons_mici/setup/small_button.png", 100, 100)
    self._icon_bg_pressed_txt = gui_app.texture("icons_mici/setup/small_button_pressed.png", 100, 100)
    self._icon_bg_disabled_txt = gui_app.texture("icons_mici/setup/small_button_disabled.png", 100, 100)
    self._icon_txt = icon_txt

  def set_opacity(self, opacity: float, smooth: bool = False):
    if smooth:
      self._opacity_filter.update(opacity)
    else:
      self._opacity_filter.x = opacity

  def _render(self, _):
    white = with_alpha(Console.TEXT_PRIMARY, int(255 * self._opacity_filter.x))
    if not self.enabled:
      bg_txt = self._icon_bg_disabled_txt
      icon_white = with_alpha(Console.TEXT_PRIMARY, int(white.a * 0.35))
    else:
      bg_txt = self._icon_bg_pressed_txt if self.is_pressed else self._icon_bg_txt
      icon_white = white

    rl.draw_texture_ex(bg_txt, rl.Vector2(self.rect.x, self.rect.y), 0.0, 1.0, white)
    icon_x = self.rect.x + (self.rect.width - self._icon_txt.width) / 2
    icon_y = self.rect.y + (self.rect.height - self._icon_txt.height) / 2
    rl.draw_texture_ex(self._icon_txt, rl.Vector2(icon_x, icon_y), 0.0, 1.0, icon_white)
