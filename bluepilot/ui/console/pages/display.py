"""
Console Display page (Screen > Display): screen brightness while driving, and when settings close by themselves.
Replaces sunnypilot's Display panel (selfdrive/ui/sunnypilot/layouts/settings/display.py), same params and values.

  OnroadScreenOffBrightness   0 auto, 1 auto (dark), 2 screen off, 3..22 a fixed 5..100 %
  OnroadScreenOffTimer        seconds before that applies: 15, 30, then 1..10 min (only for Off and a fixed level)
  InteractivityTimeout        0 = default, else 10..120 s
"""

from __future__ import annotations

from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.console.form import Choice, FormPage, Note, Section, Stepper

AUTO, AUTO_DARK, SCREEN_OFF, FIXED_MIN, FIXED_MAX = 0, 1, 2, 3, 22
FIXED_DEFAULT = 12                                    # 50 %
TIMER_STEPS = [15, 30] + [m * 60 for m in range(1, 11)]
TIMEOUT_MAX, TIMEOUT_STEP = 120, 10


def fmt_s(s: int) -> str:
  return f"{s} s" if s < 60 else f"{s // 60} min"


class DisplayPage(FormPage):
  def set_mode(self, i: int):
    if i < FIXED_MIN:
      self.p.put("OnroadScreenOffBrightness", i)
    elif self.p.int("OnroadScreenOffBrightness") < FIXED_MIN:
      self.p.put("OnroadScreenOffBrightness", FIXED_DEFAULT)

  def step_level(self, d: int):
    v = self.p.int("OnroadScreenOffBrightness")
    self.p.put("OnroadScreenOffBrightness", max(FIXED_MIN, min(FIXED_MAX, v + d)))

  def step_timer(self, d: int):
    v = self.p.int("OnroadScreenOffTimer", 15)
    i = min(range(len(TIMER_STEPS)), key=lambda k: abs(TIMER_STEPS[k] - v))
    self.p.put("OnroadScreenOffTimer", TIMER_STEPS[max(0, min(len(TIMER_STEPS) - 1, i + d))])

  def step_timeout(self, d: int):
    v = self.p.int("InteractivityTimeout")
    self.p.put("InteractivityTimeout", max(0, min(TIMEOUT_MAX, v + d * TIMEOUT_STEP)))

  def sections(self) -> list[Section]:
    out = []
    if self.p.has("OnroadScreenOffBrightness"):
      v = max(0, min(FIXED_MAX, self.p.int("OnroadScreenOffBrightness")))
      mode = min(v, FIXED_MIN)
      rows: list = [Choice(tr("Brightness"), [tr("Auto"), tr("Auto, dim"), tr("Off"), tr("Fixed")], mode, self.set_mode)]
      if mode == FIXED_MIN:
        rows.append(Stepper(tr("Level"), f"{(v - 2) * 5} %", lambda: self.step_level(-1), lambda: self.step_level(1),
                            tr("After the delay")))
      if self.p.has("OnroadScreenOffTimer"):
        timed = mode in (SCREEN_OFF, FIXED_MIN)
        rows.append(Stepper(tr("Turns off after") if mode == SCREEN_OFF else tr("Delay"),
                            fmt_s(self.p.int("OnroadScreenOffTimer", 15)),
                            lambda: self.step_timer(-1), lambda: self.step_timer(1),
                            tr("Full brightness until then") if timed else tr("Only for Off and Fixed"), enabled=timed))
      notes = {
        AUTO: tr("Follows the light outside, like when parked."),
        AUTO_DARK: tr("Follows the light outside, but goes dimmer at night. Tap to brighten."),
        SCREEN_OFF: tr("The screen goes dark after the delay. Alerts and a tap bring it back."),
        FIXED_MIN: tr("Stays at this level after the delay. Alerts and a tap bring it back."),
      }
      rows.append(Note(notes[mode]))
      out.append(Section(tr("While driving"), "sun", rows))
    if self.p.has("InteractivityTimeout"):
      t = self.p.int("InteractivityTimeout")
      out.append(Section(tr("Settings screen"), "clock", [
        Stepper(tr("Closes after"), tr("Default") if t <= 0 else fmt_s(t),
                lambda: self.step_timeout(-1), lambda: self.step_timeout(1), tr("With no taps")),
      ]))
    return out
