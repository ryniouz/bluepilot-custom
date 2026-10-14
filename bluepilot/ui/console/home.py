"""
Console Home: the truck overview, laid out like Citadel's EVTel overview.

  stat strip   battery, range, pack temperature, outside, 12 V, tires
  joined grid  battery over the last 24 h | driver assist controls
               device                     | software
Also the Alerts page (active offroad alerts).
"""

from __future__ import annotations

import time
from collections.abc import Callable

import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.lib.ev_data import finite
from bluepilot.ui.lib.theme import Console

KM_TO_MI = 0.621371
KPA_TO_PSI = 0.145038

PERSONALITY_LABELS = ["Relaxed", "Standard", "Close"]
PERSONALITY_VALUES = [2, 1, 0]          # LongitudinalPersonality: 0 aggressive, 1 standard, 2 relaxed
PROFILE_LABELS = ["Auto", "Off", "Tow"]  # BPTowProfile: 0 auto, 1 off, 2 always on


def _param(params: Params, key, default=None):
  try:
    v = params.get(key, return_default=True)
  except Exception:
    return default
  if isinstance(v, bytes):
    v = v.decode(errors="ignore")
  return default if v is None else v


def has_param(params: Params, key) -> bool:
  try:
    params.get(key, return_default=True)
    return True
  except Exception:
    return False


def truck_snapshot():
  """Live truck data when fresh, else the last known (kept across reboots)."""
  s = getattr(ui_state, "ev", None)
  if s is not None and s.available:
    return s, True
  src = getattr(ui_state, "ev_source", None)
  return (getattr(src, "last_good", None) if src is not None else None), False


def temp(c: float) -> tuple[str, str]:
  if ui_state.is_metric:
    return f"{c:.0f}", "°C"
  return f"{c * 9 / 5 + 32:.0f}", "°F"


def active_alerts(params: Params) -> list[tuple[str, int]]:
  try:
    from openpilot.selfdrive.selfdrived.alertmanager import OFFROAD_ALERTS
  except Exception:
    return []
  out = []
  for key, cfg in sorted(OFFROAD_ALERTS.items(), key=lambda x: x[1].get("severity", 0), reverse=True):
    try:
      val = params.get(key)
    except Exception:
      continue
    if not val:
      continue
    text = val.get("text", "") if isinstance(val, dict) else ""
    out.append((str(text or cfg.get("text", "")).replace("%1", "").strip(), int(cfg.get("severity", 0))))
  return out


class ConsoleHome(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._hits: list[tuple[rl.Rectangle, Callable[[], None]]] = []
    self.on_open_drive: Callable[[], None] | None = None
    self.on_open_software: Callable[[], None] | None = None
    self.on_open_assist: Callable[[], None] | None = None

  # -- header (the shell draws it) --------------------------------------------------------

  def subtitle(self) -> str:
    s, live = truck_snapshot()
    if getattr(ui_state, "charging_screen", False):
      state = tr("Charging")
    elif ui_state.started:
      state = tr("Driving")
    else:
      state = tr("Parked")
    return f"{tr('F-150 Lightning')} | {state}" + ("" if live or s is None else " · " + tr("last known data"))

  def sub_dot(self):
    if getattr(ui_state, "charging_screen", False) or ui_state.started:
      return Console.SUCCESS
    return Console.TEXT_GHOST

  # -- render -------------------------------------------------------------------------

  def _render(self, rect: rl.Rectangle):
    self._hits = []
    s, live = truck_snapshot()
    self._strip(rl.Rectangle(rect.x, rect.y, rect.width, K.STRIP_H), s, live)
    grid = rl.Rectangle(rect.x, rect.y + K.STRIP_H + K.GAP, rect.width, rect.height - K.STRIP_H - K.GAP)
    top, bottom = K.split_rows(grid, [0.70, 0.30])
    chart_r, assist_r = K.split_cols(top, [1.55, 1])
    dev_r, sw_r = K.split_cols(bottom, [1.55, 1])
    K.joined(grid, [chart_r, assist_r, dev_r, sw_r])
    self._chart(K.inset(chart_r), s)
    self._assist(K.inset(assist_r))
    self._device(K.inset(dev_r))
    self._software(K.inset(sw_r))

  def _strip(self, r: rl.Rectangle, s, live: bool):
    dash = "–"
    cells = []
    if s is not None and finite(s.soc):
      cells.append(K.Stat(tr("Battery"), f"{s.soc:.0f}", "%", tr("Live") if live else tr("Last known")))
    else:
      cells.append(K.Stat(tr("Battery"), dash, "", tr("No data yet")))
    if s is not None and finite(s.range_km):
      rng = s.range_km if ui_state.is_metric else s.range_km * KM_TO_MI
      cells.append(K.Stat(tr("Range"), f"{rng:.0f}", "km" if ui_state.is_metric else "mi", tr("Estimated") if s.range_estimated else ""))
    else:
      cells.append(K.Stat(tr("Range"), dash))
    if s is not None and finite(s.pack_temp_c):
      v, u = temp(s.pack_temp_c)
      cells.append(K.Stat(tr("Pack temp"), v, u))
    else:
      cells.append(K.Stat(tr("Pack temp"), dash))
    if s is not None and finite(s.outside_temp_c):
      v, u = temp(s.outside_temp_c)
      cells.append(K.Stat(tr("Outside"), v, u))
    else:
      cells.append(K.Stat(tr("Outside"), dash))
    if s is not None and finite(s.lv_volts):
      cells.append(K.Stat(tr("12 V"), f"{s.lv_volts:.1f}", "V", tr("Low") if s.lv_low else tr("Healthy"),
                          Console.WARNING if s.lv_low else None))
    else:
      cells.append(K.Stat(tr("12 V"), dash))
    if s is not None and len(s.tire_kpa) == 4 and all(finite(t) and t > 0 for t in s.tire_kpa):
      psi = [t * KPA_TO_PSI for t in s.tire_kpa]
      cells.append(K.Stat(tr("Tires"), f"{min(psi):.0f}–{max(psi):.0f}", "psi", tr("One is low") if s.tire_low else tr("All four OK"),
                          Console.WARNING if s.tire_low else None))
    else:
      cells.append(K.Stat(tr("Tires"), dash))
    K.stat_strip(r, cells)

  def _chart(self, r: rl.Rectangle, s):
    y = K.section_title(r, tr("Battery, last 24 h"), tr("State of charge"))
    hist = getattr(ui_state, "ev_history", None)
    values = []
    if hist is not None and hasattr(hist, "series"):
      try:
        values = [v for _, v in hist.series("soc", 24 * 3600)]
      except Exception:
        values = []
    now = time.mktime(time.localtime())  # wall clock for axis labels only
    labels = [time.strftime("%-I %p", time.localtime(now - h * 3600)) for h in (24, 18, 12, 6)] + [tr("Now")]
    K.area_chart(rl.Rectangle(r.x, y, r.width, r.y + r.height - y), [K.Series(values, Console.ACCENT)], labels,
                 vmin=0, vmax=100, unit="%", empty=tr("The chart fills in as the truck reports its charge"))

  def _assist(self, r: rl.Rectangle):
    y = K.section_title(r, tr("Driver assist"))
    link = tr("All settings")
    lw = D.text_w(link, K.CAP, semi=True)
    lr = rl.Rectangle(r.x + r.width - lw - 16, r.y - 8, lw + 32, K.H2 + 24)
    D.text(link, r.x + r.width - lw, r.y + (K.H2 - K.CAP) - 2, K.CAP, Console.ACCENT_TEXT, semi=True)
    self._hits.append((lr, lambda: self.on_open_drive and self.on_open_drive()))
    right = r.x + r.width
    rows = [("exp", tr("Experimental mode"), tr("End-to-end speed control")), ("follow", tr("Following"), "")]
    if has_param(self._params, "BPTowProfile"):
      rows.append(("profile", tr("Lightning profile"), ""))
    if has_param(self._params, "BPOnePedalMode"):
      rows.append(("pedal", tr("One-pedal driving"), ""))
    row_h = min(K.FORM_ROW_H, (r.y + r.height - y) / max(1, len(rows)))
    for i, (kind, title, desc) in enumerate(rows):
      rr = rl.Rectangle(r.x, y + i * row_h, r.width, row_h)
      cy = rr.y + rr.height / 2
      op = 0
      if kind == "pedal":
        op = int(_param(self._params, "BPOnePedalMode", 2) or 0)
        desc = tr("Estimated from coast-down") if op == 2 else ""
      K.form_row(rr, title, desc, first=i == 0)
      if kind == "exp":
        tg = K.toggle(right, cy, bool(_param(self._params, "ExperimentalMode", False)))
        self._hits.append((tg, self._toggle_experimental))
      elif kind == "follow":
        try:
          pers = int(_param(self._params, "LongitudinalPersonality", 1))
        except (TypeError, ValueError):
          pers = 1
        sel = PERSONALITY_VALUES.index(pers) if pers in PERSONALITY_VALUES else 1
        for j, sr in enumerate(K.segmented(right, cy, [tr(t) for t in PERSONALITY_LABELS], sel)):
          self._hits.append((sr, lambda v=PERSONALITY_VALUES[j]: self._put("LongitudinalPersonality", v)))
      elif kind == "profile":
        try:
          prof = int(_param(self._params, "BPTowProfile", 0))
        except (TypeError, ValueError):
          prof = 0
        for j, sr in enumerate(K.segmented(right, cy, [tr(t) for t in PROFILE_LABELS], max(0, min(2, prof)))):
          self._hits.append((sr, lambda v=j: self._put("BPTowProfile", v)))
      elif kind == "pedal":
        tg = K.toggle(right, cy, op != 0)
        self._hits.append((tg, lambda op=op: self._put("BPOnePedalMode", 0 if op != 0 else 2)))

  def _device(self, r: rl.Rectangle):
    y = K.section_title(r, tr("Device"), tr("comma 3X"))
    items = []
    try:
      ds = ui_state.sm["deviceState"]
      items.append((tr("Storage free"), f"{ds.freeSpacePercent:.0f}", "%"))
      items.append((tr("Temperature"), f"{ds.maxTempC:.0f}", "°C"))
    except Exception:
      pass
    ready = ui_state.panda_type is not None and str(ui_state.panda_type) != "unknown"
    items.append((tr("Truck link"), tr("Connected") if ready else tr("Waiting"), ""))
    ver = str(_param(self._params, "Version", "") or "")
    if ver:
      items.append((tr("BluePilot"), ver, ""))
    K.kv_grid(rl.Rectangle(r.x, y, r.width, r.y + r.height - y), items, cols=4)

  def _software(self, r: rl.Rectangle):
    available = bool(_param(self._params, "UpdateAvailable", False))
    y = K.section_title(r, tr("Software"), tr("Update ready") if available else tr("Up to date"))
    desc = str(_param(self._params, "UpdaterNewDescription", "") or "") if available else ""
    msg = desc.split(" / ")[0] if desc else (tr("Installs while parked") if available else tr("Checks on Wi-Fi"))
    label = tr("Open software")
    bw = D.text_w(label, K.KV - 2, semi=True) + 56
    D.dot(r.x + 8, y + K.KV / 2 + 2, 8, Console.ACCENT if available else Console.SUCCESS)
    D.text(D.fit(msg, K.KV, r.width - bw - 60), r.x + 28, y, K.KV)
    br = rl.Rectangle(r.x + r.width - bw, y - 16, bw, 64)
    D.button(br, label, primary=available, size=K.KV - 2)
    self._hits.append((br, lambda: self.on_open_software and self.on_open_software()))

  # -- input ------------------------------------------------------------------------------

  def _put(self, key, value):
    try:
      if isinstance(value, bool):
        self._params.put_bool(key, value)
      else:
        self._params.put(key, value)
    except Exception:
      pass

  def _toggle_experimental(self):
    if not bool(_param(self._params, "ExperimentalModeConfirmed", False)):
      # First use goes through the Assist page, which explains the mode and asks to confirm
      if self.on_open_assist:
        self.on_open_assist()
      return
    self._put("ExperimentalMode", not bool(_param(self._params, "ExperimentalMode", False)))

  def _handle_mouse_release(self, mouse_pos) -> bool:
    for r, fn in self._hits:
      if D.hit(r, mouse_pos):
        fn()
        return True
    return False


class AlertsPage(Widget):
  """Active offroad alerts, most severe first."""

  def __init__(self):
    super().__init__()
    self._params = Params()

  def _render(self, rect: rl.Rectangle):
    alerts = active_alerts(self._params)
    if not alerts:
      D.text_center(tr("No alerts"), rect.x + rect.width / 2, rect.y + rect.height / 2 - 40, K.H2, Console.TEXT_MUTED, semi=True)
      D.text_center(tr("Warnings from the device and the truck show up here."), rect.x + rect.width / 2,
                    rect.y + rect.height / 2 + 6, K.CAP, Console.TEXT_MUTED)
      return
    y = rect.y + 8
    for i, (text, sev) in enumerate(alerts):
      lines = D.wrap(text, K.KV, rect.width - 80, max_lines=3)
      h = 24 + 48 + 20 + len(lines) * 40 + 24
      if y + h > rect.y + rect.height:
        break
      if i:
        K.hline(rect.x, rect.x + rect.width, y)
      K.chip(rect.x, y + 24, tr("Critical") if sev > 0 else tr("Notice"), Console.DANGER if sev > 0 else Console.WARNING)
      ty = y + 24 + 48 + 20
      for ln in lines:
        D.text(ln, rect.x, ty, K.KV)
        ty += 40
      y += h
