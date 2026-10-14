"""
Console Home: the truck dashboard shown when parked.

  Battery     last known charge, range, tires, 12 V and pack temperature
  Assist      experimental mode, following distance, Lightning profile, one-pedal
  Device      software, connection, storage and temperature
  Updates     update state with a shortcut to Software
"""

from __future__ import annotations

from collections.abc import Callable

import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from bluepilot.ui.console import draw as D
from bluepilot.ui.lib.ev_data import finite
from bluepilot.ui.lib.theme import Console, roundness

KM_TO_MI = 0.621371
KPA_TO_PSI = 0.145038

PERSONALITY_LABELS = ["Relaxed", "Standard", "Close"]
PERSONALITY_VALUES = [2, 1, 0]          # LongitudinalPersonality: 0 aggressive, 1 standard, 2 relaxed
PROFILE_LABELS = ["Auto", "Off", "Tow"]  # BPTowProfile: 0 auto, 1 off, 2 always on


class ConsoleHome(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._hits: list[tuple[rl.Rectangle, Callable[[], None]]] = []
    self.on_open_drive: Callable[[], None] | None = None
    self.on_open_software: Callable[[], None] | None = None
    self.on_open_assist: Callable[[], None] | None = None

  # -- params ----------------------------------------------------------------------

  def _get(self, key, default=None):
    try:
      v = self._params.get(key, return_default=True)
    except Exception:
      return default
    return default if v is None else v

  def _has(self, key) -> bool:
    try:
      self._params.get(key, return_default=True)
      return True
    except Exception:
      return False

  def _put(self, key, value):
    try:
      if isinstance(value, bool):
        self._params.put_bool(key, value)
      else:
        self._params.put(key, value)
    except Exception:
      pass

  # -- render ---------------------------------------------------------------------

  def _render(self, rect: rl.Rectangle):
    self._hits = []
    gap = 32
    col_w = (rect.width - gap * 2)
    w1, w2 = col_w * 0.38, col_w * 0.31
    w3 = col_w - w1 - w2
    h = rect.height - 8
    x = rect.x
    self._battery(rl.Rectangle(x, rect.y + 8, w1, h))
    x += w1 + gap
    self._assist(rl.Rectangle(x, rect.y + 8, w2, h))
    x += w2 + gap
    top_h = (h - gap) * 0.5
    self._device(rl.Rectangle(x, rect.y + 8, w3, top_h))
    self._updates(rl.Rectangle(x, rect.y + 8 + top_h + gap, w3, h - top_h - gap))

  def _battery(self, r: rl.Rectangle):
    D.card(r)
    p = D.CARD_PAD
    x, y, right = r.x + p, r.y + p, r.x + r.width - p
    src = getattr(ui_state, "ev_source", None)
    s = getattr(ui_state, "ev", None)
    if s is None or not s.available:
      s = getattr(src, "last_good", None) if src is not None else None
    D.text(tr("Battery"), x, y, D.H2, semi=True)
    live = s is not None and getattr(ui_state, "started", False)
    status = tr("Charging") if getattr(ui_state, "charging_screen", False) else (tr("Live") if live else tr("Last known"))
    D.text_right(status, right, y + 6, D.LABEL, Console.TEXT_MUTED)
    y += 76
    if s is None or not finite(s.soc):
      D.text(D.fit(tr("No battery data yet. Turn the truck on."), D.LABEL, r.width - 2 * p), x, y + 20, D.LABEL, Console.TEXT_MUTED)
      return
    D.value_unit(f"{s.soc:.0f}", "%", x, y, 150, 56, light=True)
    if finite(s.range_km):
      metric = ui_state.is_metric
      rng = s.range_km if metric else s.range_km * KM_TO_MI
      D.text_right(tr("Range"), right, y + 92, D.LABEL, Console.TEXT_MUTED)
      vw = D.text_w(f"{rng:.0f}", 64, semi=True) + 10 + D.text_w("km" if metric else "mi", 30)
      D.value_unit(f"{rng:.0f}", "km" if metric else "mi", right - vw, y + 10, 64, 30)
    y += 176
    fill = Console.DANGER if s.soc < 10 else (Console.WARNING if s.soc < 20 else Console.SUCCESS)
    D.bar(rl.Rectangle(x, y, r.width - 2 * p, 24), s.soc / 100.0, fill)
    y += 56

    tiles = []
    if len(s.tire_kpa) == 4 and all(finite(t) and t > 0 for t in s.tire_kpa):
      psi = [t * KPA_TO_PSI for t in s.tire_kpa]
      tiles.append((tr("Front tires"), f"{psi[0]:.0f} / {psi[1]:.0f}", "psi", s.tire_low))
      tiles.append((tr("Rear tires"), f"{psi[2]:.0f} / {psi[3]:.0f}", "psi", s.tire_low))
    if finite(s.lv_volts):
      tiles.append((tr("12 V battery"), f"{s.lv_volts:.1f}", "V", s.lv_low))
    if finite(s.pack_temp_c):
      t = s.pack_temp_c if ui_state.is_metric else s.pack_temp_c * 9 / 5 + 32
      tiles.append((tr("Pack temperature"), f"{t:.0f}", "°C" if ui_state.is_metric else "°F", False))
    tw = (r.width - 2 * p - 20) / 2
    for i, (label, val, unit, warn) in enumerate(tiles[:4]):
      tr_ = rl.Rectangle(x + (i % 2) * (tw + 20), y + (i // 2) * 136, tw, 120)
      rl.draw_rectangle_rounded(tr_, roundness(tr_, 12), 8, Console.BG_RAISED)
      D.text(label, tr_.x + 24, tr_.y + 18, D.CAPTION, Console.TEXT_MUTED)
      D.value_unit(val, unit, tr_.x + 24, tr_.y + 54, 44, 26, Console.WARNING if warn else None)

  def _assist(self, r: rl.Rectangle):
    D.card(r)
    p = D.CARD_PAD
    x, y, right = r.x + p, r.y + p, r.x + r.width - p
    D.text(tr("Driver assist"), x, y, D.H2, semi=True)
    y += 80

    # Experimental mode
    exp = bool(self._get("ExperimentalMode", False))
    D.text(tr("Experimental mode"), x, y + 4, D.BODY, semi=True)
    D.text(tr("End-to-end speed control"), x, y + 46, D.CAPTION, Console.TEXT_MUTED)
    tg = D.toggle(right - 104, y + 14, exp)
    self._hits.append((tg, self._toggle_experimental))
    y += 112
    rl.draw_rectangle_rec(rl.Rectangle(x, y, r.width - 2 * p, 2), Console.BORDER_SUBTLE)
    y += 24

    # Following distance
    D.text(tr("Following distance"), x, y, D.BODY, semi=True)
    y += 52
    try:
      pers = int(self._get("LongitudinalPersonality", 1))
    except (TypeError, ValueError):
      pers = 1
    sel = PERSONALITY_VALUES.index(pers) if pers in PERSONALITY_VALUES else 1
    rects = D.segmented(rl.Rectangle(x, y, r.width - 2 * p, D.CONTROL_H), [tr(s) for s in PERSONALITY_LABELS], sel)
    for i, sr in enumerate(rects):
      self._hits.append((sr, lambda v=PERSONALITY_VALUES[i]: self._put("LongitudinalPersonality", v)))
    y += D.CONTROL_H + 28

    # Lightning profile (stream B param; shown when this build has it)
    if self._has("BPTowProfile"):
      D.text(tr("Lightning profile"), x, y, D.BODY, semi=True)
      y += 52
      try:
        prof = int(self._get("BPTowProfile", 0))
      except (TypeError, ValueError):
        prof = 0
      rects = D.segmented(rl.Rectangle(x, y, r.width - 2 * p, D.CONTROL_H), [tr(s) for s in PROFILE_LABELS], max(0, min(2, prof)))
      for i, sr in enumerate(rects):
        self._hits.append((sr, lambda v=i: self._put("BPTowProfile", v)))
      y += D.CONTROL_H + 28

    if self._has("BPOnePedalMode"):
      try:
        op = int(self._get("BPOnePedalMode", 2))
      except (TypeError, ValueError):
        op = 2
      D.text(tr("One-pedal driving"), x, y + 4, D.BODY, semi=True)
      D.text(tr("Estimated from coast-down") if op == 2 else (tr("On") if op == 1 else tr("Off")), x, y + 46, D.CAPTION, Console.TEXT_MUTED)
      tg = D.toggle(right - 104, y + 14, op != 0)
      self._hits.append((tg, lambda: self._put("BPOnePedalMode", 0 if op != 0 else 2)))

    link = tr("All driving settings")
    lr = rl.Rectangle(x, r.y + r.height - p - 44, D.text_w(link, D.BODY, semi=True), 44)
    D.text(link, lr.x, lr.y, D.BODY, Console.ACCENT_TEXT, semi=True)
    self._hits.append((lr, lambda: self.on_open_drive and self.on_open_drive()))

  def _device(self, r: rl.Rectangle):
    D.card(r)
    p = D.CARD_PAD
    x, y = r.x + p, r.y + p
    D.text(tr("Device"), x, y, D.H2, semi=True)
    y += 72
    rows = []
    try:
      ds = ui_state.sm["deviceState"]
      rows.append((tr("Storage free"), f"{ds.freeSpacePercent:.0f} %"))
      rows.append((tr("Temperature"), f"{ds.maxTempC:.0f} °C"))
    except Exception:
      pass
    ver = self._get("Version", "")
    if isinstance(ver, bytes):
      ver = ver.decode(errors="ignore")
    if ver:
      rows.append((tr("BluePilot"), str(ver)))
    for label, val in rows[:3]:
      D.text(label, x, y, D.LABEL, Console.TEXT_MUTED)
      D.text_right(val, r.x + r.width - p, y, D.LABEL, Console.TEXT_PRIMARY, semi=True)
      y += 46

  def _active_alerts(self) -> list[tuple[str, int]]:
    try:
      from openpilot.selfdrive.selfdrived.alertmanager import OFFROAD_ALERTS
    except Exception:
      return []
    out = []
    for key, cfg in sorted(OFFROAD_ALERTS.items(), key=lambda x: x[1].get("severity", 0), reverse=True):
      try:
        val = self._params.get(key)
      except Exception:
        continue
      if not val:
        continue
      text = val.get("text", "") if isinstance(val, dict) else ""
      if not text:
        text = cfg.get("text", "")
      out.append((str(text).replace("%1", "").strip(), int(cfg.get("severity", 0))))
    return out

  def _updates(self, r: rl.Rectangle):
    alerts = self._active_alerts()
    if alerts:
      self._alerts(r, alerts)
      return
    D.card(r)
    p = D.CARD_PAD
    x, y = r.x + p, r.y + p
    available = bool(self._get("UpdateAvailable", False))
    D.dot(x + 10, y + 22, 10, Console.ACCENT if available else Console.SUCCESS)
    D.text(tr("Update ready") if available else tr("Up to date"), x + 36, y, D.H2, semi=True)
    y += 64
    desc = self._get("UpdaterNewDescription", "") if available else ""
    if isinstance(desc, bytes):
      desc = desc.decode(errors="ignore")
    idle = tr("Installs while parked, then the device restarts.") if available else tr("BluePilot checks for updates on Wi-Fi.")
    msg = str(desc).split(" / ")[0] if desc else idle
    D.text(D.fit(msg, D.LABEL, r.width - 2 * p), x, y, D.LABEL, Console.TEXT_SECONDARY)
    br = rl.Rectangle(x, r.y + r.height - p - 80, 300, 80)
    D.button(br, tr("Open software"), primary=available)
    self._hits.append((br, lambda: self.on_open_software and self.on_open_software()))

  def _alerts(self, r: rl.Rectangle, alerts: list[tuple[str, int]]):
    D.card(r)
    p = D.CARD_PAD
    x, y = r.x + p, r.y + p
    D.text(tr("Alerts"), x, y, D.H2, semi=True)
    D.text_right(str(len(alerts)), r.x + r.width - p, y + 6, D.LABEL, Console.TEXT_MUTED)
    y += 72
    for text, sev in alerts:
      if y + 44 > r.y + r.height - p:
        break
      D.dot(x + 8, y + 16, 8, Console.DANGER if sev > 0 else Console.WARNING)
      for ln in D.wrap(text, D.LABEL, r.width - 2 * p - 32):
        D.text(ln, x + 32, y, D.LABEL, Console.TEXT_SECONDARY)
        y += 38
      y += 18

  # -- input ------------------------------------------------------------------------

  def _toggle_experimental(self):
    confirmed = bool(self._get("ExperimentalModeConfirmed", False))
    if not confirmed:
      # First use goes through the Assist page, which explains the mode and asks to confirm
      if self.on_open_assist:
        self.on_open_assist()
      return
    self._put("ExperimentalMode", not bool(self._get("ExperimentalMode", False)))

  def _handle_mouse_release(self, mouse_pos) -> bool:
    for r, fn in self._hits:
      if D.hit(r, mouse_pos):
        fn()
        return True
    return False
