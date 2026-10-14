#!/usr/bin/env python3
"""BluePilot data export bridge process (Custom). See DEVICE-API.md."""
import base64
import os
import secrets
import signal
import threading
import time

from openpilot.common.params import Params
from openpilot.common.gps import get_gps_location_service
from openpilot.common.swaglog import cloudlog
from openpilot.system.hardware.hw import Paths
from openpilot.system.loggerd.config import get_available_percent
from openpilot.system.version import get_build_metadata

from bluepilot.bridge import comma_connect
from bluepilot.bridge import config as cfg
from bluepilot.bridge import segments as seg_index
from bluepilot.bridge.config import (ALLOWED_FILES, DEFAULT_PORT, PARAM_KEEP_UNTIL_SYNCED, PARAM_NOTIFY_URL,
                                     PARAM_PORT, PARAM_TOKEN, STATE_DIR)
from bluepilot.bridge.link import LinkSettings, RemoteLink, local_caller
from bluepilot.bridge.live import LiveMonitor
from bluepilot.bridge.notify import Notifier
from bluepilot.bridge.params_allowlist import coerce_param
from bluepilot.bridge.roadtrip import RoadTripSettings, RoadTripUploader, UploadedStore
from bluepilot.bridge.server import BridgeContext, make_server
from bluepilot.bridge.status import (STATUS_PATH, StatusWriter, cellular_view, connectivity, disk_usage, network_view,
                                     storage_breakdown)
from bluepilot.bridge.store import EventLog, SyncedStore, iso_now
from bluepilot.bridge.usage import DataUsage


class ParamsAdapterImpl:
  def __init__(self, params: Params):
    self.p = params

  def get(self, key: str):
    v = self.p.get(key, return_default=True)
    return v.decode() if isinstance(v, bytes) else v

  def put(self, key: str, value) -> None:
    """Coerce a JSON value to the param's declared type (taken from its current/default value)."""
    current = self.p.get(key, return_default=True)
    self.p.put(key, coerce_param(value, current))

  def is_onroad(self) -> bool:
    return self.p.get_bool("IsOnroad")


def ensure_token(params: Params) -> str:
  token = params.get(PARAM_TOKEN)
  if isinstance(token, bytes):
    token = token.decode()
  if not token:
    token = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode().rstrip("=")
    params.put(PARAM_TOKEN, token)
  return token


def _int(params: Params, key: str, default: int) -> int:
  try:
    return int(params.get(key, return_default=True) or default)
  except (TypeError, ValueError):
    return default


def roadtrip_settings(params: Params) -> RoadTripSettings:
  url = params.get(cfg.PARAM_SERVER_URL)
  return RoadTripSettings(
    enabled=params.get_bool(cfg.PARAM_ROADTRIP), video=_int(params, cfg.PARAM_ROADTRIP_VIDEO, 1) == 1,
    server_url=((url.decode() if isinstance(url, bytes) else url) or "").strip(),
    limit_bytes=max(0, _int(params, cfg.PARAM_CELL_LIMIT_MB, 0)) * 1_000_000,
    limit_action=_int(params, cfg.PARAM_CELL_LIMIT_ACTION, 0),
    cellular=params.get_bool(cfg.PARAM_ROADTRIP_CELLULAR),
  )


def link_settings(params: Params) -> LinkSettings:
  rt = roadtrip_settings(params)
  return LinkSettings(enabled=params.get_bool(cfg.PARAM_REMOTE_LINK), server_url=rt.server_url,
                      limit_bytes=rt.limit_bytes, limit_action=rt.limit_action)


def _str(params: Params, key: str) -> str:
  v = params.get(key)
  return (v.decode() if isinstance(v, bytes) else v) or ""


class SlowStatus:
  """Parts of the status that cost a scan or a dbus call; refreshed with storage (every 30 s)."""

  def __init__(self, params: Params, log_root: str):
    self.params, self.log_root = params, log_root
    self.comma_queue = (0, 0)
    self.sim: dict | None = None
    self.modem_version: str | None = None

  def refresh(self, segs) -> None:
    self.comma_queue = comma_connect.pending(self.log_root, segs)
    try:
      from openpilot.system.hardware import HARDWARE
      self.sim = HARDWARE.get_sim_info()
      self.modem_version = HARDWARE.get_modem_version()
    except Exception:
      pass


def main() -> None:
  try:
    os.nice(10)
  except OSError:
    pass
  params = Params()
  ensure_token(params)
  os.makedirs(STATE_DIR, exist_ok=True)

  def token() -> str:
    t = params.get(PARAM_TOKEN)
    return (t.decode() if isinstance(t, bytes) else t) or ""

  events = EventLog()
  synced = SyncedStore()
  usage = DataUsage(cfg.state_path(cfg.USAGE_FILE), reset_day=lambda: _int(params, cfg.PARAM_CELL_RESET_DAY, 1))
  live = LiveMonitor(events, Paths.log_root(), ALLOWED_FILES, get_gps_location_service(params),
                     on_modem_bytes=usage.observe_modem)
  live.start()
  Notifier(events, lambda: ParamsAdapterImpl(params).get(PARAM_NOTIFY_URL), token).start()

  # Road Trip Mode: push finished segments and live data to our own server
  def rt_settings() -> RoadTripSettings:
    return roadtrip_settings(params)

  uploader = RoadTripUploader(rt_settings, token, Paths.log_root(), ALLOWED_FILES, synced, UploadedStore(STATE_DIR),
                              usage, lambda: network_view(live.latest_network()), live.latest)
  uploader.start()

  # Remote link: Citadel reaches this API from away through an outbound long-poll
  port = int(params.get(PARAM_PORT) or DEFAULT_PORT)
  link = RemoteLink(lambda: link_settings(params), token, local_caller(port, token),
                    lambda: network_view(live.latest_network()), usage)
  link.start()

  slow = SlowStatus(params, Paths.log_root())

  def build_connectivity() -> dict:
    segs = seg_index.scan(Paths.log_root(), ALLOWED_FILES)
    unsynced = sum(1 for x in segs if not x.locked and synced.level(x.dir) is None)
    try:
      last_synced = iso_now(os.path.getmtime(cfg.state_path(cfg.SYNCED_FILE)))
    except OSError:
      last_synced = None
    net_raw = live.latest_network()
    net = network_view(net_raw)
    dongle_id = _str(params, "DongleId")
    try:
      last_ping = int(params.get("LastAthenaPingTime") or 0) or None
    except (TypeError, ValueError):
      last_ping = None
    comma = comma_connect.status(bool(dongle_id) and dongle_id != "UnregisteredDevice", last_ping,
                                 time.monotonic_ns(), net, params.get_bool(cfg.PARAM_COMMA_WIFI_ONLY), slow.comma_queue)
    cellular = cellular_view(net_raw.get("info"), net["strength"], slow.sim, slow.modem_version,
                             params.get_bool("GsmRoaming"), _str(params, "GsmApn"), params.get_bool("GsmMetered"))
    return connectivity(net, uploader.status(), usage.summary(rt_settings().limit_bytes), comma,
                        params.get_bool(PARAM_KEEP_UNTIL_SYNCED), unsynced, last_synced, cellular, link.status())

  def build_storage() -> dict:
    segs = seg_index.scan(Paths.log_root(), ALLOWED_FILES)
    slow.refresh(segs)
    total, free = disk_usage(Paths.log_root())
    return storage_breakdown(segs, synced, total, free)

  status_writer = StatusWriter(STATUS_PATH, build_connectivity, build_storage)
  status_writer.start()

  try:
    version = get_build_metadata().openpilot.version
  except Exception:
    version = "unknown"
  dongle = params.get("DongleId")
  ctx = BridgeContext(
    token=token, events=events, synced=synced, log_root=Paths.log_root(), live=live,
    params=ParamsAdapterImpl(params), version=version,
    dongle_id=(dongle.decode() if isinstance(dongle, bytes) else dongle),
    free_space_pct=lambda: round(get_available_percent(default=0.0), 1),
    keep_until_synced=lambda: params.get_bool(PARAM_KEEP_UNTIL_SYNCED),
    connectivity=build_connectivity, storage=status_writer.latest_storage,
  )
  server = make_server(ctx, port=port)
  cloudlog.info(f"bp_bridge listening on :{port}")

  def stop(*_):
    usage.save()
    server.stopping = True
    threading.Thread(target=server.shutdown, daemon=True).start()

  signal.signal(signal.SIGTERM, stop)
  signal.signal(signal.SIGINT, stop)
  server.serve_forever(poll_interval=0.5)


if __name__ == "__main__":
  main()
