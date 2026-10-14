"""
Settings search: the magnifier in the header, on every settings section. It looks through every page's title
and, on Console form pages, every card and row (Advanced ones too, whatever the mode), and lists what it finds
grouped by section with where it lives ("Steering · Lane changes"). Tapping a result opens that page with all of
its rows shown, so an Advanced row found from Basic mode is right there.

Pages that are not form pages can add rows to the index with search_entries() -> [(card, title, sub, adv)].
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.console.form import FormPage, Nav, Note, Section

MAX_PER_SECTION = 12


@dataclass
class Hit:
  dest_title: str
  dest_icon: str
  page_title: str
  card: str            # "" for the page itself
  title: str
  sub: str
  adv: bool
  open: Callable[[], None]
  score: int = 0


def matches(query: str, *texts: str) -> bool:
  hay = " ".join(t for t in texts if t).lower()
  return all(w in hay for w in query.lower().split())


class SearchPage(FormPage):
  def __init__(self, index: Callable[[], list[Hit]], on_edit: Callable[[], None]):
    super().__init__()
    self._index = index
    self._on_edit = on_edit
    self.query = ""
    self._results: list[Hit] = []

  def run(self, query: str) -> None:
    self.query = query.strip()
    self._offset = 0.0
    q = self.query.lower()
    hits = []
    for h in self._index():
      if not matches(q, h.title, h.sub, h.card, h.page_title):
        continue
      t = h.title.lower()
      h.score = 0 if t.startswith(q) else 1 if q in t else 2 if matches(q, h.title) else 3
      hits.append(h)
    self._results = sorted(hits, key=lambda h: h.score)

  def sections(self) -> list[Section]:
    results = self._results
    top = Section(tr("Search"), "search", [
      Nav(tr("Search settings"), tr("Tap to change what you're looking for"), self._on_edit, value=f"\"{self.query}\"")],
      wide=True)
    if not results:
      top.rows.append(Note(tr("Nothing matches. Try a shorter word, like \"lane\" or \"charge\".")))
      return [top]
    top.rows.append(Note(f"{len(results)} " + (tr("result") if len(results) == 1 else tr("results")) +
                         ". " + tr("Advanced settings are included and open with the whole page shown.")))
    groups: dict[str, list[Hit]] = {}
    for h in results:
      groups.setdefault(h.dest_title, []).append(h)
    out = [top]
    for dest, hits in groups.items():
      rows = []
      for h in hits[:MAX_PER_SECTION]:
        where = h.page_title + ("  ·  " + h.card if h.card and h.card != h.page_title else "")
        if h.adv:
          where += "  (" + tr("Advanced") + ")"
        rows.append(Nav(h.title, where, h.open))
      if len(hits) > MAX_PER_SECTION:
        rows.append(Note(f"{len(hits) - MAX_PER_SECTION} " + tr("more here. Add a word to narrow it down.")))
      out.append(Section(dest, hits[0].dest_icon, rows))
    return out

  def visible_sections(self) -> list[Section]:
    return [s for s in self.sections() if s is not None]
