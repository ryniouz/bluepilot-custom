"""
Console Home: a few big cards, phone-app style, for the small 3X screen.

  Battery     charge with a thick squared bar, range, tires, 12 V, pack temperature
  Assist      experimental mode, following distance, Guest Mode, Lightning profile, one-pedal
  Charging    while plugged in: power and a tap target that reopens the charging page
  Connection  Wi-Fi, LTE and server/sync (in place of Charging when unplugged)
  Recording   recording now, the storage bar, drives waiting to sync, uploads in progress
Updates live on System > Updates and alerts behind the header chip, so neither takes a card here.
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
from bluepilot.ui.lib.theme import Console, roundness, with_alpha

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
  # Lightning-only build: card went passive for another car (stream B, BPPlatformMismatch; cleared on the next match)
  try:
    other = params.get("BPPlatformMismatch")
  except Exception:
    other = None
  if other:
    from bluepilot.ui.console.pages.vehicle import platform_name
    other = other.decode(errors="ignore") if isinstance(other, bytes) else str(other)
    out.insert(0, (tr("Detected") + f" {platform_name(other)}: " +
                   tr("driver assist is off. This build only drives the Ford F-150 Lightning."), 1))
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
    self.on_open_connectivity: Callable[[], None] | None = None
    self.on_open_storage: Callable[[], None] | None = None
    self.wifi_ssid: Callable[[], str] = lambda: ""

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
    if self.guest_armed():
      banner = rl.Rectangle(rect.x, rect.y, rect.width, 76)
      self._guest_banner(banner)
      rect = rl.Rectangle(rect.x, rect.y + 76 + 24, rect.width, rect.height - 76 - 24)
    avail = rect.width - gap * 2
    w1, w2 = avail * 0.36, avail * 0.32
    w3 = avail - w1 - w2
    x, y, h = rect.x, rect.y, rect.height
    s, live = truck_snapshot()
    self._battery(rl.Rectangle(x, y, w1, h), s, live)
    x += w1 + gap
    self._assist(rl.Rectangle(x, y, w2, h))
    x += w2 + gap
    top_h = (h - gap) * 0.53
    top = rl.Rectangle(x, y, w3, top_h)
    if _plugged_in():
      self._charging(top, getattr(ui_state, "ev", None))
    else:
      self._connection(top)
    self._recording(rl.Rectangle(x, y + top_h + gap, w3, h - top_h - gap))

  # -- Guest Mode (keys come from the Lightning control branch; hidden until they exist) ----

  def guest_available(self) -> bool:
    return has_param(self._params, "BPGuestMode")

  def guest_armed(self) -> bool:
    return self.guest_available() and bool(_param(self._params, "BPGuestMode", False))

  def guest_active(self) -> bool:
    return has_param(self._params, "BPGuestModeActive") and bool(_param(self._params, "BPGuestModeActive", False))

  def _guest_banner(self, r: rl.Rectangle):
    rl.draw_rectangle_rounded(r, roundness(r, 20), 8, with_alpha(Console.WARNING, 0x2E))
    D.icon("person", r.x + 28, r.y + (r.height - 40) / 2, 40, Console.WARNING)
    msg = tr("Guest Mode: factory driver assist for this drive") if self.guest_active() else \
      tr("Guest Mode: factory driver assist at next start")
    D.text(D.fit(msg, D.BODY, r.width - 420, semi=True), r.x + 92, r.y + (r.height - D.BODY) / 2 - 2, D.BODY,
           Console.WARNING, semi=True)
    one_trip = bool(_param(self._params, "BPGuestModeOneTrip", True))
    note = tr("Turns off after one drive") if one_trip else tr("Stays on until turned off")
    D.text_right(note, r.x + r.width - 28, r.y + (r.height - D.LABEL) / 2 - 2, D.LABEL, Console.WARNING)

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
    link_y = r.y + r.height - p - 44

    if self.guest_available():
      y = self._guest_rows(r, y)

    if has_param(self._params, "BPTowProfile") and y + 56 + D.CONTROL_H < link_y - 24:
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

    if has_param(self._params, "BPOnePedalMode") and y + 28 + 48 + D.LABEL + 8 < link_y - 24:
      K.hline(x, right, y - 4)
      y += 28
      try:
        op = int(_param(self._params, "BPOnePedalMode", 2))
      except (TypeError, ValueError):
        op = 2
      D.text(tr("One-pedal driving"), x, y + 2, D.BODY, semi=True)
      D.text(D.fit(tr("Estimated from coast-down") if op == 2 else (tr("On") if op == 1 else tr("Off")), D.LABEL, r.width - 2 * p - 130),
             x, y + 48, D.LABEL, Console.TEXT_MUTED)
      tg = D.toggle(right - 104, y + 14, op != 0)
      self._hits.append((tg, lambda op=op: self._put("BPOnePedalMode", 0 if op != 0 else 2)))

    link = tr("All driving settings")
    lr = rl.Rectangle(x - 16, link_y - 16, D.text_w(link, D.BODY, semi=True) + 32, 76)
    D.text(link, x, link_y, D.BODY, Console.ACCENT_TEXT, semi=True)
    self._hits.append((lr, lambda: self.on_open_drive and self.on_open_drive()))

  def _guest_rows(self, r: rl.Rectangle, y: float) -> float:
    p = D.CARD_PAD
    x, right = r.x + p, r.x + r.width - p
    armed = self.guest_armed()
    locked = ui_state.started
    K.hline(x, right, y - 4)
    y += 28
    D.text(tr("Guest Mode"), x, y + 2, D.BODY, semi=True)
    if locked:
      sub = tr("Applies at next start")
    elif armed:
      sub = tr("Factory assist at next start")
    else:
      sub = tr("Factory cruise and lane keeping")
    D.text(D.fit(sub, D.LABEL, r.width - 2 * p - 130), x, y + 48, D.LABEL, Console.WARNING if armed else Console.TEXT_MUTED)
    tg = D.toggle(right - 104, y + 14, armed, enabled=not locked)
    if not locked:
      self._hits.append((tg, lambda: self._put("BPGuestMode", not armed)))
    y += 112
    if armed and has_param(self._params, "BPGuestModeOneTrip"):
      one_trip = bool(_param(self._params, "BPGuestModeOneTrip", True))
      opts = [tr("One drive"), tr("Keep on")]
      for i, sr in enumerate(D.segmented(rl.Rectangle(x, y, r.width - 2 * p, D.CONTROL_H), opts, 0 if one_trip else 1)):
        if not locked:
          self._hits.append((sr, lambda v=(i == 0): self._put("BPGuestModeOneTrip", v)))
      y += D.CONTROL_H + 36
    return y

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

  def _connection(self, r: rl.Rectangle):
    from bluepilot.ui.console.pages.connectivity import ConnectivityPage
    D.card(r)
    p = D.CARD_PAD
    x, y, right = r.x + p, r.y + p, r.x + r.width - p
    D.text(tr("Connection"), x, y, D.H2, semi=True)
    y += 84
    try:
      ds = ui_state.sm["deviceState"]
      nt, level = str(ds.networkType), STRENGTH.get(str(ds.networkStrength), 0)
      info = ds.networkInfo
    except Exception:
      nt, level, info = "none", 0, None
    ssid = self.wifi_ssid()
    rows: list[tuple[str, int | None, str, rl.Color]] = []
    if nt == "wifi":
      rows.append((tr("Wi-Fi"), level, ssid or tr("Connected"), Console.WARNING if level <= 1 else Console.SUCCESS))
    else:
      rows.append((tr("Wi-Fi"), 0, tr("Not connected"), Console.TEXT_GHOST))
    if nt.startswith("cell"):
      op = str(getattr(info, "operator", "") or "") if info is not None else ""
      rows.append((tr("LTE"), level, op or NETWORK_NAMES.get(nt, nt), Console.WARNING if level <= 1 else Console.SUCCESS))
    else:
      rows.append((tr("LTE"), 0, tr("Standby") if nt == "wifi" else tr("No signal"), Console.TEXT_GHOST))
    status, color, _ = ConnectivityPage.server_state(self)
    short = {tr("Server not set up yet"): tr("Not set up"), tr("Server connected"): tr("Connected"),
             tr("Server not reachable"): tr("Not reachable"), tr("Server set, uploader off"): tr("Uploader off")}
    rows.append((tr("Server"), None, short.get(status, status), color))
    for label, lvl, value, color in rows:
      if y + 22 + D.BODY > r.y + r.height - p:
        break
      K.hline(x, right, y)
      y += 22
      D.text(label, x, y, D.BODY, Console.TEXT_MUTED)
      vw = D.text_w(D.fit(value, D.BODY, r.width * 0.5, semi=True), D.BODY, semi=True)
      D.text_right(D.fit(value, D.BODY, r.width * 0.5, semi=True), right, y, D.BODY, semi=True)
      if lvl is not None:
        K.signal_bars(right - vw - 56, y + D.BODY - 2, 28, lvl, color)
      else:
        D.dot(right - vw - 24, y + D.BODY / 2 + 2, 9, color)
      y += 72
    self._hits.append((r, lambda: self.on_open_connectivity and self.on_open_connectivity()))

  def _recording(self, r: rl.Rectangle):
    from bluepilot.ui.console.pages.drives import fmt_bytes, storage_bar, storage_breakdown
    from bluepilot.ui.lib import bridge_status as bridge
    from bluepilot.ui.lib.drive_index import indexer
    indexer().request()
    D.card(r)
    p = D.CARD_PAD
    x, y, right = r.x + p, r.y + p, r.x + r.width - p
    D.text(tr("Recording"), x, y, D.H2, semi=True)
    if ui_state.started:
      D.dot(right - D.text_w(tr("Recording now"), D.LABEL, semi=True) - 24, y + 22, 9, Console.DANGER)
      D.text_right(tr("Recording now"), right, y + 6, D.LABEL, semi=True)
    else:
      try:
        D.text_right(f"comma 3X · {ui_state.sm['deviceState'].maxTempC:.0f} °C", right, y + 6, D.LABEL, Console.TEXT_MUTED)
      except Exception:
        pass
    y += 84
    st = storage_breakdown()
    if st is not None and st.total:
      fv, fu = fmt_bytes(st.free)
      tv, tu = fmt_bytes(st.total)
      D.text(f"{fv} {fu} " + tr("free of") + f" {tv} {tu}", x, y, D.BODY, Console.TEXT_SECONDARY)
      y += 56
      storage_bar(rl.Rectangle(x, y, r.width - 2 * p, K.BAR_H), st)
      y += K.BAR_H + 32
    idx = indexer().index
    rt = bridge.get("roadTrip")
    lines: list[tuple[rl.Color, str]] = []
    if isinstance(rt, dict) and rt.get("state") == "uploading":
      cur = rt.get("current") or {}
      q = rt.get("queue") or {}
      lines.append((Console.ACCENT, tr("Uploading") + f" {int(q.get('files') or 0)} " + tr("files")
                    + (f", {int(cur.get('pct') or 0)} %" if cur else "")))
    waiting = sum(1 for d in idx.drives if not d.synced and not d.recording)
    if idx.sync_known:
      lines.append((Console.SUCCESS, tr("All drives synced")) if waiting == 0 else
                   (Console.WARNING, f"{waiting} " + (tr("drive waiting to sync") if waiting == 1 else tr("drives waiting to sync"))))
    elif idx.scanned_at:
      n = len(idx.drives)
      lines.append((Console.TEXT_GHOST, f"{n} " + (tr("drive on the comma") if n == 1 else tr("drives on the comma"))))
    for color, text in lines:
      if y + 22 + D.BODY > r.y + r.height - p:
        break
      K.hline(x, right, y)
      y += 22
      D.dot(x + 9, y + D.BODY / 2 + 2, 9, color)
      D.text(D.fit(text, D.BODY, r.width - 2 * p - 36), x + 32, y, D.BODY)
      y += 72
    self._hits.append((r, lambda: self.on_open_storage and self.on_open_storage()))

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
