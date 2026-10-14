"""
Upload and sync status for the two services the comma sends drives to, kept separate:

  comma connect   comma's own uploader (system/loggerd/uploader.py). Sends qlogs and, on Wi-Fi, the small
                  road video; marks each sent file with an xattr, which the drive index counts.
  Citadel         Lucas's own backend through the export bridge (stream C): live LTE uploads while driving
                  ("roadTrip" in the bridge status) and the home sync of whole drives over Wi-Fi ("homeSync").

Both read only local state (params, the drive index, the bridge's status file), so the UI never blocks.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

import pyray as rl

from openpilot.common.params import Params
from openpilot.selfdrive.ui.ui_state import ui_state
from openpilot.system.ui.lib.multilang import tr
from bluepilot.ui.lib import bridge_status as bridge
from bluepilot.ui.lib.drive_index import DriveIndex
from bluepilot.ui.lib.theme import Console

ATHENA_FRESH_NS = 80_000_000_000


@dataclass
class Service:
  name: str
  state: str
  color: rl.Color
  rows: list[tuple[str, str]] = field(default_factory=list)
  note: str = ""
  active: bool = False          # sending right now


def _param(params: Params, key: str, default=None):
  try:
    v = params.get(key, return_default=True)
  except Exception:
    return default
  if isinstance(v, bytes):
    v = v.decode(errors="ignore")
  return default if v is None else v


def has_param(params: Params, key: str) -> bool:
  try:
    params.get(key, return_default=True)
    return True
  except Exception:
    return False


def fmt_bytes(n: float) -> str:
  if n >= 1024 ** 3:
    return f"{n / 1024 ** 3:.1f} GB"
  if n >= 1024 ** 2:
    return f"{n / 1024 ** 2:.0f} MB"
  return f"{n / 1024:.0f} kB"


def _network() -> tuple[str, bool]:
  try:
    ds = ui_state.sm["deviceState"]
    return str(ds.networkType), bool(ds.networkMetered)
  except Exception:
    return "none", False


def _athena_online() -> bool | None:
  try:
    ping = int(ui_state.sm["deviceState"].lastAthenaPingTime)
  except Exception:
    return None
  return ping != 0 and time.monotonic_ns() - ping < ATHENA_FRESH_NS


def comma_connect(params: Params, idx: DriveIndex) -> Service:
  nt, metered = _network()
  online = _athena_online()
  off = has_param(params, "BPCommaConnect") and not _param(params, "BPCommaConnect", True)
  rows = [
    (tr("Waiting to upload"), f"{idx.connect_pending} " + tr("files") + f" · {fmt_bytes(idx.connect_pending_bytes)}"),
    (tr("Uploaded"), f"{idx.connect_sent} " + tr("files")),
    (tr("Uploads on"), tr("Wi-Fi only") if bool(_param(params, "GsmMetered", True)) else tr("Wi-Fi and LTE")),
  ]
  note = tr("Driving logs and the small road video. Full video goes only when you ask for it in comma connect.")
  if off:
    return Service(tr("comma connect"), tr("Turned off"), Console.TEXT_GHOST, rows, note)
  if online is False or nt == "none":
    state, color = tr("Offline"), Console.TEXT_GHOST
  elif idx.connect_pending == 0 and idx.scanned_at:
    state, color = tr("Everything is uploaded"), Console.SUCCESS
  elif nt == "wifi" and not metered:
    return Service(tr("comma connect"), tr("Uploading on Wi-Fi"), Console.ACCENT, rows, note, active=True)
  else:
    state, color = tr("Waiting for Wi-Fi"), Console.WARNING
  return Service(tr("comma connect"), state, color, rows, note)


def citadel_configured(params: Params) -> bool:
  if bridge.get("server", "configured", default=False):
    return True
  return has_param(params, "BPServerUrl") and bool(str(_param(params, "BPServerUrl", "") or "").strip())


def citadel_live(params: Params) -> Service:
  """Live uploads while driving (Road Trip Mode), LTE allowed."""
  rt = bridge.get("roadTrip")
  enabled = bool(rt.get("enabled")) if isinstance(rt, dict) else \
    (has_param(params, "BPRoadTripMode") and bool(_param(params, "BPRoadTripMode", False)))
  rows: list[tuple[str, str]] = []
  if isinstance(rt, dict):
    q = rt.get("queue") or {}
    today = rt.get("uploadedToday") or {}
    rows.append((tr("Waiting to upload"), f"{int(q.get('files') or 0)} " + tr("files") + f" · {fmt_bytes(int(q.get('bytes') or 0))}"))
    rows.append((tr("Sent today"), f"{int(today.get('files') or 0)} " + tr("files") + f" · {fmt_bytes(int(today.get('bytes') or 0))}"))
  video = bool(rt.get("video")) if isinstance(rt, dict) else bool(_param(params, "BPRoadTripVideo", 0)) if has_param(params, "BPRoadTripVideo") else False
  rows.append((tr("Sends"), tr("Logs and low-res video") if video else tr("Logs only")))
  note = tr("Sends while you drive, over LTE when allowed. Separate from comma connect.")
  if not citadel_configured(params):
    return Service(tr("Citadel live upload"), tr("Waiting for your server"), Console.TEXT_GHOST, rows, note)
  if not enabled:
    return Service(tr("Citadel live upload"), tr("Off"), Console.TEXT_GHOST, rows, note)
  if not isinstance(rt, dict):
    return Service(tr("Citadel live upload"), tr("Uploader not running"), Console.WARNING, rows, note)
  state = str(rt.get("state") or "idle")
  if state == "uploading":
    cur = rt.get("current") or {}
    pct = f", {int(cur.get('pct') or 0)} %" if cur else ""
    return Service(tr("Citadel live upload"), tr("Uploading") + pct, Console.ACCENT, rows, note, active=True)
  if state == "paused":
    reason = {"no_network": tr("no signal"), "no_server": tr("server not reachable"), "over_limit": tr("data limit reached"),
              "server_error": tr("server error"), "parked": tr("parked"), "disabled": tr("turned off")}.get(str(rt.get("pausedReason")), "")
    return Service(tr("Citadel live upload"), tr("Paused") + (f": {reason}" if reason else ""), Console.WARNING, rows, note)
  if state == "waiting":
    return Service(tr("Citadel live upload"), tr("Waiting for a connection"), Console.WARNING, rows, note)
  return Service(tr("Citadel live upload"), tr("Up to date"), Console.SUCCESS, rows, note)


def citadel_sync(params: Params, idx: DriveIndex) -> Service:
  """Whole drives pulled home over Wi-Fi (the export bridge's synced.json / homeSync)."""
  hs = bridge.get("homeSync")
  done = [d for d in idx.drives if not d.recording]
  synced = sum(1 for d in done if d.synced)
  waiting = len(done) - synced
  rows = [(tr("Synced drives"), f"{synced} / {len(done)}"), (tr("Not synced"), fmt_bytes(idx.unsynced_bytes))]
  if isinstance(hs, dict) and hs.get("lastSynced"):
    rows.append((tr("Last sync"), str(hs["lastSynced"]).replace("T", " ")[:16]))
  note = tr("Citadel pulls full drives when the truck is home on Wi-Fi.")
  enabled = has_param(params, "BPBridgeEnabled") and bool(_param(params, "BPBridgeEnabled", False))
  if not enabled and not idx.sync_known:
    return Service(tr("Citadel home sync"), tr("Data export is off"), Console.TEXT_GHOST, rows, note)
  if waiting == 0:
    return Service(tr("Citadel home sync"), tr("Every drive is home"), Console.SUCCESS, rows, note)
  return Service(tr("Citadel home sync"), (tr("1 drive waiting") if waiting == 1 else f"{waiting} " + tr("drives waiting")),
                 Console.WARNING, rows, note)
