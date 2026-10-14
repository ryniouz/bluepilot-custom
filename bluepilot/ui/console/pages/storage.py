"""
Console Storage page (System > Storage): what fills the comma's disk, by kind, and how it frees space.

It opens at once: free and total space are read when the page opens, and the split by kind comes from the
last finished scan (saved across restarts, bluepilot/ui/lib/drive_index.py). A fresh scan runs in the
background and the page says "Updating" until it lands. The old page waited for a full scan of every
segment (a stat per file, plus xattrs and route metrics) before showing anything.

  Space      used of total, the thick squared bar split by kind, a row per kind, unsynced drives
  Clean-up   how the comma frees space (deleter thresholds, keep-until-synced)
"""

from __future__ import annotations

import pyray as rl

from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.console import draw as D
from bluepilot.ui.console.form import Custom, FormPage, Info, Section
from bluepilot.ui.console.pages.drives import fmt_bytes, keep_until_synced, storage_bar, storage_breakdown
from bluepilot.ui.lib.drive_index import indexer
from bluepilot.ui.lib.theme import Console, roundness


def _size(n: int) -> str:
  v, u = fmt_bytes(n)
  return f"{v} {u}"


class StoragePage(FormPage):
  def show_event(self):
    super().show_event()
    indexer().request(force=True)

  def sections(self) -> list[Section]:
    indexer().request()
    st = storage_breakdown()
    if st is None:  # no disk at all (PC without a log root)
      return [Section(tr("Space"), "storage", [Info(tr("Storage"), tr("Not available"))])]
    used = st.total - st.free
    pct_free = 100.0 * st.free / st.total if st.total else 0.0

    def headline(r: rl.Rectangle):
      uv, uu = fmt_bytes(used)
      D.value_unit(uv, uu, r.x, r.y + 4, 88, 36)
      vw = D.text_w(uv, 88, semi=True) + 12 + D.text_w(uu, 36)
      D.text(tr("used of") + " " + _size(st.total), r.x + vw + 20, r.y + 46, D.BODY, Console.TEXT_MUTED)
      storage_bar(rl.Rectangle(r.x, r.y + 120, r.width, 44), st)

    def kind_row(color, label: str, n: int):
      def draw(r: rl.Rectangle):
        sw = rl.Rectangle(r.x, r.y + 18, 28, 28)
        rl.draw_rectangle_rounded(sw, roundness(sw, 6), 4, color)
        D.text(D.fit(label, D.LABEL, r.width - 240), r.x + 48, r.y + 16, D.LABEL, Console.TEXT_SECONDARY)
        D.text_right(_size(n), r.x + r.width, r.y + 16, D.LABEL, semi=True)
      return Custom(64, draw)

    rows: list = [Custom(196, headline)]
    rows += [kind_row(sl.color, sl.label, sl.bytes) for sl in st.slices if sl.bytes > 0]
    rows.append(kind_row(Console.BG_TRACK, tr("Free") + f" ({pct_free:.0f} %)", st.free))
    if st.unsynced > 0:
      rows.append(kind_row(Console.WARNING, tr("Not synced to Citadel yet"), st.unsynced))
    idx = indexer()
    if idx.busy or not idx.index.scanned_at and not st.from_bridge:
      rows.append(Info(tr("By kind"), tr("Updating…"), dot=Console.ACCENT))

    keep = keep_until_synced(self.p._params)
    cleanup = [
      Info(tr("Oldest drives go"), tr("Under 5 % free") if keep else tr("Under 10 % free")),
      Info(tr("Bookmarked"), tr("Last 5 go last")),
    ]
    if keep:
      cleanup.append(Info(tr("Drives not synced to Citadel"), tr("Kept until 5 % free")))
    return [
      Section(tr("Space"), "storage", rows),
      Section(tr("Clean-up"), "close", cleanup,
              note=tr("Space frees up by itself while the comma is parked. Bookmarked drives are kept longest.")),
    ]
