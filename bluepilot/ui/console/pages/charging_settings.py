"""
Console Charging settings page (Energy > Charging settings).

  Charging screen   show it while the truck charges; how long the screen stays on with the truck off
  The comma         what it does while parked and charging; the settings themselves live once, on
                    System > Vehicle (Charging and 12 V tabs), so this card summarises and links there

Same params as the old BluePilot rows: BPChargingScreen, BPChargeSleepMin.
"""

from __future__ import annotations

from collections.abc import Callable

import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.console.pages.cards import GAP, CardPage, as_int
from bluepilot.ui.lib.theme import Console

SLEEP_STEPS = [10, 30, 60, 0]           # BPChargeSleepMin; 0 = never
SLEEP_LABELS = ["10 min", "30 min", "1 h", "Never"]
CARD_H = 600                            # both cards sized to their content, not the whole page


def _param(params: Params, key: str, default):
  try:
    v = params.get(key, return_default=True)
  except Exception:
    return default
  return default if v is None else v


def has_param(params: Params, key: str) -> bool:
  try:
    params.get(key)
    return True
  except Exception:
    return False


class ChargingSettingsPage(CardPage):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self.on_open_power: Callable[[], None] | None = None

  def _put(self, key, value):
    try:
      if isinstance(value, bool):
        self._params.put_bool(key, value)
      else:
        self._params.put(key, value)
    except Exception:
      pass

  def set_screen(self, on: bool):
    self._put("BPChargingScreen", on)
    ui_state.charging_screen_enabled = on

  def set_sleep(self, i: int):
    self._put("BPChargeSleepMin", SLEEP_STEPS[i])
    ui_state.charge_sleep_min = SLEEP_STEPS[i]

  def _render(self, rect: rl.Rectangle):
    self._hits = []
    rect = rl.Rectangle(rect.x, rect.y, rect.width, min(rect.height, CARD_H))
    left, right = K.split_cols(rect, [1.0, 1.0])
    left.width -= GAP / 2
    right.x += GAP / 2
    right.width -= GAP / 2
    self._screen_card(left)
    self._comma_card(right)

  def _screen_card(self, r: rl.Rectangle):
    y = self._title(r, tr("Charging screen"), "plug")
    on = bool(_param(self._params, "BPChargingScreen", True))
    y = self._toggle_row(r, y, tr("Show while charging"), tr("Opens when you plug in"), on,
                         lambda: self.set_screen(not on))
    m = as_int(_param(self._params, "BPChargeSleepMin", 30), 30)
    sel = SLEEP_STEPS.index(m) if m in SLEEP_STEPS else 1
    y = self._seg_row(r, y, tr("Screen stays on"), [tr(s) for s in SLEEP_LABELS], sel, self.set_sleep, enabled=on)
    self._note(r, y + 8, tr("With the truck off, the screen turns off after this and wakes when you tap it. " +
                            "With the truck on it stays up until you minimize it."), 3)

  def _comma_card(self, r: rl.Rectangle):
    y = self._title(r, tr("The comma while charging"), "battery")
    p = D.CARD_PAD
    x, right = r.x + p, r.x + r.width - p
    rows = []
    if has_param(self._params, "BPChargeKeepAwake"):
      awake = bool(_param(self._params, "BPChargeKeepAwake", True))
      rows.append((tr("Stays on while charging"), tr("Yes") if awake else tr("No")))
    if has_param(self._params, "BPChargeSleepDelayMin"):
      d = as_int(_param(self._params, "BPChargeSleepDelayMin", 30), 30)
      rows.append((tr("Powers down after the charge"), tr("Default timer") if d == 0 else (f"{d} min" if d < 60 else f"{d / 60:g} h")))
    if has_param(self._params, "BPLvSaver"):
      rows.append((tr("12 V power saver"), tr("On") if bool(_param(self._params, "BPLvSaver", False)) else tr("Off")))
    for label, value in rows:
      if y + 80 > r.y + r.height - p - 120:
        break
      K.hline(x, right, y)
      D.text(D.fit(label, D.BODY, (right - x) * 0.62), x, y + 22, D.BODY, Console.TEXT_SECONDARY)
      D.text_right(value, right, y + 22, D.BODY, semi=True)
      y += 80
    if not rows:
      y = self._note(r, y, tr("These settings come with the Lightning control update."), 2)
    self._button_row(r, max(y, r.y + r.height - p - 104 - 8), tr("Power while parked"), tr("System > Vehicle"), tr("Open"),
                     lambda: self.on_open_power and self.on_open_power())
