"""
Console road view: what the driving screen draws over the camera, and the lead vehicle card.

  path         the planned path as a soft ribbon in the engagement colour, fading toward the
               horizon; neutral while the plan is not asking for throttle. Experimental mode
               keeps openpilot's acceleration gradient.
  lane lines   the two lines of our lane in white, neighbouring lanes fainter, road edges red
  lead marker  a mark on the lead vehicle (style below), coloured by how close it is in time
  speed tag    optional: the lead vehicle's speed in a small tag right beside it
  lead card    a fixed card under the experimental-mode button: distance, lead speed, time gap,
               relative speed and a time-gap bar

What shows is picked as a preset (Standard, Large speed, Clean, Detailed) or Custom, in the quick-controls
sheet ("Road view") or Screen > Road view, and stored as a bitmask in the BPRoadView param: the preset in
bits 13-15, the Custom switches in the low bits (kept while a preset is on, so Custom comes back as it was).
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import pyray as rl

from openpilot.common.constants import CV
from openpilot.common.params import Params
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.lib.theme import Console, Onroad, roundness, with_alpha

# -- what to show -------------------------------------------------------------------------

SHOW_DISTANCE = 1 << 0
SHOW_LEAD_SPEED = 1 << 1
SHOW_GAP = 1 << 2
SHOW_RELATIVE = 1 << 3
SHOW_LANES = 1 << 4
SHOW_EDGES = 1 << 5
SHOW_NEIGHBOURS = 1 << 6
SHOW_SPEED_TAG = 1 << 7   # lead speed beside the car (off by default)
SHOW_LEAD_CARD = 1 << 8
MARKER_SHIFT = 9          # bits 9-10: lead marker style, an index into LEAD_STYLES
MARKER_MASK = 0b11 << MARKER_SHIFT
LC_SHIFT = 11             # bits 11-12: lane change cue, an index into LC_STYLES
LC_MASK = 0b11 << LC_SHIFT
PRESET_SHIFT = 13         # bits 13-15: an index into PRESETS (0 = Custom, the low bits as set)
PRESET_MASK = 0b111 << PRESET_SHIFT
SHOW_BIG_SPEED = 1 << 16  # a much larger own speed on the speed card
SHOW_BITS = (1 << 9) - 1 | SHOW_BIG_SPEED

CUSTOM_DEFAULT = (SHOW_DISTANCE | SHOW_LEAD_SPEED | SHOW_GAP | SHOW_LANES | SHOW_EDGES | SHOW_NEIGHBOURS |
                  SHOW_LEAD_CARD)

# (key, label, what it shows, bits). Marker and lane change styles stay the driver's own in every preset.
PRESETS = (
  ("custom", "Custom", "Your own switches", 0),
  ("standard", "Standard", "Lead card with distance, speed and gap; all lane lines",
   SHOW_LEAD_CARD | SHOW_DISTANCE | SHOW_LEAD_SPEED | SHOW_GAP | SHOW_LANES | SHOW_NEIGHBOURS | SHOW_EDGES),
  ("large", "Large speed", "Big speed; the lead shows only its speed and radar or camera",
   SHOW_BIG_SPEED | SHOW_LEAD_CARD | SHOW_LEAD_SPEED | SHOW_LANES | SHOW_EDGES),
  ("clean", "Clean", "Your lane only, no lead card",
   SHOW_LANES),
  ("detailed", "Detailed", "Everything, with closing speed and a tag on the lead",
   SHOW_LEAD_CARD | SHOW_DISTANCE | SHOW_LEAD_SPEED | SHOW_GAP | SHOW_RELATIVE | SHOW_SPEED_TAG | SHOW_LANES |
   SHOW_NEIGHBOURS | SHOW_EDGES),
)
PRESET_ORDER = (1, 2, 3, 4, 0)  # how pickers list them: Standard first, Custom last

DEFAULT_SHOW = CUSTOM_DEFAULT | (1 << PRESET_SHIFT)  # new installs start on Standard
PARAM = "BPRoadView"

LEAD_STYLES = ("floor", "bracket", "corners", "chevron")
LC_STYLES = ("pointer", "off")  # lane_change_fx.py; Lucas picked Pointer (2026-10-15), the other cues are gone
LC_STYLE_LABELS = {"pointer": "Pointer", "off": "Off"}
LC_OFF = 3                       # stored value for Off; 0-2 were earlier cue styles and now mean Pointer


def lc_index(value: int) -> int:
  """BPRoadView -> index into LC_STYLES."""
  return 1 if (value & LC_MASK) >> LC_SHIFT == LC_OFF else 0


def lc_bits(index: int) -> int:
  return (LC_OFF if index else 0) << LC_SHIFT

# (bit, label) in the order the settings sheet lists them
OPTIONS = (
  (SHOW_LEAD_CARD, "Lead card"),
  (SHOW_SPEED_TAG, "Speed tag"),     # speed beside the car
  (SHOW_DISTANCE, "Distance"),
  (SHOW_LEAD_SPEED, "Lead speed"),
  (SHOW_GAP, "Time gap"),
  (SHOW_RELATIVE, "Closing"),
  (SHOW_LANES, "Lane lines"),
  (SHOW_NEIGHBOURS, "Next lanes"),
  (SHOW_EDGES, "Road edges"),
  (SHOW_BIG_SPEED, "Large speed"),
)


class RoadViewPrefs:
  """Reads BPRoadView about once a second; writes go straight to the param."""

  def __init__(self):
    self._params = Params()
    self._value = DEFAULT_SHOW
    self._read_t = 0.0

  @property
  def value(self) -> int:
    now = time.monotonic()
    if now - self._read_t > 1.0:
      self._read_t = now
      try:
        v = self._params.get(PARAM, return_default=True)
        self._value = int(v) if v is not None else DEFAULT_SHOW
      except Exception:
        self._value = DEFAULT_SHOW
    return self._value

  @property
  def preset(self) -> int:
    i = (self.value & PRESET_MASK) >> PRESET_SHIFT
    return i if i < len(PRESETS) else 0

  def set_preset(self, i: int):
    self._write((self.value & ~PRESET_MASK) | (int(i) << PRESET_SHIFT))

  @property
  def shown(self) -> int:
    """The switches in effect: the preset's, or the Custom ones."""
    p = self.preset
    return PRESETS[p][3] if p else self.value & SHOW_BITS

  def on(self, bit: int) -> bool:
    return bool(self.shown & bit)

  @property
  def big_speed(self) -> bool:
    return self.on(SHOW_BIG_SPEED)

  def customise(self):
    """Switch to Custom, starting from the current preset's switches."""
    if self.preset:
      self._write((self.value & ~(SHOW_BITS | PRESET_MASK)) | PRESETS[self.preset][3])

  def toggle(self, bit: int):
    """Flipping a switch while a preset is on starts Custom from that preset."""
    self.customise()
    self._write(self.value ^ bit)

  @property
  def marker(self) -> str:
    return LEAD_STYLES[(self.value & MARKER_MASK) >> MARKER_SHIFT]

  def next_marker(self):
    i = ((self.value & MARKER_MASK) >> MARKER_SHIFT) + 1
    self._write((self.value & ~MARKER_MASK) | ((i % len(LEAD_STYLES)) << MARKER_SHIFT))

  @property
  def lane_change(self) -> str:
    return LC_STYLES[lc_index(self.value)]

  def next_lane_change(self):
    self._write((self.value & ~LC_MASK) | lc_bits(1 - lc_index(self.value)))

  def _write(self, value: int):
    self._value = value
    try:
      self._params.put(PARAM, int(self._value))
    except Exception:
      pass


road_prefs = RoadViewPrefs()


# -- lead state ------------------------------------------------------------------------------

@dataclass
class LeadInfo:
  d_rel: float = 0.0       # m
  v_rel: float = 0.0       # m/s, negative when closing
  v_lead: float = 0.0      # m/s
  v_ego: float = 0.0       # m/s
  radar: bool = False

  @property
  def gap_s(self) -> float | None:
    return self.d_rel / self.v_ego if self.v_ego > 1.0 and self.d_rel > 0 else None

  @property
  def ttc_s(self) -> float | None:
    return self.d_rel / -self.v_rel if self.v_rel < -0.3 and self.d_rel > 0 else None


GAP_FULL_S = 3.0      # the gap bar is full at 3 s


def lead_level(lead: LeadInfo) -> rl.Color:
  """Danger when a collision is near in time; warning when following tight or closing; otherwise info."""
  gap, ttc = lead.gap_s, lead.ttc_s
  if (ttc is not None and ttc < 3.0) or (gap is not None and gap < 0.6):
    return Console.DANGER
  if (ttc is not None and ttc < 6.0) or (gap is not None and gap < 1.2):
    return Console.WARNING
  return Onroad.LEAD_RADAR


def gap_color(gap: float) -> rl.Color:
  if gap < 0.8:
    return Console.DANGER
  if gap < 1.4:
    return Console.WARNING
  return Console.SUCCESS


# -- lead marker -------------------------------------------------------------------------------

MARK_T = 10           # stroke thickness
# Marker styles in settings order; index 0 (floor pad) is the default. Lucas 2026-10-14: offer all.
LEAD_STYLE_LABELS = {"floor": "Floor", "bracket": "Bracket", "corners": "Corners", "chevron": "Chevron"}


def _keyed(parts: list[rl.Rectangle], color: rl.Color, alpha: float):
  """Squared parts with a dark keyline so they stay legible on bright roads."""
  ink = with_alpha(Console.FRAME_INK, int(150 * alpha))
  for p in parts:
    rl.draw_rectangle_rec(rl.Rectangle(p.x - 2, p.y - 2, p.width + 4, p.height + 4), ink)
  c = with_alpha(color, int(255 * alpha))
  for p in parts:
    rl.draw_rectangle_rec(p, c)


def draw_lead_marker(x: float, y: float, w: float, color: rl.Color, alpha: float, vision: bool, style: str | None = None):
  """Mark the lead at its ground contact (x, y) with width w. Camera-only leads draw lighter
  (open bracket, hollow pad, thinner corners) so radar and camera read differently without
  another colour."""
  style = style or road_prefs.marker
  x0, x1 = x - w / 2, x + w / 2
  if style == "floor":
    # A flat pad on the road under the car, like a highlighted parking spot
    pad = rl.Rectangle(x0 - w * 0.06, y - w * 0.05, w * 1.12, max(14.0, w * 0.16))
    rr = roundness(pad, pad.height / 2)
    if not vision:
      rl.draw_rectangle_rounded(pad, rr, 12, with_alpha(color, int(110 * alpha)))
    rl.draw_rectangle_rounded_lines_ex(pad, rr, 12, 6, with_alpha(color, int(255 * alpha)))
  elif style == "corners":
    # Four corner ticks framing the car, like a camera focus frame
    h = w * 0.82
    t = MARK_T if not vision else MARK_T * 0.7
    L = max(16.0, w * 0.22)
    bx0, bx1, by0, by1 = x0 - w * 0.06, x1 + w * 0.06, y - h, y + t
    parts = []
    for cx, sx in ((bx0, 1), (bx1, -1)):
      for cy, sy in ((by0, 1), (by1, -1)):
        hx = cx if sx > 0 else cx - L
        vy = cy if sy > 0 else cy - L
        parts.append(rl.Rectangle(hx, cy if sy > 0 else cy - t, L, t))
        parts.append(rl.Rectangle(cx if sx > 0 else cx - t, vy, t, L))
    _keyed(parts, color, alpha)
  elif style == "chevron":
    # A small downward chevron floating over the roof
    h = w * 0.82
    s = max(16.0, w * 0.16)
    cy = y - h - s * 1.3
    ink = with_alpha(Console.FRAME_INK, int(150 * alpha))
    c = with_alpha(color, int(255 * alpha))
    pts = [rl.Vector2(x - s, cy - s * 0.5), rl.Vector2(x, cy + s * 0.5), rl.Vector2(x + s, cy - s * 0.5)]
    if not vision:
      rl.draw_triangle(pts[0], pts[1], pts[2], c)
    for wd, col in ((MARK_T + 4, ink), (MARK_T, c)):
      rl.draw_line_ex(pts[0], pts[1], wd, col)
      rl.draw_line_ex(pts[1], pts[2], wd, col)
      for p in pts:
        rl.draw_circle_v(p, wd / 2, col)
  else:
    # Squared bracket under the lead: thick base and two short uprights
    h = max(18.0, w * 0.22)
    parts = [rl.Rectangle(x0, y - h, MARK_T, h + MARK_T), rl.Rectangle(x1 - MARK_T, y - h, MARK_T, h + MARK_T)]
    if not vision:
      parts.append(rl.Rectangle(x0, y, w, MARK_T))
    else:
      seg = w * 0.22
      parts += [rl.Rectangle(x0, y, seg, MARK_T), rl.Rectangle(x1 - seg, y, seg, MARK_T)]
    _keyed(parts, color, alpha)


TAG_H = 64
TAG_VALUE = 40
TAG_UNIT = 24
TAG_PAD = 18
TAG_GAP = 22          # from the car's side


def draw_speed_tag(x: float, y: float, w: float, lead: LeadInfo, metric: bool, alpha: float, bounds: rl.Rectangle):
  """The lead's speed in a small Console tag beside the car, level with its middle. Sits on the
  right of the car, or the left when the right would leave the screen. A dot in the lead colour
  ties it to the marker."""
  value, unit = _fmt_speed(lead.v_lead, metric)
  vw, uw = D.text_w(value, TAG_VALUE, semi=True), D.text_w(unit, TAG_UNIT)
  tw = TAG_PAD * 2 + 14 + 12 + vw + 8 + uw
  cy = y - w * 0.4
  tx = x + w / 2 + TAG_GAP
  if tx + tw > bounds.x + bounds.width - 24:
    tx = x - w / 2 - TAG_GAP - tw
  r = rl.Rectangle(tx, cy - TAG_H / 2, tw, TAG_H)
  rl.draw_rectangle_rounded(r, 1.0, 16, with_alpha(Onroad.PANEL_SOLID, int(0xE0 * alpha)))
  rl.draw_rectangle_rounded_lines_ex(r, 1.0, 16, 2, with_alpha(Console.BORDER_DEFAULT, int(255 * alpha)))
  D.dot(r.x + TAG_PAD + 7, cy, 7, with_alpha(lead_level(lead), int(255 * alpha)))
  vx = r.x + TAG_PAD + 14 + 12
  D.text(value, vx, cy - TAG_VALUE / 2 - 2, TAG_VALUE, with_alpha(Console.TEXT_PRIMARY, int(255 * alpha)), semi=True)
  D.text(unit, vx + vw + 8, cy - TAG_VALUE / 2 + (TAG_VALUE - TAG_UNIT) * 0.72, TAG_UNIT, with_alpha(Console.TEXT_MUTED, int(255 * alpha)))


# -- lead card ---------------------------------------------------------------------------------

CARD_W = 340
CARD_PAD = 26
CARD_R = 24           # kit PANEL_R
HEAD = 30
ROW_H = 60
ROW_LABEL = 28
ROW_VALUE = 40
BAR_H = 20
COMPACT_VALUE = 60    # the lead's speed when it is all the card shows
ROW_BITS = SHOW_DISTANCE | SHOW_LEAD_SPEED | SHOW_GAP | SHOW_RELATIVE


def _compact(show: int) -> bool:
  """Speed only (Large speed preset): the card is just the lead's speed and where it comes from."""
  return show & ROW_BITS == SHOW_LEAD_SPEED


def _fmt_dist(d: float, metric: bool) -> tuple[str, str]:
  if metric:
    return f"{max(0.0, d):.0f}", "m"
  return f"{max(0.0, d) * 3.28084:.0f}", "ft"


def _fmt_speed(v: float, metric: bool, signed: bool = False) -> tuple[str, str]:
  val = v * (CV.MS_TO_KPH if metric else CV.MS_TO_MPH)
  if signed:
    s = f"{val:+.0f}" if abs(val) >= 0.5 else "0"
    return s, ("km/h" if metric else "mph")
  return f"{max(0.0, val):.0f}", ("km/h" if metric else "mph")


def lead_card_height(show: int) -> float:
  if _compact(show):
    return CARD_PAD * 2 + HEAD + 10 + COMPACT_VALUE
  rows = sum(1 for b in (SHOW_DISTANCE, SHOW_LEAD_SPEED, SHOW_GAP, SHOW_RELATIVE) if show & b)
  h = CARD_PAD * 2 + HEAD + 12 + rows * ROW_H
  if show & SHOW_GAP:
    h += BAR_H + 12
  return h


def draw_lead_card(x: float, y: float, lead: LeadInfo, show: int, metric: bool, alpha: float = 1.0):
  rows: list[tuple[str, str, str, rl.Color]] = []
  if show & SHOW_DISTANCE:
    rows.append(("Distance", *_fmt_dist(lead.d_rel, metric), Console.TEXT_PRIMARY))
  if show & SHOW_LEAD_SPEED:
    rows.append(("Speed", *_fmt_speed(lead.v_lead, metric), Console.TEXT_PRIMARY))
  gap = lead.gap_s
  if show & SHOW_GAP:
    rows.append(("Gap", f"{gap:.1f}" if gap is not None and gap < 99 else "–", "s",
                 gap_color(gap) if gap is not None else Console.TEXT_PRIMARY))
  if show & SHOW_RELATIVE:
    rows.append(("Closing", *_fmt_speed(lead.v_rel, metric, signed=True),
                 Console.WARNING if lead.v_rel < -1.0 else Console.TEXT_PRIMARY))
  if not rows:
    return

  r = rl.Rectangle(x, y, CARD_W, lead_card_height(show))
  rl.draw_rectangle_rounded(r, roundness(r, CARD_R), 10, with_alpha(Onroad.PANEL_SOLID, int(0xEB * alpha)))
  rl.draw_rectangle_rounded_lines_ex(r, roundness(r, CARD_R), 10, 2, with_alpha(Console.BORDER_DEFAULT, int(255 * alpha)))

  # Header: status dot, "Lead", source on the right
  lx, rx = r.x + CARD_PAD, r.x + r.width - CARD_PAD
  hy = r.y + CARD_PAD
  D.dot(lx + 9, hy + HEAD / 2, 9, lead_level(lead))
  D.text("Lead", lx + 30, hy, HEAD, Console.TEXT_PRIMARY, semi=True)
  D.text_right("Radar" if lead.radar else "Vision", rx, hy + 2, ROW_LABEL, Console.TEXT_MUTED)
  if _compact(show):
    value, unit = _fmt_speed(lead.v_lead, metric)
    vy = hy + HEAD + 10
    uw = D.text_w(unit, ROW_LABEL + 2)
    D.text(unit, rx - uw, vy + COMPACT_VALUE * 0.78 - ROW_LABEL, ROW_LABEL + 2, Console.TEXT_MUTED)
    D.text_right(value, rx - uw - 12, vy, COMPACT_VALUE, Console.TEXT_PRIMARY, semi=True)
    return

  cy = hy + HEAD + 12
  for label, value, unit, color in rows:
    rl.draw_rectangle_rec(rl.Rectangle(lx, cy, rx - lx, 2), Console.BORDER_SUBTLE)
    vy = cy + (ROW_H - ROW_VALUE) / 2
    D.text(label, lx, vy + (ROW_VALUE - ROW_LABEL) * 0.7, ROW_LABEL, Console.TEXT_MUTED)
    uw = D.text_w(unit, ROW_LABEL)
    D.text(unit, rx - uw, vy + (ROW_VALUE - ROW_LABEL) * 0.7, ROW_LABEL, Console.TEXT_MUTED)
    D.text_right(value, rx - uw - 10, vy, ROW_VALUE, color, semi=True)
    cy += ROW_H
    if label == "Gap" and gap is not None:
      K.bar(rl.Rectangle(lx, cy, rx - lx, BAR_H), min(1.0, gap / GAP_FULL_S), gap_color(gap))
      cy += BAR_H + 12
    elif label == "Gap":
      K.bar(rl.Rectangle(lx, cy, rx - lx, BAR_H), 0.0, Console.SUCCESS)
      cy += BAR_H + 12
