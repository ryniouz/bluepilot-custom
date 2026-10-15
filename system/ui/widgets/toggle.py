import pyray as rl
from bluepilot.ui.lib.theme import Console  # Custom: Console theme
from collections.abc import Callable
from openpilot.system.ui.lib.application import MousePos
from openpilot.system.ui.widgets import Widget

# Custom: Console toggle - accent track when on, bg-high when off
ON_COLOR = Console.ACCENT_FILL
OFF_COLOR = Console.TOGGLE_OFF
KNOB_COLOR = Console.TOGGLE_KNOB
DISABLED_ON_COLOR = Console.ACCENT_TINT_STRONG
DISABLED_OFF_COLOR = Console.BG_HIGH  # Custom: BG_RAISED matched night cards, hiding the track
DISABLED_KNOB_COLOR = Console.TEXT_GHOST
WIDTH, HEIGHT = 160, 80
BG_HEIGHT = 60
KNOB_PADDING = 5  # Custom: Console inset knob
ANIMATION_SPEED = 8.0


class Toggle(Widget):
  def __init__(self, initial_state: bool = False, callback: Callable[[bool], None] | None = None):
    super().__init__()
    self._state = initial_state
    self._callback = callback
    self._enabled = True
    self._progress = 1.0 if initial_state else 0.0
    self._target = self._progress
    self._clicked = False

  def set_rect(self, rect: rl.Rectangle):
    self._rect = rl.Rectangle(rect.x, rect.y, WIDTH, HEIGHT)

  def _handle_mouse_release(self, mouse_pos: MousePos):
    if not self._enabled:
      return

    self._clicked = True
    self._state = not self._state
    self._target = 1.0 if self._state else 0.0
    if self._callback:
      self._callback(self._state)

  def get_state(self) -> bool:
    return self._state

  def set_state(self, state: bool):
    self._state = state
    self._target = 1.0 if state else 0.0

  def is_enabled(self):
    return self._enabled

  def update(self):
    if abs(self._progress - self._target) > 0.01:
      delta = rl.get_frame_time() * ANIMATION_SPEED
      self._progress += delta if self._progress < self._target else -delta
      self._progress = max(0.0, min(1.0, self._progress))

  def _render(self, rect: rl.Rectangle):
    self.update()

    if self._enabled:
      bg_color = self._blend_color(OFF_COLOR, ON_COLOR, self._progress)
      knob_color = KNOB_COLOR
    else:
      bg_color = self._blend_color(DISABLED_OFF_COLOR, DISABLED_ON_COLOR, self._progress)
      knob_color = DISABLED_KNOB_COLOR

    # Draw background
    bg_rect = rl.Rectangle(self._rect.x + 5, self._rect.y + 10, WIDTH - 10, BG_HEIGHT)
    rl.draw_rectangle_rounded(bg_rect, 1.0, 10, bg_color)

    # Draw knob
    # Custom: Console knob sits inside the track (as ToggleSP does). The stock knob overhangs the track,
    # so in day mode a white knob on a white card vanished and seemed to bite the track's end.
    knob_r = BG_HEIGHT / 2 - KNOB_PADDING
    knob_x = bg_rect.x + KNOB_PADDING + knob_r + (bg_rect.width - 2 * (KNOB_PADDING + knob_r)) * self._progress
    knob_y = bg_rect.y + BG_HEIGHT / 2
    rl.draw_circle(int(knob_x), int(knob_y), knob_r, knob_color)
    # Custom: end

    # TODO: use click callback
    clicked = self._clicked
    self._clicked = False
    return clicked

  def _blend_color(self, c1, c2, t):
    return rl.Color(int(c1.r + (c2.r - c1.r) * t), int(c1.g + (c2.g - c1.g) * t), int(c1.b + (c2.b - c1.b) * t), 255)
