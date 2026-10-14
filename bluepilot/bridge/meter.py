"""comma connect's cellular byte meter: the stock uploader adds what it sent over LTE, the bridge reads it.

A plain decimal counter in tmpfs, cumulative since boot (a reboot starts it from zero, which the bridge's
DataUsage.observe_comma treats like a modem counter restart). One writer: system/loggerd/uploader.py.
Standard library only, so the uploader can import it without pulling in the bridge.
"""
import os

METER_PATH = os.environ.get("BP_COMMA_METER_PATH", "/dev/shm/bp_comma_cell_bytes")


def read(path: str = METER_PATH) -> int | None:
  try:
    with open(path) as f:
      return int(f.read().strip() or 0)
  except (OSError, ValueError):
    return None


def add(nbytes: int, path: str = METER_PATH) -> None:
  """Never raises: metering must not break an upload."""
  if nbytes <= 0:
    return
  try:
    total = (read(path) or 0) + int(nbytes)
    tmp = f"{path}.tmp"
    with open(tmp, "w") as f:
      f.write(str(total))
    os.replace(tmp, path)
  except (OSError, ValueError):
    pass
