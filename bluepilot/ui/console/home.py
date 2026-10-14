"""
Console Home: a few big cards, phone-app style, for the small 3X screen.

  Battery     charge with a thick squared bar, range, tires, 12 V, pack temperature
  Assist      experimental mode, following distance, Lightning profile, one-pedal
  Charging    while plugged in: power and a tap target that reopens the charging page
  Device      storage, temperature, truck link (in place of Charging when unplugged)
  Updates     update state, or the active alerts
Also the Alerts page (active offroad alerts).
"""

from __future__ import annotations

from collections.abc import Callable

import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.lib.ev_data import finite
from bluepilot.ui.lib.theme import Console, roundness

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
  """Temperatures are always Celsius (Canadian units; tire pressure stays in psi)."""
  return f"{c:.0f}", "°C"


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


NETWORK_NAMES = {"wifi": "Wi-Fi", "cell2G": "2G", "cell3G": "3G", "cell4G": "LTE", "cell5G": "5G", "ethernet": "Ethernet"}
STRENGTH = {"poor": 1, "moderate": 2, "good": 3, "great": 4}


def network_status() -> tuple[str, int | None, rl.Color] | None:
  """(label, signal level 0-4 or None, colour) for the header chip; None before deviceState arrives."""
  try:
    ds = ui_state.sm["deviceState"]
    nt = str(ds.networkType)
    strength = str(ds.networkStrength)
  except Exception:
    return None
  if nt in ("none", ""):
    return tr("Offline"), 0, Console.TEXT_GHOST
  if nt == "ethernet":
    return NETWORK_NAMES[nt], None, Console.SUCCESS
  level = STRENGTH.get(strength, 0)
  color = Console.WARNING if level <= 1 else Console.SUCCESS
  return NETWORK_NAMES.get(nt, nt), level, color


def _plugged_in() -> bool:
  """A charge session is running (the charging page may be showing or minimized)."""
  session = getattr(ui_state, "charge_session", None)
  return bool(getattr(session, "active", False)) or bool(getattr(ui_state, "charging_screen", False))


def soc_color(soc: float) -> rl.Color:
  return Console.DANGER if soc < 10 else (Console.WARNING if soc < 20 else Console.SUCCESS)


class ConsoleHome(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._hits: list[tuple[rl.Rectangle, Callable[[], None]]] = []
    self.on_open_drive: Callable[[], None] | None = None
    self.on_open_software: Callable[[], None] | None = None
    self.on_open_assist: Callable[[], None] | None = None
    self.on_open_charging: Callable[[], None] | None = None
    self.on_open_alerts: Callable[[], None] | None = None

  # -- header (the shell draws it) --------------------------------------------------------

  def subtitle(self) -> str:
    s, live = truck_snapshot()
    if _plugged_in():
      state = tr("Charging")
    elif ui_state.started:
      state = tr("Driving")
    else:
      state = tr("Parked")
    return f"{tr('F-150 Lightning')} | {state}" + ("" if live or s is None else " · " + tr("last known data"))

  def sub_dot(self):
    if _plugged_in() or ui_state.started:
      return Console.SUCCESS
    return Console.TEXT_GHOST

  # -- render -------------------------------------------------------------------------

  def _render(self, rect: rl.Rectangle):
    self._hits = []
    gap = 32
    avail = rect.width - gap * 2
    w1, w2 = avail * 0.38, avail * 0.32
    w3 = avail - w1 - w2
    x, y, h = rect.x, rect.y, rect.height
    s, live = truck_snapshot()
    self._battery(rl.Rectangle(x, y, w1, h), s, live)
    x += w1 + gap
    self._assist(rl.Rectangle(x, y, w2, h))
    x += w2 + gap
    top_h = (h - gap) * 0.5
    top = rl.Rectangle(x, y, w3, top_h)
    if _plugged_in():
      self._charging(top, getattr(ui_state, "ev", None))
    else:
      self._device(top)
    self._updates(rl.Rectangle(x, y + top_h + gap, w3, h - top_h - gap))

  def _battery(self, r: rl.Rectangle, s, live: bool):
    D.card(r)
    p = D.CARD_PAD
    x, y, right = r.x + p, r.y + p, r.x + r.width - p
    D.text(tr("Battery"), x, y, D.H2, semi=True)
    status = tr("Charging") if _plugged_in() else (tr("Live") if live else tr("Last known"))
    D.text_right(status, right, y + 6, D.LABEL, Console.SUCCESS if _plugged_in() else Console.TEXT_MUTED, semi=_plugged_in())
    y += 84
    if s is None or not finite(s.soc):
      for ln in D.wrap(tr("No battery data yet. Turn the truck on once and it is kept from then on."), D.BODY, r.width - 2 * p, 3):
        D.text(ln, x, y, D.BODY, Console.TEXT_MUTED)
        y += 48
      return
    D.value_unit(f"{s.soc:.0f}", "%", x, y, 150, 56, light=True)
    if finite(s.range_km):
      metric = ui_state.is_metric
      rng = s.range_km if metric else s.range_km * KM_TO_MI
      unit = "km" if metric else "mi"
      D.text_right(tr("Range"), right, y + 8, D.LABEL, Console.TEXT_MUTED)
      vw = D.text_w(f"{rng:.0f}", 64, semi=True) + 10 + D.text_w(unit, 30)
      D.value_unit(f"{rng:.0f}", unit, right - vw, y + 52, 64, 30)
    y += 180
    K.bar(rl.Rectangle(x, y, r.width - 2 * p, K.BAR_H), s.soc / 100.0, soc_color(s.soc))
    y += K.BAR_H + 48

    tiles = []
    if len(s.tire_kpa) == 4 and all(finite(t) and t > 0 for t in s.tire_kpa):
      psi = [t * KPA_TO_PSI for t in s.tire_kpa]
      tiles.append((tr("Front tires"), f"{psi[0]:.0f} / {psi[1]:.0f}", "psi", s.tire_low))
      tiles.append((tr("Rear tires"), f"{psi[2]:.0f} / {psi[3]:.0f}", "psi", s.tire_low))
    if finite(s.lv_volts):
      tiles.append((tr("12 V battery"), f"{s.lv_volts:.1f}", "V", s.lv_low))
    if finite(s.pack_temp_c):
      v, u = temp(s.pack_temp_c)
      tiles.append((tr("Pack"), v, u, False))
    tw = (r.width - 2 * p - 24) / 2
    th = min(140, (r.y + r.height - p - y - 24) / 2)
    for i, (label, val, unit, warn) in enumerate(tiles[:4]):
      t = rl.Rectangle(x + (i % 2) * (tw + 24), y + (i // 2) * (th + 24), tw, th)
      rl.draw_rectangle_rounded(t, roundness(t, 16), 8, Console.BG_RAISED)
      D.text(D.fit(label, D.LABEL, tw - 48), t.x + 24, t.y + 20, D.LABEL, Console.TEXT_MUTED)
      D.value_unit(val, unit, t.x + 24, t.y + th - 72, 48, 28, Console.WARNING if warn else None)

  def _assist(self, r: rl.Rectangle):
    D.card(r)
    p = D.CARD_PAD
    x, y, right = r.x + p, r.y + p, r.x + r.width - p
    D.text(tr("Driver assist"), x, y, D.H2, semi=True)
    y += 92

    exp = bool(_param(self._params, "ExperimentalMode", False))
    D.text(tr("Experimental mode"), x, y + 2, D.BODY, semi=True)
    D.text(D.fit(tr("End-to-end speed control"), D.LABEL, r.width - 2 * p - 130), x, y + 48, D.LABEL, Console.TEXT_MUTED)
    tg = D.toggle(right - 104, y + 14, exp)
    self._hits.append((tg, self._toggle_experimental))
    y += 112
    K.hline(x, right, y)
    y += 32

    D.text(tr("Following distance"), x, y, D.BODY, semi=True)
    y += 56
    try:
      pers = int(_param(self._params, "LongitudinalPersonality", 1))
    except (TypeError, ValueError):
      pers = 1
    sel = PERSONALITY_VALUES.index(pers) if pers in PERSONALITY_VALUES else 1
    for i, sr in enumerate(D.segmented(rl.Rectangle(x, y, r.width - 2 * p, D.CONTROL_H), [tr(t) for t in PERSONALITY_LABELS], sel)):
      self._hits.append((sr, lambda v=PERSONALITY_VALUES[i]: self._put("LongitudinalPersonality", v)))
    y += D.CONTROL_H + 36

    if has_param(self._params, "BPTowProfile"):
      D.text(tr("Lightning profile"), x, y, D.BODY, semi=True)
      y += 56
      try:
        prof = int(_param(self._params, "BPTowProfile", 0))
      except (TypeError, ValueError):
        prof = 0
      for i, sr in enumerate(D.segmented(rl.Rectangle(x, y, r.width - 2 * p, D.CONTROL_H), [tr(t) for t in PROFILE_LABELS],
                                         max(0, min(2, prof)))):
        self._hits.append((sr, lambda v=i: self._put("BPTowProfile", v)))
      y += D.CONTROL_H + 36

    link_y = r.y + r.height - p - 44
    if has_param(self._params, "BPOnePedalMode") and y + 100 < link_y - 24:
      K.hline(x, right, y - 4)
      y += 28
      try:
        op = int(_param(self._params, "BPOnePedalMode", 2))
      except (TypeError, ValueError):
        op = 2
      D.text(tr("One-pedal driving"), x, y + 2, D.BODY, semi=True)
      D.text(tr("Estimated from coast-down") if op == 2 else (tr("On") if op == 1 else tr("Off")), x, y + 48, D.LABEL, Console.TEXT_MUTED)
      tg = D.toggle(right - 104, y + 14, op != 0)
      self._hits.append((tg, lambda op=op: self._put("BPOnePedalMode", 0 if op != 0 else 2)))

    link = tr("All driving settings")
    lr = rl.Rectangle(x - 16, link_y - 16, D.text_w(link, D.BODY, semi=True) + 32, 76)
    D.text(link, x, link_y, D.BODY, Console.ACCENT_TEXT, semi=True)
    self._hits.append((lr, lambda: self.on_open_drive and self.on_open_drive()))

  def _charging(self, r: rl.Rectangle, s):
    """Plugged in: the way back to the charging page after it was minimized."""
    D.card(r, Console.ACCENT_TINT)
    p = D.CARD_PAD
    x, y = r.x + p, r.y + p
    D.icon("bolt", x, y, 44, Console.ACCENT_TEXT)
    kind = {1: tr("AC charging"), 2: tr("DC fast charging")}.get(getattr(s, "charge_type", 0), tr("Charging")) if s else tr("Charging")
    D.text(D.fit(kind, D.H2, r.width - 2 * p - 64, semi=True), x + 64, y, D.H2, Console.ACCENT_TEXT, semi=True)
    y += 92
    kw = getattr(s, "charge_power_kw", float("nan")) if s is not None else float("nan")
    if finite(kw):
      D.value_unit(f"{kw:.1f}" if kw < 100 else f"{kw:.0f}", "kW", x, y, 88, 36)
    else:
      D.text(tr("Plugged in"), x, y + 20, D.BODY, Console.TEXT_SECONDARY)
    br = rl.Rectangle(x, r.y + r.height - p - D.CONTROL_H, r.width - 2 * p, D.CONTROL_H)
    D.button(br, tr("Open charging"), primary=True)
    self._hits.append((r, lambda: self.on_open_charging and self.on_open_charging()))

  def _device(self, r: rl.Rectangle):
    D.card(r)
    p = D.CARD_PAD
    x, y, right = r.x + p, r.y + p, r.x + r.width - p
    D.text(tr("Device"), x, y, D.H2, semi=True)
    D.text_right(tr("comma 3X"), right, y + 6, D.LABEL, Console.TEXT_MUTED)
    y += 92
    rows = []
    ready = ui_state.panda_type is not None and str(ui_state.panda_type) != "unknown"
    rows.append((tr("Truck link"), tr("Connected") if ready else tr("Waiting")))
    try:
      ds = ui_state.sm["deviceState"]
      rows.append((tr("Storage free"), f"{ds.freeSpacePercent:.0f} %"))
      rows.append((tr("Temperature"), f"{ds.maxTempC:.0f} °C"))
    except Exception:
      pass
    for label, val in rows:
      if y + D.BODY > r.y + r.height - p:
        break
      D.text(label, x, y, D.BODY, Console.TEXT_MUTED)
      D.text_right(val, right, y, D.BODY, semi=True)
      y += 64

  def _updates(self, r: rl.Rectangle):
    alerts = active_alerts(self._params)
    D.card(r)
    p = D.CARD_PAD
    x, y = r.x + p, r.y + p
    if alerts:
      D.dot(x + 10, y + D.H2 / 2 + 2, 10, Console.DANGER if alerts[0][1] > 0 else Console.WARNING)
      D.text(tr("1 alert") if len(alerts) == 1 else f"{len(alerts)} " + tr("alerts"), x + 36, y, D.H2, semi=True)
      y += 76
      for ln in D.wrap(alerts[0][0], D.LABEL, r.width - 2 * p, 2):
        D.text(ln, x, y, D.LABEL, Console.TEXT_SECONDARY)
        y += 40
      br = rl.Rectangle(x, r.y + r.height - p - D.CONTROL_H, r.width - 2 * p, D.CONTROL_H)
      D.button(br, tr("View alerts"), primary=False)
      self._hits.append((br, lambda: self.on_open_alerts and self.on_open_alerts()))
      return
    available = bool(_param(self._params, "UpdateAvailable", False))
    D.dot(x + 10, y + D.H2 / 2 + 2, 10, Console.ACCENT if available else Console.SUCCESS)
    D.text(tr("Update ready") if available else tr("Up to date"), x + 36, y, D.H2, semi=True)
    y += 76
    desc = str(_param(self._params, "UpdaterNewDescription", "") or "") if available else ""
    idle = tr("Installs while parked") if available else tr("Checks for updates on Wi-Fi")
    D.text(D.fit(desc.split(" / ")[0] if desc else idle, D.LABEL, r.width - 2 * p), x, y, D.LABEL, Console.TEXT_SECONDARY)
    br = rl.Rectangle(x, r.y + r.height - p - D.CONTROL_H, r.width - 2 * p, D.CONTROL_H)
    D.button(br, tr("Open software"), primary=available)
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
