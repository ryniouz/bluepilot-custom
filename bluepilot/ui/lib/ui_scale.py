"""
UI size for the Console shell (Screen > Theme and layout > UI size): Small, Standard or Large.

The shell and its pages are drawn under one rlgl scale, so text, icons and touch targets all grow or
shrink together and every page lays itself out for the smaller or larger logical area it is given.
Taps are scaled back into that logical area, and scissor rects (scrollers) are scaled out to the
screen. The driving view, charging page and pop-ups pushed on top (keyboard, dialogs) are not zoomed.
"""

from __future__ import annotations

import time
from contextlib import contextmanager

import pyray as rl

from openpilot.common.params import Params
from openpilot.system.ui.lib.application import MousePos, gui_app

SCALES = (0.9, 1.0, 1.15)               # BPConsoleScale 0, 1, 2
LABELS = ("Small", "Standard", "Large")
READ_EVERY_S = 1.0

_params: Params | None = None
_cached = (1, 0.0)


def scale_index() -> int:
  global _params, _cached
  idx, at = _cached
  now = time.monotonic()
  if now - at < READ_EVERY_S:
    return idx
  if _params is None:
    _params = Params()
  try:
    v = _params.get("BPConsoleScale", return_default=True)
    idx = max(0, min(len(SCALES) - 1, int(v if v is not None else 1)))
  except Exception:
    idx = 1
  _cached = (idx, now)
  return idx


def set_scale_index(idx: int):
  global _cached
  _cached = (max(0, min(len(SCALES) - 1, int(idx))), time.monotonic())


def current() -> float:
  return SCALES[scale_index()]


def logical(rect: rl.Rectangle, z: float) -> rl.Rectangle:
  return rl.Rectangle(rect.x / z, rect.y / z, rect.width / z, rect.height / z)


@contextmanager
def zoomed(z: float):
  """Draw and take taps at z times size. Inside, use logical(rect, z) as the layout rect."""
  if abs(z - 1.0) < 1e-3:
    yield
    return

  events, last = gui_app._mouse_events, gui_app._last_mouse_event
  gui_app._mouse_events = [e._replace(pos=MousePos(e.pos.x / z, e.pos.y / z)) for e in events]
  if last is not None:
    gui_app._last_mouse_event = last._replace(pos=MousePos(last.pos.x / z, last.pos.y / z))
  base = 1.0 / getattr(gui_app, "_scale", 1.0)
  rl.set_mouse_scale(base / z, base / z)

  scissor = rl.begin_scissor_mode

  def _scissor(x, y, w, h):
    return scissor(int(x * z), int(y * z), int(w * z), int(h * z))

  rl.begin_scissor_mode = _scissor
  rl.rl_draw_render_batch_active()
  rl.rl_push_matrix()
  rl.rl_scalef(z, z, 1.0)
  try:
    yield
  finally:
    rl.rl_draw_render_batch_active()
    rl.rl_pop_matrix()
    rl.begin_scissor_mode = scissor
    rl.set_mouse_scale(base, base)
    gui_app._mouse_events, gui_app._last_mouse_event = events, last
