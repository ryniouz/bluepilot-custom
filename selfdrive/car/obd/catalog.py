"""
Custom: OBD PID catalog for the F-150 Lightning (stream B).

A small built-in set covers the values the comma cannot read from its own CAN connection
(state of health inputs, module voltages, 12 V SOC, charger internals). A fuller catalog can be
dropped on the device at /data/bp_obd/pids.csv in the scanner-app column layout
(request, ecu_header, name, short_name, formula, byte_start, byte_len, mul, div, ofs, signed, unit);
it is read at start and replaces the built-in set.

Every request must be a read: mode 0x01, 0x09 or 0x22. Anything else is rejected when the catalog
is loaded, so the client can never send a write, routine or session-control request.
"""
import csv
import os
from dataclasses import dataclass, field

from openpilot.selfdrive.car.obd.formula import Formula

USER_CATALOG = "/data/bp_obd/pids.csv"
READ_SERVICES = (0x01, 0x09, 0x22)
DEFAULT_HEADER = "7DF"  # functional (broadcast) request: whichever module owns the DID answers on 7E8-7EF

# unit normalisation: everything published is metric, like carStateBP
_UNIT_FIX = {
  "fahrengheit": ("degC", lambda v: (v - 32.) / 1.8),
  "fahrenheit": ("degC", lambda v: (v - 32.) / 1.8),
  "psi": ("kPa", lambda v: v * 6.894757),
  "celicium": ("degC", lambda v: v),
  "volts": ("V", lambda v: v),
  "none": ("", lambda v: v),
}


@dataclass
class Pid:
  header: str            # request CAN ID, 3 hex digits
  request: str           # e.g. "224801"
  name: str
  short_name: str
  unit: str
  decode: object         # callable(bytes payload after the DID) -> float
  period_s: float = 5.0  # how often to ask
  min: float | None = None
  max: float | None = None
  extra: list = field(default_factory=list)  # other signals in the same response: (short_name, name, unit, decode)

  @property
  def service(self) -> int:
    return int(self.request[:2], 16)


def _metric(unit: str, fn):
  u = unit.strip()
  key = u.lower()
  if key in _UNIT_FIX:
    new_unit, conv = _UNIT_FIX[key]
    return new_unit, (lambda d: conv(fn(d)))
  return u, fn


def check_request(request: str) -> str:
  r = request.strip().upper()
  if len(r) < 4 or len(r) % 2 or any(c not in "0123456789ABCDEF" for c in r):
    raise ValueError(f"bad OBD request {request!r}")
  if int(r[:2], 16) not in READ_SERVICES:
    raise ValueError(f"OBD request {request!r} is not a read (only services 01, 09, 22 are allowed)")
  return r


def field_decoder(byte_start: int, byte_len: int, mul: float, div: float, ofs: float, signed: bool):
  """Plain byte-field decode: big-endian integer of byte_len bytes, * mul / div + ofs."""
  div = div or 1.
  mul = 1. if mul == 0 else mul

  def decode(d: bytes) -> float:
    chunk = d[byte_start:byte_start + max(1, byte_len)]
    if len(chunk) < max(1, byte_len):
      raise ValueError("short response")
    raw = int.from_bytes(chunk, "big", signed=signed)
    return raw * mul / div + ofs
  return decode


def _p(header, request, short, name, unit, formula, period_s, lo=None, hi=None) -> Pid:
  unit, fn = _metric(unit, Formula(formula))
  return Pid(header, check_request(request), name, short, unit, fn, period_s, lo, hi)


# Built-in set: Ford enhanced (mode 22) DIDs on the Lightning's 11-bit diagnostic IDs.
# BECM 7E4 (HV battery), SOBDM 7E2 (charger), BCM 726, ABS 760.
BUILTIN = [
  _p("7E4", "224801", "HvbSoc", "HV battery state of charge", "percent", "INT16(A,B)*0.002", 5, 0, 100),
  _p("7E4", "224845", "HvbSocD", "HV battery SOC displayed", "percent", "A*0.5", 10, 0, 100),
  _p("7E4", "224848", "HvbEte", "HV battery energy to empty", "kWh", "INT16(A,B)*0.002", 10, 0, 140),
  _p("7E4", "224800", "HvbT", "HV battery temperature", "fahrenheit", "(A-50)*1.8+32", 10),
  _p("7E4", "224846", "HvbCit", "HV battery coolant inlet temperature", "fahrenheit", "(A-50)*1.8+32", 10),
  _p("7E4", "224841", "HvbAvgModV", "HV battery average module voltage", "volts", "INT16(A,B)*0.001", 10, 0, 10),
  _p("7E4", "224840", "HvbMinModV", "HV battery minimum module voltage", "volts", "INT16(A,B)*0.001", 10, 0, 10),
  _p("7E4", "224810", "HvbAge", "HV battery age", "months", "INT16(A,B)*0.005", 300, 0, 320),
  _p("7E2", "22480D", "HvbV", "HV battery voltage (charger)", "volts", "INT16(A,B)*0.01", 2, 0, 600),
  _p("7E2", "22480B", "HvbA", "HV current (charger)", "A", "((SIGNED(A)*256)+B)*0.02", 2, -600, 600),
  _p("7E2", "22484D", "ChgSt", "HV charger status", "none", "A", 5, 0, 6),
  _p("7E2", "224851", "Evse", "EVSE type", "none", "A", 5, 0, 12),
  _p("7E2", "22484A", "ChgOV", "HV charger output voltage", "volts", "INT16(A,B)*0.01", 5, 0, 600),
  _p("7E4", "22490C", "HvbSoh", "HV battery state of health", "percent", "A*0.5", 600, 0, 100),
  _p("7E4", "22485C", "HvbCapAh", "HV battery capacity", "Ah", "INT16(A,B)*0.1", 600, 0, 1000),
  _p("7E6", "2248DE", "HvbCHP", "Coolant heater power", "kW", "INT16(A,B)*0.001", 5, 0, 20),
  _p("7E6", "2248DF", "HvbCHOp", "Coolant heater mode", "none", "A", 10, 0, 200),
  _p("7E2", "22484E", "ChgInPwr", "Charger input power available", "kW", "INT16(A,B)*0.005", 5, 0, 600),
  _p("7E2", "2248C4", "ChgMaxP", "Charger maximum power", "kW", "INT16(A,B)*0.05", 30, 0, 500),
  _p("7E2", "224888", "ChgACT", "AC charge port temperature", "degC", "A-40", 10, -40, 150),
  _p("7E2", "22489E", "DCChgSt", "DC charger status", "none", "A", 5, 0, 18),
  # AC side of the on-board charger: functional requests, as the old EVTel agent sent them. Never seen
  # answered on this truck yet (no charge has been logged), so treat them as unverified until one is.
  _p("7DF", "22485E", "ACInV", "AC charger input voltage", "volts", "INT16(A,B)*0.01", 5, 0, 300),
  _p("7DF", "22485F", "ACInA", "AC charger input current", "A", "A", 5, 0, 100),
  _p("7DF", "224860", "ACInF", "AC charger input frequency", "Hz", "A*0.5", 30, 30, 90),
  _p("7DF", "224861", "PilotDC", "Charge pilot duty cycle", "percent", "A*0.5", 10, 0, 100),
  _p("7DF", "224862", "ProxSt", "Charge plug proximity status", "none", "A", 10, 0, 18),
  _p("726", "22402A", "LvV", "12 V battery voltage", "volts", "A/20+6", 10, 0, 20),
  _p("726", "224028", "LvSoc", "12 V battery state of charge", "percent", "A", 30, 0, 100),
  _p("726", "222813", "TireLF", "Tire pressure left front", "psi", "(((256*A)+B)/3+22/3)*0.145", 30),
  _p("726", "222814", "TireRF", "Tire pressure right front", "psi", "(((256*A)+B)/3+22/3)*0.145", 30),
  _p("726", "222816", "TireLR", "Tire pressure left rear", "psi", "(((256*A)+B)/3+22/3)*0.145", 30),
  _p("726", "222815", "TireRR", "Tire pressure right rear", "psi", "(((256*A)+B)/3+22/3)*0.145", 30),
]


def _f(row, key, default=0.):
  try:
    return float(row.get(key) or default)
  except ValueError:
    return default


def load_csv(path: str) -> tuple[list[Pid], list[str]]:
  """Load a scanner-app style catalog. Returns (pids, problems); bad rows are skipped and reported."""
  by_key: dict[tuple[str, str], Pid] = {}
  problems = []
  with open(path, newline="", errors="replace") as f:
    for n, row in enumerate(csv.DictReader(f), start=2):
      try:
        request = check_request(row["request"])
        header = (row.get("ecu_header") or "").strip().upper()
        header = DEFAULT_HEADER if not header or header.startswith("(") else header
        int(header, 16)
        formula = (row.get("formula") or "").strip()
        if formula:
          fn = Formula(formula)
        else:
          fn = field_decoder(int(_f(row, "byte_start")), int(_f(row, "byte_len", 1)) or 1, _f(row, "mul", 1),
                             _f(row, "div", 1), _f(row, "ofs"), (row.get("signed") or "").strip().lower() == "true")
        unit, fn = _metric(row.get("unit") or "", fn)
        short = (row.get("short_name") or row.get("name") or request).strip()
        name = (row.get("name") or short).strip()
        lo, hi = _f(row, "min"), _f(row, "max")
        lo, hi = (lo, hi) if hi > lo else (None, None)
      except (KeyError, ValueError) as e:
        problems.append(f"line {n}: {e}")
        continue
      key = (header, request)
      if key in by_key:  # several signals decoded from one response: one request, extra decoders
        by_key[key].extra.append((short, name, unit, fn))
      else:
        by_key[key] = Pid(header, request, name, short, unit, fn, 5.0, lo, hi)
  return list(by_key.values()), problems


def load_catalog(path: str = USER_CATALOG) -> tuple[list[Pid], str]:
  """User catalog if present and usable, else the built-in set. Returns (pids, source description)."""
  if os.path.isfile(path):
    try:
      pids, problems = load_csv(path)
      if pids:
        note = f" ({len(problems)} rows skipped)" if problems else ""
        return pids, f"{path}: {len(pids)} requests{note}"
    except OSError:
      pass
  return list(BUILTIN), f"built-in: {len(BUILTIN)} requests"
