"""
Live value history for the Console Statistics page and Home's battery chart.

Every frame the UI hands over the current EvSnapshot and the raw carStateBP / chargingStateBP
messages. Each numeric value becomes a signal (a key such as "ev.soc" or
"carStateBP.evBattery.packVoltage") that is sampled into two ring buffers:

  fine    2 Hz for the last hour   (Statistics graph, 30 s to 1 h windows)
  coarse  one sample per 30 s for 24 h (Home's battery chart, the 24 h window)

Storage is numpy, about 90 KB per signal, so a few hundred signals stay under 30 MB.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, fields

import numpy as np

from bluepilot.ui.lib.ev_data import STALE_S, EvSnapshot

FINE_HZ = 2.0
FINE_S = 3600.0
COARSE_DT = 30.0
COARSE_S = 24 * 3600.0
RAW_SERVICES = ("carStateBP", "chargingStateBP")
KPA_TO_PSI = 0.145038  # Canadian units: °C and km, but tire pressure in psi


@dataclass(frozen=True)
class SignalInfo:
  key: str
  label: str
  unit: str
  group: str
  digits: int = 1


# Curated EvSnapshot values, listed first on the Statistics page
EV_SIGNALS: dict[str, tuple[str, str, str, int]] = {
  # field: (label, unit, group, digits)
  "soc": ("State of charge", "%", "Battery", 1),
  "voltage": ("Pack voltage", "V", "Battery", 1),
  "current_a": ("Pack current", "A", "Battery", 1),
  "power_kw": ("Pack power", "kW", "Battery", 1),
  "pack_temp_c": ("Pack temperature", "°C", "Battery", 1),
  "pack_delta_temp_c": ("Module temperature spread", "°C", "Battery", 1),
  "coolant_temp_c": ("Coolant temperature", "°C", "Battery", 1),
  "charge_limit_kw": ("Charge power limit", "kW", "Battery", 0),
  "discharge_limit_kw": ("Discharge power limit", "kW", "Battery", 0),
  "range_km": ("Range", "km", "Driving", 0),
  "wh_per_km": ("Efficiency (trip)", "Wh/km", "Driving", 0),
  "motor_torque_nm": ("Motor torque", "Nm", "Driving", 0),
  "trip_used_kwh": ("Trip energy used", "kWh", "Driving", 2),
  "trip_regen_kwh": ("Trip energy regenerated", "kWh", "Driving", 2),
  "trip_km": ("Trip distance", "km", "Driving", 2),
  "charge_power_kw": ("Charging power", "kW", "Charging", 1),
  "charge_time_to_full_min": ("Time to full", "min", "Charging", 0),
  "charging": ("Charging", "", "Charging", 0),
  "heater_on": ("Battery heater", "", "Charging", 0),
  "charge_conditioning": ("Battery conditioning", "", "Charging", 0),
  "lv_volts": ("12 V battery", "V", "Vehicle", 2),
  "outside_temp_c": ("Outside temperature", "°C", "Vehicle", 1),
}
TIRES = ("Front left tire", "Front right tire", "Rear left tire", "Rear right tire")

# Unit from a capnp field name suffix, for the raw carStateBP values
_SUFFIX_UNITS = [
  ("Percent", "%"), ("Perc", "%"), ("Kwh", "kWh"), ("Kw", "kW"), ("KwPerKm", "kW/km"), ("WhPerKm", "Wh/km"),
  ("TempC", "°C"), ("C", "°C"), ("Kpa", "psi"), ("Nm", "Nm"), ("Km", "km"), ("Hours", "h"), ("Seconds", "s"),
  ("Voltage", "V"), ("Volt", "V"), ("Current", "A"), ("Amps", "A"),
]
_SKIP_RAW = re.compile(r"(Available|Raw|Value)$")


def _humanize(name: str) -> str:
  words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name).split()
  return " ".join([words[0].capitalize()] + [w.lower() if len(w) > 1 else w for w in words[1:]]) if words else name


def _raw_unit(name: str) -> str:
  for suf, unit in _SUFFIX_UNITS:
    if name.endswith(suf) and (len(name) == len(suf) or name[-len(suf) - 1].islower() or name[-len(suf) - 1].isdigit()):
      return unit
  if name.endswith("Actual") and name.startswith("volt"):
    return "V"
  if name.endswith("Actual") and name.startswith("amps"):
    return "A"
  return ""


def flatten(obj, prefix: str, out: dict[str, float]) -> None:
  """Numeric and boolean leaves of a capnp message (dict from to_dict()), keyed by dotted path."""
  if isinstance(obj, dict):
    for k, v in obj.items():
      flatten(v, f"{prefix}.{k}" if prefix else k, out)
  elif isinstance(obj, bool):
    out[prefix] = 1.0 if obj else 0.0
  elif isinstance(obj, (int, float)):
    leaf = prefix.rsplit(".", 1)[-1]
    if not _SKIP_RAW.search(leaf):
      out[prefix] = float(obj) * (KPA_TO_PSI if leaf.endswith("Kpa") else 1.0)


class _Ring:
  __slots__ = ("t", "v", "n", "i", "cap")

  def __init__(self, cap: int):
    self.cap = cap
    self.t = np.zeros(cap)
    self.v = np.full(cap, np.nan, dtype=np.float32)
    self.n = 0
    self.i = 0

  def push(self, t: float, v: float):
    self.t[self.i] = t
    self.v[self.i] = v
    self.i = (self.i + 1) % self.cap
    self.n = min(self.n + 1, self.cap)

  def window(self, t0: float, t1: float) -> tuple[np.ndarray, np.ndarray]:
    if self.n == 0:
      return np.empty(0), np.empty(0, dtype=np.float32)
    if self.n < self.cap:
      t, v = self.t[:self.n], self.v[:self.n]
    else:
      t, v = np.roll(self.t, -self.i), np.roll(self.v, -self.i)
    m = (t >= t0) & (t <= t1)
    return t[m], v[m]


class EvHistory:
  """Per-signal ring buffers. Timestamps are time.monotonic() seconds."""

  def __init__(self):
    self._fine: dict[str, _Ring] = {}
    self._coarse: dict[str, _Ring] = {}
    self._info: dict[str, SignalInfo] = {}
    self.latest: dict[str, float] = {}
    self._next_fine = 0.0
    self._next_coarse = 0.0
    self._coarse_acc: dict[str, list[float]] = {}
    self.paused = False

  # -- catalog ----------------------------------------------------------------------------

  def keys(self) -> list[str]:
    """Signals seen so far, curated EV values first, then the raw messages in arrival order."""
    return list(self._info)

  def info(self, key: str) -> SignalInfo:
    return self._info.get(key) or SignalInfo(key, key, "", "Other")

  def _register(self, key: str):
    if key in self._info:
      return
    if key.startswith("ev."):
      f = key[3:]
      if f.startswith("tire_kpa."):
        idx = int(f.rsplit(".", 1)[1])
        self._info[key] = SignalInfo(key, TIRES[idx] if idx < 4 else f, "psi", "Vehicle", 0)
      else:
        label, unit, group, digits = EV_SIGNALS.get(f, (_humanize(f), "", "Other", 1))
        self._info[key] = SignalInfo(key, label, unit, group, digits)
    else:
      parts = key.split(".")
      service, leaf = parts[0], parts[-1]
      group = f"{service} · {_humanize(parts[1])}" if len(parts) > 2 else service
      self._info[key] = SignalInfo(key, _humanize(leaf), _raw_unit(leaf), group, 2)
    self._fine[key] = _Ring(int(FINE_S * FINE_HZ))
    self._coarse[key] = _Ring(int(COARSE_S / COARSE_DT))

  # -- sampling ----------------------------------------------------------------------------

  @staticmethod
  def snapshot_values(snap: EvSnapshot) -> dict[str, float]:
    out: dict[str, float] = {}
    for f in fields(snap):
      name = f.name
      if name not in EV_SIGNALS and name != "tire_kpa":
        continue
      v = getattr(snap, name)
      if name == "tire_kpa":
        for i, t in enumerate(v[:4]):
          out[f"ev.tire_kpa.{i}"] = float(t) * KPA_TO_PSI
      elif isinstance(v, bool):
        out[f"ev.{name}"] = 1.0 if v else 0.0
      elif isinstance(v, (int, float)):
        out[f"ev.{name}"] = float(v)
    return out

  def update(self, sm, snap: EvSnapshot | None, now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    if now < self._next_fine:
      return
    self._next_fine = now + 1.0 / FINE_HZ
    values: dict[str, float] = {}
    if snap is not None:
      # Only record EV values while there is live truck data; NaN gaps are kept so the graph shows dropouts
      if snap.available:
        values.update(self.snapshot_values(snap))
    mono = time.monotonic()
    for svc in RAW_SERVICES:
      try:
        fresh = svc in sm.recv_frame and sm.recv_frame[svc] > 0 and mono - float(sm.recv_time.get(svc, 0.0)) < STALE_S
        if fresh:
          flatten(sm[svc].to_dict(), svc, values)
      except Exception:
        continue
    self.push(values, now)

  def push(self, values: dict[str, float], now: float) -> None:
    for k in values:
      self._register(k)
    self.latest = values
    if self.paused:
      return
    for k, ring in self._fine.items():
      ring.push(now, values.get(k, math.nan))
    for k, v in values.items():
      if math.isfinite(v):
        self._coarse_acc.setdefault(k, []).append(v)
    if now >= self._next_coarse:
      self._next_coarse = now + COARSE_DT
      for k, ring in self._coarse.items():
        acc = self._coarse_acc.get(k)
        ring.push(now, float(np.mean(acc)) if acc else math.nan)
      self._coarse_acc = {}

  # -- reading -----------------------------------------------------------------------------

  def arrays(self, key: str, window_s: float, end: float | None = None) -> tuple[np.ndarray, np.ndarray]:
    """(times, values) for `key` in [end - window_s, end]; the coarse buffer serves windows over an hour."""
    end = time.monotonic() if end is None else end
    rings = self._coarse if window_s > FINE_S or end < time.monotonic() - FINE_S else self._fine
    ring = rings.get(key)
    if ring is None:
      return np.empty(0), np.empty(0, dtype=np.float32)
    return ring.window(end - window_s, end)

  def series(self, key: str, window_s: float) -> list[tuple[float, float]]:
    """Home's API: [(monotonic time, value)], oldest first. "soc" is accepted for "ev.soc"."""
    if "." not in key:
      key = f"ev.{key}"
    t, v = self.arrays(key, window_s)
    return list(zip(t.tolist(), v.tolist(), strict=False))

  def oldest(self, key: str | None = None) -> float | None:
    """Earliest timestamp available in the coarse history (bounds how far the graph can pan)."""
    rings = [self._coarse[key]] if key in self._coarse else list(self._coarse.values())
    ts = [r.window(0, math.inf)[0] for r in rings]
    ts = [t[0] for t in ts if len(t)]
    return min(ts) if ts else None
