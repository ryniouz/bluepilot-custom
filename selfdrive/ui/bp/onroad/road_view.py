"""
Console road view: what the driving screen draws over the camera, and the lead vehicle card.

  path         the planned path as a soft ribbon in the engagement colour, fading toward the
               horizon; neutral while the plan is not asking for throttle. Experimental mode
               keeps openpilot's acceleration gradient.
  lane lines   the two lines of our lane in white, neighbouring lanes fainter, road edges red
  lead marker  a squared bracket under the lead vehicle, coloured by how close it is in time
  lead card    a fixed card under the experimental-mode button: distance, lead speed, time gap,
               relative speed and a time-gap bar

What shows is chosen in the quick-controls sheet ("Road view") and stored as a bitmask in the
BPRoadView param.
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
SHOW_LEAD_CARD = 1 << 8   # bit 7 unused

DEFAULT_SHOW = (SHOW_DISTANCE | SHOW_LEAD_SPEED | SHOW_GAP | SHOW_LANES | SHOW_EDGES | SHOW_NEIGHBOURS |
                SHOW_LEAD_CARD)
PARAM = "BPRoadView"

# (bit, label) in the order the settings sheet lists them
OPTIONS = (
  (SHOW_LEAD_CARD, "Lead card"),
  (SHOW_DISTANCE, "Distance"),
  (SHOW_LEAD_SPEED, "Lead speed"),
  (SHOW_GAP, "Time gap"),
  (SHOW_RELATIVE, "Relative speed"),
  (SHOW_LANES, "Lane lines"),
  (SHOW_NEIGHBOURS, "Next lanes"),
  (SHOW_EDGES, "Road edges"),
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

  def on(self, bit: int) -> bool:
    return bool(self.value & bit)

  def toggle(self, bit: int):
    self._value = self.value ^ bit
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

MARK_T = 10           # bracket thickness


def draw_lead_marker(x: float, y: float, w: float, color: rl.Color, alpha: float, vision: bool):
  """Squared bracket under the lead: a thick base with two short uprights. Camera-only leads are
  drawn open (uprights only) so radar and camera read differently without another colour."""
  a = int(255 * alpha)
  c = with_alpha(color, a)
  ink = with_alpha(Console.FRAME_INK, int(150 * alpha))
  h = max(18.0, w * 0.22)
  x0, x1 = x - w / 2, x + w / 2
  parts = [rl.Rectangle(x0, y - h, MARK_T, h + MARK_T), rl.Rectangle(x1 - MARK_T, y - h, MARK_T, h + MARK_T)]
  if not vision:
    parts.append(rl.Rectangle(x0, y, w, MARK_T))
  else:
    seg = w * 0.22
    parts += [rl.Rectangle(x0, y, seg, MARK_T), rl.Rectangle(x1 - seg, y, seg, MARK_T)]
  for p in parts:  # a dark keyline keeps the bracket legible on bright roads
    rl.draw_rectangle_rec(rl.Rectangle(p.x - 2, p.y - 2, p.width + 4, p.height + 4), ink)
  for p in parts:
    rl.draw_rectangle_rec(p, c)


# -- lead card ---------------------------------------------------------------------------------

CARD_W = 340
CARD_PAD = 26
CARD_R = 24           # kit PANEL_R
HEAD = 30
ROW_H = 60
ROW_LABEL = 28
ROW_VALUE = 40
BAR_H = 20


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
    rows.append(("Relative", *_fmt_speed(lead.v_rel, metric, signed=True),
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
  D.text_right("Radar" if lead.radar else "Camera", rx, hy + 2, ROW_LABEL, Console.TEXT_MUTED)

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
