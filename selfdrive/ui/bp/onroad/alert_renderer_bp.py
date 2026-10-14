from typing import Optional
import pyray as rl
from cereal import log

from openpilot.selfdrive.ui.onroad.alert_renderer import AlertRenderer, ALERT_PADDING, Alert
from openpilot.selfdrive.ui.bp.onroad.console_cues import cue_icon, notice, notice_size
from bluepilot.ui.console import draw as D
from bluepilot.ui.lib.theme import Console, Onroad, roundness, with_alpha
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.selfdrive.ui.bp.lib.ui_debug_logger import bp_ui_log

AlertSize = log.SelfdriveState.AlertSize
AlertStatus = log.SelfdriveState.AlertStatus

# Custom: Console alerts. openpilot decides when an alert shows, how long, its size and its
# sound; this only decides how it looks.
#   informational (normal, not full)  notification card at the top centre (console_cues.notice)
#   prompt / critical, small and mid  openpilot's rect at the bottom, as a Console card: a
#                                     square icon tile in the status colour, left-aligned title
#                                     and subtitle, a thick status-coloured frame
#   full screen                       a flat status ground with a large icon above the stock text
PILL_TOP_Y = 24            # level with the speed card
PILL_SIDE_MARGIN = 560     # fallback when the road view has not set the band

ALERT_RADIUS = 24          # kit PANEL_R
FRAME_W = 6                # status frame on prompt cards
TILE = 132                 # icon tile on bottom cards
TILE_R = 24
TITLE_MID = 72
SUB_MID = 50
TITLE_SMALL = 64
FULL_ICON = 128

# Bottom cards stay deep in both modes (white text over the camera reads the same by day)
CARD_GROUND = {
  AlertStatus.normal: Onroad.ALERT_NORMAL,
  AlertStatus.userPrompt: Onroad.ALERT_NORMAL,
  AlertStatus.critical: Onroad.ALERT_CRITICAL,
}
FULL_GROUND = {
  AlertStatus.normal: Onroad.ALERT_NORMAL,
  AlertStatus.userPrompt: Onroad.ALERT_PROMPT,
  AlertStatus.critical: Onroad.ALERT_CRITICAL,
}
STATUS_COLOR = {
  AlertStatus.normal: Console.ACCENT,
  AlertStatus.userPrompt: Console.WARNING,
  AlertStatus.critical: Console.DANGER_FILL,
}
SUB_TEXT = with_alpha(Onroad.ALERT_TEXT, 0xC8)


class AlertRendererBP(AlertRenderer):
  """BluePilot AlertRenderer. Custom: Console notification card and alert cards."""

  def __init__(self):
    super().__init__()
    self._font_semi = gui_app.font(FontWeight.SEMI_BOLD)
    self._font_body = gui_app.font(FontWeight.NORMAL)
    # Set by the road view each frame: the free band between the signal tiles. The
    # notification card centres in it.
    self.notify_band: tuple[float, float] | None = None

  def _render(self, rect: rl.Rectangle):
    from openpilot.selfdrive.ui.ui_state import ui_state
    alert = self.get_alert(ui_state.sm)
    bp_ui_log.state("AlertRenderer", "has_alert", alert is not None)
    if alert:
      bp_ui_log.state("AlertRenderer", "alert_size", alert.size)

    # SunnyPilot on-road screen-off timer (OnroadScreenOffBrightness / OnroadScreenOffTimer) is
    # driven from here every frame — must match stock AlertRenderer._render (MICI does this in
    # mici/onroad/alert_renderer.py). Calling super()._render for non-informational alerts would
    # duplicate this and double-decrement the timer.
    if gui_app.sunnypilot_ui():
      ui_state.onroad_brightness_handle_alerts(ui_state.started, alert)

    if not alert:
      return

    if alert.status == AlertStatus.normal and alert.size != AlertSize.full:
      r = self._get_pill_rect(rect, alert)
      if r is not None:
        notice(r, alert.text1 or "", alert.text2 or "", Console.ACCENT, self._icon_for(alert))
      return

    alert_rect = self._get_alert_rect(rect, alert.size)
    if alert.size == AlertSize.full:
      self._draw_full(alert_rect, alert)
    else:
      self._draw_card(alert_rect, alert)

  # -- notification ------------------------------------------------------------------------

  @staticmethod
  def _icon_for(alert) -> str:
    t = f"{alert.text1} {alert.text2}".lower()
    if "lane change" in t or "changing lanes" in t:
      return "lane_right" if "right" in t else "lane_left"
    if "blindspot" in t or "blind spot" in t:
      return "car"
    return "bell"

  def _get_pill_rect(self, rect: rl.Rectangle, alert) -> Optional[rl.Rectangle]:
    """Notification card rect: centred in the band between the signal tiles."""
    line1, line2 = alert.text1 or "", alert.text2 or ""
    if not line1 and not line2:
      return None
    band_l, band_r = self.notify_band if self.notify_band else (rect.x + PILL_SIDE_MARGIN, rect.x + rect.width - PILL_SIDE_MARGIN)
    if band_r - band_l < 100:
      return None
    w, h = notice_size(line1, line2, band_r - band_l)
    return rl.Rectangle(band_l + (band_r - band_l - w) / 2, rect.y + PILL_TOP_Y, w, h)

  # -- prompt and critical cards (small, mid) ----------------------------------------------

  def _draw_card(self, rect: rl.Rectangle, alert: Alert) -> None:
    status = alert.status
    accent = STATUS_COLOR.get(status, Console.ACCENT)
    r = roundness(rect, ALERT_RADIUS)
    rl.draw_rectangle_rounded(rect, r, 10, CARD_GROUND.get(status, Onroad.ALERT_NORMAL))
    if status == AlertStatus.userPrompt:
      rl.draw_rectangle_rounded_lines_ex(rect, r, 10, FRAME_W, accent)
    elif status == AlertStatus.normal:
      rl.draw_rectangle_rounded_lines_ex(rect, r, 10, 2, Console.BORDER_DEFAULT)

    # Icon tile: status colour with a dark mark; white with a red mark on a critical card
    tile = min(TILE, rect.height - 2 * 32)
    t = rl.Rectangle(rect.x + 40, rect.y + (rect.height - tile) / 2, tile, tile)
    critical = status == AlertStatus.critical
    rl.draw_rectangle_rounded(t, roundness(t, TILE_R), 10, Onroad.ALERT_TEXT if critical else accent)
    icon = "warning" if status != AlertStatus.normal else "bell"
    isz = tile * 0.58
    cue_icon(icon, t.x + (tile - isz) / 2, t.y + (tile - isz) / 2 - 2, isz, Console.DANGER_FILL if critical else Console.FRAME_INK)

    tx = t.x + tile + 40
    max_w = rect.x + rect.width - ALERT_PADDING - tx
    if alert.size == AlertSize.small or not alert.text2:
      size = TITLE_SMALL if alert.size == AlertSize.small else TITLE_MID
      text = D.fit(alert.text1, size, max_w, semi=True)
      rl.draw_text_ex(self._font_semi, text, rl.Vector2(tx, rect.y + (rect.height - size) / 2 - 2), size, 0, Onroad.ALERT_TEXT)
    else:
      y = rect.y + (rect.height - TITLE_MID - 14 - SUB_MID) / 2 - 2
      rl.draw_text_ex(self._font_semi, D.fit(alert.text1, TITLE_MID, max_w, semi=True), rl.Vector2(tx, y), TITLE_MID, 0,
                      Onroad.ALERT_TEXT)
      rl.draw_text_ex(self._font_body, D.fit(alert.text2, SUB_MID, max_w), rl.Vector2(tx, y + TITLE_MID + 14), SUB_MID, 0, SUB_TEXT)

  # -- full screen ---------------------------------------------------------------------------

  def _draw_full(self, rect: rl.Rectangle, alert: Alert) -> None:
    status = alert.status
    rl.draw_rectangle_rec(rect, FULL_GROUND.get(status, Onroad.ALERT_NORMAL))
    if status != AlertStatus.normal:
      cue_icon("warning", rect.x + (rect.width - FULL_ICON) / 2, rect.y + 56, FULL_ICON, Onroad.ALERT_TEXT)
    # stock text layout untouched; the icon sits in the space above the title
    text_rect = rl.Rectangle(rect.x + ALERT_PADDING, rect.y + ALERT_PADDING, rect.width - 2 * ALERT_PADDING, rect.height - 2 * ALERT_PADDING)
    self._draw_text(text_rect, alert)

  # kept for callers of the base API
  def _draw_background(self, rect: rl.Rectangle, alert: Alert) -> None:
    rl.draw_rectangle_rec(rect, FULL_GROUND.get(alert.status, Onroad.ALERT_NORMAL))

