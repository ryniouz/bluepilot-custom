"""
Console Drives section: Previous drives, Offloading and Storage.

  Previous drives  every drive still on the comma, newest first, grouped by day, with distance,
                   length and whether Citadel has synced it
  Offloading       comma connect uploads (uploaderState) and the Citadel sync from the data-export bridge
  Storage          how the disk is used, with one thick stacked bar, and what gets deleted when

All three read bluepilot.ui.lib.drive_index, which scans the disk on a background thread.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import pyray as rl

from openpilot.common.params import Params
from openpilot.system.ui.lib.application import MouseEvent
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.console.home import _param, has_param
from bluepilot.ui.lib import bridge_status
from bluepilot.ui.lib.drive_index import Drive, indexer
from bluepilot.ui.lib.theme import Console, roundness

GAP = 32
ROW_H = 128
DAY_H = 72
DRAG_PX = 16
GB = 1024 ** 3


def fmt_bytes(n: float) -> tuple[str, str]:
  if n >= GB:
    return (f"{n / GB:.1f}", "GB")
  if n >= 1024 ** 2:
    return (f"{n / 1024 ** 2:.0f}", "MB")
  return (f"{n / 1024:.0f}", "kB")


def fmt_duration(s: float) -> str:
  m = int(round(s / 60))
  if m < 60:
    return f"{m} min"
  return f"{m // 60} h {m % 60:02d} min"


def fmt_hours(s: float) -> str:
  return f"{s / 3600:.1f}"


def day_label(ts: float) -> str:
  if ts <= 0:
    return tr("Date unknown")
  today = time.localtime()
  d = time.localtime(ts)
  if (d.tm_year, d.tm_yday) == (today.tm_year, today.tm_yday):
    return tr("Today")
  yesterday = time.localtime(time.mktime(today) - 86400)
  if (d.tm_year, d.tm_yday) == (yesterday.tm_year, yesterday.tm_yday):
    return tr("Yesterday")
  return time.strftime("%A, %B %-d", d)


def keep_until_synced(params: Params) -> bool:
  """Mirrors the deleter: only active with the export bridge on and its keep setting on."""
  if not has_param(params, "BPBridgeEnabled"):
    return False
  return bool(_param(params, "BPBridgeEnabled", False)) and bool(_param(params, "BPKeepUntilSynced", True))


class _Scroll:
  """Vertical drag-to-scroll for a list drawn inside a clip rect."""

  def __init__(self):
    self.offset = 0.0
    self.content_h = 0.0
    self.view = rl.Rectangle(0, 0, 0, 0)
    self._press: tuple[float, float] | None = None
    self._press_offset = 0.0
    self.dragging = False

  def clamp(self):
    self.offset = max(0.0, min(self.offset, max(0.0, self.content_h - self.view.height)))

  def event(self, ev: MouseEvent):
    if ev.left_pressed and D.hit(self.view, ev.pos):
      self._press = (ev.pos.x, ev.pos.y)
      self._press_offset = self.offset
      self.dragging = False
    elif ev.left_down and self._press is not None:
      dy = ev.pos.y - self._press[1]
      if not self.dragging and abs(dy) > DRAG_PX:
        self.dragging = True
      if self.dragging:
        self.offset = self._press_offset - dy
        self.clamp()
    elif ev.left_released:
      self._press = None

  def indicator(self):
    max_off = self.content_h - self.view.height
    if max_off <= 0:
      return
    th = max(60.0, self.view.height * self.view.height / self.content_h)
    ty = self.view.y + (self.view.height - th) * self.offset / max_off
    bar = rl.Rectangle(self.view.x + self.view.width - 8, ty, 6, th)
    rl.draw_rectangle_rounded(bar, 1.0, 6, Console.BG_TRACK)


def _sync_tag(d: Drive, sync_known: bool) -> tuple[str, rl.Color] | None:
  if d.recording:
    return tr("Recording"), Console.DANGER
  if not sync_known:
    return None
  if d.synced:
    return tr("Synced"), Console.SUCCESS
  if d.synced_segments:
    return tr("Partly synced"), Console.WARNING
  return tr("Not synced"), Console.TEXT_GHOST


class DrivesPage(Widget):
  def __init__(self):
    super().__init__()
    self._scroll = _Scroll()

  def show_event(self):
    super().show_event()
    indexer().request(force=True)

  def _render(self, rect: rl.Rectangle):
    indexer().request()
    idx = indexer().index
    strip = rl.Rectangle(rect.x, rect.y, rect.width, K.STRIP_H)
    total_s = sum(d.duration_s for d in idx.drives)
    km = sum(d.distance_m or 0.0 for d in idx.drives) / 1000.0
    have_km = any(d.distance_m is not None for d in idx.drives)
    cells = [K.Stat(tr("Drives on the comma"), str(len(idx.drives)), "", tr("Oldest are deleted first")),
             K.Stat(tr("Recorded"), fmt_hours(total_s), "h", (f"{km:.0f} km" if have_km else ""))]
    if idx.sync_known:
      unsynced = sum(1 for d in idx.drives if not d.synced and not d.recording)
      cells.append(K.Stat(tr("Not synced yet"), str(unsynced), "", tr("Kept until Citadel has them"),
                          Console.WARNING if unsynced else Console.SUCCESS))
    else:
      v, u = fmt_bytes(idx.drive_bytes)
      cells.append(K.Stat(tr("Space used"), v, u))
    K.stat_strip(strip, cells)

    body = rl.Rectangle(rect.x, rect.y + K.STRIP_H + GAP, rect.width, rect.height - K.STRIP_H - GAP)
    D.card(body)
    view = rl.Rectangle(body.x + 32, body.y + 8, body.width - 64, body.height - 16)
    self._scroll.view = view
    if not idx.scanned_at:
      D.text_center(tr("Looking for drives…"), view.x + view.width / 2, view.y + view.height / 2 - 20, D.BODY, Console.TEXT_MUTED)
      return
    if not idx.drives:
      D.text_center(tr("No drives on the comma yet"), view.x + view.width / 2, view.y + view.height / 2 - 40, D.H2,
                    Console.TEXT_MUTED, semi=True)
      D.text_center(tr("Drives show up here after the truck has been driven."), view.x + view.width / 2,
                    view.y + view.height / 2 + 16, D.LABEL, Console.TEXT_MUTED)
      return

    rl.begin_scissor_mode(int(view.x), int(view.y), int(view.width), int(view.height))
    y = view.y - self._scroll.offset
    last_day = None
    for d in idx.drives:
      day = day_label(d.start_wall)
      if day != last_day:
        if y + DAY_H > view.y and y < view.y + view.height:
          D.text(day, view.x, y + 28, D.LABEL, Console.TEXT_MUTED, semi=True)
        y += DAY_H
        last_day = day
      if y + ROW_H > view.y and y < view.y + view.height:
        self._row(rl.Rectangle(view.x, y, view.width, ROW_H), d, idx.sync_known)
      y += ROW_H
    rl.end_scissor_mode()
    self._scroll.content_h = y + self._scroll.offset - view.y
    self._scroll.clamp()
    self._scroll.indicator()

  def _row(self, r: rl.Rectangle, d: Drive, sync_known: bool):
    K.hline(r.x, r.x + r.width - 16, r.y)
    when = time.strftime("%-I:%M %p", time.localtime(d.start_wall)) if d.start_wall else tr("Time unknown")
    D.text(when, r.x, r.y + 24, D.BODY, semi=True)
    place = d.start_place if not d.end_place or d.end_place == d.start_place else f"{d.start_place} to {d.end_place}"
    sub = fmt_duration(d.duration_s) + (f" · {place}" if place else "")
    D.text(D.fit(sub, D.LABEL, r.width * 0.5), r.x, r.y + 72, D.LABEL, Console.TEXT_MUTED)

    right = r.x + r.width - 24
    tag = _sync_tag(d, sync_known)
    if tag is not None:
      c = K.signal_chip(right, r.y + (ROW_H - 60) / 2, tag[0], None, tag[1])
      right = c.x - 32
    if d.bookmarked:
      bw = D.text_w(tr("Bookmarked"), 26, semi=True) + 28
      K.tag(right - bw, r.y + (ROW_H - 44) / 2, tr("Bookmarked"), accent=True)
      right -= bw + 32
    if d.distance_m is not None:
      v, u = f"{d.distance_m / 1000:.1f}", "km"
    else:
      v, u = fmt_bytes(d.bytes)
    w = D.text_w(v, 44, semi=True) + 10 + D.text_w(u, 26)
    D.value_unit(v, u, right - w, r.y + (ROW_H - 44) / 2 - 4, 44, 26)

  def _handle_mouse_event(self, ev: MouseEvent):
    self._scroll.event(ev)

  def _handle_mouse_release(self, pos) -> bool:
    if self._scroll.dragging:
      self._scroll.dragging = False
      return True
    return False


@dataclass
class Slice:
  label: str
  bytes: int
  color: rl.Color


@dataclass
class Storage:
  total: int
  free: int
  slices: list[Slice]           # left to right on the bar; free is the empty track after them
  unsynced: int                 # overlaps the drive slices: drawn as a marker, not a slice
  from_bridge: bool


def storage_breakdown() -> Storage | None:
  """Disk use by kind, from the export bridge when it is running, else from the comma's own scan."""
  b = bridge_status.get("storage")
  if isinstance(b, dict) and b.get("totalBytes"):
    c = b.get("categories") or {}
    slices = [Slice(tr("Video"), int(c.get("video", 0)), Console.ACCENT),
              Slice(tr("Low-res video"), int(c.get("videoLowRes", 0)), Console.INFO),
              Slice(tr("Logs"), int(c.get("logs", 0)), Console.PURPLE),
              Slice(tr("System, maps and caches"), int(c.get("system", 0)), Console.TEXT_GHOST)]
    return Storage(int(b["totalBytes"]), int(b.get("freeBytes", 0)), slices, int(c.get("unsynced", 0)), True)
  idx = indexer().index
  if not idx.disk_total:
    return None
  other_drive = max(0, idx.drive_bytes - idx.video_bytes - idx.low_res_bytes - idx.log_bytes)
  slices = [Slice(tr("Video"), idx.video_bytes, Console.ACCENT),
            Slice(tr("Low-res video"), idx.low_res_bytes, Console.INFO),
            Slice(tr("Logs"), idx.log_bytes + other_drive, Console.PURPLE),
            Slice(tr("System, maps and caches"), idx.other_bytes, Console.TEXT_GHOST)]
  return Storage(idx.disk_total, idx.disk_free, slices, idx.unsynced_bytes if idx.sync_known else 0, False)


def storage_bar(r: rl.Rectangle, st: Storage):
  """One thick squared bar, a colour per kind, free space as the empty track."""
  rl.draw_rectangle_rounded(r, roundness(r, 6), 4, Console.BG_TRACK)
  x = r.x
  rl.begin_scissor_mode(int(r.x), int(r.y), int(r.width), int(r.height))
  for sl in st.slices:
    w = r.width * sl.bytes / st.total if st.total else 0
    if w >= 1:
      rl.draw_rectangle_rec(rl.Rectangle(x, r.y, w, r.height), sl.color)
      x += w
      rl.draw_rectangle_rec(rl.Rectangle(x - 2, r.y, 2, r.height), Console.BG_PANEL)
  rl.end_scissor_mode()
  if st.unsynced > 0 and st.total:
    # Unsynced recordings: a warning underline under the drive part of the bar
    drive_w = r.width * sum(s.bytes for s in st.slices[:3]) / st.total
    uw = max(6.0, r.width * st.unsynced / st.total)
    rl.draw_rectangle_rec(rl.Rectangle(r.x + max(0.0, drive_w - uw), r.y + r.height + 6, min(uw, drive_w), 6), Console.WARNING)
