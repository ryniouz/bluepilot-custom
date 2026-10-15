"""
Console first-run setup: welcome, safety notice, terms and a short driving guide,
drawn in the Console theme instead of the stock pages and full-screen training images.

Writes the same params as the stock OnboardingWindow and sunnypilot's consent page (HasAcceptedTerms,
HasAcceptedTermsSP, SunnylinkEnabled, CompletedSunnylinkConsentVersion, CompletedTrainingVersion,
RecordFront, DoUninstall), so either flow sees the other's progress. Safety notice and both consents
are kept; only their look changed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import IntEnum

import pyray as rl

from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.application import gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.version import sunnylink_consent_declined, sunnylink_consent_version, terms_version, terms_version_sp, training_version
from openpilot.system.ui.widgets import Widget
from bluepilot.ui.console import draw as D
from bluepilot.ui.console.home import has_param
from bluepilot.ui.lib.theme import Console, roundness

MARGIN = 96
ICON_BOX = 280
BTN_W = 360


@dataclass
class Step:
  icon: str
  title: str
  body: str
  choice: tuple[str, str] | None = None   # (no, yes) labels for a RecordFront question


def guide_steps() -> list[Step]:
  steps = [
    Step("home", tr("Welcome"), tr("Your comma runs Citadel Auto OS, tuned for the F-150 Lightning. A few screens on how it drives with you.")),
    Step("wheel", tr("Turning it on"),
         tr("Press the cruise button on the steering wheel. Steering and speed control start together. Brake or cancel to take over.")),
    Step("eye", tr("Stay in charge"),
         tr("This is driver assistance, not self-driving. Keep your eyes on the road; the driver camera checks you are paying attention.")),
    Step("person", tr("Driver camera"), tr("Keep video from the driver camera? It helps improve driver monitoring. You can change this later."),
         choice=(tr("Don't record"), tr("Record"))),
    Step("calibrate", tr("Calibration"),
         tr("For the first few minutes on straight roads the comma learns how it is mounted. Progress shows under System, Calibration.")),
    Step("flask", tr("Experimental Mode"),
         tr("Lets the driving model handle speed too, including stopping for lights. It is off until you turn it on from Home.")),
  ]
  if has_param(ui_state.params, "BPGuestMode"):
    steps.append(Step("person", tr("Guest Mode"),
                      tr("Lending the truck? Guest Mode leaves Ford's own cruise and lane keeping in charge for the next drive.")))
  steps.append(Step("check", tr("You're set"), tr("Enjoy the drive. Settings, updates and storage are all one tap away from Home.")))
  return steps


def _frame(rect: rl.Rectangle):
  rl.draw_rectangle_rec(rect, Console.BG_PAGE)


def _hero(rect: rl.Rectangle, ic: str, title: str, body: str, top: float):
  """Big tinted icon on the left, title and body to its right."""
  box = rl.Rectangle(rect.x + MARGIN, top, ICON_BOX, ICON_BOX)
  rl.draw_rectangle_rounded(box, roundness(box, 48), 12, Console.ACCENT_TINT)
  D.icon(ic, box.x + (ICON_BOX - 144) / 2, box.y + (ICON_BOX - 144) / 2, 144, Console.ACCENT_TEXT)
  tx = box.x + ICON_BOX + 72
  tw = rect.x + rect.width - MARGIN - tx
  D.text(title, tx, top + 8, 72, semi=True)
  for i, ln in enumerate(D.wrap(body, 40, tw, 5)):
    D.text(ln, tx, top + 120 + i * 58, 40, Console.TEXT_SECONDARY)


def _buttons(rect: rl.Rectangle, left: str | None, right: str, danger: bool = False) -> tuple[rl.Rectangle | None, rl.Rectangle]:
  y = rect.y + rect.height - MARGIN - 96
  rb = rl.Rectangle(rect.x + rect.width - MARGIN - BTN_W, y, BTN_W, 96)
  if danger:
    rl.draw_rectangle_rounded(rb, roundness(rb, 8), 8, Console.DANGER_FILL)
    D.text_center(right, rb.x + rb.width / 2, rb.y + (rb.height - D.BODY) / 2 - 2, D.BODY, Console.ON_ACCENT, semi=True)
  else:
    D.button(rb, right, primary=True, size=D.BODY)
  lb = None
  if left:
    lb = rl.Rectangle(rb.x - 24 - BTN_W, y, BTN_W, 96)
    D.button(lb, left, primary=False, size=D.BODY)
  return lb, rb


class ConsoleTraining(Widget):
  def __init__(self, on_done: Callable[[], None] | None = None):
    super().__init__()
    self._on_done = on_done
    self._steps = guide_steps()
    self._i = 0
    self._hits: list[tuple[rl.Rectangle, Callable[[], None]]] = []

  def restart(self):
    self._steps = guide_steps()
    self._i = 0

  def _render(self, rect: rl.Rectangle):
    self._hits = []
    _frame(rect)
    n = len(self._steps)
    step = self._steps[self._i]
    # Thick squared progress segments across the top
    seg_gap = 12
    seg_w = (rect.width - 2 * MARGIN - seg_gap * (n - 1)) / n
    for i in range(n):
      seg = rl.Rectangle(rect.x + MARGIN + i * (seg_w + seg_gap), rect.y + 72, seg_w, 16)
      rl.draw_rectangle_rounded(seg, roundness(seg, 4), 4, Console.ACCENT_FILL if i <= self._i else Console.BG_TRACK)
    D.text(f"{self._i + 1} / {n}", rect.x + MARGIN, rect.y + 120, D.LABEL, Console.TEXT_MUTED)
    _hero(rect, step.icon, step.title, step.body, rect.y + 240)

    last = self._i == n - 1
    if step.choice is not None:
      lb, rb = _buttons(rect, step.choice[0], step.choice[1])
      self._hits.append((lb, lambda: self._record(False)))
      self._hits.append((rb, lambda: self._record(True)))
    else:
      lb, rb = _buttons(rect, tr("Start over") if last else (tr("Back") if self._i else None),
                        tr("Finish") if last else tr("Next"))
      if lb is not None:
        self._hits.append((lb, self.restart if last else self._back))
      self._hits.append((rb, self._next))

  def _record(self, yes: bool):
    ui_state.params.put_bool("RecordFront", yes)
    self._next()

  def _back(self):
    self._i = max(0, self._i - 1)

  def _next(self):
    if self._i < len(self._steps) - 1:
      self._i += 1
      return
    self._i = 0
    if self._on_done:
      self._on_done()

  def _handle_mouse_release(self, pos) -> bool:
    for r, fn in self._hits:
      if D.hit(r, pos):
        fn()
        return True
    return False


class _State(IntEnum):
  WELCOME = 0
  SAFETY = 1
  TERMS = 2
  SUNNYLINK = 3
  SUNNYLINK_OFF = 4
  GUIDE = 5
  DECLINE = 6


# Custom: no sunnylink step. Citadel Auto OS links through its own services and sunnylinkd doesn't run
# (system/manager/process_config.py); the consent params are left as they are.
FLOW = [(_State.WELCOME, "Welcome"), (_State.SAFETY, "Safety"), (_State.TERMS, "Terms"), (_State.GUIDE, "Guide")]

SAFETY_LINES = [
  "You are always the driver. Keep your eyes on the road and your hands ready to steer.",
  "Citadel Auto OS can make mistakes at any time, including at the worst moment.",
  "The driver camera watches that you pay attention and warns you when you don't.",
  "Use it only where you would drive yourself, and take over whenever something feels wrong.",
]


def _flow_bar(rect: rl.Rectangle, state: _State):
  """Where the person is in the whole setup: labelled squared segments across the top."""
  idx = {s: i for i, (s, _) in enumerate(FLOW)}
  cur = idx.get(_State.SUNNYLINK if state == _State.SUNNYLINK_OFF else state, 0)
  n, gap = len(FLOW), 12
  w = (rect.width - 2 * MARGIN - gap * (n - 1)) / n
  for i, (_, label) in enumerate(FLOW):
    x = rect.x + MARGIN + i * (w + gap)
    seg = rl.Rectangle(x, rect.y + 72, w, 16)
    rl.draw_rectangle_rounded(seg, roundness(seg, 4), 4, Console.ACCENT_FILL if i <= cur else Console.BG_TRACK)
    D.text(tr(label), x, rect.y + 104, D.LABEL, Console.TEXT_PRIMARY if i == cur else Console.TEXT_MUTED, semi=i == cur)


class ConsoleOnboarding(Widget):
  """First-run setup after install: welcome, safety notice, terms, driving guide.

  The OS's own setup (Wi-Fi, software URL, download) runs before this and belongs to AGNOS, not the fork."""

  def __init__(self):
    super().__init__()
    p = ui_state.params
    self._accepted = p.get("HasAcceptedTerms") == terms_version and p.get("HasAcceptedTermsSP") == terms_version_sp
    self._trained = p.get("CompletedTrainingVersion") == training_version
    self._sunnylink_done = True  # Custom: the sunnylink step is gone (see FLOW)
    self._guide = ConsoleTraining(on_done=self._on_guide_done)
    self._hits: list[tuple[rl.Rectangle | None, Callable[[], None]]] = []
    if not self._accepted:
      self._state = _State.WELCOME
    elif not self._sunnylink_done:
      self._state = _State.SUNNYLINK
    else:
      self._state = _State.GUIDE

  @property
  def completed(self) -> bool:
    return self._accepted and self._sunnylink_done and self._trained

  def _go(self, state: _State):
    self._state = state

  def _advance(self):
    if not self._sunnylink_done:
      self._state = _State.SUNNYLINK
    elif not self._trained:
      self._state = _State.GUIDE
    else:
      gui_app.pop_widget()

  def _accept(self):
    ui_state.params.put("HasAcceptedTerms", terms_version)
    ui_state.params.put("HasAcceptedTermsSP", terms_version_sp)
    self._accepted = True
    self._advance()

  def _sunnylink(self, enable: bool):
    # Same params as sunnypilot's SunnylinkConsentPage
    ui_state.params.put_bool("SunnylinkEnabled", enable)
    ui_state.params.put("CompletedSunnylinkConsentVersion", sunnylink_consent_version if enable else sunnylink_consent_declined)
    self._sunnylink_done = True
    self._advance()

  def _uninstall(self):
    ui_state.params.put_bool("DoUninstall", True)
    gui_app.request_close()

  def _on_guide_done(self):
    ui_state.params.put("CompletedTrainingVersion", training_version)
    self._trained = True
    gui_app.pop_widget()

  def _render(self, rect: rl.Rectangle):
    self._hits = []
    st = self._state
    if st == _State.GUIDE:
      self._guide.render(rect)
      return -1
    _frame(rect)
    if st != _State.DECLINE:
      _flow_bar(rect, st)
    top = rect.y + 220
    if st == _State.WELCOME:
      _hero(rect, "home", tr("Welcome"),
            tr("Your comma is about to drive with Citadel Auto OS on the F-150 Lightning. Setup takes about two minutes."), top)
      _, rb = _buttons(rect, None, tr("Get started"))
      self._hits.append((rb, lambda: self._go(_State.SAFETY)))
    elif st == _State.SAFETY:
      _hero(rect, "eye", tr("Before you drive"), "", top)
      tx = rect.x + MARGIN + ICON_BOX + 72
      tw = rect.x + rect.width - MARGIN - tx
      y = top + 120
      for line in SAFETY_LINES:
        D.dot(tx + 8, y + 22, 7, Console.ACCENT)
        for i, ln in enumerate(D.wrap(tr(line), 36, tw - 36, 2)):
          D.text(ln, tx + 36, y + i * 48, 36, Console.TEXT_SECONDARY)
        y += 48 * len(D.wrap(tr(line), 36, tw - 36, 2)) + 20
      lb, rb = _buttons(rect, tr("Back"), tr("I understand"))
      self._hits += [(lb, lambda: self._go(_State.WELCOME)), (rb, lambda: self._go(_State.TERMS))]
    elif st == _State.TERMS:
      _hero(rect, "list", tr("Terms of Service"),
            tr("Citadel Auto OS is built on BluePilot, sunnypilot and openpilot. Accept their Terms of Service to use it.") + " " +
            tr("Read them at sunnypilot.ai/terms before you continue."), top)
      lb, rb = _buttons(rect, tr("Decline"), tr("Agree"))
      self._hits += [(lb, lambda: self._go(_State.DECLINE)), (rb, self._accept)]
    elif st == _State.DECLINE:
      _hero(rect, "close", tr("Terms not accepted"),
            tr("Citadel Auto OS can't run without the Terms of Service. Go back to accept them, or uninstall it."), top)
      lb, rb = _buttons(rect, tr("Back"), tr("Uninstall"), danger=True)
      self._hits += [(lb, lambda: self._go(_State.TERMS)), (rb, self._uninstall)]
    elif st == _State.SUNNYLINK:
      _hero(rect, "cloud", tr("sunnylink"),
            tr("Secure remote access to this comma: manage and back up settings, and watch a live dashboard.") + " " +
            tr("You can change this later in Connect."), top)
      lb, rb = _buttons(rect, tr("Not now"), tr("Turn on"))
      self._hits += [(lb, lambda: self._go(_State.SUNNYLINK_OFF)), (rb, lambda: self._sunnylink(True))]
    elif st == _State.SUNNYLINK_OFF:
      _hero(rect, "cloud", tr("Keep sunnylink off?"),
            tr("Without sunnylink, remote settings, backups and the live dashboard aren't available. Driving isn't affected."), top)
      lb, rb = _buttons(rect, tr("Back"), tr("Keep it off"), danger=True)
      self._hits += [(lb, lambda: self._go(_State.SUNNYLINK)), (rb, lambda: self._sunnylink(False))]
    return -1

  def _handle_mouse_release(self, pos) -> bool:
    for r, fn in self._hits:
      if r is not None and D.hit(r, pos):
        fn()
        return True
    return False
