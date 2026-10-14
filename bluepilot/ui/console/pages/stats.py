"""
Console Statistics page: an OBD-scanner-style live view of every value the truck sends.

  left   every signal in ui_state.ev_history, grouped, with its live value. Tap one to add it to the
         graph (up to four); tap again to take it off.
  right  one graph. Each picked signal gets its own lane and scale. The window buttons zoom
         (30 s to 24 h); dragging the graph sideways pans back in time; "Live" jumps back to now.

  sets   one-tap graph sets (Battery, Charging, Driving) above the list
  quiet  values the truck isn't sending right now sit folded at the bottom, never as a column of dashes
"""

from __future__ import annotations

import math
import time

import numpy as np
import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import MouseEvent
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.lib.theme import Console

WINDOWS = [(30, "30 s"), (120, "2 min"), (600, "10 min"), (3600, "1 h"), (24 * 3600, "24 h")]
MAX_PICKS = 4
ROW_H = 84
GROUP_H = 64
LIST_W = 0.42
PAD = 28
VALUE = 30
LABEL = 28
CAP = 24
GUTTER = 96           # left of each lane, for its scale
DRAG_PX = 16          # movement before a press counts as a drag instead of a tap
SETS_H = 84
GROUP_ICONS = {"Battery": "battery", "Driving": "wheel", "Charging": "plug", "Vehicle": "car", "Tires": "gauge",
               "Thermal": "thermo", "Other": "list"}
# One-tap graph sets: the first few of these that the truck is sending
GRAPH_SETS = [
  ("Battery", ["ev.soc", "ev.power_kw", "ev.pack_temp_c", "ev.voltage"]),
  ("Charging", ["ev.charge_power_kw", "ev.soc", "ev.pack_temp_c", "ev.coolant_temp_c"]),
  ("Driving", ["ev.power_kw", "ev.wh_per_km", "ev.range_km", "ev.motor_torque_nm"]),
]


def series_colors() -> list[rl.Color]:
  return [Console.ACCENT, Console.SUCCESS, Console.WARNING, Console.PURPLE]


def fmt_value(v: float, digits: int, unit: str) -> str:
  if v is None or not math.isfinite(v):
    return "--"
  if unit == "" and v in (0.0, 1.0):
    return tr("On") if v else tr("Off")
  return f"{v:.{digits}f}"


class StatsPage(Widget):
  def __init__(self):
    super().__init__()
    self.picks: list[str] = []
    self.window_i = 0
    self.end_offset = 0.0           # seconds back from now that the graph's right edge sits
    self._scroll = 0.0
    self._rows: list[tuple[rl.Rectangle, str]] = []
    self._seg_rects: list[rl.Rectangle] = []
    self._live_rect: rl.Rectangle | None = None
    self._clear_rect: rl.Rectangle | None = None
    self._list_rect = rl.Rectangle(0, 0, 0, 0)
    self._graph_rect = rl.Rectangle(0, 0, 0, 0)
    self._press: tuple[float, float] | None = None
    self._press_scroll = 0.0
    self._press_offset = 0.0
    self._dragging = False
    self._content_h = 0.0
    self._set_rects: list[tuple[rl.Rectangle, list[str]]] = []
    self.show_quiet = False
    self._quiet_rect: rl.Rectangle | None = None

  # -- data ---------------------------------------------------------------------------------

  @staticmethod
  def history():
    return getattr(ui_state, "ev_history", None)

  def subtitle(self) -> str:
    h = self.history()
    n = len(h.keys()) if h is not None else 0
    if n == 0:
      return tr("Energy") + " | " + tr("Waiting for truck data")
    return tr("Energy") + " | " + f"{n} " + tr("live values")

  def sub_dot(self):
    h = self.history()
    return Console.SUCCESS if h is not None and h.latest else Console.TEXT_GHOST

  def action(self) -> str | None:
    return tr("Clear graph") if self.picks else None

  def on_action(self):
    self.picks = []

  def toggle_pick(self, key: str):
    if key in self.picks:
      self.picks.remove(key)
    elif len(self.picks) < MAX_PICKS:
      self.picks.append(key)
    else:
      self.picks = self.picks[1:] + [key]

  # -- render ------------------------------------------------------------------------------

  def _render(self, rect: rl.Rectangle):
    h = self.history()
    if not self.picks and h is not None:
      # Start with the pack state of charge and power so the graph is never empty
      self.picks = [k for k in ("ev.soc", "ev.power_kw") if k in h.keys()]
    lw = rect.width * LIST_W
    self._list_rect = rl.Rectangle(rect.x, rect.y, lw, rect.height)
    self._graph_rect = rl.Rectangle(rect.x + lw + K.GAP, rect.y, rect.width - lw - K.GAP, rect.height)
    K.panel(self._list_rect)
    K.panel(self._graph_rect)
    self._draw_list(self._list_rect, h)
    self._draw_graph(self._graph_rect, h)

  def _live(self, h, key: str) -> bool:
    v = h.latest.get(key)
    return v is not None and math.isfinite(v)

  def _draw_sets(self, r: rl.Rectangle, h) -> float:
    """One-tap graph sets along the top of the list. Returns the y below them."""
    self._set_rects = []
    x, y = r.x + PAD, r.y + 18
    D.text(tr("Graph"), x, y + (60 - CAP) / 2 - 1, CAP, Console.TEXT_MUTED)
    x += D.text_w(tr("Graph"), CAP) + 20
    for label, keys in GRAPH_SETS:
      picks = [k for k in keys if k in h.keys() and self._live(h, k)][:MAX_PICKS - 1]
      if not picks:
        continue
      w = D.text_w(tr(label), K.CAP, semi=True) + 44
      if x + w > r.x + r.width - PAD:
        break
      on = self.picks == picks
      c = K.chip(x, y, tr(label), accent=on)
      self._set_rects.append((c, picks))
      x += c.width + 12
    K.hline(r.x + PAD, r.x + r.width - PAD, r.y + SETS_H - K.HAIR)
    return r.y + SETS_H

  def _draw_list(self, r: rl.Rectangle, h):
    self._rows = []
    self._set_rects = []
    self._quiet_rect = None
    if h is None or not h.keys():
      D.text(tr("No values yet"), r.x + PAD, r.y + PAD, LABEL + 4, semi=True)
      for i, line in enumerate(D.wrap(tr("Values appear here as soon as the truck is awake: ignition on, or charging."),
                                      CAP + 2, r.width - 2 * PAD, 3)):
        D.text(line, r.x + PAD, r.y + PAD + 52 + i * 36, CAP + 2, Console.TEXT_MUTED)
      return
    latest = h.latest
    colors = series_colors()
    top = self._draw_sets(r, h)
    inner = rl.Rectangle(r.x, top + 4, r.width, r.y + r.height - top - 12)
    live = [k for k in h.keys() if self._live(h, k) or k in self.picks]
    quiet = [k for k in h.keys() if k not in live]
    rl.begin_scissor_mode(int(inner.x), int(inner.y), int(inner.width), int(inner.height))
    y = inner.y - self._scroll
    group = None

    def row(key: str, y: float, dim: bool = False):
      info = h.info(key)
      rr = rl.Rectangle(r.x, y, r.width, ROW_H)
      if y + ROW_H > inner.y and y < inner.y + inner.height:
        picked = key in self.picks
        if picked:
          c = colors[self.picks.index(key) % len(colors)]
          bg = rl.Rectangle(r.x + 12, y + 6, r.width - 24, ROW_H - 12)
          rl.draw_rectangle_rounded(bg, 0.3, 8, Console.BG_RAISED)
          D.dot(r.x + PAD + 6, y + ROW_H / 2, 7, c)
        lx = r.x + PAD + (24 if picked else 0)
        v = latest.get(key)
        has = v is not None and math.isfinite(v)
        val = fmt_value(v, info.digits, info.unit) if has else tr("No data")
        unit = info.unit if has and val not in (tr("On"), tr("Off")) else ""
        vsize = VALUE if has else CAP
        vw = D.text_w(val, vsize, semi=has) + (10 + D.text_w(unit, CAP) if unit else 0)
        D.text(D.fit(info.label, LABEL, r.x + r.width - PAD - vw - 24 - lx), lx, y + (ROW_H - LABEL) / 2 - 2, LABEL,
               Console.TEXT_GHOST if dim else (Console.TEXT_PRIMARY if picked else Console.TEXT_SECONDARY))
        if has:
          D.value_unit(val, unit, r.x + r.width - PAD - vw, y + (ROW_H - VALUE) / 2 - 2, VALUE, CAP)
        else:
          D.text_right(val, r.x + r.width - PAD, y + (ROW_H - CAP) / 2 - 2, CAP, Console.TEXT_GHOST)
        if not picked:
          K.hline(r.x + PAD, r.x + r.width - PAD, y + ROW_H - K.HAIR)
        self._rows.append((rr, key))
      return y + ROW_H

    for key in live:
      info = h.info(key)
      if info.group != group:
        group = info.group
        if y + GROUP_H > inner.y and y < inner.y + inner.height:
          gy = y + GROUP_H - CAP - 12
          D.icon(GROUP_ICONS.get(group, "list"), r.x + PAD, gy - 2, CAP + 4, Console.TEXT_MUTED)
          D.text(D.fit(tr(group), CAP, r.width - 2 * PAD - 44, semi=True), r.x + PAD + 40, gy, CAP, Console.TEXT_MUTED, semi=True)
        y += GROUP_H
      y = row(key, y)

    if quiet:
      qr = rl.Rectangle(r.x + PAD, y + 16, r.width - 2 * PAD, 72)
      if y + 88 > inner.y and y < inner.y + inner.height:
        rl.draw_rectangle_rounded(qr, 0.3, 8, Console.BG_RAISED)
        label = (tr("Hide") if self.show_quiet else tr("Show")) + f" {len(quiet)} " + tr("not reporting now")
        D.text(D.fit(label, CAP, qr.width - 80), qr.x + 24, qr.y + (72 - CAP) / 2 - 2, CAP, Console.TEXT_MUTED, semi=True)
        D.icon("chevron", qr.x + qr.width - 52, qr.y + 20, 32, Console.TEXT_MUTED)
      self._quiet_rect = qr
      y += 104
      if self.show_quiet:
        for key in quiet:
          y = row(key, y, dim=True)
    rl.end_scissor_mode()
    self._content_h = y + self._scroll - inner.y
    max_scroll = max(0.0, self._content_h - inner.height)
    self._scroll = max(0.0, min(self._scroll, max_scroll))
    if max_scroll > 0:  # scroll indicator
      th = inner.height * inner.height / self._content_h
      ty = inner.y + (inner.height - th) * self._scroll / max_scroll
      rl.draw_rectangle_rounded(rl.Rectangle(r.x + r.width - 10, ty, 4, th), 1.0, 4, Console.BORDER_STRONG)

  def _draw_graph(self, r: rl.Rectangle, h):
    inner = K.inset(r, PAD, 24)
    # Controls: Live on the left (a button when panned back), window buttons on the right
    labels = [lab for _, lab in WINDOWS]
    live_w = D.text_w(tr("Live"), CAP + 2, semi=True) + 80
    if sum(D.text_w(lab, CAP, semi=True) + 56 for lab in labels) + 12 > inner.width - live_w:  # narrow (UI size Large)
      labels = [lab.replace(" min", "m").replace(" s", "s").replace(" h", "h") for lab in labels]
    self._seg_rects = K.segmented(inner.x + inner.width, inner.y + 40, labels, self.window_i)
    room = (self._seg_rects[0].x - 6 - inner.x) if self._seg_rects else inner.width
    self._live_rect = None
    if self.end_offset > 0.5:
      label = tr("Live") if room >= live_w else "»"
      w = D.text_w(label, CAP + 2, semi=True) + 56
      self._live_rect = rl.Rectangle(inner.x, inner.y, w, 80)
      D.button(self._live_rect, label, primary=True, size=CAP + 2)
    else:
      D.dot(inner.x + 8, inner.y + 40, 8, Console.SUCCESS)
      if room >= live_w:
        D.text(tr("Live"), inner.x + 28, inner.y + 40 - CAP / 2 - 2, CAP, Console.TEXT_SECONDARY, semi=True)

    plot = rl.Rectangle(inner.x, inner.y + 80 + 24, inner.width, inner.height - 80 - 24 - CAP - 16)
    window = WINDOWS[self.window_i][0]
    end = time.monotonic() - self.end_offset
    picks = [k for k in self.picks if h is not None and k in h.keys()]
    if not picks:
      D.text_center(tr("Tap a value on the left to graph it"), plot.x + plot.width / 2, plot.y + plot.height / 2 - CAP, CAP + 4,
                    Console.TEXT_MUTED)
      return

    # time axis (every other label when they would touch)
    step = (plot.width - GUTTER) / 4
    every = 1 if step > 1.5 * D.text_w("-10 min", CAP) + 32 else 2
    for i in range(5):
      x = plot.x + GUTTER + (plot.width - GUTTER) * i / 4
      ago = self.end_offset + window * (1 - i / 4)
      lab = tr("Now") if ago < 0.5 else _ago(ago)
      w = D.text_w(lab, CAP)
      lx = x if i == 0 else (x - w if i == 4 else x - w / 2)
      if i % every == 0:
        D.text(lab, lx, plot.y + plot.height + 12, CAP, Console.TEXT_MUTED)
      if 0 < i < 4:
        K.vline(x, plot.y, plot.y + plot.height, Console.BORDER_SUBTLE)

    lane_h = plot.height / len(picks)
    colors = series_colors()
    for li, key in enumerate(picks):
      lane = rl.Rectangle(plot.x, plot.y + li * lane_h, plot.width, lane_h)
      if li:
        K.hline(lane.x, lane.x + lane.width, lane.y, Console.BORDER_DEFAULT)
      self._draw_lane(lane, h, key, colors[self.picks.index(key) % len(colors)], window, end)

  def _draw_lane(self, lane: rl.Rectangle, h, key: str, color: rl.Color, window: float, end: float):
    info = h.info(key)
    t, v = h.arrays(key, window, end)
    ok = np.isfinite(v)
    head = f"{info.label}"
    # Same live value as the list (blank when the truck stops sending), not the last one in the window
    cur = h.latest.get(key, float("nan"))
    D.text(D.fit(head, CAP + 2, lane.width * 0.6, semi=True), lane.x + 8, lane.y + 10, CAP + 2, color, semi=True)
    if math.isfinite(float(cur)):
      val = fmt_value(float(cur), info.digits, info.unit)
      D.text_right(val + (f" {info.unit}" if info.unit and val not in (tr("On"), tr("Off")) else ""),
                   lane.x + lane.width - 8, lane.y + 10, CAP + 2, Console.TEXT_PRIMARY, semi=True)
    else:
      D.text_right(tr("Not reporting now"), lane.x + lane.width - 8, lane.y + 12, CAP, Console.TEXT_GHOST)
    area = rl.Rectangle(lane.x + GUTTER, lane.y + CAP + 30, lane.width - GUTTER, lane.height - CAP - 40)
    if ok.sum() < 2:
      D.text_center(tr("No data in this window"), area.x + area.width / 2, area.y + area.height / 2 - CAP / 2, CAP,
                    Console.TEXT_GHOST)
      return
    lo, hi = float(np.min(v[ok])), float(np.max(v[ok]))
    if hi - lo < 1e-6:
      lo, hi = lo - 1, hi + 1
    pad = (hi - lo) * 0.08
    lo, hi = lo - pad, hi + pad
    D.text_right(_short(hi - pad), area.x - 12, area.y - 4, CAP - 2, Console.TEXT_MUTED)
    D.text_right(_short(lo + pad), area.x - 12, area.y + area.height - CAP + 4, CAP - 2, Console.TEXT_MUTED)
    K.hline(area.x, area.x + area.width, area.y + area.height, Console.BORDER_SUBTLE)

    t0 = end - window
    xs = area.x + area.width * (t - t0) / window
    ys = area.y + area.height * (1 - (v - lo) / (hi - lo))
    # thin the points to about one per 2 px
    step = max(1, len(xs) // int(max(1, area.width / 2)))
    prev = None
    for i in range(0, len(xs), step):
      if not ok[i]:
        prev = None
        continue
      p = rl.Vector2(float(xs[i]), float(ys[i]))
      if prev is not None:
        rl.draw_line_ex(prev, p, 3, color)
      prev = p
    if prev is not None and self.end_offset < 0.5:
      rl.draw_circle_v(prev, 7, color)

  # -- input -------------------------------------------------------------------------------

  def _handle_mouse_event(self, ev: MouseEvent):
    if ev.left_pressed:
      self._press = (ev.pos.x, ev.pos.y)
      self._press_scroll = self._scroll
      self._press_offset = self.end_offset
      self._dragging = False
    elif ev.left_down and self._press is not None:
      dx, dy = ev.pos.x - self._press[0], ev.pos.y - self._press[1]
      if not self._dragging and max(abs(dx), abs(dy)) > DRAG_PX:
        self._dragging = True
      if self._dragging:
        if D.hit(self._list_rect, rl.Vector2(*self._press)):
          self._scroll = max(0.0, self._press_scroll - dy)
        elif D.hit(self._graph_rect, rl.Vector2(*self._press)):
          window = WINDOWS[self.window_i][0]
          plot_w = max(1.0, self._graph_rect.width - 2 * PAD - GUTTER)
          self.end_offset = self._clamp_offset(self._press_offset + dx * window / plot_w)
    elif ev.left_released:
      self._press = None

  def _clamp_offset(self, off: float) -> float:
    h = self.history()
    oldest = h.oldest() if h is not None else None
    limit = max(0.0, time.monotonic() - oldest - WINDOWS[self.window_i][0] * 0.5) if oldest else 0.0
    return max(0.0, min(off, limit))

  def _handle_mouse_release(self, pos) -> bool:
    if self._dragging:
      self._dragging = False
      return True
    for i, sr in enumerate(self._seg_rects):
      if D.hit(sr, pos):
        self.window_i = i
        self.end_offset = self._clamp_offset(self.end_offset)
        return True
    for sr, picks in self._set_rects:
      if D.hit(sr, pos):
        self.picks = list(picks)
        return True
    if self._quiet_rect is not None and D.hit(self._quiet_rect, pos) and D.hit(self._list_rect, pos):
      self.show_quiet = not self.show_quiet
      return True
    if self._live_rect is not None and D.hit(self._live_rect, pos):
      self.end_offset = 0.0
      return True
    for row, key in self._rows:
      if D.hit(row, pos) and D.hit(self._list_rect, pos):
        self.toggle_pick(key)
        return True
    return False


def _short(v: float) -> str:
  a = abs(v)
  if a >= 1000:
    return f"{v / 1000:.1f}k"
  if a >= 100:
    return f"{v:.0f}"
  return f"{v:.1f}"


def _ago(s: float) -> str:
  if s < 90:
    return f"-{s:.0f} s"
  if s < 5400:
    return f"-{s / 60:.0f} min"
  return f"-{s / 3600:.1f} h"
