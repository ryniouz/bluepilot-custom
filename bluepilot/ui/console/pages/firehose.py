"""
Console Firehose Mode page (Connect > Firehose), built from the Console form components.

Firehose Mode has no switch: the comma uploads extra training data to comma whenever it is on an unmetered
network. This page says what it is, when it runs, whether it runs now, and how many of this truck's segments
comma has taken for training. The count comes from comma's API through the stock Firehose panel
(FirehoseLayoutBase: refreshed every 30 s while parked and awake, cached in ApiCache_FirehoseStats), which this
page reads instead of starting a second poller.
"""

from __future__ import annotations

import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.console import draw as D
from bluepilot.ui.console.form import Custom, FormPage, Info, Note, Section
from bluepilot.ui.lib.theme import Console
from bluepilot.ui.lib.upload_status import comma_wifi_only

STATS_KEY = "ApiCache_FirehoseStats"


def firehose_state(network_type: str, metered: bool) -> tuple[bool, str]:
  """(active, why): stock rule, active on any connection that isn't metered."""
  if network_type in ("none", ""):
    return False, "no_network"
  if metered:
    return False, "metered"
  return True, ""


class FirehosePage(FormPage):
  def __init__(self, stats_source=None):
    super().__init__()
    self._src = stats_source   # the stock Firehose panel, which polls comma's API

  def segment_count(self) -> int:
    n = getattr(self._src, "_segment_count", None)
    if isinstance(n, int):
      return n
    try:
      stats = Params().get(STATS_KEY)
      return int((stats or {}).get("firehose", 0))
    except Exception:
      return 0

  @staticmethod
  def _network() -> tuple[str, bool]:
    try:
      ds = ui_state.sm["deviceState"]
      return str(ds.networkType), bool(ds.networkMetered)
    except Exception:
      return "none", False

  def sections(self) -> list[Section]:
    nt, metered = self._network()
    active, why = firehose_state(nt, metered)
    n = self.segment_count()
    if active:
      head, sub, tone = tr("Active"), tr("Uploading training data while connected"), Console.SUCCESS
    elif why == "metered":
      head, sub, tone = tr("Waiting for Wi-Fi"), tr("Metered connection, nothing is sent"), Console.WARNING
    else:
      head, sub, tone = tr("Not connected"), tr("Starts on the next unmetered Wi-Fi"), Console.TEXT_GHOST

    def hero(r: rl.Rectangle):
      D.dot(r.x + 16, r.y + 34, 14, tone)
      D.text(D.fit(head, D.H2 + 6, r.width - 48, semi=True), r.x + 48, r.y + 12, D.H2 + 6, semi=True)
      D.text(D.fit(sub, D.LABEL, r.width - 48), r.x + 48, r.y + 66, D.LABEL, Console.TEXT_MUTED)
      return None

    if nt in ("none", ""):
      conn = tr("Not connected")
    elif nt.startswith("cell"):
      conn = tr("LTE") + ", " + (tr("metered") if metered else tr("unmetered"))
    else:
      conn = tr("Wi-Fi") + ", " + (tr("metered") if metered else tr("unmetered"))
    status = Section(tr("Status"), "flame", [
      Custom(116, hero),
      Info(tr("Connection"), conn),
      Info(tr("Segments in training"), f"{n:,}" if n > 0 else tr("None yet")),
      Info(tr("comma connect"), tr("Wi-Fi only") if comma_wifi_only(self.p._params) else tr("Wi-Fi and LTE")),
    ])
    what = Section(tr("What it does"), "cloud", [
      Note(tr("comma's driving models learn from real drives. Firehose Mode lets comma pull more of your logs and " +
              "camera video than comma connect normally sends, to train future models.")),
      Note(tr("Nothing changes while you drive, and there's nothing to turn on.")),
    ])
    when = Section(tr("When it uploads"), "wifi", [
      Note(tr("Only on a network that isn't metered, such as home Wi-Fi. It never uses LTE data.")),
      Note(tr("Best results: park on home Wi-Fi with the comma powered for a few hours, about once a week.")),
    ])
    faq = Section(tr("Good to know"), "list", [
      Note(tr("Drive as you normally would. Where and how you drive doesn't matter.")),
      Note(tr("comma takes a selection of your segments, not every drive.")),
      Note(tr("comma trains only on drives from openpilot and a few approved forks, so drives from this build may " +
              "not be used even when they upload.")),
    ])
    return [status, what, when, faq]
