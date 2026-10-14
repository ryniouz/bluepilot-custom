"""
Console About page (System > About): the software's name, Citadel Auto OS, with its logo and version.
The boot screens show the logo only; the name lives here.

  Left    logo, "Citadel Auto OS", version
  Right   software details (branch, commit, date), this device, and what it is built on (credits kept:
          BluePilot, sunnypilot and openpilot are MIT-licensed and their notices stay with the code)
"""

from __future__ import annotations

import os

import pyray as rl

from openpilot.common.params import Params
from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.console.boot import logo_texture
from bluepilot.ui.console.home import _param
from bluepilot.ui.console.pages.cards import GAP, CardPage
from bluepilot.ui.console.pages.updates import commit_date
from bluepilot.ui.lib.theme import Console

NAME = "Citadel Auto OS"
LOGO_H = 220
ROW = 76


def _bp_version() -> str:
  try:
    with open(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "BPVERSION")) as f:
      return f.read().strip()
  except OSError:
    return ""


class AboutPage(CardPage):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._base = _bp_version()

  def _get(self, key: str) -> str:
    v = _param(self._params, key, "")
    return str(v or "").strip()

  def _render(self, rect: rl.Rectangle):
    self._hits = []
    left, right = K.split_cols(rect, [0.9, 1.1])
    left.width -= GAP / 2
    right.x += GAP / 2
    right.width -= GAP / 2

    D.card(left)
    cx = left.x + left.width / 2
    y = left.y + max(72, (left.height - (LOGO_H + 56 + 76 + 56 + 40)) / 2)  # the block sits in the middle
    tex = logo_texture(LOGO_H)
    if tex is not None:
      rl.draw_texture(tex, int(cx - tex.width / 2), int(y), rl.WHITE)
      y += tex.height + 56
    D.text_center(D.fit(tr(NAME), D.H1, left.width - 2 * D.CARD_PAD, semi=True), cx, y, D.H1, semi=True)
    y += 76
    version = self._get("Version") or self._base
    if version:
      D.text_center(tr("Version") + " " + version, cx, y, D.BODY, Console.TEXT_SECONDARY)
    D.text_center(tr("For the Ford F-150 Lightning"), cx, y + 56, D.LABEL, Console.TEXT_MUTED)

    commit = self._get("GitCommit")[:7]
    rows = [
      (tr("Branch"), self._get("GitBranch")),
      (tr("Commit"), commit + (f"  ·  {commit_date(self._get('GitCommitDate'))}" if commit and self._get("GitCommitDate") else "")),
      (tr("Device"), "comma 3X"),
      (tr("Serial"), self._get("HardwareSerial")),
      (tr("Dongle ID"), self._get("DongleId")),
    ]
    y = self._title(right, tr("Software"), "cpu")
    p = D.CARD_PAD
    x, r_edge = right.x + p, right.x + right.width - p
    for label, value in rows:
      if not value:
        continue
      K.hline(x, r_edge, y)
      D.text(label, x, y + 20, D.LABEL, Console.TEXT_MUTED)
      room = r_edge - x - D.text_w(label, D.LABEL) - 32
      D.text_right(D.fit(value, D.LABEL, room, semi=True), r_edge, y + 20, D.LABEL, semi=True)
      y += ROW
    y += 24
    based = tr("Built on BluePilot") + (f" {self._base}" if self._base else "") + ", sunnypilot " + tr("and") + " openpilot. " + \
      tr("Their licences and notices are kept with the software.")
    self._note(right, y, based, 3)
