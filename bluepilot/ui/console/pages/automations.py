"""
Console Home automations page (Connect > Home).

  Left    where home is: at home or away (and how that was decided), home networks, home position,
          the last thing an automation did
  Right   the rules, each with a toggle (bluepilot/ui/lib/automations.py does the work)
"""

from __future__ import annotations

from collections.abc import Callable

import pyray as rl

from openpilot.common.params import Params
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.widgets import Widget
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.lib.automations import RULES, automations, has_keys, home_ssids
from bluepilot.ui.lib.home_location import home_location
from bluepilot.ui.lib.theme import Console

GAP = 32
ROW = 76
RULE_ROW = 124


class AutomationsPage(Widget):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._hits: list[tuple[rl.Rectangle, Callable[[], None]]] = []
    self.on_open_wifi: Callable[[], None] | None = None

  def _render(self, rect: rl.Rectangle):
    self._hits = []
    left, right = K.split_cols(rect, [1, 1.15])
    left.width -= GAP / 2
    right.x += GAP / 2
    right.width -= GAP / 2
    self._home_card(left)
    self._rules_card(right)

  def _row(self, r: rl.Rectangle, y: float, label: str, value: str, bottom: float) -> float:
    p = D.CARD_PAD
    if y + ROW > bottom + 8:
      return y
    K.hline(r.x + p, r.x + r.width - p, y)
    D.text(label, r.x + p, y + 20, D.LABEL, Console.TEXT_MUTED)
    room = r.width - 2 * p - D.text_w(label, D.LABEL) - 28
    D.text_right(D.fit(value, D.LABEL, room, semi=True), r.x + r.width - p, y + 20, D.LABEL, semi=True)
    return y + ROW

  def _home_card(self, r: rl.Rectangle):
    D.card(r)
    p = D.CARD_PAD
    x = r.x + p
    D.text(tr("Home"), x, r.y + p, D.H2, semi=True)
    a = automations()
    h = home_location()
    homes = home_ssids(self._params)
    if a.at_home is None:
      at = h.at_home()
      status, color = ((tr("At home"), Console.SUCCESS) if at else (tr("Away from home"), Console.ACCENT)) if at is not None \
        else (tr("Home isn't set"), Console.TEXT_GHOST)
    else:
      status, color = (tr("At home"), Console.SUCCESS) if a.at_home else (tr("Away from home"), Console.ACCENT)
    y = r.y + p + 72
    D.dot(x + 10, y + D.BODY / 2 + 2, 10, color)
    D.text(D.fit(status, D.BODY, r.width - 2 * p - 36, semi=True), x + 36, y, D.BODY, semi=True)
    y += 52
    if a.reason:
      D.text(tr("From") + " " + tr(a.reason), x + 36, y, D.LABEL, Console.TEXT_MUTED)
    y += 56
    bottom = r.y + r.height - p - 84
    y = self._row(r, y, tr("Home networks"), ", ".join(homes) if homes else tr("None yet"), bottom)
    y = self._row(r, y, tr("Home position"), tr("Saved") if h.home else tr("Not set"), bottom)
    y = self._row(r, y, tr("Last action"), f"{a.last_action_at}  {tr(a.last_action)}" if a.last_action else tr("Nothing yet"), bottom)
    if y + 3 * 40 < bottom:
      for i, ln in enumerate(D.wrap(tr("Mark a network as home on Connect > Status while connected to it. Set the home position " +
                                       "there too, from where the truck is parked."), D.LABEL, r.width - 2 * p, 3)):
        D.text(ln, x, y + 16 + i * 40, D.LABEL, Console.TEXT_MUTED)
    b = rl.Rectangle(x, r.y + r.height - p - 72, D.text_w(tr("Wi-Fi settings"), D.LABEL, semi=True) + 64, 72)
    D.button(b, tr("Wi-Fi settings"), primary=False, size=D.LABEL)
    self._hits.append((b, lambda: self.on_open_wifi and self.on_open_wifi()))
    if h.last is not None and h.home is None:
      b2 = rl.Rectangle(b.x + b.width + 16, b.y, D.text_w(tr("Set home here"), D.LABEL, semi=True) + 64, 72)
      D.button(b2, tr("Set home here"), primary=True, size=D.LABEL)
      self._hits.append((b2, h.set_home_here))

  def _rules_card(self, r: rl.Rectangle):
    D.card(r)
    p = D.CARD_PAD
    x, right = r.x + p, r.x + r.width - p
    D.text(tr("Automations"), x, r.y + p, D.H2, semi=True)
    y = r.y + p + 76
    ready = has_keys(self._params)
    a = automations()
    for rule in RULES:
      if y + RULE_ROW > r.y + r.height - p + 8:
        break
      K.hline(x, right, y)
      on = ready and a.enabled(rule)
      D.text(D.fit(tr(rule.title), D.BODY, r.width - 2 * p - 140, semi=True), x, y + 18, D.BODY, semi=True)
      for i, ln in enumerate(D.wrap(tr(rule.sub), D.LABEL - 2, r.width - 2 * p - 140, 2)):
        D.text(ln, x, y + 62 + i * 34, D.LABEL - 2, Console.TEXT_MUTED)
      tg = D.toggle(right - 104, y + (RULE_ROW - 60) / 2, on, enabled=ready)
      if ready:
        self._hits.append((tg, lambda rule=rule, on=on: a.set_enabled(rule, not on)))
      y += RULE_ROW + (34 if len(D.wrap(tr(rule.sub), D.LABEL - 2, r.width - 2 * p - 140, 2)) > 1 else 0)

  def _handle_mouse_release(self, pos) -> bool:
    for r, fn in self._hits:
      if D.hit(r, pos):
        fn()
        return True
    return False
