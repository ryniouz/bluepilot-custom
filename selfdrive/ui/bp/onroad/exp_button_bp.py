import pyray as rl

from openpilot.selfdrive.ui.onroad.exp_button import FACE_SIZE, ExpButton
from openpilot.selfdrive.ui.bp.lib.steering_wheel_style import (
  ensure_steering_wheel_icon_style_initialized,
  get_steering_wheel_icon_style,
  SteeringWheelIconStyle,
)
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
# BluePilot: seasonal theme packs (steering wheel icon override)
from openpilot.selfdrive.ui.bp.lib import theme_pack
from bluepilot.ui.console import draw as D  # Custom: shared Console icons
from bluepilot.ui.lib.theme import Console, is_day, with_alpha  # Custom: Console theme


class ExpButtonBP(ExpButton):
  """BluePilot experimental-mode button with optional steering-wheel animation."""

  def __init__(self, button_size: int, icon_size: int):
    super().__init__(button_size, icon_size)
    self._txt_wheel_comma_4 = gui_app.texture("icons_mici/wheel.png", icon_size, icon_size)
    self._icon_size_console = self._icon_size  # Custom: Console line-icon size (set by ExpButton)
    self._icon_size = icon_size
    self._animate_steering_wheel = self._params.get_bool("BPAnimateSteeringWheel")
    self._wheel_icon_style = ensure_steering_wheel_icon_style_initialized(self._params, SteeringWheelIconStyle.COMMA_3X)
    self._theme_pack = theme_pack.get_active_pack(force=True)
    self._param_counter = 0

  def _update_state(self) -> None:
    super()._update_state()

    # BluePilot: Refresh display params periodically so onroad changes are picked up.
    self._param_counter += 1
    if self._param_counter >= 60:
      self._param_counter = 0
      self._animate_steering_wheel = self._params.get_bool("BPAnimateSteeringWheel")
      self._wheel_icon_style = get_steering_wheel_icon_style(self._params, SteeringWheelIconStyle.COMMA_3X)
      self._theme_pack = theme_pack.get_active_pack()

  def _draw_console_face(self, center_x: float, center_y: float, is_exp: bool) -> None:
    """Custom: a round translucent glass face (Lucas 2026-10-14) instead of the rounded square: a
    tinted disc, a soft sheen on the upper half, a thin lit rim and a faint shadow ring."""
    c = rl.Vector2(center_x, center_y)
    r = FACE_SIZE / 2
    day = is_day()
    rl.draw_ring(c, r, r + 6, 0, 360, 72, rl.Color(0, 0, 0, 0x18 if day else 0x30))
    if is_exp:
      fill = with_alpha(Console.ACCENT_FILL, 0xE6)
    else:
      fill = with_alpha(Console.BG_PANEL, (0xE6 if self.is_pressed else 0xA8) if not day else (0xF2 if self.is_pressed else 0xC8))
    rl.draw_circle_v(c, r, fill)
    rl.draw_circle_gradient(rl.Vector2(center_x, center_y - r * 0.38), r * 0.6, rl.Color(255, 255, 255, 0x22 if not day else 0x55),
                            rl.Color(255, 255, 255, 0))
    rim = rl.Color(255, 255, 255, 0x40) if not day else Console.BORDER_DEFAULT
    rl.draw_ring(c, r - 2, r, 0, 360, 72, rim)

  def _render(self, rect: rl.Rectangle) -> None:
    center_x = int(self._rect.x + self._rect.width // 2)
    center_y = int(self._rect.y + self._rect.height // 2)

    self._white_color.a = 180 if self.is_pressed or not self._engageable else 255

    experimental_mode = self._held_or_actual_mode()
    # Custom: Console face (rounded square, accent fill in experimental mode). The Console
    # line-icon wheel is the default; a theme-pack wheel or the comma-4 style still wins.
    self._draw_console_face(center_x, center_y, experimental_mode)
    rotation = -ui_state.sm['carState'].steeringAngleDeg if self._animate_steering_wheel else 0.0

    if experimental_mode:
      sz = self._icon_size_console
      D.icon("flask", center_x - sz / 2, center_y - sz / 2, sz, Console.ON_ACCENT)
      return

    wheel_texture = self._txt_wheel_comma_4 if self._wheel_icon_style == SteeringWheelIconStyle.COMMA_4 else None
    # BluePilot: theme pack steering wheel icon wins over the built-in styles
    if self._theme_pack is not None:
      pack_wheel = self._theme_pack.wheel_texture(self._icon_size)
      if pack_wheel is not None:
        wheel_texture = pack_wheel

    if wheel_texture is None:
      sz = self._icon_size_console
      rl.rl_push_matrix()
      rl.rl_translatef(center_x, center_y, 0)
      rl.rl_rotatef(rotation, 0, 0, 1)
      D.icon("wheel", -sz / 2, -sz / 2, sz, self._white_color)
      rl.rl_pop_matrix()
    else:
      rl.draw_texture_pro(
        wheel_texture,
        rl.Rectangle(0, 0, wheel_texture.width, wheel_texture.height),
        rl.Rectangle(center_x, center_y, wheel_texture.width, wheel_texture.height),
        rl.Vector2(wheel_texture.width / 2, wheel_texture.height / 2),
        rotation,
        self._white_color,
      )
    # Custom: end
