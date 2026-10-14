"""
Console Trips page (Energy > Trips): how much the truck has been driven with the comma.

  This week   drives, distance, time at the wheel
  All time    the same, over the comma's whole life
  Averages    a typical drive: length, time and average speed, and this week's share of the total

Reads the drive stats sunnypilot's Trips panel already fetches from comma connect (ApiCache_DriveStats,
refreshed every 30 s while parked and awake). Distances arrive in miles and show in km.
"""

from __future__ import annotations

import pyray as rl

from openpilot.common.constants import CV
from openpilot.common.params import Params
from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.console.pages.cards import GAP, CardPage
from bluepilot.ui.lib.theme import Console

PARAM_KEY = "ApiCache_DriveStats"
READ_EVERY = 60  # frames


def summarize(group: dict | None) -> dict:
  """{drives, km, hours, avg_km, avg_min, avg_kmh} from one comma connect stats group."""
  group = group or {}
  try:
    drives = int(group.get("routes", 0) or 0)
    km = float(group.get("distance", 0) or 0) * CV.MPH_TO_KPH
    minutes = float(group.get("minutes", 0) or 0)
  except (TypeError, ValueError):
    drives, km, minutes = 0, 0.0, 0.0
  return {
    "drives": drives,
    "km": km,
    "hours": minutes / 60.0,
    "avg_km": km / drives if drives else 0.0,
    "avg_min": minutes / drives if drives else 0.0,
    "avg_kmh": km / (minutes / 60.0) if minutes > 0 else 0.0,
  }


def fmt_km(km: float) -> str:
  return f"{km:,.0f}" if km >= 10 else f"{km:.1f}"


def fmt_hours(h: float) -> tuple[str, str]:
  if h < 1:
    return f"{h * 60:.0f}", "min"
  return (f"{h:,.0f}" if h >= 10 else f"{h:.1f}"), "h"


class TripsPage(CardPage):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._stats: dict = {}
    self._frame = READ_EVERY

  def _read(self):
    self._frame += 1
    if self._frame < READ_EVERY:
      return
    self._frame = 0
    try:
      s = self._params.get(PARAM_KEY)
    except Exception:
      s = None
    self._stats = s if isinstance(s, dict) else {}

  def show_event(self):
    super().show_event()
    self._frame = READ_EVERY

  def has_data(self) -> bool:
    return summarize(self._stats.get("all")).get("drives", 0) > 0

  def subtitle(self) -> str:
    self._read()
    if not self.has_data():
      return tr("Energy") + " | " + tr("No drives yet")
    week = summarize(self._stats.get("week"))
    return tr("Energy") + " | " + f"{week['drives']} " + (tr("drive") if week["drives"] == 1 else tr("drives")) + " " + tr("this week")

  def sub_dot(self):
    return Console.SUCCESS if self.has_data() else Console.TEXT_GHOST

  def _render(self, rect: rl.Rectangle):
    self._hits = []
    self._read()
    if not self.has_data():
      self._empty(rect)
      return
    week, total = summarize(self._stats.get("week")), summarize(self._stats.get("all"))
    head = K.H2 + 20
    strip_h = max(170.0, min(K.STRIP_H + 40, (rect.height - 3 * head - 2 * GAP) / 3))
    share = week["km"] / total["km"] if total["km"] > 0 else 0.0
    sections = []
    for title, caption, s in ((tr("This week"), tr("Last 7 days"), week), (tr("All time"), tr("Since this comma was set up"), total)):
      hv, hu = fmt_hours(s["hours"])
      sections.append((title, caption, [
        K.Stat(tr("Drives"), f"{s['drives']:,}"),
        K.Stat(tr("Distance"), fmt_km(s["km"]), "km"),
        K.Stat(tr("Time driving"), hv, hu),
      ]))
    sections.append((tr("A typical drive"), tr("Averaged over all time"), [
      K.Stat(tr("Distance"), fmt_km(total["avg_km"]), "km"),
      K.Stat(tr("Length"), f"{total['avg_min']:.0f}", "min"),
      K.Stat(tr("Average speed"), f"{total['avg_kmh']:.0f}", "km/h"),
    ]))
    sections[0][2][1].note = f"{share * 100:.0f} % " + tr("of all time")
    y = rect.y
    for title, caption, cells in sections:
      y = K.section_title(rl.Rectangle(rect.x, y, rect.width, K.H2), title, caption)
      K.stat_strip(rl.Rectangle(rect.x, y, rect.width, strip_h), cells)
      y += strip_h + GAP

  def _empty(self, rect: rl.Rectangle):
    w = min(rect.width, 1100)
    r = rl.Rectangle(rect.x + (rect.width - w) / 2, rect.y + 24, w, min(rect.height - 24, 460))
    D.card(r)
    p = D.CARD_PAD + 16
    D.icon("route", r.x + p, r.y + p, 64, Console.TEXT_SECONDARY)
    D.text(tr("No drives yet"), r.x + p + 96, r.y + p + 8, D.H2, semi=True)
    y = r.y + p + 112
    body = tr("Drives, distance and time at the wheel show here after the first drive, once the comma is online " +
              "and registered with comma connect.")
    for ln in D.wrap(body, D.BODY - 2, r.width - 2 * p, 3):
      D.text(ln, r.x + p, y, D.BODY - 2, Console.TEXT_SECONDARY)
      y += 48
