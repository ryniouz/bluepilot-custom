"""
What this build is made of, for System > About and System > Updates: Citadel Auto OS's own version and the
versions of everything under it (BluePilot, sunnypilot, openpilot, AGNOS).

  Citadel Auto OS   CITADEL_VERSION at the top of the tree (Lucas's own number, starting at 0.0.1)
  BluePilot         BPVERSION
  sunnypilot        sunnypilot/common/version.h (SUNNYPILOT_VERSION)
  openpilot         common/version.h (COMMA_VERSION)
  AGNOS             /VERSION on the comma (HARDWARE.get_os_version), and the one this build asks for in launch_env.sh

Files are read once; the AGNOS version is read on the comma only.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from functools import cache

BASEDIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

# The upstream commit this build is based on (lightning-console-7 = BluePilotDev/openpilot bp-dev d27bc20).
# Bump it when the fork is rebased on newer BluePilot.
UPSTREAM_REPO = "https://github.com/BluePilotDev/openpilot"
UPSTREAM_BASE_BRANCH = "bp-dev"
UPSTREAM_BASE_COMMIT = "d27bc20a7c13eed7ec1947d4c59b98835facea87"


def _read(*path: str) -> str:
  try:
    with open(os.path.join(BASEDIR, *path)) as f:
      return f.read().strip()
  except OSError:
    return ""


def _define(text: str, name: str) -> str:
  m = re.search(rf'#define\s+{name}\s+"([^"]*)"', text)
  return m.group(1) if m else ""


def parse_version(v: str) -> tuple[int, ...]:
  """'7.0.0' -> (7, 0, 0); '18.5' -> (18, 5); anything that isn't digits and dots -> ()."""
  nums = re.findall(r"\d+", v or "")
  return tuple(int(n) for n in nums) if re.fullmatch(r"\s*v?\d+(\.\d+)*\s*", v or "") else ()


def newer(a: str, b: str) -> bool:
  """True when version a is newer than version b (both dotted numbers)."""
  pa, pb = parse_version(a), parse_version(b)
  if not pa or not pb:
    return False
  n = max(len(pa), len(pb))
  return pa + (0,) * (n - len(pa)) > pb + (0,) * (n - len(pb))


@dataclass(frozen=True)
class Versions:
  citadel: str
  bluepilot: str
  sunnypilot: str
  openpilot: str
  agnos: str            # running on the comma; "" on a PC
  agnos_wanted: str     # what launch_env.sh asks for


@cache
def _files() -> tuple[str, str, str, str, str]:
  launch = _read("launch_env.sh")
  m = re.search(r'AGNOS_VERSION="([^"]+)"', launch)
  return (_read("CITADEL_VERSION") or "0.0.1", _read("BPVERSION"),
          _define(_read("sunnypilot", "common", "version.h"), "SUNNYPILOT_VERSION"),
          _define(_read("common", "version.h"), "COMMA_VERSION"), m.group(1) if m else "")


@cache
def _agnos() -> str:
  try:
    from openpilot.system.hardware import HARDWARE, TICI
    return str(HARDWARE.get_os_version() or "").strip() if TICI else ""
  except Exception:
    return ""


def versions() -> Versions:
  citadel, bp, sp, op, wanted = _files()
  return Versions(citadel, bp, sp, op, _agnos(), wanted)


def citadel_version(basedir: str | None = None) -> str:
  """CITADEL_VERSION of this tree, or of another one (the downloaded update in /data/safe_staging/finalized)."""
  if basedir is None:
    return versions().citadel
  try:
    with open(os.path.join(basedir, "CITADEL_VERSION")) as f:
      return f.read().strip()
  except OSError:
    return ""
