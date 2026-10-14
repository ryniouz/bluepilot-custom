from typing import Optional
import pyray as rl
from cereal import log

from openpilot.selfdrive.ui.onroad.alert_renderer import AlertRenderer, ALERT_PADDING, Alert
from openpilot.selfdrive.ui.bp.onroad.console_cues import cue_icon, notice, notice_size
from bluepilot.ui.console import draw as D
from bluepilot.ui.lib.theme import Console, Onroad, Radius, mix, roundness, with_alpha
from openpilot.system.ui.lib.text_measure import measure_text_cached
from openpilot.system.ui.lib.application import gui_app, FontWeight
from openpilot.selfdrive.ui.bp.lib.ui_debug_logger import bp_ui_log

AlertSize = log.SelfdriveState.AlertSize
AlertStatus = log.SelfdriveState.AlertStatus

# Custom: Console alerts. openpilot decides when an alert shows, how long, its size and its
# sound; this only decides how it looks. Every alert uses the notification card's anatomy:
# a squared status bar, a free-standing icon (no tile, Lucas 22:42), then title over subtitle in sentence case.
#   informational (normal, not full)  notification card at the top centre (console_cues.notice)
#   prompt (yellow), small and mid    translucent Console panel over the road, amber bar + amber icon
#   critical (red), small and mid     translucent red card, white bar + white icon
#   full screen                       deep status ground, large icon, wrapped title + subtitle
PILL_TOP_Y = 24            # level with the speed card
PILL_SIDE_MARGIN = 560     # fallback when the road view has not set the band

ALERT_RADIUS = 24          # kit PANEL_R
BAR_W = 16                 # status bar on the left of a card
ICON = 120                 # free-standing icon on bottom cards
TITLE_MID = 68
SUB_MID = 46
TITLE_SMALL = 62
FULL_ICON = 200
FULL_TITLE = 112
FULL_SUB = 54
CARD_MIN_W = 960           # prompt and critical cards: sized to their words, centred over the dock's place
CARD_SIDE = 40             # never closer to the screen edges than this

STATUS_COLOR = {
  AlertStatus.normal: Console.ACCENT,
  AlertStatus.userPrompt: Console.WARNING,
  AlertStatus.critical: Console.DANGER_FILL,
}
# Full screen: a deep status ground so the bright icon and white text carry the urgency
FULL_GROUND = {
  AlertStatus.normal: Onroad.ALERT_NORMAL,
  AlertStatus.userPrompt: mix(Console.WARNING, Console.FRAME_INK, 0.6),
  AlertStatus.critical: mix(Console.DANGER_FILL, Console.FRAME_INK, 0.3),
}
SUB_TEXT = with_alpha(Onroad.ALERT_TEXT, 0xC8)


_SMALL_WORDS = {"a", "an", "and", "at", "for", "in", "of", "on", "or", "the", "to", "with"}


def sentence(text: str) -> str:
  """openpilot shouts some alerts in capitals or Title Case; the Console speaks in sentence case.
  Acronyms and mixed-case names (ACC, openpilot, BluePilot) are left alone."""
  if not text:
    return text
  text = " ".join(text.split())  # "Reverse\nGear" and stray spacing
  if text.upper() == text and any(c.isalpha() for c in text):
    return text[:1] + text[1:].lower()
  words = text.split(" ")
  alpha = [w for w in words[1:] if w[:1].isalpha()]
  title_case = len(alpha) >= 1 and all(w[0].isupper() or w.lower() in _SMALL_WORDS for w in alpha) and \
    any(w[0].isupper() for w in alpha)
  if not title_case:
    return text
  out = [words[0]]
  for w in words[1:]:
    out.append(w.lower() if (w[:1].isupper() and w[1:].islower()) else w)
  return " ".join(out)


# Icon by what the alert is about, matched over title and subtitle in this order: specific causes
# first, so "TAKE CONTROL IMMEDIATELY / CAN Bus Disconnected" shows a cable and an overheat a
# thermometer; the generic take-control rule is last. The alert map with every alert is in
# /mnt/project-files/comma/console-ui/driving/alerts/ALERTS.md.
ICON_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
  (("calibrat", "remount", "fell off mount"), "calibrate"),
  (("experimental",), "flask"),
  (("bookmark",), "bookmark"),
  (("unknown vehicle", "car unrecognized"), "car"),
  (("dashcam", "branch is not tested", "joystick", "maneuver", "audio feedback"), "bell"),
  (("risk of collision", "brake!", "aeb"), "warning"),
  (("touch steering wheel",), "hands"),
  (("system unresponsive",), "cpu"),
  (("distract", "unresponsive", "no face", "pay attention", "eyes on road"), "eye"),
  (("blindspot", "blind spot"), "car_rear"),
  (("lane change", "changing lanes"), "lane"),
  (("turning left",), "lane_left"),
  (("turning right",), "lane_right"),
  (("can bus", "usb error", "relay", "harness", "security key"), "plug"),
  (("overheat", "fan malfunction"), "thermo"),
  (("low battery",), "battery"),
  (("storage",), "download"),
  (("memory", "process", "lagging", "system unresponsive", "communication", "initializing", "waiting to start"),
   "cpu"),
  (("camera",), "screen"),
  (("locationd", "paramsd", "posenet", "sensor", "radar"), "pulse"),
  (("cruise", "speed", "slow down", "drive above", "below", "standstill", "brake hold"), "gauge"),
  (("gear", "door", "seatbelt", "parking brake", "pedal", "stability control", "release brake"), "car"),
  (("personality",), "sliders"),
  (("lkas", "lane centering", "steer", "wheel", "take control", "hands", "disengage", "lane departure", "actuation",
    "time limit", "mismatch"), "hands"),
)


def alert_icon(alert) -> str:
  text = f"{alert.text1 or ''} {alert.text2 or ''}".lower()
  for keys, icon in ICON_RULES:
    if any(k in text for k in keys):
      if icon == "lane":
        return "lane_right" if "right" in text else "lane_left"
      return icon
  return "alert"


class AlertRendererBP(AlertRenderer):
  """BluePilot AlertRenderer. Custom: Console notification card and alert cards."""

  def __init__(self):
    super().__init__()
    self._font_semi = gui_app.font(FontWeight.SEMI_BOLD)
    self._font_body = gui_app.font(FontWeight.NORMAL)
    # Set by the road view each frame: the free band between the signal tiles. The
    # notification card centres in it.
    self.notify_band: tuple[float, float] | None = None
    self.notify_top: float | None = None
    self.guest = False

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
      ui_state.onroad_brightness_handle_alerts(ui_state, alert)

    if not alert:
      return

    # Custom: on a Guest Mode drive openpilot is passive by design; its engage prompts and
    # "unavailable" alerts are expected noise, so only critical alerts still show
    if self.guest and alert.status != AlertStatus.critical:
      return

    if alert.status == AlertStatus.normal and alert.size != AlertSize.full:
      r = self._get_pill_rect(rect, alert)
      if r is not None:
        notice(r, sentence(alert.text1 or ""), sentence(alert.text2 or ""), Console.ACCENT, alert_icon(alert) if alert_icon(alert) != "alert" else "bell")
      return

    alert_rect = self._get_alert_rect(rect, alert.size)
    if alert.size == AlertSize.full:
      self._draw_full(alert_rect, alert)
    else:
      self._draw_card(self._fit_card(rect, alert_rect, alert), alert)

  def _fit_card(self, screen: rl.Rectangle, r: rl.Rectangle, alert: Alert) -> rl.Rectangle:
    """Custom: a card as wide as its words (at least CARD_MIN_W), centred, instead of edge to edge, so it reads
    as one notification above the road rather than a band across it."""
    icon = min(ICON, r.height - 2 * 24)
    lead = 32 + BAR_W + 32 + icon + 32
    title, sub = sentence(alert.text1), sentence(alert.text2)
    small = alert.size == AlertSize.small or not sub
    words = measure_text_cached(self._font_semi, title, TITLE_SMALL if alert.size == AlertSize.small else TITLE_MID).x
    if not small:
      words = max(words, measure_text_cached(self._font_body, sub, SUB_MID).x)
    w = max(CARD_MIN_W, min(screen.width - 2 * CARD_SIDE, lead + words + ALERT_PADDING))
    return rl.Rectangle(screen.x + (screen.width - w) / 2, r.y, w, r.height)

  # -- notification ------------------------------------------------------------------------

  def _get_pill_rect(self, rect: rl.Rectangle, alert) -> Optional[rl.Rectangle]:
    """Notification card rect: centred in the band between the signal tiles."""
    line1, line2 = sentence(alert.text1 or ""), sentence(alert.text2 or "")
    if not line1 and not line2:
      return None
    band_l, band_r = self.notify_band if self.notify_band else (rect.x + PILL_SIDE_MARGIN, rect.x + rect.width - PILL_SIDE_MARGIN)
    if band_r - band_l < 100:
      return None
    w, h = notice_size(line1, line2, band_r - band_l)
    top = self.notify_top if self.notify_top is not None else rect.y + PILL_TOP_Y
    return rl.Rectangle(band_l + (band_r - band_l - w) / 2, top, w, h)

  # -- prompt and critical cards (small, mid) ----------------------------------------------

  def _draw_card(self, rect: rl.Rectangle, alert: Alert) -> None:
    status = alert.status
    critical = status == AlertStatus.critical
    accent = STATUS_COLOR.get(status, Console.ACCENT)
    r = roundness(rect, ALERT_RADIUS)
    if critical:
      ground, ink, sub_ink, edge = with_alpha(Onroad.ALERT_CRITICAL, 0xE0), Onroad.ALERT_TEXT, SUB_TEXT, with_alpha(Onroad.ALERT_TEXT, 0x40)
    else:
      ground, ink, sub_ink, edge = Onroad.PANEL, Console.TEXT_PRIMARY, Console.TEXT_SECONDARY, Console.BORDER_DEFAULT
    rl.draw_rectangle_rounded(rect, r, 10, ground)
    rl.draw_rectangle_rounded_lines_ex(rect, r, 10, 2, edge)

    # Status bar, then the icon on its own in the status colour (white on the red card)
    bar = Onroad.ALERT_TEXT if critical else accent
    b = rl.Rectangle(rect.x + 32, rect.y + 28, BAR_W, rect.height - 56)
    rl.draw_rectangle_rounded(b, roundness(b, Radius.XS), 4, bar)
    isz = min(ICON, rect.height - 2 * 24)
    ix = b.x + BAR_W + 32
    cue_icon(alert_icon(alert), ix, rect.y + (rect.height - isz) / 2, isz, bar)

    tx = ix + isz + 32
    max_w = rect.x + rect.width - ALERT_PADDING - tx
    title, sub = sentence(alert.text1), sentence(alert.text2)
    if alert.size == AlertSize.small or not sub:
      size = TITLE_SMALL if alert.size == AlertSize.small else TITLE_MID
      rl.draw_text_ex(self._font_semi, D.fit(title, size, max_w, semi=True), rl.Vector2(tx, rect.y + (rect.height - size) / 2 - 2),
                      size, 0, ink)
    else:
      y = rect.y + (rect.height - TITLE_MID - 12 - SUB_MID) / 2 - 2
      rl.draw_text_ex(self._font_semi, D.fit(title, TITLE_MID, max_w, semi=True), rl.Vector2(tx, y), TITLE_MID, 0, ink)
      rl.draw_text_ex(self._font_body, D.fit(sub, SUB_MID, max_w), rl.Vector2(tx, y + TITLE_MID + 12), SUB_MID, 0, sub_ink)

  # -- full screen ---------------------------------------------------------------------------

  def _draw_full(self, rect: rl.Rectangle, alert: Alert) -> None:
    status = alert.status
    rl.draw_rectangle_rec(rect, FULL_GROUND.get(status, Onroad.ALERT_NORMAL))
    accent = Onroad.ALERT_TEXT if status == AlertStatus.critical else STATUS_COLOR.get(status, Console.ACCENT)

    max_w = rect.width - 2 * ALERT_PADDING - 120
    title = D.wrap(sentence(alert.text1), FULL_TITLE, max_w, max_lines=2, semi=True)
    sub = D.wrap(sentence(alert.text2), FULL_SUB, max_w, max_lines=2) if alert.text2 else []
    title_lh, sub_lh = FULL_TITLE * 1.1, FULL_SUB * 1.25
    total = FULL_ICON + 48 + len(title) * title_lh + (24 + len(sub) * sub_lh if sub else 0)
    y = rect.y + (rect.height - total) / 2
    cx = rect.x + rect.width / 2

    cue_icon(alert_icon(alert), cx - FULL_ICON / 2, y, FULL_ICON, accent)
    y += FULL_ICON + 48
    for line in title:
      w = measure_text_cached(self._font_semi, line, FULL_TITLE).x
      rl.draw_text_ex(self._font_semi, line, rl.Vector2(cx - w / 2, y), FULL_TITLE, 0, Onroad.ALERT_TEXT)
      y += title_lh
    if sub:
      y += 24
      for line in sub:
        w = measure_text_cached(self._font_body, line, FULL_SUB).x
        rl.draw_text_ex(self._font_body, line, rl.Vector2(cx - w / 2, y), FULL_SUB, 0, SUB_TEXT)
        y += sub_lh

  # kept for callers of the base API
  def _draw_background(self, rect: rl.Rectangle, alert: Alert) -> None:
    rl.draw_rectangle_rec(rect, FULL_GROUND.get(alert.status, Onroad.ALERT_NORMAL))

