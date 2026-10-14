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

import pyray as rl

import cereal.messaging as messaging
from openpilot.common.params import Params
from openpilot.system.ui.lib.application import MouseEvent
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.console.home import _param, has_param, network_status
from bluepilot.ui.lib.drive_index import Drive, DriveIndex, indexer
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


class OffloadPage(Widget):
  """comma connect uploads on the left, the Citadel sync on the right."""

  def __init__(self):
    super().__init__()
    self._params = Params()
    self._sm: messaging.SubMaster | None = None

  def show_event(self):
    super().show_event()
    indexer().request(force=True)

  def _uploader(self):
    if self._sm is None:
      try:
        self._sm = messaging.SubMaster(["uploaderState"])
      except Exception:
        return None
    try:
      self._sm.update(0)
      return self._sm["uploaderState"] if self._sm.seen["uploaderState"] else None
    except Exception:
      return None

  def _render(self, rect: rl.Rectangle):
    indexer().request()
    idx = indexer().index
    left, right = K.split_cols(rect, [1, 1])
    left.width -= GAP / 2
    right.x += GAP / 2
    right.width -= GAP / 2
    self._connect_card(left)
    self._citadel_card(right, idx)

  def _card_head(self, r: rl.Rectangle, ic: str, title: str, status: str, color: rl.Color) -> float:
    D.card(r)
    p = D.CARD_PAD
    D.icon(ic, r.x + p, r.y + p - 2, 44, Console.TEXT_SECONDARY)
    D.text(title, r.x + p + 64, r.y + p, D.H2, semi=True)
    y = r.y + p + 84
    D.dot(r.x + p + 10, y + D.BODY / 2 + 2, 10, color)
    D.text(D.fit(status, D.BODY, r.width - 2 * p - 36, semi=True), r.x + p + 36, y, D.BODY, semi=True)
    return y + 72

  def _rows(self, r: rl.Rectangle, y: float, rows: list[tuple[str, str]]):
    p = D.CARD_PAD
    for label, value in rows:
      if y + D.BODY > r.y + r.height - p:
        break
      K.hline(r.x + p, r.x + r.width - p, y)
      D.text(label, r.x + p, y + 26, D.BODY, Console.TEXT_MUTED)
      D.text_right(D.fit(value, D.BODY, r.width * 0.5, semi=True), r.x + r.width - p, y + 26, D.BODY, semi=True)
      y += 92

  def _connect_card(self, r: rl.Rectangle):
    up = self._uploader()
    net = network_status()
    online = net is not None and net[0] != tr("Offline")
    if up is None:
      status, color = tr("Uploader not running"), Console.TEXT_GHOST
      rows = []
    else:
      count = int(up.immediateQueueCount) + int(up.rawQueueCount)
      size = float(up.immediateQueueSize) + float(up.rawQueueSize)
      if count == 0:
        status, color = tr("Everything is uploaded"), Console.SUCCESS
      elif online:
        status, color = tr("Uploading"), Console.ACCENT
      else:
        status, color = tr("Waiting for a connection"), Console.WARNING
      v, u = fmt_bytes(size)
      rows = [(tr("Waiting to upload"), f"{count} " + (tr("file") if count == 1 else tr("files")) + f" · {v} {u}")]
      if up.lastFilename:
        rows.append((tr("Last upload"), f"{float(up.lastSpeed):.1f} MB/s"))
    rows.append((tr("Connection"), net[0] if net is not None else "–"))
    y = self._card_head(r, "cloud", tr("comma connect"), status, color)
    self._rows(r, y, rows)
    p = D.CARD_PAD
    for i, ln in enumerate(D.wrap(tr("Driving logs and the small road video upload on Wi-Fi while parked."), D.LABEL,
                                  r.width - 2 * p, 2)):
      D.text(ln, r.x + p, r.y + r.height - p - 80 + i * 40, D.LABEL, Console.TEXT_MUTED)

  def _citadel_card(self, r: rl.Rectangle, idx: DriveIndex):
    p = D.CARD_PAD
    enabled = bool(_param(self._params, "BPBridgeEnabled", False)) if has_param(self._params, "BPBridgeEnabled") else False
    if not enabled and not idx.sync_known:
      self._card_head(r, "export", tr("Citadel sync"), tr("Data export is off"), Console.TEXT_GHOST)
      y = r.y + p + 180
      for ln in D.wrap(tr("Turn on Data export in Connect to let Citadel pull every drive. Until then, drives only go to comma connect."),
                       D.BODY, r.width - 2 * p, 4):
        D.text(ln, r.x + p, y, D.BODY, Console.TEXT_SECONDARY)
        y += 50
      return
    done = [d for d in idx.drives if not d.recording]
    synced = sum(1 for d in done if d.synced)
    waiting = len(done) - synced
    if waiting == 0:
      status, color = tr("Citadel has every drive"), Console.SUCCESS
    else:
      status, color = (tr("1 drive waiting") if waiting == 1 else f"{waiting} " + tr("drives waiting")), Console.WARNING
    y = self._card_head(r, "export", tr("Citadel sync"), status, color)
    frac = 1.0 - (idx.unsynced_bytes / idx.drive_bytes) if idx.drive_bytes else 1.0
    K.bar(rl.Rectangle(r.x + p, y, r.width - 2 * p, K.BAR_H), frac, Console.SUCCESS)
    y += K.BAR_H + 40
    v, u = fmt_bytes(idx.unsynced_bytes)
    keep = keep_until_synced(self._params)
    self._rows(r, y, [(tr("Synced drives"), f"{synced} / {len(done)}"),
                      (tr("Not synced"), f"{v} {u}"),
                      (tr("Keep until synced"), tr("On") if keep else tr("Off"))])


class StoragePage(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()

  def show_event(self):
    super().show_event()
    indexer().request(force=True)

  def _render(self, rect: rl.Rectangle):
    indexer().request()
    idx = indexer().index
    D.card(rect)
    p = 48
    x, y, w = rect.x + p, rect.y + p, rect.width - 2 * p
    if not idx.disk_total:
      D.text(tr("Reading storage…"), x, y, D.BODY, Console.TEXT_MUTED)
      return
    used = idx.disk_total - idx.disk_free
    uv, uu = fmt_bytes(used)
    tv, tu = fmt_bytes(idx.disk_total)
    D.text(tr("Storage"), x, y, D.H2, semi=True)
    pct = 100.0 * idx.disk_free / idx.disk_total
    D.text_right(f"{pct:.0f} % " + tr("free"), x + w, y + 4, D.BODY, Console.WARNING if pct < 10 else Console.TEXT_MUTED, semi=True)
    y += 76
    D.value_unit(uv, uu, x, y, 96, 40)
    vw = D.text_w(uv, 96, semi=True) + 12 + D.text_w(uu, 40)
    D.text(tr("used of") + f" {tv} {tu}", x + vw + 20, y + 50, D.BODY, Console.TEXT_MUTED)
    y += 140

    # One thick stacked bar: drives | everything else | free
    bar = rl.Rectangle(x, y, w, 48)
    rl.draw_rectangle_rounded(bar, roundness(bar, 6), 4, Console.BG_TRACK)
    segs = [(idx.drive_bytes, Console.ACCENT), (idx.other_bytes, Console.TEXT_GHOST)]
    bx = bar.x
    for n, color in segs:
      sw = bar.width * n / idx.disk_total
      if sw >= 2:
        rl.draw_rectangle_rounded(rl.Rectangle(bx, bar.y, sw, bar.height), roundness(bar, 6), 4, color)
        bx += sw
    y += 48 + 40

    dv, du = fmt_bytes(idx.drive_bytes)
    ov, ou = fmt_bytes(idx.other_bytes)
    fv, fu = fmt_bytes(idx.disk_free)
    rows = [(Console.ACCENT, tr("Drives"), f"{dv} {du}", f"{len(idx.drives)} " + tr("drives"))]
    if idx.sync_known:
      nv, nu = fmt_bytes(idx.unsynced_bytes)
      rows.append((None, tr("Not synced to Citadel"), f"{nv} {nu}", ""))
    if idx.bookmarked_bytes:
      bv, bu = fmt_bytes(idx.bookmarked_bytes)
      rows.append((None, tr("Bookmarked drives"), f"{bv} {bu}", ""))
    rows += [(Console.TEXT_GHOST, tr("System, models and maps"), f"{ov} {ou}", ""),
             (Console.BG_TRACK, tr("Free"), f"{fv} {fu}", "")]
    for color, label, value, note in rows:
      if y + 80 > rect.y + rect.height - p - 60:
        break
      K.hline(x, x + w, y)
      lx = x
      if color is not None:
        sw = rl.Rectangle(x, y + 30, 28, 28)
        rl.draw_rectangle_rounded(sw, roundness(sw, 6), 4, color)
        lx += 48
      else:
        lx += 48
        D.text("–", x + 4, y + 22, D.BODY, Console.TEXT_MUTED)
      D.text(label, lx, y + 22, D.BODY, Console.TEXT_SECONDARY if color is None else None)
      vr = D.text_right(value, x + w, y + 22, D.BODY, semi=True)
      if note:
        D.text_right(note, x + w - vr - 40, y + 26, D.LABEL, Console.TEXT_MUTED)
      y += 88

    keep = keep_until_synced(self._params)
    note = (tr("Drives Citadel hasn't synced are kept until free space drops to 5 %.") if keep else
            tr("When free space drops below 10 %, the oldest drives are deleted first."))
    D.text(D.fit(note, D.LABEL, w), x, rect.y + rect.height - p - D.LABEL, D.LABEL, Console.TEXT_MUTED)
