"""Constants and paths for the bridge. No openpilot imports, so it is testable off-device."""
import os

DEFAULT_PORT = 8090

# Param keys (declared in common/params_keys.h, Custom block)
PARAM_ENABLED = "BPBridgeEnabled"
PARAM_PORT = "BPBridgePort"
PARAM_TOKEN = "BPBridgeToken"
PARAM_NOTIFY_URL = "BPBridgeNotifyUrl"
PARAM_KEEP_UNTIL_SYNCED = "BPKeepUntilSynced"
PARAM_ROADTRIP = "BPRoadTripMode"
PARAM_ROADTRIP_VIDEO = "BPRoadTripVideo"
PARAM_SERVER_URL = "BPServerUrl"
PARAM_CELL_LIMIT_MB = "BPCellLimitMB"
PARAM_CELL_LIMIT_ACTION = "BPCellLimitAction"
PARAM_CELL_RESET_DAY = "BPCellResetDay"
PARAM_ROADTRIP_CELLULAR = "BPRoadTripCellular"
PARAM_COMMA_WIFI_ONLY = "BPCommaConnectWifiOnly"
PARAM_REMOTE_LINK = "BPRemoteLink"

STATE_DIR = os.environ.get("BP_BRIDGE_STATE_DIR", "/data/bluepilot/bridge")
EVENTS_FILE = "events.jsonl"
SYNCED_FILE = "synced.json"
USAGE_FILE = "usage.json"
MAX_EVENTS = 2000

# Files a client may download from a segment directory.
ALLOWED_FILES = frozenset({
  "rlog.zst", "qlog.zst", "rlog", "qlog",
  "qcamera.ts", "fcamera.hevc", "ecamera.hevc", "dcamera.hevc",
})

SYNC_LEVELS = ("logs", "full")

LIVE_HZ_MIN = 0.2
LIVE_HZ_MAX = 5.0
SSE_PING_S = 15.0


def state_path(name: str, state_dir: str | None = None) -> str:
  return os.path.join(state_dir or STATE_DIR, name)
