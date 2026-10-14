"""
Console Vehicle page (System > Vehicle). This build only drives the Ford F-150 Lightning, so the all-makes
platform list is gone and the page groups the Lightning's own settings.

  Left    the truck: a fixed "Ford F-150 Lightning", whether the comma recognised it (or which other car it
          refused, BPPlatformMismatch), the platform lock (BPLockedPlatform) and the OBD adapter
  Right   tabs:
            Driving     Lightning tune, follow the drive mode, towing, one-pedal
            Alerts      low and critical battery %, low tire pressure (stored in kPa, shown in PSI), low 12 V
            Guest Mode  factory driver assist for the next drive, and whether it stays on
            Charging    stay on while charging, power down after charging
            12 V        the 12 V battery's charge, and how the comma treats it while parked: power saver,
                        power down below a charge, ignore the truck's own 12 V top-up wakes (stream B,
                        lightning-12v.md)

Keys come from the Lightning control branch (stream B); each row shows only once its key exists.
"""

from __future__ import annotations

from collections.abc import Callable

import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.console import draw as D
from bluepilot.ui.console import kit as K
from bluepilot.ui.console.home import _param, has_param
from bluepilot.ui.console.pages.cards import GAP, CardPage, as_float, as_int
from bluepilot.ui.lib.obd_link import live_values
from bluepilot.ui.lib.theme import Console

LIGHTNING = "FORD_F_150_LIGHTNING_MK1"
KPA_PER_PSI = 6.89476
TABS = ["Drive", "Alerts", "Guest", "Charge", "12 V"]
SOC_STEPS = [0, 40, 50, 60, 70, 80]
SAVER_MIN_STEPS = [5, 10, 15, 30, 60]


def platform_name(fp: str) -> str:
  """FORD_BRONCO_SPORT_MK1 -> Ford Bronco Sport Mk1."""
  name = " ".join(w.capitalize() for w in str(fp).split("_")) if fp else ""
  return name.replace("F 150", "F-150").replace("F 250", "F-250")


class VehiclePage(CardPage):
  def __init__(self):
    super().__init__()
    self._params = Params()
    self._tab = 0
    self.on_open_obd: Callable[[], None] | None = None

  def _get(self, key, default=None):
    return _param(self._params, key, default)

  def _put(self, key, value):
    try:
      if isinstance(value, bool):
        self._params.put_bool(key, value)
      else:
        self._params.put(key, value)
    except Exception:
      pass

  def _render(self, rect: rl.Rectangle):
    self._hits = []
    left, right = K.split_cols(rect, [0.85, 1.15] if rect.width >= 1600 else [1.0, 1.0])
    left.width -= GAP / 2
    right.x += GAP / 2
    right.width -= GAP / 2
    self._truck_card(left)

    tabs = rl.Rectangle(right.x, right.y, right.width, 72)
    rects = D.segmented(tabs, [tr(t) for t in TABS], self._tab)
    for i, r in enumerate(rects):
      self._hits.append((r, lambda i=i: setattr(self, "_tab", i)))
    body = rl.Rectangle(right.x, right.y + 72 + 24, right.width, right.height - 72 - 24)
    [self._driving_card, self._alerts_card, self._guest_card, self._power_card, self._lv_card][self._tab](body)

  # -- truck --------------------------------------------------------------------------------

  def _truck_card(self, r: rl.Rectangle):
    y = self._title(r, tr("Your truck"), "car")
    p = D.CARD_PAD
    x = r.x + p
    name = tr("Ford F-150 Lightning")
    size = D.H1 if D.text_w(name, D.H1, semi=True) <= r.width - 2 * p else D.H2
    D.text(D.fit(name, size, r.width - 2 * p, semi=True), x, y + (D.H1 - size) / 2, size, semi=True)
    y += 76

    locked = str(self._get("BPLockedPlatform", LIGHTNING) or "") if has_param(self._params, "BPLockedPlatform") else None
    mismatch = str(self._get("BPPlatformMismatch", "") or "") if has_param(self._params, "BPPlatformMismatch") else ""
    cp = ui_state.CP
    seen = str(cp.carFingerprint) if cp is not None else ""
    if mismatch:
      status, color = tr("Driver assist off"), Console.WARNING
    elif locked == "":
      status, color = tr("Lock off: any recognised car can be driven"), Console.WARNING
    elif seen == LIGHTNING:
      status, color = tr("Recognised"), Console.SUCCESS
    elif seen:
      status, color = tr("Recognised as") + " " + platform_name(seen), Console.WARNING
    else:
      status, color = tr("Waiting for the truck"), Console.TEXT_GHOST
    D.dot(x + 10, y + D.BODY / 2 + 2, 10, color)
    D.text(D.fit(status, D.BODY, r.width - 2 * p - 36, semi=True), x + 36, y, D.BODY, semi=True)
    y += 60
    if mismatch:
      y = self._note(r, y, tr("Detected") + f" {platform_name(mismatch)}: " +
                     tr("driver assist off, this build only drives the Lightning"), 3, Console.WARNING) + 16
    else:
      y += 8

    if locked is not None:
      on = locked != ""
      offroad = ui_state.is_offroad()
      y = self._toggle_row(r, y, tr("Only drive the Lightning"),
                           tr("Any other car stays passive") if offroad else tr("Change it while parked"), on,
                           lambda: self._put("BPLockedPlatform", "" if on else LIGHTNING), enabled=offroad)
    self._button_row(r, y, tr("OBD adapter"), tr("Tires, cell temps, 12 V"), tr("Open"),
                     lambda: self.on_open_obd and self.on_open_obd())

  # -- tabs ---------------------------------------------------------------------------------

  def _missing(self, r: rl.Rectangle, y: float) -> None:
    self._note(r, y + 8, tr("These settings come with the Lightning control update."))

  def _driving_card(self, r: rl.Rectangle):
    y = self._title(r, tr("Driving"), "steer")
    if not has_param(self._params, "BPLightningTune"):
      return self._missing(r, y)
    tune = bool(self._get("BPLightningTune", True))
    y = self._toggle_row(r, y, tr("Lightning tune"), tr("Steering and speed tuned for this truck"), tune,
                         lambda: self._put("BPLightningTune", not tune))
    if has_param(self._params, "BPDriveModeTune"):
      dm = bool(self._get("BPDriveModeTune", True))
      y = self._toggle_row(r, y, tr("Follow the drive mode"), tr("Sport, off-road and slippery change the tune"), dm,
                           lambda: self._put("BPDriveModeTune", not dm), enabled=tune)
    if has_param(self._params, "BPTowProfile"):
      tow = max(0, min(2, as_int(self._get("BPTowProfile", 0), 0)))
      y = self._seg_row(r, y, tr("Towing tune"), [tr("Auto"), tr("Off"), tr("On")], tow,
                        lambda i: self._put("BPTowProfile", int(i)), enabled=tune)
    if has_param(self._params, "BPOnePedalMode"):
      op = max(0, min(2, as_int(self._get("BPOnePedalMode", 2), 2)))
      y = self._seg_row(r, y, tr("One-pedal drive"), [tr("Off"), tr("On"), tr("Detect")], op,
                        lambda i: self._put("BPOnePedalMode", int(i)))
    self._note(r, y, tr("Towing Auto follows a hitched trailer or Tow/Haul. One-pedal Detect tells from how the truck slows."), 3)

  def _alerts_card(self, r: rl.Rectangle):
    y = self._title(r, tr("Alerts"), "bell")
    if not has_param(self._params, "BPLowSocAlertPct"):
      return self._missing(r, y)
    low = as_int(self._get("BPLowSocAlertPct", 20), 20)
    crit = as_int(self._get("BPCriticalSocAlertPct", 10), 10) if has_param(self._params, "BPCriticalSocAlertPct") else None
    y = self._step_row(r, y, tr("Low battery"), f"{low} %",
                       lambda: self._put("BPLowSocAlertPct", max(max(10, (crit or 0) + 5), low - 5)),
                       lambda: self._put("BPLowSocAlertPct", min(50, low + 5)))
    if crit is not None:
      y = self._step_row(r, y, tr("Critical battery"), f"{crit} %",
                         lambda: self._put("BPCriticalSocAlertPct", max(5, crit - 5)),
                         lambda: self._put("BPCriticalSocAlertPct", min(low - 5, crit + 5)))
    if has_param(self._params, "BPTireLowPressureKpa"):
      kpa = as_int(self._get("BPTireLowPressureKpa", 240), 240)
      psi = round(kpa / KPA_PER_PSI)
      y = self._step_row(r, y, tr("Low tire pressure"), f"{psi} PSI",
                         lambda: self._put("BPTireLowPressureKpa", round(max(20, psi - 1) * KPA_PER_PSI)),
                         lambda: self._put("BPTireLowPressureKpa", round(min(50, psi + 1) * KPA_PER_PSI)))
    if has_param(self._params, "BPLowVoltAlertV"):
      v = as_float(self._get("BPLowVoltAlertV", 11.8), 11.8)
      y = self._step_row(r, y, tr("Low 12 V battery"), f"{v:.1f} V",
                         lambda: self._put("BPLowVoltAlertV", f"{max(11.0, v - 0.1):.1f}"),
                         lambda: self._put("BPLowVoltAlertV", f"{min(12.6, v + 0.1):.1f}"))
    self._note(r, y, tr("Shown as a pop-up while driving and on Home when parked."), 2)

  def _guest_card(self, r: rl.Rectangle):
    y = self._title(r, tr("Guest Mode"), "person")
    if not has_param(self._params, "BPGuestMode"):
      return self._missing(r, y)
    armed = bool(self._get("BPGuestMode", False))
    active = has_param(self._params, "BPGuestModeActive") and bool(self._get("BPGuestModeActive", False))
    sub = tr("On for this drive") if active else (tr("Starts at the next drive") if armed else tr("Ford's own driver assist drives"))
    y = self._toggle_row(r, y, tr("Guest Mode"), sub, armed, lambda: self._put("BPGuestMode", not armed))
    if has_param(self._params, "BPGuestModeOneTrip"):
      one = bool(self._get("BPGuestModeOneTrip", True))
      y = self._toggle_row(r, y, tr("One drive only"), tr("Turns itself off after the drive"), one,
                           lambda: self._put("BPGuestModeOneTrip", not one))
    self._note(r, y, tr("For when someone else drives: the comma stops steering and braking at the next start, and the " +
                        "truck's factory systems take over. Recording still works."), 3)

  def _power_card(self, r: rl.Rectangle):
    y = self._title(r, tr("Charging"), "plug")
    if not has_param(self._params, "BPChargeKeepAwake"):
      return self._missing(r, y)
    awake = bool(self._get("BPChargeKeepAwake", True))
    y = self._toggle_row(r, y, tr("Stay on while charging"), tr("Shows the charge with the truck off"), awake,
                         lambda: self._put("BPChargeKeepAwake", not awake))
    if has_param(self._params, "BPChargeSleepDelayMin"):
      m = max(0, as_int(self._get("BPChargeSleepDelayMin", 30), 30))
      value = tr("Default") if m == 0 else (f"{m} min" if m < 60 else f"{m / 60:g} h")
      steps = [0, 10, 30, 60, 120, 240]
      i = min(range(len(steps)), key=lambda k: abs(steps[k] - m))
      y = self._step_row(r, y, tr("Power down after"), value,
                         lambda: self._put("BPChargeSleepDelayMin", steps[max(0, i - 1)]),
                         lambda: self._put("BPChargeSleepDelayMin", steps[min(len(steps) - 1, i + 1)]),
                         sub=tr("Once charging ends"))
    self._note(r, y + 4, tr("Default uses the comma's own power-off timer. The screen itself sleeps per Energy > Charging settings."), 2)

  # -- 12 V -----------------------------------------------------------------------------------

  def _lv_reading(self) -> tuple[float | None, float | None, str]:
    """(SOC %, volts, where from): the offroad monitor's chargingStateBP.lowVoltBattery first, then the OBD
    adapter, then the harness voltage the comma sees."""
    soc = volts = None
    note = ""
    try:
      sm = ui_state.sm
      if "chargingStateBP" in sm.data and sm.recv_frame["chargingStateBP"] > 0:
        cs = sm["chargingStateBP"]
        lv = getattr(cs, "lowVoltBattery", None)
        soc = getattr(lv, "socPercent", None) if lv is not None else None
        volts = getattr(lv, "voltage", None) if lv is not None else None
        volts = volts or getattr(cs, "harnessVoltage", None)
        note = str(getattr(cs, "shutdownReason", "") or "")
    except Exception:
      pass
    obd = live_values()
    if soc is None and "LvSoc" in obd:
      soc = obd["LvSoc"].value
    if volts is None and "LvV" in obd:
      volts = obd["LvV"].value
    if volts is None:
      try:
        ps = ui_state.sm["peripheralState"]
        volts = ps.voltage / 1000.0 if ps.voltage > 0 else None
      except Exception:
        pass
    return (soc if soc and soc > 0 else None), (volts if volts and volts > 0 else None), note

  def _lv_card(self, r: rl.Rectangle):
    y = self._title(r, tr("12 V battery"), "bolt")
    p = D.CARD_PAD
    x, right = r.x + p, r.x + r.width - p
    soc, volts, note = self._lv_reading()
    # the reading: charge as a thick bar when known, voltage beside it
    if soc is not None:
      D.text(f"{soc:.0f} %", x, y, D.H1, semi=True)
      if volts is not None:
        D.text_right(f"{volts:.1f} V", right, y + 8, D.H2, Console.TEXT_SECONDARY, semi=True)
      low = as_int(self._get("BPLvShutdownSoc", 0), 0) if has_param(self._params, "BPLvShutdownSoc") else 0
      K.bar(rl.Rectangle(x, y + 80, right - x, 28), soc / 100.0,
            Console.SUCCESS if soc >= 60 else (Console.WARNING if soc >= 40 else Console.DANGER),
            target=low / 100.0 if low else None)
      y += 136
    elif volts is not None:
      D.text(f"{volts:.1f} V", x, y, D.H1, semi=True)
      D.text_right(D.fit(tr("Charge shows with the truck data"), D.LABEL, right - x - 260), right, y + 22, D.LABEL,
                   Console.TEXT_MUTED)
      y += 96
    if note:
      y = self._note(r, y - 12, note, 1) + 12

    if not has_param(self._params, "BPLvSaver"):
      return self._missing(r, y)
    saver = bool(self._get("BPLvSaver", False))
    mins = max(1, as_int(self._get("BPLvSaverOffroadMin", 10), 10))
    y = self._toggle_row(r, y, tr("12 V power saver"),
                         tr("Sleeps") + f" {mins} min " + tr("after parking"), saver,
                         lambda: self._put("BPLvSaver", not saver))
    if saver and has_param(self._params, "BPLvSaverOffroadMin"):
      i = min(range(len(SAVER_MIN_STEPS)), key=lambda k: abs(SAVER_MIN_STEPS[k] - mins))
      y = self._step_row(r, y, tr("Sleep after"), f"{mins} min",
                         lambda: self._put("BPLvSaverOffroadMin", SAVER_MIN_STEPS[max(0, i - 1)]),
                         lambda: self._put("BPLvSaverOffroadMin", SAVER_MIN_STEPS[min(len(SAVER_MIN_STEPS) - 1, i + 1)]),
                         sub=tr("Power saver"))
    if has_param(self._params, "BPLvShutdownSoc"):
      pct = max(0, as_int(self._get("BPLvShutdownSoc", 0), 0))
      i = min(range(len(SOC_STEPS)), key=lambda k: abs(SOC_STEPS[k] - pct))
      y = self._step_row(r, y, tr("Sleep below"), tr("Off") if pct == 0 else f"{pct} %",
                         lambda: self._put("BPLvShutdownSoc", SOC_STEPS[max(0, i - 1)]),
                         lambda: self._put("BPLvShutdownSoc", SOC_STEPS[min(len(SOC_STEPS) - 1, i + 1)]),
                         sub=tr("12 V charge"))
    if has_param(self._params, "BPLvWakeFilter"):
      wf = bool(self._get("BPLvWakeFilter", True))
      y = self._toggle_row(r, y, tr("Ignore 12 V top-ups"), tr("Not a drive"),
                           wf, lambda: self._put("BPLvWakeFilter", not wf))
    self._note(r, y, tr("Parked, the truck wakes now and then to top up its 12 V from the big battery. " +
                        "The comma sleeps through it."), 3)
