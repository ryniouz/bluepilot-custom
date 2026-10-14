"""Metadata for the remotely editable settings, so a client can render them
like the on-device settings screens (groups, titles, types, ranges, choices).

Every key here must also be in params_allowlist.WRITABLE (checked by tests).
"""

ONOFF = "bool"


def _bool(key, title, desc=""):
  return {"key": key, "type": "bool", "title": title, "description": desc}


def _choice(key, title, options, desc=""):
  return {"key": key, "type": "choice", "title": title, "description": desc,
          "options": [{"value": v, "label": label} for v, label in options]}


def _number(key, title, kind, lo, hi, step, unit="", desc=""):
  return {"key": key, "type": kind, "title": title, "description": desc, "min": lo, "max": hi, "step": step, "unit": unit}


GROUPS = [
  {"id": "driving", "title": "Driving", "settings": [
    _choice("LongitudinalPersonality", "Driving personality", [(0, "Aggressive"), (1, "Standard"), (2, "Relaxed")],
            "Following distance and acceleration style."),
    _bool("ExperimentalMode", "Experimental mode", "End-to-end longitudinal control and the wide camera."),
    _bool("DynamicExperimentalControl", "Dynamic experimental control", "Switch between chill and experimental modes automatically."),
    _bool("SmartCruiseControlVision", "Slow for curves (vision)"),
    _bool("SmartCruiseControlMap", "Slow for curves (map)", "Needs offline maps on the device."),
    _bool("IsMetric", "Metric units"),
  ]},
  {"id": "speed_limit", "title": "Speed limit", "settings": [
    _choice("SpeedLimitMode", "Speed limit", [(0, "Off"), (1, "Information"), (2, "Warning"), (3, "Assist")]),
    _choice("SpeedLimitPolicy", "Speed limit source", [(0, "Car only"), (1, "Map only"), (2, "Car first"),
                                                      (3, "Map first"), (4, "Combined")]),
    _choice("SpeedLimitOffsetType", "Speed limit offset", [(0, "None"), (1, "Fixed"), (2, "Percent")]),
    _number("SpeedLimitValueOffset", "Offset amount", "int", -30, 30, 1, desc="km/h or mph when fixed, % when percent."),
  ]},
  # Custom: 7.0 lateral tuning, per scheme (Drive > BluePilot tuning > Lateral Tuning on the device)
  {"id": "lateral", "title": "Steering (BluePilot)", "settings": [
    _choice("FordPrefLateralControl", "Primary control variable", [(0, "Curvature"), (1, "Angle")],
            "Curvature is the original strategy. Angle steers with path_angle directly (BluePilot 7.0)."),
    _bool("disable_BP_lat_UI", "Disable BluePilot steering", "Use the stock curvature-only path."),
    _bool("BlinkerPauseLaneChange", "Pause steering with blinker under speed"),
    _number("BlinkerMinLateralControlSpeed", "Blinker pause below", "int", 5, 50, 1, desc="km/h or mph, as the units setting."),
  ]},
  {"id": "lateral_angle", "title": "Angle tuning", "settings": [
    _number("FordLowSpeedFactor_ang", "Low speed adjustment factor", "float", 0.5, 1.5, 0.01),
    _number("FordHighSpeedFactor_ang", "High speed adjustment factor", "float", 0.5, 1.5, 0.01),
    _number("FordHighSpeedDampening_ang", "High speed, low curve factor", "float", 0.25, 1.25, 0.01,
            desc="Reduce if it oversteers on the highway, increase if it understeers."),
    _number("lane_change_factor_high_ang", "Lane change factor (high speed)", "float", 0.85, 1.5, 0.05),
    _bool("enable_lane_positioning_ang", "Lane positioning"),
    _number("custom_path_offset_ang", "In-lane offset", "float", -0.5, 0.5, 0.01, "m"),
    _number("lane_centering_strength_ang", "Lane centering strength", "float", 0.0, 1.0, 0.05),
  ]},
  {"id": "lateral_curvature", "title": "Curvature tuning", "settings": [
    _bool("enable_human_turn_detection_curv", "Human turn detection", "Reset steering when you take a sharp turn yourself."),
    _number("lane_change_factor_high_curv", "Lane change factor (high speed)", "float", 0.5, 1.0, 0.05),
    _bool("enable_lane_positioning_curv", "Lane positioning"),
    _number("custom_path_offset_curv", "In-lane offset", "float", -0.5, 0.5, 0.05, "m"),
    _bool("enable_lane_full_mode_curv", "Lane-full mode"),
    _choice("custom_profile_curv", "Custom tuning profile", [(0, "Off"), (1, "On")],
            "Turns on the three values below."),
    _number("pc_blend_ratio_high_C_UI_curv", "Curvature blend ratio (high)", "float", 0.0, 1.0, 0.05),
    _number("pc_blend_ratio_low_C_UI_curv", "Curvature blend ratio (low)", "float", 0.0, 1.0, 0.05),
    _number("LC_PID_gain_UI_curv", "Centering PID gain", "float", 0.0, 50.0, 0.5),
  ]},
  {"id": "longitudinal", "title": "Speed control (BluePilot)", "settings": [
    _bool("disable_BP_long_UI", "Bypass BluePilot speed control", "Only applies with openpilot longitudinal."),
    _bool("disable_downhill_comp_UI", "Disable downhill compensation"),
  ]},
  {"id": "display", "title": "Driving screen", "settings": [
    _bool("ShowBlindspotOverlay", "Blindspot overlay"),
    _bool("ShowBrakeStatus", "Brake status", "Speed turns red while braking."),
    _bool("BPHideOnroadBorder", "Hide status border"),
    _bool("BPShowConfidenceBall", "Confidence ball"),
    _bool("BPAnimateSteeringWheel", "Animate steering wheel"),
    _bool("FordPrefShowRadarLeadOverlay", "Radar lead overlay (Ford ACC)"),
    _choice("FordPrefRadarOverlaySize", "Radar overlay size", [(0, "Small"), (1, "Medium"), (2, "Large")]),
    _bool("show_lead_speed", "Lead vehicle speed"),
    _bool("FordPrefHybridBatteryStatus", "Battery status"),
    _bool("FordPrefHybridPowerFlow", "Power flow"),
    _choice("FordPrefHybridDriveGaugeSize", "Gauge size", [(0, "Small"), (1, "Large")]),
    _choice("FordPrefGaugeStyle", "Gauge style", [(0, "Flat"), (1, "Arched")]),
    _bool("FordPrefHybridPowerFlowAlternate", "Alternate power flow"),
    _bool("BlindSpot", "Blindspot icons"),
    _bool("TorqueBar", "Steering arc"),
    _bool("RainbowMode", "Rainbow path"),
    _bool("StandstillTimer", "Standstill timer"),
    _bool("RoadNameToggle", "Road name"),
    _bool("GreenLightAlert", "Green light alert"),
    _bool("LeadDepartAlert", "Lead departing alert"),
    _bool("TrueVEgoUI", "Always show true speed"),
    _bool("HideVEgoUI", "Hide speed"),
    _bool("ShowTurnSignals", "Turn signals"),
    _bool("RocketFuel", "Acceleration bar"),
    _choice("ChevronInfo", "Metrics below lead", [(0, "Off"), (1, "Distance"), (2, "Speed"), (3, "Time"), (4, "All")]),
    _choice("DevUIInfo", "Developer readouts", [(0, "Off"), (1, "Bottom"), (2, "Right"), (3, "Right and bottom")]),
    _number("OnroadScreenOffBrightness", "Brightness while driving", "int", 0, 22, 1),
    _bool("send_hands_free_cluster_msg", "BlueCruise icon on dash"),
  ]},
  {"id": "device", "title": "Device", "settings": [
    _number("vbatt_pause_charging", "12 V battery limit", "float", 11.0, 14.0, 0.1, "V",
            "Pause the comma when the truck's 12 V battery drops below this."),
    _bool("BPKeepUntilSynced", "Keep drives until synced"),
  ]},
  {"id": "connectivity", "title": "Uploads and data", "settings": [
    _bool("BPRoadTripMode", "Citadel uploads (Road Trip Mode)",
          "Upload each finished minute of driving, and live data while driving, to Citadel."),
    _bool("BPRoadTripCellular", "Citadel uploads over LTE", "Off: Citadel uploads wait for Wi-Fi."),
    _choice("BPRoadTripVideo", "Road trip uploads", [(0, "Telemetry only"), (1, "Telemetry and low-res video")],
            "Telemetry is about 50 MB an hour; with low-res video about 250 MB an hour."),
    _number("BPCellLimitMB", "Monthly LTE limit", "int", 0, 200000, 100, "MB", "0 means no limit."),
    _choice("BPCellLimitAction", "When the limit is reached", [(0, "Telemetry only"), (1, "Stop uploading")]),
    _number("BPCellResetDay", "Billing month starts on day", "int", 1, 31, 1),
    _bool("BPRemoteLink", "Remote access from Citadel",
          "Lets Citadel change settings and show live data when the truck is away from home. A few KB a minute."),
    _bool("BPCommaConnectWifiOnly", "comma connect uploads on Wi-Fi only",
          "comma connect stays on; its uploads wait for unmetered Wi-Fi."),
  ]},
]


def all_settings() -> list[dict]:
  return [s for g in GROUPS for s in g["settings"]]


def validate_value(meta: dict, value):
  """Check a value against its metadata; return the normalized value or raise ValueError."""
  t = meta["type"]
  if t == "bool":
    if isinstance(value, bool):
      return value
    if isinstance(value, (int, str)) and str(value).lower() in ("0", "1", "true", "false"):
      return str(value).lower() in ("1", "true")
    raise ValueError(f"{meta['key']} expects true or false")
  if t == "choice":
    allowed = [o["value"] for o in meta["options"]]
    for a in allowed:
      if value == a or (isinstance(a, int) and not isinstance(value, bool) and str(value) == str(a)):
        return a
    raise ValueError(f"{meta['key']} must be one of {allowed}")
  if t in ("int", "float"):
    if isinstance(value, bool):
      raise ValueError(f"{meta['key']} expects a number")
    try:
      v = float(value)
    except (TypeError, ValueError):
      raise ValueError(f"{meta['key']} expects a number") from None
    if not meta["min"] <= v <= meta["max"]:
      raise ValueError(f"{meta['key']} must be between {meta['min']} and {meta['max']}")
    return int(round(v)) if t == "int" else v
  raise ValueError(f"unknown type {t}")


BY_KEY = {s["key"]: s for s in all_settings()}
