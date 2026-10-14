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

The accent follows the BPConsoleAccent param (blue, teal, violet, ember). Accent colours
are mutable rl.Color objects that are rewritten in place, so modules that imported them
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


def with_alpha(color: rl.Color, alpha: int | float) -> rl.Color:
  """Copy of color with a new alpha. Floats in [0, 1] are treated as a fraction."""
  if isinstance(alpha, float) and alpha <= 1.0:
    alpha = int(255 * alpha)
  return rl.Color(color.r, color.g, color.b, max(0, min(255, int(alpha))))


def fade(color: rl.Color, factor: float) -> rl.Color:
  """Multiply a colour's existing alpha by factor."""
  return rl.Color(color.r, color.g, color.b, max(0, min(255, int(color.a * factor))))


def mix(a: rl.Color, b: rl.Color, t: float) -> rl.Color:
  """Linear blend from a (t=0) to b (t=1), alpha included."""
  t = max(0.0, min(1.0, t))
  return rl.Color(
    int(a.r + (b.r - a.r) * t),
    int(a.g + (b.g - a.g) * t),
    int(a.b + (b.b - a.b) * t),
    int(a.a + (b.a - a.a) * t),
  )


def copy(color: rl.Color) -> rl.Color:
  return rl.Color(color.r, color.g, color.b, color.a)


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


# Accent themes. Only the accent family changes; surfaces and status never do.
ACCENTS: dict[str, dict[str, str]] = {
  "blue": {"ACCENT": "#4797ff", "ACCENT_TEXT": "#4797ff", "ACCENT_FILL": "#005ed9",
           "ACCENT_FILL_HOVER": "#006fff", "ACCENT_TINT": "#05254d", "ACCENT_TINT_STRONG": "#0b4ead"},
  "teal": {"ACCENT": "#2dd4bf", "ACCENT_TEXT": "#2dd4bf", "ACCENT_FILL": "#0f766e",
           "ACCENT_FILL_HOVER": "#0d9488", "ACCENT_TINT": "#0b2f2c", "ACCENT_TINT_STRONG": "#115e59"},
  "violet": {"ACCENT": "#a78bfa", "ACCENT_TEXT": "#a78bfa", "ACCENT_FILL": "#6d28d9",
             "ACCENT_FILL_HOVER": "#7c3aed", "ACCENT_TINT": "#251a45", "ACCENT_TINT_STRONG": "#4c2fa0"},
  "ember": {"ACCENT": "#ff8a3d", "ACCENT_TEXT": "#ff8a3d", "ACCENT_FILL": "#c2410c",
            "ACCENT_FILL_HOVER": "#ea580c", "ACCENT_TINT": "#3a2010", "ACCENT_TINT_STRONG": "#7c2d12"},
}
ACCENT_NAMES = list(ACCENTS.keys())
ACCENT_LABELS = ["Blue", "Teal", "Violet", "Ember"]

_current_accent = "blue"
_derived: list[tuple[rl.Color, str, int]] = []


def accent_alpha(alpha: int, attr: str = "ACCENT") -> rl.Color:
  """An accent-family colour at a fixed alpha that keeps following the accent theme."""
  c = with_alpha(getattr(Console, attr), alpha)
  _derived.append((c, attr, alpha))
  return c


def set_accent(name: str) -> None:
  """Switch the accent family in place. Unknown names fall back to blue."""
  global _current_accent
  name = (name or "blue").strip().lower()
  if name not in ACCENTS:
    name = "blue"
  if name == _current_accent:
    return
  for attr, value in ACCENTS[name].items():
    _assign(getattr(Console, attr), hex_color(value))
  for c, attr, alpha in _derived:
    _assign(c, with_alpha(getattr(Console, attr), alpha))
  _current_accent = name


def current_accent() -> str:
  return _current_accent


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
  BORDER_ENGAGED = mix(Console.SUCCESS, Console.BG_PAGE, 0.35)
  BORDER_OVERRIDE = mix(Console.WARNING, Console.BG_PAGE, 0.35)
  BORDER_LAT_ONLY = mix(Console.INFO, Console.BG_PAGE, 0.35)
  BORDER_LONG_ONLY = mix(Console.PURPLE, Console.BG_PAGE, 0.35)

  # Alerts
  ALERT_NORMAL = with_alpha(Console.BG_PANEL, 0xF2)
  ALERT_PROMPT = mix(Console.WARNING, Console.BG_PAGE, 0.25)
  ALERT_CRITICAL = mix(Console.DANGER_FILL, Console.BG_PAGE, 0.2)

  # Lead markers
  LEAD_RADAR = Console.INFO
  LEAD_VISION = Console.WARNING
  LEAD_CLOSE = Console.DANGER

  # Text over the camera
  TEXT = Console.TEXT_PRIMARY
  TEXT_DIM = Console.TEXT_MUTED
  TEXT_GHOST = Console.TEXT_GHOST
  SHADOW = rl.Color(0, 0, 0, 140)


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
