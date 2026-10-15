"""
Console Trips page (Energy > Trips): how much the truck has been driven with the comma.

  This week   drives, distance, time at the wheel
  All time    the same, over the comma's whole life
  Typical     a typical drive: length, time and average speed; this week's share of the total sits under
              this week's distance

Reads the drive stats sunnypilot's Trips panel already fetches from comma connect (ApiCache_DriveStats,
refreshed every 30 s while parked and awake). Distances arrive in miles and show in km.
"""

from __future__ import annotations

import pyray as rl

from openpilot.common.constants import CV
from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.console.form import Custom, FormPage, Note, Section
from bluepilot.ui.lib.theme import Console

PARAM_KEY = "ApiCache_DriveStats"
READ_EVERY = 60  # frames
STATS_H = 44 + K.VAL + 12 + K.CAP + 20


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


def stats_row(cells: list[K.Stat]) -> Custom:
  """Equal cells inside a card: caption, value with its unit, note; hairlines between cells."""
  def draw(r: rl.Rectangle):
    cw = r.width / max(1, len(cells))
    for i, c in enumerate(cells):
      x = r.x + i * cw + (28 if i else 0)
      if i:
        K.vline(r.x + i * cw, r.y + 12, r.y + r.height - 20)
      w = cw - (28 if i else 0) - 12
      D.text(D.fit(c.label, K.CAP, w), x, r.y + 4, K.CAP, Console.TEXT_MUTED)
      D.value_unit(c.value, c.unit, x, r.y + 44, K.VAL, K.CAP)
      if c.note:
        D.text(D.fit(c.note, K.CAP, w), x, r.y + 44 + K.VAL + 12, K.CAP, Console.TEXT_SECONDARY)
  return Custom(STATS_H, draw)


class TripsPage(FormPage):
  def __init__(self):
    super().__init__()
    self._stats: dict = {}
    self._frame = READ_EVERY

  def _read(self):
    self._frame += 1
    if self._frame < READ_EVERY:
      return
    self._frame = 0
    try:
      s = self.p._params.get(PARAM_KEY)
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

  def sections(self) -> list[Section]:
    self._read()
    if not self.has_data():
      return [Section(tr("No drives yet"), "route", [
        Note(tr("Drives, distance and time at the wheel show here after the first drive, once the comma is online " +
                "and registered with comma connect.")),
      ])]
    week, total = summarize(self._stats.get("week")), summarize(self._stats.get("all"))
    share = week["km"] / total["km"] if total["km"] > 0 else 0.0

    def totals(s: dict, note: str = "") -> list[K.Stat]:
      hv, hu = fmt_hours(s["hours"])
      return [K.Stat(tr("Drives"), f"{s['drives']:,}"),
              K.Stat(tr("Distance"), fmt_km(s["km"]), "km", note=note),
              K.Stat(tr("Time driving"), hv, hu)]

    return [
      Section(tr("This week"), "clock", [stats_row(totals(week, f"{share * 100:.0f} % " + tr("of all time")))], wide=True),
      Section(tr("All time"), "route", [stats_row(totals(total))], wide=True),
      Section(tr("A typical drive"), "gauge", [stats_row([
        K.Stat(tr("Distance"), fmt_km(total["avg_km"]), "km"),
        K.Stat(tr("Length"), f"{total['avg_min']:.0f}", "min"),
        K.Stat(tr("Average speed"), f"{total['avg_kmh']:.0f}", "km/h"),
      ])], note=tr("Averaged over every drive since this comma was set up."), wide=True),
    ]
