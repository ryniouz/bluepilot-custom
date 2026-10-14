"""
Screen > Road view: the road view options (BPRoadView bits, also on the quick controls Road view sheet) and the
driving-view rows of the old BluePilot tuning panel. The sunnypilot Visuals rows live on Screen > Onroad display.
Same params as before; rows whose param this build lacks are left out.
"""

from __future__ import annotations

from openpilot.selfdrive.ui.bp.onroad.road_view import (LC_STYLE_LABELS, LC_STYLES, LEAD_STYLE_LABELS, LEAD_STYLES, LC_MASK,
                                                        LC_SHIFT, MARKER_MASK, MARKER_SHIFT, OPTIONS, PRESET_ORDER,
                                                        PRESETS, road_prefs)
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.console.form import Choice, Note, Section, Toggle
from bluepilot.ui.console.pages.drive import DrivePage

ROAD_SUBS = {
  "Lead card": "Distance, speed and gap, top right",
  "Speed tag": "Lead speed beside the car",
  "Distance": "On the lead card",
  "Lead speed": "On the lead card",
  "Time gap": "On the lead card",
  "Closing": "How fast you're closing in",
  "Lane lines": "Your lane",
  "Next lanes": "The lanes beside you",
  "Road edges": "Curbs and road edges",
  "Large speed": "A much bigger speed on the speed card",
}


def _ui_refresh():
  try:
    ui_state.update_params()
  except Exception:
    pass


class DrivingScreenPage(DrivePage):
  def toggle(self, key, title, sub, **kw):  # driving view flags are cached in ui_state; re-read them on change
    t = super().toggle(key, title, sub, **kw)
    if t is not None and t.fn is not None:
      fn = t.fn
      t.fn = lambda: (fn(), _ui_refresh())
    return t

  def _choice(self, key: str, title: str, labels: list[str], default: int = 0, **kw) -> Choice | None:
    if not self.has(key):
      return None
    sel = max(0, min(len(labels) - 1, self.p.int(key, default)))
    return Choice(title, [tr(x) for x in labels], sel, lambda i: (self.p.put(key, i), _ui_refresh()), **kw)

  def _set_bits(self, mask: int, shift: int, i: int):
    road_prefs._write((road_prefs.value & ~mask) | (i << shift))

  def sections(self):
    v = road_prefs.value
    order = list(PRESET_ORDER)
    preset = road_prefs.preset
    road_rows: list = [
      Choice(tr("Style"), [tr(PRESETS[i][1]) for i in order], order.index(preset),
             lambda k: road_prefs.set_preset(order[k])),
    ]
    if preset:
      road_rows.append(Note(tr(PRESETS[preset][2]) + ". " + tr("Change any switch to make it your own.")))
    road_rows += [
      Toggle(tr(label), tr(ROAD_SUBS.get(label, "")), road_prefs.on(bit), lambda b=bit: road_prefs.toggle(b))
      for bit, label in OPTIONS
    ]
    marker = (v & MARKER_MASK) >> MARKER_SHIFT
    lc = (v & LC_MASK) >> LC_SHIFT
    styles = Section(tr("Lead car and lane change"), "car", [
      Choice(tr("Lead car marker"), [tr(LEAD_STYLE_LABELS[s]) for s in LEAD_STYLES], marker,
             lambda i: self._set_bits(MARKER_MASK, MARKER_SHIFT, i), radio=False),
      Choice(tr("Lane change cue"), [tr(LC_STYLE_LABELS[s]) for s in LC_STYLES], lc,
             lambda i: self._set_bits(LC_MASK, LC_SHIFT, i), radio=False),
      self.toggle("FordPrefShowRadarLeadOverlay", tr("Radar lead marker"), tr("With the truck's own cruise")),
      self._choice("FordPrefRadarOverlaySize", tr("Radar marker size"), ["Small", "Medium", "Large"], 1)
      if self.p.bool("FordPrefShowRadarLeadOverlay") else None,
    ], note=tr("Quick controls change the road view too: swipe up on the driving screen."))

    extras = Section(tr("On the driving view"), "gauge", [
      self.toggle("ShowBrakeStatus", tr("Red speed when braking"), tr("While the brake lights are on")),
      self.toggle("ShowBlindspotOverlay", tr("Blind spot screen edge"), tr("Red glow on that side")),
      self.toggle("BPAnimateSteeringWheel", tr("Turning wheel icon"), tr("Follows the steering angle")),
      self.toggle("BPShowConfidenceBall", tr("Model confidence"), tr("Dot on the left edge")),
      self.toggle("BPDisableLaneLineStatusColor", tr("Green lane lines when engaged"), tr("Otherwise they stay white"),
                  invert=True),
      self.toggle("BPRainbowLines", tr("Rainbow lane lines"), tr("Just for fun")),
      self.toggle("BpShowLateralControl", tr("Steering mode badge"), tr("Curvature or angle, on the round button")),
    ], note=tr("Speedometer, steering arc, chimes and the other overlays are on Onroad display."))
    return [Section(tr("Road view"), "eye", road_rows), styles, extras]
