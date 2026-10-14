"""
Console theme for the comma 3X UI.

Single source of truth for colours, type, spacing and radius on the device screen.
Values come from the Console design system (dark theme), the same tokens the
Citadel web apps use, so the truck screen and the EV apps read as one product.

Rules carried over from Console:
  - Dark ground, surfaces step one tone toward the viewer (page -> panel -> raised -> high).
  - One accent does the interactive work. Status colours mean state only.
  - Inter 400 for text, 600 for headings, labels and numerals. No italics, no emoji.
  - Squared bars (2 px corners), 4 px spacing grid, no decorative gradients.

The accent follows the BPConsoleAccent param (blue, teal, violet, ember) and the palette
follows BPConsoleMode (auto, day, night). Tokens are mutable rl.Color objects rewritten in
place, and colours derived from them at import are rebuilt, so modules that imported them
pick up a change without re-importing.
"""

from __future__ import annotations

import pyray as rl

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def hex_color(value: str, alpha: int | None = None) -> rl.Color:
  """'#rrggbb' or '#rrggbbaa' -> rl.Color."""
  v = value.lstrip("#")
  r, g, b = int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)
  a = int(v[6:8], 16) if len(v) == 8 else 255
  if alpha is not None:
    a = alpha
  return rl.Color(r, g, b, a)


# Colours built from tokens before the UI starts drawing are recorded with the recipe that
# made them, so a day/night or accent switch can rebuild them in place. Recording stops at
# freeze_derived() (first UI frame) so per-frame helper calls do not pile up.
_derived: list[tuple[rl.Color, object]] = []
_recording = True


def _record(color: rl.Color, recipe) -> rl.Color:
  if _recording:
    _derived.append((color, recipe))
  return color


def freeze_derived() -> None:
  global _recording
  _recording = False


def _with_alpha_raw(color: rl.Color, alpha: int | float) -> rl.Color:
  if isinstance(alpha, float) and alpha <= 1.0:
    alpha = int(255 * alpha)
  return rl.Color(color.r, color.g, color.b, max(0, min(255, int(alpha))))


def with_alpha(color: rl.Color, alpha: int | float) -> rl.Color:
  """Copy of color with a new alpha. Floats in [0, 1] are treated as a fraction."""
  return _record(_with_alpha_raw(color, alpha), lambda: _with_alpha_raw(color, alpha))


def _fade_raw(color: rl.Color, factor: float) -> rl.Color:
  return rl.Color(color.r, color.g, color.b, max(0, min(255, int(color.a * factor))))


def fade(color: rl.Color, factor: float) -> rl.Color:
  """Multiply a colour's existing alpha by factor."""
  return _record(_fade_raw(color, factor), lambda: _fade_raw(color, factor))


def _mix_raw(a: rl.Color, b: rl.Color, t: float) -> rl.Color:
  t = max(0.0, min(1.0, t))
  return rl.Color(
    int(a.r + (b.r - a.r) * t),
    int(a.g + (b.g - a.g) * t),
    int(a.b + (b.b - a.b) * t),
    int(a.a + (b.a - a.a) * t),
  )


def mix(a: rl.Color, b: rl.Color, t: float) -> rl.Color:
  """Linear blend from a (t=0) to b (t=1), alpha included."""
  return _record(_mix_raw(a, b, t), lambda: _mix_raw(a, b, t))


def copy(color: rl.Color) -> rl.Color:
  return _record(rl.Color(color.r, color.g, color.b, color.a), lambda: rl.Color(color.r, color.g, color.b, color.a))


def _assign(dst: rl.Color, src: rl.Color) -> None:
  dst.r, dst.g, dst.b, dst.a = src.r, src.g, src.b, src.a


# ---------------------------------------------------------------------------
# Tokens (Console, dark)
# ---------------------------------------------------------------------------


class Console:
  # Ground
  BG_PAGE = hex_color("#131416")
  BG_PANEL = hex_color("#1c1e21")
  BG_RAISED = hex_color("#282b2f")
  BG_HIGH = hex_color("#34383d")
  BG_TRACK = hex_color("#f9fafa", 0x2E)  # empty part of every bar

  # Lines
  BORDER_SUBTLE = hex_color("#34383d")
  BORDER_DEFAULT = hex_color("#42474d")
  BORDER_STRONG = hex_color("#737c87")

  # Text
  TEXT_PRIMARY = hex_color("#f9fafa")
  TEXT_SECONDARY = hex_color("#dee0e3")
  TEXT_MUTED = hex_color("#b7bcc2")
  TEXT_GHOST = hex_color("#737c87")

  # Accent family (rewritten in place by set_accent)
  ACCENT = hex_color("#4797ff")
  ACCENT_TEXT = hex_color("#4797ff")
  ACCENT_FILL = hex_color("#005ed9")
  ACCENT_FILL_HOVER = hex_color("#006fff")
  ACCENT_TINT = hex_color("#05254d")
  ACCENT_TINT_STRONG = hex_color("#0b4ead")
  ON_ACCENT = hex_color("#ffffff")

  # Status: marks, always paired with a word
  SUCCESS = hex_color("#37be5f")
  WARNING = hex_color("#e79613")
  DANGER = hex_color("#ee6368")
  DANGER_FILL = hex_color("#f0383b")
  INFO = hex_color("#3ca9d7")
  PURPLE = hex_color("#b47cde")
  LIME = hex_color("#bfe041")  # charts only

  SCRIM = rl.Color(0, 0, 0, 153)
  TRANSPARENT = rl.Color(0, 0, 0, 0)

  # Component roles that differ between day and night beyond the token swap
  TOGGLE_OFF = hex_color("#34383d")
  TOGGLE_KNOB = hex_color("#f9fafa")
  FRAME_INK = hex_color("#131416")   # what status frames and alerts deepen toward
  ALERT_BG = hex_color("#1c1e21")    # ground of a normal driving alert (dark in both modes, over the camera)


# Day (light) and night (dark) palettes from the Console design system. Status hues are
# brighter in day so they hold up on a light ground; the accent family follows ACCENTS.
PALETTES: dict[str, dict[str, str]] = {
  "dark": {
    "BG_PAGE": "#131416", "BG_PANEL": "#1c1e21", "BG_RAISED": "#282b2f", "BG_HIGH": "#34383d", "BG_TRACK": "#f9fafa2e",
    "BORDER_SUBTLE": "#34383d", "BORDER_DEFAULT": "#42474d", "BORDER_STRONG": "#737c87",
    "TEXT_PRIMARY": "#f9fafa", "TEXT_SECONDARY": "#dee0e3", "TEXT_MUTED": "#b7bcc2", "TEXT_GHOST": "#737c87",
    "SUCCESS": "#37be5f", "WARNING": "#e79613", "DANGER": "#ee6368", "DANGER_FILL": "#f0383b",
    "INFO": "#3ca9d7", "PURPLE": "#b47cde", "LIME": "#bfe041", "SCRIM": "#00000099",
    "TOGGLE_OFF": "#34383d", "TOGGLE_KNOB": "#f9fafa", "FRAME_INK": "#131416", "ALERT_BG": "#1c1e21",
  },
  "light": {
    "BG_PAGE": "#f4f5f6", "BG_PANEL": "#ffffff", "BG_RAISED": "#f9fafa", "BG_HIGH": "#eef0f1", "BG_TRACK": "#21232714",
    "BORDER_SUBTLE": "#eef0f1", "BORDER_DEFAULT": "#dee0e3", "BORDER_STRONG": "#c2c6cb",
    "TEXT_PRIMARY": "#212327", "TEXT_SECONDARY": "#50565e", "TEXT_MUTED": "#676f79", "TEXT_GHOST": "#808893",
    "SUCCESS": "#38cc65", "WARNING": "#f5a524", "DANGER": "#f0383b", "DANGER_FILL": "#f0383b",
    "INFO": "#6bd2fd", "PURPLE": "#a354e3", "LIME": "#bfe041", "SCRIM": "#21232766",
    "TOGGLE_OFF": "#c2c6cb", "TOGGLE_KNOB": "#ffffff", "FRAME_INK": "#212327", "ALERT_BG": "#212327",
  },
}

# Accent themes per mode. Only the accent family changes with the accent; status never does.
ACCENTS: dict[str, dict[str, dict[str, str]]] = {
  "blue": {
    "dark": {"ACCENT": "#4797ff", "ACCENT_TEXT": "#4797ff", "ACCENT_FILL": "#005ed9",
             "ACCENT_FILL_HOVER": "#006fff", "ACCENT_TINT": "#05254d", "ACCENT_TINT_STRONG": "#0b4ead"},
    "light": {"ACCENT": "#006fff", "ACCENT_TEXT": "#005ed9", "ACCENT_FILL": "#006fff",
              "ACCENT_FILL_HOVER": "#005ed9", "ACCENT_TINT": "#e6f1ff", "ACCENT_TINT_STRONG": "#cce2ff"},
  },
  "teal": {
    "dark": {"ACCENT": "#2dd4bf", "ACCENT_TEXT": "#2dd4bf", "ACCENT_FILL": "#0f766e",
             "ACCENT_FILL_HOVER": "#0d9488", "ACCENT_TINT": "#0b2f2c", "ACCENT_TINT_STRONG": "#115e59"},
    "light": {"ACCENT": "#0d9488", "ACCENT_TEXT": "#0f766e", "ACCENT_FILL": "#0f766e",
              "ACCENT_FILL_HOVER": "#115e59", "ACCENT_TINT": "#e6f7f5", "ACCENT_TINT_STRONG": "#b9ebe4"},
  },
  "violet": {
    "dark": {"ACCENT": "#a78bfa", "ACCENT_TEXT": "#a78bfa", "ACCENT_FILL": "#6d28d9",
             "ACCENT_FILL_HOVER": "#7c3aed", "ACCENT_TINT": "#251a45", "ACCENT_TINT_STRONG": "#4c2fa0"},
    "light": {"ACCENT": "#7c3aed", "ACCENT_TEXT": "#6d28d9", "ACCENT_FILL": "#7c3aed",
              "ACCENT_FILL_HOVER": "#6d28d9", "ACCENT_TINT": "#f1ecfe", "ACCENT_TINT_STRONG": "#ddd2fc"},
  },
  "ember": {
    "dark": {"ACCENT": "#ff8a3d", "ACCENT_TEXT": "#ff8a3d", "ACCENT_FILL": "#c2410c",
             "ACCENT_FILL_HOVER": "#ea580c", "ACCENT_TINT": "#3a2010", "ACCENT_TINT_STRONG": "#7c2d12"},
    "light": {"ACCENT": "#ea580c", "ACCENT_TEXT": "#c2410c", "ACCENT_FILL": "#c2410c",
              "ACCENT_FILL_HOVER": "#9a3412", "ACCENT_TINT": "#fff1e8", "ACCENT_TINT_STRONG": "#fed7bd"},
  },
}
ACCENT_NAMES = list(ACCENTS.keys())
ACCENT_LABELS = ["Blue", "Teal", "Violet", "Ember"]

MODE_NAMES = ["auto", "day", "night"]   # BPConsoleMode
MODE_LABELS = ["Auto", "Day", "Night"]

_current_accent = "blue"
_current_mode = "dark"   # resolved palette: "dark" (night) or "light" (day)


def accent_alpha(alpha: int, attr: str = "ACCENT") -> rl.Color:
  """An accent-family colour at a fixed alpha that keeps following the accent and mode."""
  src = getattr(Console, attr)
  c = _with_alpha_raw(src, alpha)
  _derived.append((c, lambda: _with_alpha_raw(src, alpha)))
  return c


def _apply(mode: str, accent: str) -> None:
  for attr, value in PALETTES[mode].items():
    _assign(getattr(Console, attr), hex_color(value))
  for attr, value in ACCENTS[accent][mode].items():
    _assign(getattr(Console, attr), hex_color(value))
  for c, recipe in _derived:
    _assign(c, recipe())


def set_accent(name: str) -> None:
  """Switch the accent family in place. Unknown names fall back to blue."""
  global _current_accent
  name = (name or "blue").strip().lower()
  if name not in ACCENTS:
    name = "blue"
  if name == _current_accent:
    return
  _current_accent = name
  _apply(_current_mode, name)


def current_accent() -> str:
  return _current_accent


def set_mode(mode: str) -> None:
  """Switch between the night ("dark") and day ("light") palettes in place."""
  global _current_mode
  mode = "light" if mode in ("light", "day") else "dark"
  if mode == _current_mode:
    return
  _current_mode = mode
  _apply(mode, _current_accent)


def current_mode() -> str:
  return _current_mode


def is_day() -> bool:
  return _current_mode == "light"


# ---------------------------------------------------------------------------
# Onroad (driving screen) roles, built from the tokens
# ---------------------------------------------------------------------------


class Onroad:
  """Colour roles for the driving screen. Everything here derives from Console tokens."""

  # Ground used behind HUD text over the camera (flat, translucent bg-page; no gradient)
  BAND = with_alpha(Console.BG_PAGE, 0x8C)
  PANEL = with_alpha(Console.BG_PANEL, 0xD9)
  PANEL_SOLID = Console.BG_PANEL
  RAISED = with_alpha(Console.BG_RAISED, 0xE6)
  OUTLINE = with_alpha(Console.BORDER_DEFAULT, 0xFF)

  # Engagement state (border, set-speed label, path edge)
  DISENGAGED = Console.BORDER_STRONG
  ENGAGED = Console.SUCCESS
  OVERRIDE = Console.WARNING
  LAT_ONLY = Console.INFO
  LONG_ONLY = Console.PURPLE

  # 30 px frame: the same status hues, deepened toward the page so the frame does not glare
  BORDER_DISENGAGED = mix(Console.BG_HIGH, Console.BG_PAGE, 0.1)
  BORDER_ENGAGED = mix(Console.SUCCESS, Console.FRAME_INK, 0.35)
  BORDER_OVERRIDE = mix(Console.WARNING, Console.FRAME_INK, 0.35)
  BORDER_LAT_ONLY = mix(Console.INFO, Console.FRAME_INK, 0.35)
  BORDER_LONG_ONLY = mix(Console.PURPLE, Console.FRAME_INK, 0.35)

  # Alerts
  # Driving alerts stay deep in both modes so their white text and urgency read the same by day
  ALERT_NORMAL = with_alpha(Console.ALERT_BG, 0xF2)
  ALERT_PROMPT = mix(Console.WARNING, Console.FRAME_INK, 0.25)
  ALERT_CRITICAL = mix(Console.DANGER_FILL, Console.FRAME_INK, 0.2)
  ALERT_TEXT = Console.ON_ACCENT

  # Lead markers
  LEAD_RADAR = Console.INFO
  LEAD_VISION = Console.WARNING
  LEAD_CLOSE = Console.DANGER

  # Text over the camera
  TEXT = Console.TEXT_PRIMARY
  TEXT_DIM = Console.TEXT_MUTED
  TEXT_GHOST = Console.TEXT_GHOST
  SHADOW = with_alpha(Console.BG_PAGE, 140)


# ---------------------------------------------------------------------------
# Type, spacing, radius
# ---------------------------------------------------------------------------


class Space:
  S1 = 4
  S2 = 8
  S3 = 12
  S4 = 16
  S5 = 20
  S6 = 24
  S8 = 32


class Radius:
  XS = 2
  SM = 4
  MD = 8
  LG = 14


def roundness(rect_or_h, radius_px: float, rect_w: float | None = None) -> float:
  """Convert a pixel corner radius to raylib's 0..1 roundness for draw_rectangle_rounded.

  raylib uses roundness * min(w, h) / 2 as the radius.
  """
  if hasattr(rect_or_h, "height"):  # rl.Rectangle is a cffi factory, not a type
    m = min(rect_or_h.width, rect_or_h.height)
  else:
    m = min(rect_or_h, rect_w) if rect_w is not None else rect_or_h
  if m <= 0:
    return 0.0
  return max(0.0, min(1.0, 2.0 * radius_px / m))


def draw_panel(rect: rl.Rectangle, color: rl.Color | None = None, radius: float = Radius.MD,
               outline: rl.Color | None = None, outline_px: float = 2.0) -> None:
  """Flat Console panel: no glow, no shadow, optional hairline."""
  rl.draw_rectangle_rounded(rect, roundness(rect, radius), 8, color if color is not None else Onroad.PANEL)
  if outline is not None and outline.a > 0:
    rl.draw_rectangle_rounded_lines_ex(rect, roundness(rect, radius), 8, outline_px, outline)


def draw_bar(rect: rl.Rectangle, frac: float, fill: rl.Color, track: rl.Color | None = None) -> None:
  """Squared Console bar: track plus a left-anchored fill, 2 px corners."""
  frac = max(0.0, min(1.0, frac))
  rl.draw_rectangle_rounded(rect, roundness(rect, Radius.XS), 4, track if track is not None else Console.BG_TRACK)
  if frac > 0:
    fill_rect = rl.Rectangle(rect.x, rect.y, max(1.0, rect.width * frac), rect.height)
    rl.draw_rectangle_rounded(fill_rect, roundness(fill_rect, Radius.XS), 4, fill)


def draw_status_dot(cx: float, cy: float, r: float, color: rl.Color) -> None:
  rl.draw_circle(int(cx), int(cy), r, color)


# Driving-screen type scale. The device is ~2160x1080 at arm's length, so the Console
# web scale is multiplied, but the ratios and the two weights stay the same.
class OnroadType:
  SPEED = 176        # current speed numeral (600)
  SPEED_UNIT = 56    # unit under the speed (400, muted)
  SET_LABEL = 36     # "MAX" label (600, caption style)
  SET_SPEED = 88     # set speed numeral (600)
  STAT_VALUE = 52    # HUD stat values (600)
  STAT_LABEL = 30    # HUD stat labels (400, muted)
  STAT_UNIT = 30     # units next to values (400, muted)
  PILL = 46          # small alert pill line 1 (600)
  PILL_SUB = 38      # small alert pill line 2 (400)


__all__ = [
  "Console", "Onroad", "Space", "Radius", "OnroadType", "ACCENTS", "ACCENT_NAMES", "ACCENT_LABELS",
  "hex_color", "with_alpha", "accent_alpha", "fade", "mix", "copy", "set_accent", "current_accent",
  "roundness", "draw_panel", "draw_bar", "draw_status_dot",
]
