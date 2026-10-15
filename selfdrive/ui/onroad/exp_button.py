import time
import pyray as rl
from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.widgets import Widget
from bluepilot.ui.console import draw as D  # Custom: shared Console icons
from bluepilot.ui.lib.theme import Console, Onroad, roundness, copy as copy_color  # Custom: Console theme

# Custom: Console rounded-square button, inset in the stock touch area
FACE_SIZE = 164
FACE_RADIUS = 28


class ExpButton(Widget):
  def __init__(self, button_size: int, icon_size: int):
    super().__init__()
    self._params = Params()
    self._experimental_mode: bool = False
    self._engageable: bool = False

    # State hold mechanism
    self._hold_duration = 2.0  # seconds
    self._held_mode: bool | None = None
    self._hold_end_time: float | None = None

    # Custom: Console panel button with hairline ring
    self._white_color: rl.Color = copy_color(Console.TEXT_PRIMARY)
    self._black_bg: rl.Color = Onroad.PANEL
    # Custom: shared Console line icons ("wheel", "flask") replace the stock textures
    self._icon_size = FACE_SIZE * 0.5
    # Stock textures stay loaded: ExpButtonBP draws them for the comma-4 wheel style
    self._txt_wheel: rl.Texture = gui_app.texture('icons/chffr_wheel.png', icon_size, icon_size)
    self._txt_exp: rl.Texture = gui_app.texture('icons/experimental.png', icon_size, icon_size)
    self._rect = rl.Rectangle(0, 0, button_size, button_size)

  def set_rect(self, rect: rl.Rectangle) -> None:
    self._rect.x, self._rect.y = rect.x, rect.y

  def _update_state(self) -> None:
    selfdrive_state = ui_state.sm["selfdriveState"]
    self._experimental_mode = selfdrive_state.experimentalMode
    self._engageable = selfdrive_state.engageable or selfdrive_state.enabled

  def _handle_mouse_release(self, _):
    super()._handle_mouse_release(_)
    if self._is_toggle_allowed():
      new_mode = not self._experimental_mode
      self._params.put_bool("ExperimentalMode", new_mode)

      # Hold new state temporarily
      self._held_mode = new_mode
      self._hold_end_time = time.monotonic() + self._hold_duration

  def _render(self, rect: rl.Rectangle) -> None:
    center_x = int(self._rect.x + self._rect.width // 2)
    center_y = int(self._rect.y + self._rect.height // 2)

    self._white_color.a = 180 if self.is_pressed or not self._engageable else 255

    is_exp = self._held_or_actual_mode()
    # Custom: Console face. Accent fill marks experimental mode; a hairline otherwise.
    self._draw_console_face(center_x, center_y, is_exp)
    sz = self._icon_size
    if is_exp:
      D.icon("flask", center_x - sz / 2, center_y - sz / 2, sz, Console.ON_ACCENT)
    else:
      D.icon("wheel", center_x - sz / 2, center_y - sz / 2, sz, self._white_color)
    # Custom: end

  # Custom: Console face shared with ExpButtonBP
  def _draw_console_face(self, center_x: float, center_y: float, is_exp: bool) -> None:
    face = rl.Rectangle(center_x - FACE_SIZE / 2, center_y - FACE_SIZE / 2, FACE_SIZE, FACE_SIZE)
    r = roundness(face, FACE_RADIUS)
    if is_exp:
      rl.draw_rectangle_rounded(face, r, 10, Console.ACCENT_FILL)
    else:
      rl.draw_rectangle_rounded(face, r, 10, Console.BG_HIGH if self.is_pressed else self._black_bg)
      rl.draw_rectangle_rounded_lines_ex(face, r, 10, 2, Console.BORDER_DEFAULT)
  # Custom: end

  def _held_or_actual_mode(self):
    now = time.monotonic()
    if self._hold_end_time and now < self._hold_end_time:
      return self._held_mode

    if self._hold_end_time and now >= self._hold_end_time:
      self._hold_end_time = self._held_mode = None

    return self._experimental_mode

  def _is_toggle_allowed(self):
    if not self._params.get_bool("ExperimentalModeConfirmed"):
      return False

    # Mirror exp mode toggle using persistent car params
    return ui_state.has_longitudinal_control
