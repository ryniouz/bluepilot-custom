"""
The Citadel Auto OS update flow behind System > Updates, as one state the page draws:

  UP_TO_DATE   nothing newer on the update branch of Lucas's fork
  CHECKING     updated (or, on a PC, this module) is checking the fork and upstream BluePilot
  AVAILABLE    the fork's update branch has a newer commit: "Download and install"
  DOWNLOADING  updated is fetching it; BPUpdateProgress carries the percentage, stage and size/speed
  READY        downloaded and finalized: "Install now" restarts the comma, which swaps it in
  FAILED       the last check or download failed (LastUpdateException)

On the comma the work is the stock updater's (system/updated/updated.py): SIGUSR1 checks, SIGHUP downloads,
DoReboot installs. On a PC (the simulator) there is no updated, so this module checks the fork and BluePilot
itself and plays the download with made-up progress, so the whole flow can be seen; nothing is installed.
"""

from __future__ import annotations

import datetime
import os
import threading
import time
from enum import Enum

from openpilot.system.hardware import PC
from bluepilot.system.update_check import check_all

SIM_DOWNLOAD_S = 14.0
SIM_SIZE_MB = 186.0


class State(Enum):
  UP_TO_DATE = "up_to_date"
  CHECKING = "checking"
  AVAILABLE = "available"
  DOWNLOADING = "downloading"
  READY = "ready"
  FAILED = "failed"


def _text(v) -> str:
  if isinstance(v, bytes):
    v = v.decode(errors="ignore")
  return str(v or "").strip("\x00").strip()


def state_of(p) -> State:
  """p: a ParamCache (or anything with get/bool)."""
  updater = _text(p.get("UpdaterState", ""))
  if p.bool("UpdateAvailable"):
    return State.READY
  if updater.startswith(("downloading", "finalizing")):
    return State.DOWNLOADING
  if updater.startswith("checking"):
    return State.CHECKING
  if p.bool("UpdaterFetchAvailable"):
    return State.AVAILABLE
  if _text(p.get("LastUpdateException", "")) or _text(p.get("UpdaterFetchFailed", "")):
    return State.FAILED
  return State.UP_TO_DATE


def progress_of(p) -> tuple[str, int, str]:
  """(stage, overall percent, size/speed detail) from BPUpdateProgress."""
  raw = p.get("BPUpdateProgress", None)
  if not isinstance(raw, dict):
    return "download", 0, ""
  try:
    return str(raw.get("stage", "download")), max(0, min(100, int(raw.get("pct", 0)))), str(raw.get("detail", ""))
  except (TypeError, ValueError):
    return "download", 0, ""


class UpdateFlow:
  def __init__(self, params):
    self.p = params          # the page's ParamCache: writes land in the cache at once
    self._busy = False

  # -- actions --------------------------------------------------------------------------------

  def check(self):
    if PC:
      self._thread(self._sim_check)
    else:
      os.system("pkill -SIGUSR1 -f system.updated.updated")  # updated also runs the fork and BluePilot checks

  def download(self):
    if PC:
      self._thread(self._sim_download)
    else:
      os.system("pkill -SIGHUP -f system.updated.updated")

  def install(self):
    """The page shows its install screen first, then calls this: the comma restarts and swaps the update in."""
    if PC:
      for key, value in (("UpdateAvailable", False), ("UpdaterFetchAvailable", False), ("UpdaterState", "idle")):
        self.p.put(key, value)
      self.p._params.remove("BPUpdateProgress")
    else:
      self.p.put("DoReboot", True)

  @property
  def simulated(self) -> bool:
    return PC

  # -- PC (simulator) -------------------------------------------------------------------------

  def _thread(self, fn):
    if self._busy:
      return
    self._busy = True

    def run():
      try:
        fn()
      finally:
        self._busy = False
    threading.Thread(target=run, name="console-update-flow", daemon=True).start()

  def _sim_check(self):
    params = self.p._params
    self.p.put("UpdaterState", "checking...")
    started = time.monotonic()
    check_all(params)
    time.sleep(max(0.0, 1.5 - (time.monotonic() - started)))   # long enough to see "Checking"
    fork = params.get("BPForkStatus") or {}
    if fork.get("error"):
      self.p.put("LastUpdateException", str(fork["error"]))
    else:
      params.remove("LastUpdateException")
    available = bool(fork.get("available")) and not fork.get("error")
    desc = f"{fork.get('version') or ''} / {fork.get('branch', '')} / {fork.get('commit', '')} / "
    self.p.put("UpdaterNewDescription", desc if available else "")
    self.p.put("UpdaterFetchAvailable", available)
    self.p.put("LastUpdateTime", datetime.datetime.now(datetime.UTC).replace(tzinfo=None))
    self.p.put("UpdaterState", "idle")

  def _sim_download(self):
    params = self.p._params
    self.p.put("UpdaterState", "downloading...")
    t0 = time.monotonic()
    while (f := (time.monotonic() - t0) / SIM_DOWNLOAD_S) < 1.0:
      if f < 0.7:
        mb = SIM_SIZE_MB * f / 0.7
        detail = f"{mb:.1f} MB of {SIM_SIZE_MB:.0f} MB · {SIM_SIZE_MB / (SIM_DOWNLOAD_S * 0.7):.1f} MB/s"
        stage = "download"
      elif f < 0.8:
        stage, detail = "resolve", ""
      elif f < 0.9:
        stage, detail = "apply", ""
      else:
        stage, detail = "finalize", ""
        self.p.put("UpdaterState", "finalizing update...")
      params.put("BPUpdateProgress", {"stage": stage, "pct": int(100 * f), "detail": detail})
      self.p.invalidate()
      time.sleep(0.1)
    params.put("BPUpdateProgress", {"stage": "finalize", "pct": 100, "detail": ""})
    self.p.put("UpdaterState", "idle")
    self.p.put("UpdaterFetchAvailable", False)
    self.p.put("UpdateAvailable", True)
