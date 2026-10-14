"""
Console upload settings (Drives > Upload settings, also opened from Connect > Cellular).

  comma connect     Wi-Fi only (BPCommaConnectWifiOnly; without it, stock GsmMetered)
  Citadel uploads   Road Trip Mode (BPRoadTripMode), over LTE (BPRoadTripCellular), low-res video (BPRoadTripVideo),
                    remote access from Citadel (BPRemoteLink, status in services.citadel.link)
  LTE data limit    monthly limit (BPCellLimitMB), what happens at the limit (BPCellLimitAction),
                    the day the month starts (BPCellResetDay)

The Citadel and limit keys belong to the data export bridge (stream C, PR #1); each control shows only once
its key exists, and the bridge applies changes on its next pass.
"""

from __future__ import annotations

from collections.abc import Callable

import pyray as rl

from openpilot.common.params import Params
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.console.home import _param, has_param
from bluepilot.ui.lib import bridge_status as bridge
from bluepilot.ui.lib.upload_status import citadel_configured
from bluepilot.ui.lib.theme import Console

GAP = 32
SET_ROW = 104
LIMITS_MB = [0, 2000, 5000, 10000, 20000]
LIMIT_LABELS = ["Off", "2", "5", "10", "20"]


def _int(v, default: int) -> int:
  try:
    if isinstance(v, bytes):
      v = v.decode(errors="ignore")
    return int(v)
  except (TypeError, ValueError):
    return default


class UploadSettingsPage(Widget):
  def __init__(self, wifi_manager=None):
    super().__init__()
    self._params = Params()
    self._wifi = wifi_manager
    self._hits: list[tuple[rl.Rectangle, Callable[[], None]]] = []

  def _render(self, rect: rl.Rectangle):
    self._hits = []
    left, right = K.split_cols(rect, [1.0, 1.0])
    left.width -= GAP / 2
    right.x += GAP / 2
    right.width -= GAP / 2
    top, bottom = K.split_rows(left, [0.45, 1.0])
    top.height -= GAP / 2
    bottom.y += GAP / 2
    bottom.height -= GAP / 2
    self._comma_card(top)
    self._citadel_card(bottom)
    self._limit_card(right)

  # -- pieces -------------------------------------------------------------------------------

  def _title(self, r: rl.Rectangle, title: str, icon: str) -> float:
    D.card(r)
    p = D.CARD_PAD
    D.icon(icon, r.x + p, r.y + p - 2, 44, Console.TEXT_SECONDARY)
    D.text(title, r.x + p + 64, r.y + p, D.H2, semi=True)
    return r.y + p + 76

  def _toggle_row(self, r: rl.Rectangle, y: float, title: str, sub: str, on: bool, fn: Callable[[], None] | None,
                  enabled: bool = True) -> float:
    p = D.CARD_PAD
    x, right = r.x + p, r.x + r.width - p
    if y + SET_ROW > r.y + r.height - p + 8:
      return y
    K.hline(x, right, y)
    col = Console.TEXT_PRIMARY if enabled else Console.TEXT_GHOST
    D.text(D.fit(title, D.BODY, right - x - 140, semi=True), x, y + 16, D.BODY, col, semi=True)
    D.text(D.fit(sub, D.LABEL, right - x - 140), x, y + 62, D.LABEL, Console.TEXT_MUTED)
    D.toggle(right - 104, y + (SET_ROW - 60) / 2, on, enabled=enabled)
    if enabled and fn is not None:
      self._hits.append((rl.Rectangle(x, y, right - x, SET_ROW), fn))
    return y + SET_ROW

  def _seg_row(self, r: rl.Rectangle, y: float, title: str, labels: list[str], sel: int,
               fn: Callable[[int], None], enabled: bool = True) -> float:
    p = D.CARD_PAD
    x, right = r.x + p, r.x + r.width - p
    if y + 56 + 72 > r.y + r.height - p + 8:
      return y
    K.hline(x, right, y)
    D.text(title, x, y + 16, D.BODY, Console.TEXT_PRIMARY if enabled else Console.TEXT_GHOST, semi=True)
    seg = rl.Rectangle(x, y + 66, right - x, 64)
    rects = D.segmented(seg, labels, sel if enabled else -1)
    if enabled:
      for i, sr in enumerate(rects):
        self._hits.append((sr, lambda i=i: fn(i)))
    return y + 66 + 64 + 24

  def _note(self, r: rl.Rectangle, y: float, text: str, lines: int = 3) -> float:
    p = D.CARD_PAD
    for ln in D.wrap(text, D.LABEL, r.width - 2 * p, lines):
      if y + 40 > r.y + r.height - p:
        break
      D.text(ln, r.x + p, y + 12, D.LABEL, Console.TEXT_MUTED)
      y += 40
    return y

  # -- cards --------------------------------------------------------------------------------

  def _comma_card(self, r: rl.Rectangle):
    y = self._title(r, tr("comma connect"), "cloud")
    if has_param(self._params, "BPCommaConnectWifiOnly"):
      wo = bool(_param(self._params, "BPCommaConnectWifiOnly", True))
      y = self._toggle_row(r, y, tr("Wi-Fi only"), tr("Off: logs and small video also go over LTE"), wo,
                           lambda: self._params.put_bool("BPCommaConnectWifiOnly", not wo))
    else:
      metered = bool(_param(self._params, "GsmMetered", True))
      y = self._toggle_row(r, y, tr("Also upload over LTE"), tr("Small files go over LTE either way"), not metered,
                           self._toggle_metered)
    self._note(r, y, tr("comma connect keeps working as before. Full video goes only when you ask for it in comma connect."), 2)

  def _citadel_card(self, r: rl.Rectangle):
    y = self._title(r, tr("Citadel uploads"), "route")
    if not has_param(self._params, "BPRoadTripMode"):
      self._note(r, y + 8, tr("Live uploads to Citadel come with the data export update. Home sync over Wi-Fi works without it."))
      return
    configured = citadel_configured(self._params)
    on = bool(_param(self._params, "BPRoadTripMode", False))
    y = self._toggle_row(r, y, tr("Road Trip Mode"), tr("Upload while you drive") if configured else tr("Needs your Citadel server"),
                         on and configured, lambda: self._params.put_bool("BPRoadTripMode", not on), enabled=configured)
    if has_param(self._params, "BPRoadTripCellular"):
      cell = bool(_param(self._params, "BPRoadTripCellular", True))
      y = self._toggle_row(r, y, tr("Over LTE"), tr("Off: waits for Wi-Fi"), cell,
                           lambda: self._params.put_bool("BPRoadTripCellular", not cell), enabled=on and configured)
    if has_param(self._params, "BPRoadTripVideo"):
      video = _int(_param(self._params, "BPRoadTripVideo", 1), 1)
      y = self._toggle_row(r, y, tr("Low-res video"), tr("Off: logs only"), bool(video) and on and configured,
                           lambda: self._params.put("BPRoadTripVideo", 0 if video else 1), enabled=on and configured)
    if has_param(self._params, "BPRemoteLink"):
      link = bool(_param(self._params, "BPRemoteLink", True))
      self._toggle_row(r, y, tr("Remote access from Citadel"), self._link_text(link), link and configured,
                       lambda: self._params.put_bool("BPRemoteLink", not link), enabled=configured)

  @staticmethod
  def _link_text(on: bool) -> str:
    """services.citadel.link from the bridge: settings and live data from Citadel while away."""
    if not on:
      return tr("Settings and live data while away")
    st = bridge.get("services", "citadel", "link")
    if not isinstance(st, dict):
      return tr("Settings and live data, a few KB a minute")
    state = str(st.get("state") or "")
    reason = {"no_server": tr("no server"), "no_network": tr("no signal"), "over_limit": tr("data limit reached"),
              "server_error": tr("server error"), "disabled": tr("turned off")}.get(str(st.get("pausedReason")), "")
    return {"connected": tr("Connected"), "connecting": tr("Connecting"), "waiting": tr("Waiting for a connection"),
            "paused": tr("Paused") + (f": {reason}" if reason else "")}.get(state, tr("Settings and live data while away"))

  def _limit_card(self, r: rl.Rectangle):
    y = self._title(r, tr("LTE data limit"), "cell")
    if not has_param(self._params, "BPCellLimitMB"):
      self._note(r, y + 8, tr("The monthly LTE limit comes with the data export update. Data used is still counted on Connect > Cellular."))
      return
    cur = _int(_param(self._params, "BPCellLimitMB", 0), 0)
    sel = LIMITS_MB.index(cur) if cur in LIMITS_MB else 0
    y = self._seg_row(r, y, tr("Monthly limit, GB"), [tr(t) for t in LIMIT_LABELS], sel,
                      lambda i: self._params.put("BPCellLimitMB", LIMITS_MB[i]))
    if has_param(self._params, "BPCellLimitAction"):
      act = _int(_param(self._params, "BPCellLimitAction", 0), 0)
      y = self._seg_row(r, y, tr("When it's reached"), [tr("Logs only"), tr("Stop uploads")], 1 if act else 0,
                        lambda i: self._params.put("BPCellLimitAction", int(i)), enabled=cur > 0)
    if has_param(self._params, "BPCellResetDay"):
      y = self._day_row(r, y)
    self._note(r, y, tr("Counts this comma's LTE use, not your whole plan. comma connect's small logs count too."), 2)

  def _day_row(self, r: rl.Rectangle, y: float) -> float:
    p = D.CARD_PAD
    x, right = r.x + p, r.x + r.width - p
    if y + 104 > r.y + r.height - p + 8:
      return y
    K.hline(x, right, y)
    day = max(1, min(31, _int(_param(self._params, "BPCellResetDay", 1), 1)))
    plus = rl.Rectangle(right - 72, y + 20, 72, 64)
    minus = rl.Rectangle(plus.x - 16 - 72 - 96, y + 20, 72, 64)
    D.text(D.fit(tr("Month starts on day"), D.BODY, minus.x - x - 16, semi=True), x, y + 34, D.BODY, semi=True)
    D.button(minus, "-", primary=False)
    D.text_center(str(day), minus.x + 72 + 8 + 48, y + 30, D.H2, semi=True)
    D.button(plus, "+", primary=False)
    self._hits.append((minus, lambda: self._params.put("BPCellResetDay", max(1, day - 1))))
    self._hits.append((plus, lambda: self._params.put("BPCellResetDay", min(31, day + 1))))
    return y + 104

  # -- actions ------------------------------------------------------------------------------

  def _toggle_metered(self):
    metered = not bool(_param(self._params, "GsmMetered", True))
    self._params.put_bool("GsmMetered", metered)
    if self._wifi is not None:
      try:
        apn = _param(self._params, "GsmApn", "") or ""
        apn = apn.decode(errors="ignore") if isinstance(apn, bytes) else str(apn)
        self._wifi.update_gsm_settings(bool(_param(self._params, "GsmRoaming", False)), apn.strip(), metered)
      except Exception:
        pass

  def _handle_mouse_release(self, pos) -> bool:
    for r, fn in self._hits:
      if D.hit(r, pos):
        fn()
        return True
    return False
