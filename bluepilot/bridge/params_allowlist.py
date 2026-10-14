"""Params the export API may read and (offroad only) write.

Display, cruise and BluePilot tuning keys only. Never safety, calibration,
identity or credential keys.
"""

READ_ONLY = frozenset({
  "FordPrefHevDataAvailable", "FordPrefHevBattDataAvailable", "IsOnroad", "DongleId", "Version",
})

WRITABLE = frozenset({
  # BluePilot display
  "ShowBlindspotOverlay", "ShowBrakeStatus", "BPHideOnroadBorder", "BPShowConfidenceBall", "BPAnimateSteeringWheel",
  "FordPrefShowRadarLeadOverlay", "FordPrefRadarOverlaySize", "show_lead_speed", "FordPrefHybridBatteryStatus",
  "FordPrefHybridPowerFlow", "FordPrefHybridDriveGaugeSize", "FordPrefGaugeStyle", "FordPrefHybridPowerFlowAlternate",
  "send_hands_free_cluster_msg",
  # BluePilot lateral / longitudinal. Custom: 7.0 splits lateral tuning per scheme (*_curv / *_ang); the 6.0 names
  # still exist as params but nothing reads them after the one-time migration, so they are not writable here.
  "FordPrefLateralControl", "BlinkerPauseLaneChange", "BlinkerMinLateralControlSpeed", "disable_BP_lat_UI",
  "enable_human_turn_detection_curv", "lane_change_factor_high_curv", "enable_lane_positioning_curv",
  "custom_path_offset_curv", "enable_lane_full_mode_curv", "custom_profile_curv", "pc_blend_ratio_high_C_UI_curv",
  "pc_blend_ratio_low_C_UI_curv", "LC_PID_gain_UI_curv",
  "FordLowSpeedFactor_ang", "FordHighSpeedFactor_ang", "FordHighSpeedDampening_ang", "lane_change_factor_high_ang",
  "enable_lane_positioning_ang", "custom_path_offset_ang", "lane_centering_strength_ang",
  "disable_BP_long_UI", "disable_downhill_comp_UI", "vbatt_pause_charging",
  # sunnypilot visuals / cruise
  "BlindSpot", "TorqueBar", "RainbowMode", "StandstillTimer", "RoadNameToggle", "GreenLightAlert", "LeadDepartAlert",
  "TrueVEgoUI", "HideVEgoUI", "ShowTurnSignals", "RocketFuel", "ChevronInfo", "DevUIInfo",
  "SmartCruiseControlVision", "SmartCruiseControlMap", "DynamicExperimentalControl", "SpeedLimitMode",
  "SpeedLimitPolicy", "SpeedLimitOffsetType", "SpeedLimitValueOffset", "LongitudinalPersonality", "ExperimentalMode",
  "OnroadScreenOffBrightness", "IsMetric",
  # bridge
  "BPKeepUntilSynced", "BPBridgeNotifyUrl", "BPServerUrl",
  "BPRoadTripMode", "BPRoadTripVideo", "BPCellLimitMB", "BPCellLimitAction", "BPCellResetDay", "BPRoadTripCellular",
  "BPCommaConnectWifiOnly", "BPRemoteLink",
})

READABLE = READ_ONLY | WRITABLE


def coerce_param(value, current):
  if isinstance(current, bool):
    if isinstance(value, str):
      if value.strip().lower() not in ("0", "1", "true", "false"):
        raise ValueError("expected a boolean")
      return value.strip().lower() in ("1", "true")
    return bool(value)
  if isinstance(current, int):
    return int(float(value))
  if isinstance(current, float):
    return float(value)
  return str(value)
