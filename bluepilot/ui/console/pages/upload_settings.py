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

import pyray as rl

from openpilot.common.params import Params
from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.console.home import _param, has_param
from bluepilot.ui.console.pages.cards import GAP, SET_ROW, CardPage, as_int
from bluepilot.ui.lib import bridge_status as bridge
from bluepilot.ui.lib.upload_status import citadel_configured

LIMITS_MB = [0, 2000, 5000, 10000, 20000]
LIMIT_LABELS = ["Off", "2", "5", "10", "20"]


class UploadSettingsPage(CardPage):
  def __init__(self, wifi_manager=None):
    super().__init__()
    self._params = Params()
    self._wifi = wifi_manager

  def _render(self, rect: rl.Rectangle):
    self._hits = []
    left, right = K.split_cols(rect, [1.0, 1.0])
    left.width -= GAP / 2
    right.x += GAP / 2
    right.width -= GAP / 2
    # Citadel gets the left column; comma connect (one switch) sits above the data limit on the right
    top_h = 76 + SET_ROW + 2 * D.CARD_PAD + (88 if right.height > 900 else 0)
    top = rl.Rectangle(right.x, right.y, right.width, top_h)
    rest = rl.Rectangle(right.x, right.y + top_h + GAP, right.width, right.height - top_h - GAP)
    self._citadel_card(left)
    self._comma_card(top)
    self._limit_card(rest)

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
      video = as_int(_param(self._params, "BPRoadTripVideo", 1), 1)
      y = self._toggle_row(r, y, tr("Low-res video"), tr("Off: logs only"), bool(video) and on and configured,
                           lambda: self._params.put("BPRoadTripVideo", 0 if video else 1), enabled=on and configured)
    if has_param(self._params, "BPRemoteLink"):
      link = bool(_param(self._params, "BPRemoteLink", True))
      self._toggle_row(r, y, tr("Remote access"), self._link_text(link), link and configured,
                       lambda: self._params.put_bool("BPRemoteLink", not link), enabled=configured)

  @staticmethod
  def _link_text(on: bool) -> str:
    """services.citadel.link from the bridge: settings and live data from Citadel while away."""
    if not on:
      return tr("Citadel can't reach the truck while away")
    st = bridge.get("services", "citadel", "link")
    if not isinstance(st, dict):
      return tr("From Citadel while away")
    state = str(st.get("state") or "")
    reason = {"no_server": tr("no server"), "no_network": tr("no signal"), "over_limit": tr("data limit reached"),
              "server_error": tr("server error"), "disabled": tr("turned off")}.get(str(st.get("pausedReason")), "")
    return {"connected": tr("Connected"), "connecting": tr("Connecting"), "waiting": tr("Waiting for a connection"),
            "paused": tr("Paused") + (f": {reason}" if reason else "")}.get(state, tr("From Citadel while away"))

  def _limit_card(self, r: rl.Rectangle):
    y = self._title(r, tr("LTE data limit"), "cell")
    if not has_param(self._params, "BPCellLimitMB"):
      self._note(r, y + 8, tr("The monthly LTE limit comes with the data export update. Data used is still counted on Connect > Cellular."))
      return
    cur = as_int(_param(self._params, "BPCellLimitMB", 0), 0)
    sel = LIMITS_MB.index(cur) if cur in LIMITS_MB else 0
    y = self._seg_row(r, y, tr("Monthly limit, GB"), [tr(t) for t in LIMIT_LABELS], sel,
                      lambda i: self._params.put("BPCellLimitMB", LIMITS_MB[i]))
    if has_param(self._params, "BPCellLimitAction"):
      act = as_int(_param(self._params, "BPCellLimitAction", 0), 0)
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
    day = max(1, min(31, as_int(_param(self._params, "BPCellResetDay", 1), 1)))
    plus = rl.Rectangle(right - 72, y + 20, 72, 64)
    minus = rl.Rectangle(plus.x - 16 - 72 - 96, y + 20, 72, 64)
    D.text(D.fit(tr("Resets on day"), D.BODY, minus.x - x - 16, semi=True), x, y + 34, D.BODY, semi=True)
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
