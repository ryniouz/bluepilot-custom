"""
Console Connectivity page (Connect > Status): one look at every link the comma has.

  Wi-Fi         signal, network, home networks (tap to mark the connected one as home)
  LTE           signal, carrier, data used this month and since start-up
  Server, sync  self-hosted server (not built yet), comma connect, Citadel sync
  Home          GPS home location: set it from where the truck is parked, and whether it is home now
"""

from __future__ import annotations

import json
from collections.abc import Callable

import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.console.home import STRENGTH, _param, has_param
from bluepilot.ui.lib import bridge_status as bridge
from bluepilot.ui.lib.drive_index import indexer
from bluepilot.ui.lib.home_location import home_location
from bluepilot.ui.lib.net_usage import fmt_data, usage
from bluepilot.ui.lib.theme import Console

GAP = 32
ROW = 76


def home_wifi(params: Params) -> list[str]:
  try:
    raw = params.get("BPHomeWifi")
    data = json.loads(raw) if isinstance(raw, (str, bytes)) else raw
    return [str(s) for s in data] if isinstance(data, list) else []
  except Exception:
    return []


def _short_time(iso: str) -> str:
  """'2026-10-14T07:12:30' -> '07:12' today, else 'Oct 14 07:12'."""
  import time as _t
  try:
    t = _t.strptime(iso[:19], "%Y-%m-%dT%H:%M:%S")
  except ValueError:
    return iso.replace("T", " ")[:16]
  if _t.strftime("%Y-%m-%d") == iso[:10]:
    return _t.strftime("%H:%M", t)
  return _t.strftime("%b %d %H:%M", t)


def _text(v) -> str:
  if isinstance(v, bytes):
    v = v.decode(errors="ignore")
  return str(v or "").strip("\x00").strip()


class ConnectivityPage(Widget):
  def __init__(self, wifi_manager=None):
    super().__init__()
    self._params = Params()
    self._wifi = wifi_manager
    self._hits: list[tuple[rl.Rectangle, Callable[[], None]]] = []
    self.on_open_wifi: Callable[[], None] | None = None
    self.on_open_export: Callable[[], None] | None = None
    self.on_open_uploads: Callable[[], None] | None = None
    self.on_open_cellular: Callable[[], None] | None = None
    self.on_open_automations: Callable[[], None] | None = None

  def show_event(self):
    super().show_event()
    indexer().request()

  # -- data ---------------------------------------------------------------------------------

  def _connected_ssid(self) -> str:
    try:
      return _text(self._wifi.connected_ssid) if self._wifi is not None else ""
    except Exception:
      return ""

  @staticmethod
  def _device_state():
    try:
      return ui_state.sm["deviceState"]
    except Exception:
      return None

  # -- render -------------------------------------------------------------------------------

  def _render(self, rect: rl.Rectangle):
    self._hits = []
    ds = self._device_state()
    if ds is not None:
      usage().tick(ds)
    cols = K.split_cols(rect, [1, 1])
    left, right = cols[0], cols[1]
    left.width -= GAP / 2
    right.x += GAP / 2
    right.width -= GAP / 2
    lt, lb = K.split_rows(left, [1, 1])
    rt, rb = K.split_rows(right, [1, 1])
    for r in (lt, rt):
      r.height -= GAP / 2
    for r in (lb, rb):
      r.y += GAP / 2
      r.height -= GAP / 2
    self._wifi_card(lt, ds)
    self._lte_card(lb, ds)
    self._server_card(rt, ds)
    self._home_card(rb)

  def _head(self, r: rl.Rectangle, title: str, level: int | None, status: str, color: rl.Color) -> float:
    D.card(r)
    p = D.CARD_PAD
    D.text(title, r.x + p, r.y + p, D.H2, semi=True)
    sx = r.x + p
    y = r.y + p + 72
    if level is not None:
      sx += K.signal_bars(sx, y + D.BODY - 2, 32, level, color) + 18
    else:
      D.dot(sx + 10, y + D.BODY / 2 + 2, 10, color)
      sx += 36
    D.text(D.fit(status, D.BODY, r.x + r.width - p - sx, semi=True), sx, y, D.BODY, semi=True)
    return y + 68

  def _row(self, r: rl.Rectangle, y: float, label: str, value: str, value_color: rl.Color | None = None,
           button: bool = False) -> float:
    """A label/value row; skipped when it would run into the card's bottom button (button=True) or edge."""
    p = D.CARD_PAD
    bottom = r.y + r.height - p - (72 + 12 if button else 0)
    if y + ROW > bottom + 8:
      return y
    K.hline(r.x + p, r.x + r.width - p, y)
    lw = D.text_w(label, D.LABEL)
    label = D.fit(label, D.LABEL, r.width * 0.6)
    D.text(label, r.x + p, y + 20, D.LABEL, Console.TEXT_MUTED)
    room = r.width - 2 * p - min(lw, r.width * 0.6) - 28
    D.text_right(D.fit(value, D.LABEL, room, semi=True), r.x + r.width - p, y + 20, D.LABEL, value_color, semi=True)
    return y + ROW

  def _button(self, r: rl.Rectangle, label: str, fn: Callable[[], None], primary: bool = False, right_of: float = 0.0):
    p = D.CARD_PAD
    w = D.text_w(label, D.LABEL, semi=True) + 64
    x = r.x + p if not right_of else right_of
    b = rl.Rectangle(x, r.y + r.height - p - 72, w, 72)
    if x + w > r.x + r.width - p + 1:  # no room left on this card's button row
      return rl.Rectangle(x - 16, b.y, 0, 72)
    D.button(b, label, primary=primary, size=D.LABEL)
    self._hits.append((b, fn))
    return b

  def _wifi_card(self, r: rl.Rectangle, ds):
    on_wifi = ds is not None and str(ds.networkType) == "wifi"
    ssid = self._connected_ssid()
    homes = home_wifi(self._params)
    if on_wifi:
      level = STRENGTH.get(str(ds.networkStrength), 0)
      status = ssid or tr("Connected")
      color = Console.WARNING if level <= 1 else Console.SUCCESS
    else:
      level, status, color = 0, tr("Not connected"), Console.TEXT_GHOST
    y = self._head(r, tr("Wi-Fi"), level, status, color)
    if on_wifi and ssid and ssid in homes:
      K.tag(r.x + r.width - D.CARD_PAD - D.text_w(tr("Home"), 26, semi=True) - 28, r.y + D.CARD_PAD + 2, tr("Home"), accent=True)
    fav = _text(_param(self._params, "WifiFavoriteSSID", ""))
    y = self._row(r, y, tr("Preferred network"), fav or tr("None"), button=True)
    self._row(r, y, tr("Home networks"), ", ".join(homes) if homes else tr("None yet"), button=True)
    b = self._button(r, tr("Wi-Fi settings"), lambda: self.on_open_wifi and self.on_open_wifi())
    if on_wifi and ssid:
      is_home = ssid in homes
      self._button(r, tr("Not home") if is_home else tr("This is home"), lambda s=ssid: self._toggle_home(s),
                   primary=not is_home, right_of=b.x + b.width + 16)

  def _lte_card(self, r: rl.Rectangle, ds):
    on_cell = ds is not None and str(ds.networkType).startswith("cell")
    info = None
    try:
      info = ds.networkInfo if ds is not None else None
    except Exception:
      info = None
    operator = _text(getattr(info, "operator", "")) if info is not None else ""
    tech = _text(getattr(info, "technology", "")) if info is not None else ""
    if on_cell:
      level = STRENGTH.get(str(ds.networkStrength), 0)
      status = " · ".join(x for x in (operator, tech) if x) or tr("Connected")
      color = Console.WARNING if level <= 1 else Console.SUCCESS
    else:
      level = 0
      status = tr("Standby, Wi-Fi is in use") if ds is not None and str(ds.networkType) == "wifi" else tr("No signal")
      color = Console.TEXT_GHOST
    y = self._head(r, tr("LTE"), level, status, color)
    y = self._row(r, y, *self.data_used(), button=True)
    cell = bridge.get("usage", "cell")
    if isinstance(cell, dict):
      y = self._row(r, y, tr("Today"), fmt_data(int(cell.get("todayBytes") or 0)), button=True)
    else:
      y = self._row(r, y, tr("Since start-up"), fmt_data(usage().boot_bytes), button=True)
    self._button(r, tr("Cellular settings"), lambda: self.on_open_cellular and self.on_open_cellular())

  def data_used(self) -> tuple[str, str, rl.Color | None]:
    """'Data this month' row: the bridge's count (with its limit) when it runs, else the UI's own."""
    month = bridge.get("usage", "cell", "monthBytes")
    month = int(month) if isinstance(month, (int, float)) else usage().month_bytes
    text, color = fmt_data(month), None
    limit = bridge.get("usage", "limitBytes", default=0)
    if not limit and has_param(self._params, "BPCellLimitMB"):
      try:
        limit = int(_text(_param(self._params, "BPCellLimitMB", "0")) or 0) * 1_000_000
      except ValueError:
        limit = 0
    if limit:
      text += " " + tr("of") + " " + fmt_data(int(limit))
      if bridge.get("usage", "overLimit", default=False) or month >= limit:
        color = Console.WARNING
    return tr("Data this month"), text, color

  @staticmethod
  def _road_trip_text() -> str:
    rt = bridge.get("roadTrip")
    if not isinstance(rt, dict):
      return tr("On, waiting for the uploader")
    state = str(rt.get("state") or "idle")
    if state == "uploading":
      q = rt.get("queue") or {}
      return tr("Uploading") + f", {int(q.get('files') or 0)} " + tr("files left")
    if state == "paused":
      reason = {"no_network": tr("no signal"), "no_server": tr("no server"), "over_limit": tr("data limit reached"),
                "server_error": tr("server error"), "parked": tr("parked")}.get(str(rt.get("pausedReason")), "")
      return tr("Paused") + (f", {reason}" if reason else "")
    return tr("Up to date") if state == "idle" else tr("Waiting")

  def server_state(self) -> tuple[str, rl.Color, str]:
    srv = bridge.get("server")
    url = _text(_param(self._params, "BPServerUrl", "")) if has_param(self._params, "BPServerUrl") else ""
    if isinstance(srv, dict) and srv.get("configured"):
      host = _text(srv.get("url") or url).split("://")[-1].split("/")[0]
      if srv.get("reachable"):
        return tr("Server connected"), Console.SUCCESS, host
      return tr("Server not reachable"), Console.WARNING, host
    if url:
      return tr("Server set, uploader off"), Console.TEXT_GHOST, url.split("://")[-1].split("/")[0]
    return tr("Server not set up yet"), Console.TEXT_GHOST, ""

  def _server_card(self, r: rl.Rectangle, ds):
    from bluepilot.ui.lib import upload_status as us
    status, color, host = self.server_state()
    y = self._head(r, tr("Uploads and sync"), None, status, color)
    D.text(D.fit(host or tr("Set it up in Data export"), D.LABEL, r.width - 2 * D.CARD_PAD - 36),
           r.x + D.CARD_PAD + 36, y - 30, D.LABEL, Console.TEXT_MUTED)
    y += 24
    idx = indexer().index
    for svc in (us.comma_connect(self._params, idx), us.citadel_live(self._params), us.citadel_sync(self._params, idx)):
      y = self._row(r, y, svc.name, svc.state, svc.color)
    self._hits.append((r, lambda: self.on_open_uploads and self.on_open_uploads()))

  def _home_card(self, r: rl.Rectangle):
    h = home_location()
    at = h.at_home()
    if h.home is None:
      status, color = tr("Home isn't set"), Console.TEXT_GHOST
    elif at is None:
      status, color = tr("Location unknown"), Console.TEXT_GHOST
    elif at:
      status, color = tr("At home"), Console.SUCCESS
    else:
      status, color = tr("Away from home"), Console.ACCENT
    y = self._head(r, tr("Home location"), None, status, color)
    if h.last is not None:
      when = h.last.get("t", "")
      y = self._row(r, y, tr("Last GPS position"), tr("Now") if h.fresh else (_short_time(when) if when else tr("Saved")),
                    button=True)
    else:
      y = self._row(r, y, tr("Last GPS position"), tr("None yet"))
    for ln in D.wrap(tr("GPS only runs while the truck is on."), D.LABEL,
                     r.width - 2 * D.CARD_PAD, 2):
      if y + 40 < r.y + r.height - D.CARD_PAD - 96:
        D.text(ln, r.x + D.CARD_PAD, y + 16, D.LABEL, Console.TEXT_MUTED)
        y += 40
    b = self._button(r, tr("Automations"), lambda: self.on_open_automations and self.on_open_automations())
    if h.last is not None:
      b = self._button(r, tr("Set home here"), self._set_home, primary=h.home is None, right_of=b.x + b.width + 16)
      if h.home is not None:
        self._button(r, tr("Clear"), h.clear_home, right_of=b.x + b.width + 16)

  # -- input --------------------------------------------------------------------------------

  def _set_home(self):
    home_location().set_home_here()

  def _toggle_home(self, ssid: str):
    homes = home_wifi(self._params)
    homes = [s for s in homes if s != ssid] if ssid in homes else homes + [ssid]
    try:
      self._params.put("BPHomeWifi", json.dumps(homes))
    except Exception:
      pass

  def _handle_mouse_release(self, pos) -> bool:
    for r, fn in self._hits:
      if D.hit(r, pos):
        fn()
        return True
    return False
