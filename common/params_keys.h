#pragma once

#include <string>
#include <unordered_map>

#include "cereal/gen/cpp/log.capnp.h"

inline static std::unordered_map<std::string, ParamKeyAttributes> keys = {
    {"AccessToken", {CLEAR_ON_MANAGER_START | DONT_LOG, STRING}},
    {"AdbEnabled", {PERSISTENT | BACKUP, BOOL}},
    {"AlwaysOnDM", {PERSISTENT | BACKUP, BOOL}},
    {"ApiCache_Device", {PERSISTENT, STRING}},
    {"ApiCache_FirehoseStats", {PERSISTENT, JSON}},
    {"AssistNowToken", {PERSISTENT, STRING}},
    {"AthenadPid", {PERSISTENT, INT}},
    {"AthenadUploadQueue", {PERSISTENT, JSON}},
    {"AthenadRecentlyViewedRoutes", {PERSISTENT, STRING}},
    {"BootCount", {PERSISTENT, INT}},
    {"CalibrationParams", {PERSISTENT, BYTES}},
    {"CameraDebugExpGain", {CLEAR_ON_MANAGER_START, STRING}},
    {"CameraDebugExpTime", {CLEAR_ON_MANAGER_START, STRING}},
    {"CarBatteryCapacity", {PERSISTENT, INT}},
    {"CarParams", {CLEAR_ON_MANAGER_START | CLEAR_ON_ONROAD_TRANSITION, BYTES}},
    {"CarParamsCache", {CLEAR_ON_MANAGER_START, BYTES}},
    {"CarParamsPersistent", {PERSISTENT, BYTES}},
    {"CarParamsPrevRoute", {PERSISTENT, BYTES}},
    {"CompletedTrainingVersion", {PERSISTENT, STRING, "0"}},
    {"ControlsReady", {CLEAR_ON_MANAGER_START | CLEAR_ON_ONROAD_TRANSITION, BOOL}},
    {"CurrentBootlog", {PERSISTENT, STRING}},
    {"CurrentRoute", {CLEAR_ON_MANAGER_START | CLEAR_ON_ONROAD_TRANSITION, STRING}},
    {"DisableLogging", {CLEAR_ON_MANAGER_START | CLEAR_ON_ONROAD_TRANSITION, BOOL}},
    {"DisablePowerDown", {PERSISTENT | BACKUP, BOOL}},
    {"DisableUpdates", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"DisengageOnAccelerator", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"DongleId", {PERSISTENT, STRING}},
    {"DoReboot", {CLEAR_ON_MANAGER_START, BOOL}},
    {"DoShutdown", {CLEAR_ON_MANAGER_START, BOOL}},
    {"DoUninstall", {CLEAR_ON_MANAGER_START, BOOL}},
    {"DriverTooDistracted", {CLEAR_ON_MANAGER_START | CLEAR_ON_IGNITION_ON, BOOL}},
    {"AlphaLongitudinalEnabled", {PERSISTENT | DEVELOPMENT_ONLY | BACKUP, BOOL}},
    {"ExperimentalMode", {PERSISTENT | BACKUP, BOOL}},
    {"ExperimentalModeConfirmed", {PERSISTENT | BACKUP, BOOL}},
    {"FirmwareQueryDone", {CLEAR_ON_MANAGER_START | CLEAR_ON_ONROAD_TRANSITION, BOOL}},
    {"ForcePowerDown", {PERSISTENT, BOOL}},
    {"GitBranch", {PERSISTENT, STRING}},
    {"GitCommit", {PERSISTENT, STRING}},
    {"GitCommitDate", {PERSISTENT, STRING}},
    {"GitDiff", {PERSISTENT, STRING}},
    {"GithubSshKeys", {PERSISTENT | BACKUP, STRING}},
    {"GithubUsername", {PERSISTENT | BACKUP, STRING}},
    {"GitRemote", {PERSISTENT, STRING}},
    {"GsmApn", {PERSISTENT | BACKUP, STRING}},
    {"GsmMetered", {PERSISTENT | BACKUP, BOOL, "1"}},
    {"GsmRoaming", {PERSISTENT | BACKUP, BOOL}},
    {"HardwareSerial", {PERSISTENT, STRING}},
    {"HasAcceptedTerms", {PERSISTENT, STRING, "0"}},
    {"InstallDate", {PERSISTENT, TIME}},
    {"IsDriverViewEnabled", {CLEAR_ON_MANAGER_START, BOOL}},
    {"IsEngaged", {PERSISTENT, BOOL}},
    {"IsLdwEnabled", {PERSISTENT | BACKUP, BOOL}},
    {"IsMetric", {PERSISTENT | BACKUP, BOOL, "1"}},  // Custom: Canadian units (km, km/h) by default
    {"IsOffroad", {CLEAR_ON_MANAGER_START, BOOL}},
    {"IsOnroad", {PERSISTENT, BOOL}},
    {"IsRhdDetected", {PERSISTENT, BOOL}},
    {"IsReleaseBranch", {CLEAR_ON_MANAGER_START, BOOL}},
    {"IsTakingSnapshot", {CLEAR_ON_MANAGER_START, BOOL}},
    {"IsTestedBranch", {CLEAR_ON_MANAGER_START, BOOL}},
    {"JoystickDebugMode", {CLEAR_ON_MANAGER_START | CLEAR_ON_OFFROAD_TRANSITION, BOOL}},
    {"LanguageSetting", {PERSISTENT | BACKUP, STRING, "en"}},
    {"LastAthenaPingTime", {CLEAR_ON_MANAGER_START, INT}},
    {"LastGPSPosition", {PERSISTENT, STRING}},
    {"LastManagerExitReason", {CLEAR_ON_MANAGER_START, STRING}},
    {"LastOffroadStatusPacket", {CLEAR_ON_MANAGER_START | CLEAR_ON_OFFROAD_TRANSITION, JSON}},
    {"LastAgnosPowerMonitorShutdown", {CLEAR_ON_MANAGER_START, STRING}},
    {"LastPowerDropDetected", {CLEAR_ON_MANAGER_START, STRING}},
    {"LastUpdateException", {CLEAR_ON_MANAGER_START, STRING}},
    {"LastUpdateRouteCount", {PERSISTENT, INT, "0"}},
    {"LastUpdateTime", {PERSISTENT, TIME}},
    {"LastUpdateUptimeOnroad", {PERSISTENT, FLOAT, "0.0"}},
    {"LiveDelay", {PERSISTENT | BACKUP, BYTES}},
    {"LiveParameters", {PERSISTENT, JSON}},
    {"LiveParametersV2", {PERSISTENT, BYTES}},
    {"LivestreamEncoderBitrate", {CLEAR_ON_MANAGER_START | DONT_LOG, INT}},
    {"LiveTorqueParameters", {PERSISTENT | DONT_LOG, BYTES}},
    {"LocationFilterInitialState", {PERSISTENT, BYTES}},
    {"LateralManeuverMode", {CLEAR_ON_MANAGER_START | CLEAR_ON_OFFROAD_TRANSITION, BOOL}},
    {"LongitudinalManeuverMode", {CLEAR_ON_MANAGER_START | CLEAR_ON_OFFROAD_TRANSITION, BOOL}},
    {"LongitudinalPersonality", {PERSISTENT | BACKUP, INT, std::to_string(static_cast<int>(cereal::LongitudinalPersonality::STANDARD))}},
    {"NetworkMetered", {PERSISTENT | BACKUP, BOOL}},
    {"ObdMultiplexingChanged", {CLEAR_ON_MANAGER_START | CLEAR_ON_ONROAD_TRANSITION, BOOL}},
    {"ObdMultiplexingEnabled", {CLEAR_ON_MANAGER_START | CLEAR_ON_ONROAD_TRANSITION, BOOL}},
    {"Offroad_CarUnrecognized", {CLEAR_ON_MANAGER_START | CLEAR_ON_ONROAD_TRANSITION, JSON}},
    {"Offroad_ConnectivityNeeded", {CLEAR_ON_MANAGER_START, JSON}},
    {"Offroad_ConnectivityNeededPrompt", {CLEAR_ON_MANAGER_START, JSON}},
    {"Offroad_ExcessiveActuation", {PERSISTENT, JSON}},
    {"Offroad_IsTakingSnapshot", {CLEAR_ON_MANAGER_START, JSON}},
    {"Offroad_NeosUpdate", {CLEAR_ON_MANAGER_START, JSON}},
    {"Offroad_NoFirmware", {CLEAR_ON_MANAGER_START | CLEAR_ON_ONROAD_TRANSITION, JSON}},
    {"Offroad_Recalibration", {CLEAR_ON_MANAGER_START | CLEAR_ON_ONROAD_TRANSITION, JSON}},
    {"Offroad_TemperatureTooHigh", {CLEAR_ON_MANAGER_START, JSON}},
    {"Offroad_UnregisteredHardware", {CLEAR_ON_MANAGER_START, JSON}},
    {"Offroad_UpdateFailed", {CLEAR_ON_MANAGER_START, JSON}},
    {"Offroad_DriverMonitoringUncertain", {CLEAR_ON_MANAGER_START | CLEAR_ON_ONROAD_TRANSITION, JSON}},
    {"OnroadCycleRequested", {CLEAR_ON_MANAGER_START, BOOL}},
    {"OpenpilotEnabledToggle", {PERSISTENT | BACKUP, BOOL, "1"}},
    {"PandaHeartbeatLost", {CLEAR_ON_MANAGER_START | CLEAR_ON_OFFROAD_TRANSITION, BOOL}},
    {"PrimeType", {PERSISTENT, INT}},
    {"RecordAudio", {PERSISTENT | BACKUP, BOOL}},
    {"RecordAudioFeedback", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"RecordFront", {PERSISTENT | BACKUP, BOOL}},
    {"RecordFrontLock", {PERSISTENT, BOOL}},  // for the internal fleet
    {"SecOCKey", {PERSISTENT | DONT_LOG | BACKUP, STRING}},
    {"ShowDebugInfo", {PERSISTENT, BOOL}},
    {"RouteCount", {PERSISTENT, INT, "0"}},
    {"SnoozeUpdate", {CLEAR_ON_MANAGER_START | CLEAR_ON_OFFROAD_TRANSITION, BOOL}},
    {"SshEnabled", {PERSISTENT | BACKUP, BOOL}},
    {"TermsVersion", {PERSISTENT, STRING}},
    {"TorqueBar", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"TrainingVersion", {PERSISTENT, STRING}},
    {"UbloxAvailable", {PERSISTENT, BOOL}},
    {"UpdateAvailable", {CLEAR_ON_MANAGER_START | CLEAR_ON_ONROAD_TRANSITION, BOOL}},
    {"UpdateFailedCount", {CLEAR_ON_MANAGER_START, INT}},
    {"UpdaterAvailableBranches", {PERSISTENT, STRING}},
    {"UpdaterCurrentDescription", {CLEAR_ON_MANAGER_START, STRING}},
    {"UpdaterCurrentReleaseNotes", {CLEAR_ON_MANAGER_START, BYTES}},
    {"UpdaterFetchAvailable", {CLEAR_ON_MANAGER_START, BOOL}},
    {"UpdaterNewDescription", {CLEAR_ON_MANAGER_START, STRING}},
    {"UpdaterNewReleaseNotes", {CLEAR_ON_MANAGER_START, BYTES}},
    {"UpdaterState", {CLEAR_ON_MANAGER_START, STRING}},
    {"UpdaterTargetBranch", {CLEAR_ON_MANAGER_START, STRING}},
    {"UpdaterLastFetchTime", {PERSISTENT, TIME}},
    {"UptimeOffroad", {PERSISTENT, FLOAT, "0.0"}},
    {"UptimeOnroad", {PERSISTENT, FLOAT, "0.0"}},
    {"UsbGpuPresent", {CLEAR_ON_MANAGER_START | CLEAR_ON_OFFROAD_TRANSITION, BOOL}},
    {"UsbGpuCompiled", {CLEAR_ON_MANAGER_START | CLEAR_ON_OFFROAD_TRANSITION, BOOL}},
    {"Version", {PERSISTENT, STRING}},

    // --- sunnypilot params --- //
    {"ApiCache_DriveStats", {PERSISTENT, JSON}},
    {"AutoLaneChangeBsmDelay", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"AutoLaneChangeTimer", {PERSISTENT | BACKUP, INT, "0"}},
    {"BlinkerLateralReengageDelay", {PERSISTENT | BACKUP, INT, "0"}},  // seconds
    {"BlinkerMinLateralControlSpeed", {PERSISTENT | BACKUP, INT, "20"}},  // MPH or km/h
    {"BlinkerPauseLateralControl", {PERSISTENT | BACKUP, INT, "0"}},
    {"Brightness", {PERSISTENT | BACKUP, INT, "0"}},
    {"CarList", {PERSISTENT, JSON}},
    {"CarParamsSP", {CLEAR_ON_MANAGER_START | CLEAR_ON_ONROAD_TRANSITION, BYTES}},
    {"CarParamsSPCache", {CLEAR_ON_MANAGER_START, BYTES}},
    {"CarParamsSPPersistent", {PERSISTENT, BYTES}},
    {"CarPlatformBundle", {PERSISTENT | BACKUP, JSON}},
    {"ChevronInfo", {PERSISTENT | BACKUP, INT, "4"}},
    {"CompletedSunnylinkConsentVersion", {PERSISTENT, STRING, "0"}},
    {"CustomAccIncrementsEnabled", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"CustomAccLongPressIncrement", {PERSISTENT | BACKUP, INT, "5"}},
    {"CustomAccShortPressIncrement", {PERSISTENT | BACKUP, INT, "1"}},
    {"DeviceBootMode", {PERSISTENT | BACKUP, INT, "0"}},
    {"DevUIInfo", {PERSISTENT | BACKUP, INT, "0"}},
    {"EnableCopyparty", {PERSISTENT | BACKUP, BOOL}},
    {"EnableGithubRunner", {PERSISTENT | BACKUP, BOOL}},
    {"GreenLightAlert", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"GithubRunnerSufficientVoltage", {CLEAR_ON_MANAGER_START , BOOL}},
    {"HasAcceptedTermsSP", {PERSISTENT, STRING, "0"}},
    {"HideVEgoUI", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"IntelligentCruiseButtonManagement", {PERSISTENT | BACKUP , BOOL}},
    {"InteractivityTimeout", {PERSISTENT | BACKUP, INT, "0"}},
    {"IsDevelopmentBranch", {CLEAR_ON_MANAGER_START, BOOL}},
    {"IsReleaseSpBranch", {CLEAR_ON_MANAGER_START, BOOL}},
    {"LastGPSPositionLLK", {PERSISTENT, STRING}},
    {"LeadDepartAlert", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"MaxTimeOffroad", {PERSISTENT | BACKUP, INT, "1800"}},
    {"ModelRunnerTypeCache", {CLEAR_ON_ONROAD_TRANSITION, INT}},
    {"OffroadMode", {CLEAR_ON_MANAGER_START, BOOL}},
    {"Offroad_TiciSupport", {CLEAR_ON_MANAGER_START, JSON}},
    {"OnroadScreenOffBrightness", {PERSISTENT | BACKUP, INT, "0"}},
    {"OnroadScreenOffBrightnessMigrated", {PERSISTENT | BACKUP, STRING, "0.0"}},
    {"OnroadScreenOffTimer", {PERSISTENT | BACKUP, INT, "15"}},
    {"OnroadScreenOffTimerMigrated", {PERSISTENT | BACKUP, STRING, "0.0"}},
    {"OnroadUploads", {PERSISTENT | BACKUP, BOOL, "1"}},
    {"QuickBootToggle", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"QuietMode", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"RainbowMode", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"RocketFuel", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"ShowAdvancedControls", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"ShowTurnSignals", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"StandstillTimer", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"TrueVEgoUI", {PERSISTENT | BACKUP, BOOL, "0"}},

    // MADS params
    {"Mads", {PERSISTENT | BACKUP, BOOL, "1"}},
    {"MadsMainCruiseAllowed", {PERSISTENT | BACKUP, BOOL, "1"}},
    {"MadsSteeringMode", {PERSISTENT | BACKUP, INT, "0"}},
    {"MadsUnifiedEngagementMode", {PERSISTENT | BACKUP, BOOL, "1"}},

    // Model Manager params
    {"ModelManager_ActiveBundle", {PERSISTENT, JSON}},
    {"ModelManager_ClearCache", {CLEAR_ON_MANAGER_START, BOOL}},
    {"ModelManager_DownloadIndex", {CLEAR_ON_MANAGER_START | CLEAR_ON_ONROAD_TRANSITION, INT}},
    {"ModelManager_Favs", {PERSISTENT | BACKUP, STRING}},
    {"ModelManager_LastSyncTime", {CLEAR_ON_MANAGER_START | CLEAR_ON_OFFROAD_TRANSITION, INT, "0"}},
    {"ModelManager_ModelsCache", {PERSISTENT | BACKUP, JSON}},

    // Neural Network Lateral Control
    {"NeuralNetworkLateralControl", {PERSISTENT | BACKUP, BOOL, "0"}},

    // sunnylink params
    {"EnableSunnylinkUploader", {PERSISTENT | BACKUP, BOOL}},
    {"LastSunnylinkPingTime", {CLEAR_ON_MANAGER_START, INT}},
    {"ParamsVersion", {PERSISTENT, INT}},
    {"SunnylinkCache_Roles", {PERSISTENT, STRING}},
    {"SunnylinkCache_Users", {PERSISTENT, STRING}},
    {"SunnylinkDongleId", {PERSISTENT, STRING}},
    {"SunnylinkdPid", {PERSISTENT, INT}},
    {"SunnylinkEnabled", {PERSISTENT, BOOL, "1"}},
    {"SunnylinkTempFault", {CLEAR_ON_MANAGER_START | CLEAR_ON_OFFROAD_TRANSITION, BOOL, "0"}},

    // Backup Manager params
    {"BackupManager_CreateBackup", {PERSISTENT, BOOL}},
    {"BackupManager_RestoreVersion", {PERSISTENT, STRING}},

    // sunnypilot car specific params
    {"HyundaiLongitudinalTuning", {PERSISTENT | BACKUP, INT, "0"}},
    {"SubaruStopAndGo", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"SubaruStopAndGoManualParkingBrake", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"TeslaCoopSteering", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"ToyotaEnforceStockLongitudinal", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"ToyotaStopAndGoHack", {PERSISTENT | BACKUP, BOOL, "0"}},

    {"DynamicExperimentalControl", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"BlindSpot", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"ShowBlindspotOverlay", {PERSISTENT | BACKUP, BOOL, "1"}},

    // sunnypilot model params
    {"CameraOffset", {PERSISTENT | BACKUP, FLOAT, "0.0"}},
    {"LagdToggle", {PERSISTENT | BACKUP, BOOL, "1"}},
    {"LagdToggleDelay", {PERSISTENT | BACKUP, FLOAT, "0.2"}},
    {"LagdValueCache", {PERSISTENT, FLOAT, "0.2"}},
    {"LaneTurnDesire", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"LaneTurnValue", {PERSISTENT | BACKUP, FLOAT, "19.0"}},
    {"PlanplusControl", {PERSISTENT | BACKUP, FLOAT, "1.0"}},

    // mapd
    {"MapAdvisorySpeedLimit", {CLEAR_ON_ONROAD_TRANSITION, FLOAT}},
    {"MapdVersion", {PERSISTENT, STRING}},
    {"MapSpeedLimit", {CLEAR_ON_ONROAD_TRANSITION, FLOAT, "0.0"}},
    {"NextMapSpeedLimit", {CLEAR_ON_ONROAD_TRANSITION, JSON}},
    {"Offroad_OSMUpdateRequired", {CLEAR_ON_MANAGER_START, JSON}},
    {"OsmDbUpdatesCheck", {CLEAR_ON_MANAGER_START, BOOL}},  // mapd database update happens with device ON, reset on boot
    {"OSMDownloadBounds", {PERSISTENT, STRING}},
    {"OsmDownloadedDate", {PERSISTENT, STRING, "0.0"}},
    {"OSMDownloadLocations", {PERSISTENT, JSON}},
    {"OSMDownloadProgress", {CLEAR_ON_MANAGER_START, JSON}},
    {"OsmLocal", {PERSISTENT, BOOL}},
    {"OsmLocationName", {PERSISTENT, STRING}},
    {"OsmLocationTitle", {PERSISTENT, STRING}},
    {"OsmLocationUrl", {PERSISTENT, STRING}},
    {"OsmStateName", {PERSISTENT, STRING, "All"}},
    {"OsmStateTitle", {PERSISTENT, STRING}},
    {"OsmWayTest", {PERSISTENT, STRING}},
    {"RoadName", {CLEAR_ON_ONROAD_TRANSITION, STRING}},
    {"RoadNameToggle", {PERSISTENT | BACKUP, BOOL, "0"}},

    // Speed Limit
    {"SpeedLimitMode", {PERSISTENT | BACKUP, INT, "1"}},
    {"SpeedLimitOffsetType", {PERSISTENT | BACKUP, INT, "0"}},
    {"SpeedLimitPolicy", {PERSISTENT | BACKUP, INT, "3"}},
    {"SpeedLimitValueOffset", {PERSISTENT | BACKUP, INT, "0"}},

    // Smart Cruise Control
    {"MapTargetVelocities", {CLEAR_ON_ONROAD_TRANSITION, STRING}},
    {"SmartCruiseControlMap", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"SmartCruiseControlVision", {PERSISTENT | BACKUP, BOOL, "0"}},

    // Torque lateral control custom params
    {"CustomTorqueParams", {PERSISTENT | BACKUP , BOOL}},
    {"EnforceTorqueControl", {PERSISTENT | BACKUP, BOOL}},
    {"LiveTorqueParamsToggle", {PERSISTENT | BACKUP , BOOL}},
    {"LiveTorqueParamsRelaxedToggle", {PERSISTENT | BACKUP , BOOL}},
    {"TorqueControlTune", {PERSISTENT | BACKUP, FLOAT, "0.0"}},
    {"TorqueParamsOverrideEnabled", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"TorqueParamsOverrideFriction", {PERSISTENT | BACKUP, FLOAT, "0.1"}},
    {"TorqueParamsOverrideLatAccelFactor", {PERSISTENT | BACKUP, FLOAT, "2.5"}},

    // Blue Pilot
    {"send_hands_free_cluster_msg", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"enable_human_turn_detection", {PERSISTENT | BACKUP, BOOL, "1"}},
    {"lane_change_factor_high", {PERSISTENT | BACKUP, FLOAT, "0.85"}},
    {"pc_blend_ratio_high_C_UI", {PERSISTENT | BACKUP, FLOAT, "0.4"}},
    {"pc_blend_ratio_low_C_UI", {PERSISTENT | BACKUP, FLOAT, "0.4"}},
    {"enable_lane_positioning", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"custom_path_offset", {PERSISTENT | BACKUP, FLOAT,"0.0"}},
    {"enable_lane_full_mode", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"custom_profile", {PERSISTENT | BACKUP, INT, "0"}},
    {"LC_PID_gain_UI", {PERSISTENT | BACKUP, FLOAT, "3.0"}},
    {"FordPrefLateralControl", {PERSISTENT | BACKUP, INT, "0"}},
    {"FordAngleLowSpeedFactor", {PERSISTENT | BACKUP, FLOAT, "1.0"}},
    {"FordAngleHighSpeedFactor", {PERSISTENT | BACKUP, FLOAT, "1.0"}},

    // Blue Pilot: lateral-tuning params split by control scheme (curvature vs angle) -- see
    // sunnypilot/system/params_migration.py for the one-time migration from the params above.
    {"enable_human_turn_detection_curv", {PERSISTENT | BACKUP, BOOL, "1"}},
    {"lane_change_factor_high_curv", {PERSISTENT | BACKUP, FLOAT, "0.85"}},
    {"lane_change_factor_high_ang", {PERSISTENT | BACKUP, FLOAT, "1.0"}},
    {"pc_blend_ratio_high_C_UI_curv", {PERSISTENT | BACKUP, FLOAT, "0.4"}},
    {"pc_blend_ratio_low_C_UI_curv", {PERSISTENT | BACKUP, FLOAT, "0.4"}},
    {"enable_lane_positioning_curv", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"custom_path_offset_curv", {PERSISTENT | BACKUP, FLOAT, "0.0"}},
    {"enable_lane_full_mode_curv", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"custom_profile_curv", {PERSISTENT | BACKUP, INT, "0"}},
    {"LC_PID_gain_UI_curv", {PERSISTENT | BACKUP, FLOAT, "3.0"}},
    {"FordLowSpeedFactor_ang", {PERSISTENT | BACKUP, FLOAT, "1.0"}},
    {"FordHighSpeedFactor_ang", {PERSISTENT | BACKUP, FLOAT, "1.0"}},
    {"FordHighSpeedDampening_ang", {PERSISTENT | BACKUP, FLOAT, "1.0"}},
    {"BPLateralSchemeParamsMigratedV1", {PERSISTENT | BACKUP, STRING, "0"}},

    // BluePilot: angle-mode lane centering trim (advanced lane positioning) -- see
    // opendbc/sunnypilot/car/ford/lane_center_trim.py.
    {"enable_lane_positioning_ang", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"custom_path_offset_ang", {PERSISTENT | BACKUP, FLOAT, "0.0"}},
    {"lane_centering_strength_ang", {PERSISTENT | BACKUP, FLOAT, "0.25"}},

    {"disable_BP_lat_UI", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"disable_BP_long_UI", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"disable_downhill_comp_UI", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"disable_ford_radar_UI", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"vbatt_pause_charging", {PERSISTENT | BACKUP, FLOAT, "11.8"}},
    {"show_lead_speed", {PERSISTENT | BACKUP, BOOL, "1"}},
    {"FordPrefSteerAngleCurvature", {PERSISTENT | BACKUP, BOOL, "0"}},  // pinion-sourced curvature measurement (bad-yaw-sensor workaround); read at car init
    {"FordPrefShowRadarLeadOverlay", {PERSISTENT | BACKUP, BOOL, "1"}},
    {"FordPrefRadarOverlaySize", {PERSISTENT | BACKUP, INT, "1"}},
    {"FordPrefHybridBatteryStatus", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"FordPrefHybridPowerFlow", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"FordPrefHybridDriveGaugeSize", {PERSISTENT | BACKUP, INT, "1"}},
    {"FordPrefGaugeStyle", {PERSISTENT | BACKUP, INT, "0"}},  // hybrid/EV gauge style: 0=flat, 1=arched
    {"FordPrefHevDataAvailable", {CLEAR_ON_MANAGER_START, BOOL, "0"}},
    {"FordPrefHevBattDataAvailable", {CLEAR_ON_MANAGER_START, BOOL, "0"}},
    {"mici_complication", {PERSISTENT | BACKUP, INT, "0"}},
    {"ShowBrakeStatus", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"FordPrefHybridPowerFlowAlternate", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"mici_hide_onroad_fade", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"mici_hide_onroad_border", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"BPHideOnroadBorder", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"BPHideCameraView", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"BPRadRacerTheme", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"BPThemePack", {PERSISTENT | BACKUP, STRING, ""}},
    {"BPThemeAutoSeasonal", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"BPRainbowLines", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"BPShowConfidenceBall", {PERSISTENT | BACKUP, BOOL, "1"}},
    {"BPAutoSetSpeed", {PERSISTENT | BACKUP, BOOL, "0"}},  // Custom: Resume/Set uses the preferred speed for the detected limit
    {"BPAutoSetTable", {PERSISTENT | BACKUP, STRING, "{\"50\":65,\"60\":75,\"80\":90,\"90\":110,\"100\":120}"}},  // Custom: limit km/h -> set km/h
    {"BPRoadView", {PERSISTENT | BACKUP, INT, "8567"}},  // Custom: road view preset Standard (bits 13-15) + the old default switches
    {"BPAnimateSteeringWheel", {PERSISTENT | BACKUP, BOOL, "1"}},
    // BluePilot: No static defaults; the first active UI persists its matching device styles (C4=0, C3X=1).
    {"BPSteeringWheelIconStyle", {PERSISTENT | BACKUP, INT}},
    {"BPDMStylingChoice", {PERSISTENT | BACKUP, INT}},
    {"BPUseCustomSounds", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"BPCustSoundsSelection", {PERSISTENT | BACKUP, INT, "0"}},  // 0=Comma 4, 1=Comma 3x, 2=Tesla
    {"BpShowLateralControl", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"BPDisableLaneLineStatusColor", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"BPUIDebugLog", {PERSISTENT, BOOL, "0"}},
    {"BPSettingsMode", {PERSISTENT | BACKUP, INT, "0"}},
    {"Blindspot", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"BlinkerPauseLaneChange", {PERSISTENT | BACKUP, BOOL, "0"}},

    // Custom: Lightning control and CAN (stream B)
    {"BPLightningTune", {PERSISTENT | BACKUP, BOOL, "1"}},          // Lightning tune profile, selected by fingerprint
    {"BPTowProfile", {PERSISTENT | BACKUP, INT, "0"}},              // 0 auto (trailer or Tow/Haul), 1 off, 2 always on
    {"BPDriveModeTune", {PERSISTENT | BACKUP, BOOL, "1"}},          // follow the drive mode (sport, off-road, slippery)
    {"BPOnePedalMode", {PERSISTENT | BACKUP, INT, "2"}},            // 0 off, 1 on, 2 estimate from coast-down
    {"BPLowSocAlertPct", {PERSISTENT | BACKUP, INT, "20"}},
    {"BPCriticalSocAlertPct", {PERSISTENT | BACKUP, INT, "10"}},
    {"BPTireLowPressureKpa", {PERSISTENT | BACKUP, INT, "240"}},
    {"BPLowVoltAlertV", {PERSISTENT | BACKUP, FLOAT, "11.8"}},
    {"BPChargeKeepAwake", {PERSISTENT | BACKUP, BOOL, "1"}},        // stay on offroad while the truck charges
    {"BPChargeSleepDelayMin", {PERSISTENT | BACKUP, INT, "30"}},    // power down this long after an offroad charge ends; 0 = use MaxTimeOffroad
    {"BPChargingActive", {CLEAR_ON_MANAGER_START, BOOL, "0"}},      // written by charging_monitor
    {"BPChargeLastActiveTs", {CLEAR_ON_MANAGER_START, FLOAT}},      // time.monotonic() of the last charging sample
    {"BPGuestMode", {PERSISTENT, BOOL, "0"}},                        // factory driver assist: card goes passive (noOutput) at the next car start
    {"BPGuestModeOneTrip", {PERSISTENT | BACKUP, BOOL, "1"}},       // turn Guest Mode off again after one drive
    {"BPGuestModeActive", {CLEAR_ON_MANAGER_START | CLEAR_ON_OFFROAD_TRANSITION, BOOL, "0"}},  // this drive is running as Guest Mode (UI)
    {"BPGuestModeUsed", {PERSISTENT, BOOL, "0"}},                    // set by card on a guest drive; cleared at the next offroad start
    {"BPLockedPlatform", {PERSISTENT | BACKUP, STRING, "FORD_F_150_LIGHTNING_MK1"}},  // only control this platform; anything else stays passive. Empty = any car
    {"BPPlatformMismatch", {CLEAR_ON_MANAGER_START, STRING}},       // fingerprint of a car the lock refused (for the UI)
    {"BPObdEnabled", {PERSISTENT | BACKUP, BOOL, "0"}},             // OBD adapter link on/off (read-only PID polling)
    {"BPObdTransport", {PERSISTENT | BACKUP, STRING, "wifi"}},      // wifi, usb, bluetooth or simulated
    {"BPObdAddress", {PERSISTENT | BACKUP, STRING, ""}},            // wifi host[:port], usb /dev path, bluetooth MAC[#channel]
    {"BPObdPollWhenOff", {PERSISTENT | BACKUP, BOOL, "0"}},         // also poll while the truck is off and not charging (keeps modules awake)
    {"BPLvSaver", {PERSISTENT | BACKUP, BOOL, "0"}},                // 12 V power saving: short offroad time, higher 12 V cutoffs
    {"BPLvSaverOffroadMin", {PERSISTENT | BACKUP, INT, "10"}},      // power-saving offroad time, minutes
    {"BPLvShutdownSoc", {PERSISTENT | BACKUP, INT, "0"}},           // power down offroad below this 12 V SOC (%); 0 = off
    {"BPLvWakeFilter", {PERSISTENT | BACKUP, BOOL, "1"}},           // a Lightning 12 V top-up wake is not a drive
    {"BPLvState", {CLEAR_ON_MANAGER_START, JSON}},                   // written by charging_monitor: 12 V SOC/voltage, top-up wake, timestamps
    // Custom: end

    // BluePilot: Portal (Web Routes Server)
    {"EnableWebRoutesServer", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"BPPortalPort", {PERSISTENT | BACKUP, INT, "8088"}},

    // BluePilot: connect backend — 0=Comma Connect, 1=Konik Stable, 2=Offline Mode.
    // Per-backend dongle ID caches let comma <-> Konik switch without losing either identity;
    // see bluepilot/backend_switch.py. BPUseKonik is legacy (bool toggle); migrated once to
    // BPConnectBackend=1 then cleared.
    {"BPConnectBackend", {PERSISTENT | BACKUP, INT, "0"}},
    {"BPUseKonik", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"BPActiveBackend", {PERSISTENT, STRING}},
    {"BPDongleIdComma", {PERSISTENT, STRING}},
    {"BPDongleIdKonik", {PERSISTENT, STRING}},

    // BluePilot: UI params
    {"BPLastSeenVersion", {PERSISTENT, STRING}},

    // Custom: Console UI params (stream A, Comma Console UI)
    {"BPConsoleAccent", {PERSISTENT | BACKUP, STRING, "blue"}},
    {"BPConsoleMode", {PERSISTENT | BACKUP, STRING, "auto"}},  // auto, day, night
    {"BPLayoutPreset", {PERSISTENT | BACKUP, INT, "1"}},
    {"BPConsoleScale", {PERSISTENT | BACKUP, INT, "1"}},  // UI size: 0 small, 1 standard, 2 large
    {"BPAutoHomeWifi", {PERSISTENT | BACKUP, BOOL, "1"}},  // join a saved home network when parked at home
    {"BPAutoHotspotHome", {PERSISTENT | BACKUP, BOOL, "1"}},  // turn the hotspot off at home
    {"BPAutoHotspotAway", {PERSISTENT | BACKUP, BOOL, "0"}},  // turn the hotspot on when driving away from home
    {"BPEvHud", {PERSISTENT | BACKUP, BOOL, "1"}},
    {"BPEvHudTireAlert", {PERSISTENT | BACKUP, BOOL, "1"}},
    {"BPChargingScreen", {PERSISTENT | BACKUP, BOOL, "1"}},
    {"BPChargeSleepMin", {PERSISTENT | BACKUP, INT, "30"}},  // display off after this many minutes of ignition-off charging, 0 = never
    {"BPChargeOffDcMin", {PERSISTENT | BACKUP, INT, "60"}},  // same, DC fast charging with the truck off
    {"BPChargeOnAcMin", {PERSISTENT | BACKUP, INT, "0"}},    // charging screen at full brightness this long with someone inside, AC; 0 = always
    {"BPChargeOnDcMin", {PERSISTENT | BACKUP, INT, "0"}},    // same, DC fast charging
    {"BPChargeOnThen", {PERSISTENT | BACKUP, INT, "0"}},     // after that with the truck on: 0 dim, 1 display off
    {"BPChargeOffThen", {PERSISTENT | BACKUP, INT, "1"}},    // after that with the truck off: 0 dim, 1 display off
    {"BPChargeMinimal", {PERSISTENT | BACKUP, BOOL, "1"}},   // truck off: the minimal dark charging screen
    {"BPLastEvSnapshot", {PERSISTENT, JSON}},
    {"BPCanadianUnitsSet", {PERSISTENT, BOOL, "0"}},  // one-time switch of IsMetric to km for this build
    {"BPUpdateRepo", {PERSISTENT | BACKUP, STRING, "https://github.com/ryniouz/bluepilot-custom.git"}},  // updated.py fetches from here
    {"BPUpdateBranch", {PERSISTENT | BACKUP, STRING}},  // pinned update branch; empty = UpdaterTargetBranch / current
    {"BPLteUsage", {PERSISTENT, STRING}},  // JSON: this month's LTE bytes
    {"BPHomeWifi", {PERSISTENT | BACKUP, STRING}},  // JSON list of home Wi-Fi SSIDs
    {"BPLastLocation", {PERSISTENT, STRING}},  // JSON lat/lon of the last good GPS fix
    {"BPHomeLocation", {PERSISTENT | BACKUP, STRING}},  // JSON lat/lon of home
    {"BPObdDongle", {PERSISTENT | BACKUP, STRING}},  // JSON mac/name of the chosen Bluetooth OBD dongle
    {"BPPhoneLink", {PERSISTENT | BACKUP, STRING}},  // JSON mac/name of the phone picked for the planned Bluetooth link
    // Custom: end

    // WiFi Management
    {"WifiFavoriteSSID", {PERSISTENT | BACKUP, STRING}},

    // Custom: data export bridge (bluepilot/bridge)
    {"BPBridgeEnabled", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"BPBridgePort", {PERSISTENT | BACKUP, INT, "8090"}},
    {"BPBridgeToken", {PERSISTENT, STRING}},
    {"BPBridgeNotifyUrl", {PERSISTENT | BACKUP, STRING}},
    {"BPKeepUntilSynced", {PERSISTENT | BACKUP, BOOL, "1"}},
    {"BPRoadTripMode", {PERSISTENT | BACKUP, BOOL, "0"}},
    {"BPRoadTripVideo", {PERSISTENT | BACKUP, INT, "1"}},
    {"BPServerUrl", {PERSISTENT | BACKUP, STRING}},
    {"BPCellLimitMB", {PERSISTENT | BACKUP, INT, "0"}},
    {"BPCellLimitAction", {PERSISTENT | BACKUP, INT, "0"}},
    {"BPCellResetDay", {PERSISTENT | BACKUP, INT, "1"}},
    {"BPRoadTripCellular", {PERSISTENT | BACKUP, BOOL, "1"}},
    {"BPCommaConnectWifiOnly", {PERSISTENT | BACKUP, BOOL, "1"}},
    {"BPRemoteLink", {PERSISTENT | BACKUP, BOOL, "1"}},             // Citadel can reach the bridge API from away
    // End Custom
};
