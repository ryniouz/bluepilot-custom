"""
Custom: Guest Mode (stream B).

Guest Mode hands driving back to the truck's factory systems for a driver who doesn't know the comma.
It reuses upstream's passive (dashcam) path: card sees BPGuestMode at car start, sets CP.passive, and the
panda runs noOutput, which opens the harness relay so the camera talks to the car directly and the comma
cannot transmit. Nothing here changes panda safety.

It only takes effect at a car start (card reads it once). With BPGuestModeOneTrip on, it switches itself
off at the first offroad transition after a guest drive, so the next drive is normal BluePilot again.
"""
from openpilot.common.params import Params


def guest_mode_requested(params: Params) -> bool:
  return params.get_bool("BPGuestMode")


def mark_drive_start(params: Params, guest: bool) -> None:
  """Called by card once the car is up: records what this drive is running as."""
  params.put_bool("BPGuestModeActive", guest)
  if guest:
    params.put_bool("BPGuestModeUsed", True)


def offroad_reset(params: Params) -> bool:
  """Called at each offroad start. Clears a one-trip Guest Mode after the drive that used it. Returns True if cleared."""
  if not params.get_bool("BPGuestModeUsed"):
    return False
  params.remove("BPGuestModeUsed")
  if params.get("BPGuestModeOneTrip", return_default=True):
    params.put_bool("BPGuestMode", False)
    return True
  return False
