"""
Pure helpers behind Connect > Wi-Fi and Connect > Connect backend (no drawing, no D-Bus), so they can be tested
without a screen or NetworkManager.

  Wi-Fi     signal bars for a network, the status line under it, the preferred-network choices, whether a saved
            preferred network has gone stale, and whether the hotspot may share LTE (IPv4 forwarding)
  Backend   which backend is selected vs. running, and the short dongle ID shown on the page
"""

from __future__ import annotations

import math
from collections.abc import Iterable

MIN_PASSWORD_LENGTH = 8   # NetworkManager rejects shorter WPA keys; the stock panel uses the same bounds
MAX_PASSWORD_LENGTH = 64


def text(v) -> str:
  """A param or D-Bus value as plain text (params hand back bytes or str, sometimes NUL-padded)."""
  if isinstance(v, bytes):
    v = v.decode("utf-8", errors="replace")
  return str(v or "").strip("\x00").strip()


# -- Wi-Fi ------------------------------------------------------------------------------------------

def signal_level(strength: int) -> int:
  """NetworkManager strength 0-100 as 1-4 bars (a network that's listed always shows one bar)."""
  return max(1, min(4, math.ceil(max(0, strength) / 25)))


def network_status(*, connected: bool, connecting: bool, forgetting: bool, saved: bool, secured: bool,
                   supported: bool = True) -> str:
  """The line under a network's name. English source strings; the page translates them."""
  if forgetting:
    return "Forgetting…"
  if connecting:
    return "Connecting…"
  if connected:
    return "Connected"
  if not supported:
    return "Security not supported"
  if saved:
    return "Saved"
  return "Secured" if secured else "Open"


def tap_action(*, connected: bool, saved: bool, secured: bool, supported: bool, busy: bool) -> str:
  """What tapping a network does: 'password' (ask for it first), 'connect', or 'none'. Mirrors the stock panel:
  an unsaved secured network asks for a password, anything else that isn't already connected connects."""
  if busy or not supported or connected:
    return "none"
  if not saved and secured:
    return "password"
  return "connect"


def saved_ssids(connections: Iterable[str], tethering_ssid: str) -> list[str]:
  """Saved Wi-Fi networks a person would recognise: the comma's own hotspot profile is left out."""
  return sorted({s for s in connections if s and s != tethering_ssid}, key=str.lower)


def preferred_choices(saved: list[str], favorite: str) -> tuple[list[str], int]:
  """Options for Preferred network: 'None' first, then the saved networks. Returns (options, selected index).
  A favorite that isn't saved (yet) stays listed so the page never shows a selection that isn't there."""
  options = ["None"] + list(saved)
  if favorite and favorite not in saved:
    options.append(favorite)
  return options, options.index(favorite) if favorite else 0


def stale_favorite(favorite: str, connections: Iterable[str]) -> bool:
  """The preferred network was forgotten: clear it (the BluePilot panel did the same). Only judged once
  NetworkManager has reported its saved connections, so an empty list at start-up never clears it."""
  conns = set(connections)
  return bool(favorite) and bool(conns) and favorite not in conns


def forwarding_allowed(prime_type: int) -> bool:
  """Stock rule: the hotspot may share LTE (net.ipv4.ip_forward) unless the SIM is comma prime's.
  PrimeType NONE = 0 and LITE = 2 are the user's own SIM plans."""
  return int(prime_type) in (0, 2)


# -- Connect backend --------------------------------------------------------------------------------

def backend_pending(selected: str, active: str | None) -> bool:
  """The selected backend differs from the one the device registered with at start-up (restart to apply).
  Before the first start with backend switching, BPActiveBackend is unset and nothing is pending."""
  return bool(active) and selected != active


def short_id(dongle_id: str | None) -> str:
  """'1a2b3c4d5e6f7a8b' -> '1a2b3c…7a8b', as the old Restore row showed it."""
  d = text(dongle_id)
  return f"{d[:6]}…{d[-4:]}" if len(d) > 12 else d
