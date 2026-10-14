using Cxx = import "./include/c++.capnp";
$Cxx.namespace("cereal");

@0xb526ba661d550a59;

# custom.capnp: a home for empty structs reserved for custom forks
# These structs are guaranteed to remain reserved and empty in mainline
# cereal, so use these if you want custom events in your fork.

# DO rename the structs
# DON'T change the identifier (e.g. @0x81c2f05a394cf4af)

struct ModularAssistiveDrivingSystem {
  state @0 :ModularAssistiveDrivingSystemState;
  enabled @1 :Bool;
  active @2 :Bool;
  available @3 :Bool;

  enum ModularAssistiveDrivingSystemState {
    disabled @0;
    paused @1;
    enabled @2;
    softDisabling @3;
    overriding @4;
  }
}

struct IntelligentCruiseButtonManagement {
  state @0 :IntelligentCruiseButtonManagementState;
  sendButton @1 :SendButtonState;
  vTarget @2 :Float32;

  enum IntelligentCruiseButtonManagementState {
    inactive @0;      # No button press or default state
    preActive @1;     # Pre-active state before transitioning to increasing or decreasing
    increasing @2;    # Increasing speed
    decreasing @3;    # Decreasing speed
    holding @4;       # Holding steady speed
  }

  enum SendButtonState {
    none @0;
    increase @1;
    decrease @2;
  }
}

# Same struct as Log.RadarState.LeadData
struct LeadData {
  dRel @0 :Float32;
  yRel @1 :Float32;
  vRel @2 :Float32;
  aRel @3 :Float32;
  vLead @4 :Float32;
  dPath @6 :Float32;
  vLat @7 :Float32;
  vLeadK @8 :Float32;
  aLeadK @9 :Float32;
  fcw @10 :Bool;
  status @11 :Bool;
  aLeadTau @12 :Float32;
  modelProb @13 :Float32;
  radar @14 :Bool;
  radarTrackId @15 :Int32 = -1;

  aLeadDEPRECATED @5 :Float32;
}

struct SelfdriveStateSP @0x81c2f05a394cf4af {
  mads @0 :ModularAssistiveDrivingSystem;
  intelligentCruiseButtonManagement @1 :IntelligentCruiseButtonManagement;

  enum AudibleAlert {
    none @0;

    engage @1;
    disengage @2;
    refuse @3;

    warningSoft @4;
    warningImmediate @5;

    prompt @6;
    promptRepeat @7;
    promptDistracted @8;

    # unused, these are reserved for upstream events so we don't collide
    reserved9 @9;
    reserved10 @10;
    reserved11 @11;
    reserved12 @12;
    reserved13 @13;
    reserved14 @14;
    reserved15 @15;
    reserved16 @16;
    reserved17 @17;
    reserved18 @18;
    reserved19 @19;
    reserved20 @20;
    reserved21 @21;
    reserved22 @22;
    reserved23 @23;
    reserved24 @24;
    reserved25 @25;
    reserved26 @26;
    reserved27 @27;
    reserved28 @28;
    reserved29 @29;
    reserved30 @30;

    promptSingleLow @31;
    promptSingleHigh @32;
  }
}

struct ModelManagerSP @0xaedffd8f31e7b55d {
  activeBundle @0 :ModelBundle;
  selectedBundle @1 :ModelBundle;
  availableBundles @2 :List(ModelBundle);

  struct DownloadUri {
    uri @0 :Text;
    sha256 @1 :Text;
  }

  enum DownloadStatus {
    notDownloading @0;
    downloading @1;
    downloaded @2;
    cached @3;
    failed @4;
  }

  struct DownloadProgress {
    status @0 :DownloadStatus;
    progress @1 :Float32;
    eta @2 :UInt32;
  }

  struct Artifact {
    fileName @0 :Text;
    downloadUri @1 :DownloadUri;
    downloadProgress @2 :DownloadProgress;
  }

  struct Model {
    type @0 :Type;
    artifact @1 :Artifact;  # Main artifact
    metadata @2 :Artifact;  # Metadata artifact

    enum Type {
      supercombo @0;
      navigation @1;
      vision @2;
      policy @3;
      offPolicy @4;
    }
  }

  enum Runner {
    snpe @0;
    tinygrad @1;
    stock @2;
  }

  struct Override {
    key @0 :Text;
    value @1 :Text;
  }

  struct ModelBundle {
    index @0 :UInt32;
    internalName @1 :Text;
    displayName @2 :Text;
    models @3 :List(Model);
    status @4 :DownloadStatus;
    generation @5 :UInt32;
    environment @6 :Text;
    runner @7 :Runner;
    is20hz @8 :Bool;
    ref @9 :Text;
    minimumSelectorVersion @10 :UInt32;
    overrides @11 :List(Override);
  }
}

struct LongitudinalPlanSP @0xf35cc4560bbf6ec2 {
  dec @0 :DynamicExperimentalControl;
  longitudinalPlanSource @1 :LongitudinalPlanSource;
  smartCruiseControl @2 :SmartCruiseControl;
  speedLimit @3 :SpeedLimit;
  vTarget @4 :Float32;
  aTarget @5 :Float32;
  events @6 :List(OnroadEventSP.Event);
  e2eAlerts @7 :E2eAlerts;

  struct DynamicExperimentalControl {
    state @0 :DynamicExperimentalControlState;
    enabled @1 :Bool;
    active @2 :Bool;

    enum DynamicExperimentalControlState {
      acc @0;
      blended @1;
    }
  }

  struct SmartCruiseControl {
    vision @0 :Vision;
    map @1 :Map;

    struct Vision {
      state @0 :VisionState;
      vTarget @1 :Float32;
      aTarget @2 :Float32;
      currentLateralAccel @3 :Float32;
      maxPredictedLateralAccel @4 :Float32;
      enabled @5 :Bool;
      active @6 :Bool;
    }

    struct Map {
      state @0 :MapState;
      vTarget @1 :Float32;
      aTarget @2 :Float32;
      enabled @3 :Bool;
      active @4 :Bool;
    }

    enum VisionState {
      disabled @0; # System disabled or inactive.
      enabled @1; # No predicted substantial turn on vision range.
      entering @2; # A substantial turn is predicted ahead, adapting speed to turn comfort levels.
      turning @3; # Actively turning. Managing acceleration to provide a roll on turn feeling.
      leaving @4; # Road ahead straightens. Start to allow positive acceleration.
      overriding @5; # System overriding with manual control.
    }

    enum MapState {
      disabled @0; # System disabled or inactive.
      enabled @1; # No predicted substantial turn on map range.
      turning @2; # Actively turning. Managing acceleration to provide a roll on turn feeling.
      overriding @3; # System overriding with manual control.
    }
  }

  struct SpeedLimit {
    resolver @0 :Resolver;
    assist @1 :Assist;

    struct Resolver {
      speedLimit @0 :Float32;
      distToSpeedLimit @1 :Float32;
      source @2 :Source;
      speedLimitOffset @3 :Float32;
      speedLimitLast @4 :Float32;
      speedLimitFinal @5 :Float32;
      speedLimitFinalLast @6 :Float32;
      speedLimitValid @7 :Bool;
      speedLimitLastValid @8 :Bool;
    }

    struct Assist {
      state @0 :AssistState;
      enabled @1 :Bool;
      active @2 :Bool;
      vTarget @3 :Float32;
      aTarget @4 :Float32;
    }

    enum Source {
      none @0;
      car @1;
      map @2;
    }

    enum AssistState {
      disabled @0;
      inactive @1; # No speed limit set or not enabled by parameter.
      preActive @2;
      pending @3; # Awaiting new speed limit.
      adapting @4; # Reducing speed to match new speed limit.
      active @5; # Cruising at speed limit.
    }
  }

  enum LongitudinalPlanSource {
    cruise @0;
    sccVision @1;
    sccMap @2;
    speedLimitAssist @3;
  }

  struct E2eAlerts {
    greenLightAlert @0 :Bool;
    leadDepartAlert @1 :Bool;
  }
}

struct OnroadEventSP @0xda96579883444c35 {
  events @0 :List(Event);

  struct Event {
    name @0 :EventName;

    # event types
    enable @1 :Bool;
    noEntry @2 :Bool;
    warning @3 :Bool;   # alerts presented only when  enabled or soft disabling
    userDisable @4 :Bool;
    softDisable @5 :Bool;
    immediateDisable @6 :Bool;
    preEnable @7 :Bool;
    permanent @8 :Bool; # alerts presented regardless of openpilot state
    overrideLateral @10 :Bool;
    overrideLongitudinal @9 :Bool;
  }

  enum EventName {
    lkasEnable @0;
    lkasDisable @1;
    manualSteeringRequired @2;
    manualLongitudinalRequired @3;
    silentLkasEnable @4;
    silentLkasDisable @5;
    silentBrakeHold @6;
    silentWrongGear @7;
    silentReverseGear @8;
    silentDoorOpen @9;
    silentSeatbeltNotLatched @10;
    silentParkBrake @11;
    controlsMismatchLateral @12;
    hyundaiRadarTracksConfirmed @13;
    experimentalModeSwitched @14;
    wrongCarModeAlertOnly @15;
    pedalPressedAlertOnly @16;
    laneTurnLeft @17;
    laneTurnRight @18;
    speedLimitPreActive @19;
    speedLimitActive @20;
    speedLimitChanged @21;
    speedLimitPending @22;
    e2eChime @23;
  }
}

struct CarParamsSP @0x80ae746ee2596b11 {
  flags @0 :UInt32;        # flags for car specific quirks in sunnypilot
  safetyParam @1 : Int16;  # flags for sunnypilot's custom safety flags
  pcmCruiseSpeed @3 :Bool;
  intelligentCruiseButtonManagementAvailable @4 :Bool;
  enableGasInterceptor @5 :Bool;

  neuralNetworkLateralControl @2 :NeuralNetworkLateralControl;

  struct NeuralNetworkLateralControl {
    model @0 :Model;
    fuzzyFingerprint @1 :Bool;

    struct Model {
      path @0 :Text;
      name @1 :Text;
    }
  }
}

struct CarControlSP @0xa5cd762cd951a455 {
  mads @0 :ModularAssistiveDrivingSystem;
  params @1 :List(Param);
  leadOne @2 :LeadData;
  leadTwo @3 :LeadData;
  intelligentCruiseButtonManagement @4 :IntelligentCruiseButtonManagement;

  struct Param {
    key @0 :Text;
    type @2 :ParamType;
    value @3 :Data;

    valueDEPRECATED @1 :Text; # The data type change may cause issues with backwards compatibility.
  }

  enum ParamType {
    string @0;
    bool @1;
    int @2;
    float @3;
    time @4;
    json @5;
    bytes @6;
  }
}

struct BackupManagerSP @0xf98d843bfd7004a3 {
  backupStatus @0 :Status;
  restoreStatus @1 :Status;
  backupProgress @2 :Float32;
  restoreProgress @3 :Float32;
  lastError @4 :Text;
  currentBackup @5 :BackupInfo;
  backupHistory @6 :List(BackupInfo);

  enum Status {
    idle @0;
    inProgress @1;
    completed @2;
    failed @3;
  }

  struct Version {
    major @0 :UInt16;
    minor @1 :UInt16;
    patch @2 :UInt16;
    build @3 :UInt16;
    branch @4 :Text;
  }

  struct MetadataEntry {
    key @0 :Text;
    value @1 :Text;
    tags @2 :List(Text);
  }

  struct BackupInfo {
    deviceId @0 :Text;
    version @1 :UInt32;
    config @2 :Text;
    isEncrypted @3 :Bool;
    createdAt @4 :Text;  # ISO timestamp
    updatedAt @5 :Text;  # ISO timestamp
    sunnypilotVersion @6 :Version;
    backupMetadata @7 :List(MetadataEntry);
  }
}

struct CarStateSP @0xb86e6369214c01c8 {
  speedLimit @0 :Float32;
}

struct LiveMapDataSP @0xf416ec09499d9d19 {
  speedLimitValid @0 :Bool;
  speedLimit @1 :Float32;
  speedLimitAheadValid @2 :Bool;
  speedLimitAhead @3 :Float32;
  speedLimitAheadDistance @4 :Float32;
  roadName @5 :Text;
}

struct ModelDataV2SP @0xa1680744031fdb2d {
  laneTurnDirection @0 :TurnDirection;

  enum TurnDirection {
    none @0;
    turnLeft @1;
    turnRight @2;
  }
}

struct CustomReserved10 @0xcb9fd56c7057593a {
}

# Custom: offroad charging state, published by selfdrive/car/charging_monitor.py while offroad (stream B).
# Onroad, the same data is in carStateBP.charging.
struct ChargingStateBP @0xc2243c65e0340384 {
  charging @0 :CarStateBP.Charging;
  evBattery @1 :CarStateBP.EvBattery;
  canAlive @2 :Bool;           # frames seen on the car's main bus in the last 2 s
  keepAwake @3 :Bool;          # BPChargeKeepAwake and charging: power monitoring will not time out
  sleepInSeconds @4 :Float32;  # countdown after a charge ends (BPChargeSleepDelayMin), -1 when not counting
  lowVoltBattery @5 :CarStateBP.LowVoltBattery;  # 12 V battery: CAN first, then the OBD adapter
  lowVoltSource @6 :LowVoltSource;
  harnessVoltage @7 :Float32;  # 12 V at the comma's harness (peripheralState), 0 when unknown
  wake @8 :Wake;
  powerSaver @9 :Bool;         # BPLvSaver: 12 V power-saving mode is on
  shutdownReason @10 :Text;    # what will power the comma down next, for the UI ("" = nothing pending)

  enum LowVoltSource {
    none @0;
    can @1;
    obd @2;
  }

  # Why the truck's network is awake while the comma is offroad. A Lightning wakes on its own every so
  # often to top up the 12 V battery from the HV pack; that is not a drive.
  struct Wake {
    dataAvailable @0 :Bool;          # BodyInfo_3_FD1 (0x3B3) or HEV_Powertrain_Data6 (0x480) on the bus
    reason @1 :Reason;
    ignition @2 :Ignition;           # Ignition_Status (0x3B3)
    remoteStart @3 :Bool;            # Remote_Start_Status (0x3B3) non-zero
    dcdcOn @4 :Bool;                 # DcdcOn_B_Rq (0x480): HV-to-12 V converter requested
    lowVoltSupport @5 :Bool;         # ULoBattSpprtSustn_B_Rq (0x480): 12 V support (top-up) requested
    nextWakeMinutes @6 :Int32;       # WakeAlarm0_T_Rq (0x478), unverified meaning; -1 when unknown
    lowVoltTopUps @7 :UInt16;        # 12 V top-up wakes seen since the comma started

    enum Reason {
      unknown @0;          # CAN is up but nothing explains it
      asleep @1;           # no CAN
      ignitionOn @2;       # Run or Start: a drive
      charging @3;
      lowVoltTopUp @4;     # ignition off, 12 V support requested, not charging
      remoteStart @5;
      conditioning @6;     # battery or cabin conditioning without a charge
      accessory @7;
    }

    enum Ignition {
      unknown @0;
      off @1;
      accessory @2;
      run @3;
      start @4;
    }
  }
}

# Custom: OBD adapter link (ELM327 over Wi-Fi, USB or Bluetooth), separate from the panda and CAN
struct ObdStateBP @0x9ccdc8676701b412 {
  enabled @0 :Bool;                  # BPObdEnabled
  transport @1 :Transport;
  link @2 :Link;
  message @3 :Text;                  # one line for the UI: what is happening or what is wrong
  adapter @4 :Text;                  # adapter banner, e.g. "ELM327 v1.5"
  protocol @5 :Text;                 # ATDP answer
  bluetoothAvailable @6 :Bool;
  bluetoothMessage @7 :Text;         # why Bluetooth is unavailable, when it is
  usbDevices @8 :List(Text);         # /dev/ttyUSB*, /dev/ttyACM* seen right now
  requestsPerSecond @9 :Float32;
  lastResponseAgeS @10 :Float32;     # -1 before the first answer
  catalog @11 :Text;                 # which PID catalog is loaded
  values @12 :List(Value);
  polling @13 :Bool;                 # false while the truck is off and not charging (no 12 V drain)

  struct Value {
    name @0 :Text;
    shortName @1 :Text;
    value @2 :Float32;
    unit @3 :Text;                   # metric: degC, kPa, V, A, kWh, percent
    ageS @4 :Float32;
    header @5 :Text;
    request @6 :Text;
  }

  enum Transport {
    none @0;
    bluetooth @1;
    wifi @2;
    usb @3;
    simulated @4;
  }

  enum Link {
    off @0;           # BPObdEnabled is off
    unavailable @1;   # the chosen transport cannot work on this device (e.g. no Bluetooth in AGNOS)
    connecting @2;
    initializing @3;
    connected @4;     # adapter answers and the truck responds
    carAsleep @5;     # adapter answers, truck does not
    idle @6;          # connected earlier; paused while the truck is off and not charging
    error @7;
  }
}

struct ControllerStateBP @0xcd96dafb67a082d0 {
  lateralUncertainty @0 :Float32;  # BluePilot: lateral uncertainty for angleState (e.g. torque bar)
}

struct CarStateBP @0xb057204d7deadf3f {
  hybridDrive @0 :HybridDrive;
  hybridBattery @1 :HybridBattery;
  brakeLightStatus @2 :BrakeLightStatus;
  # Custom: Lightning EV data, vehicle mode and tune state (stream B). Append-only field numbers.
  evBattery @3 :EvBattery;
  tirePressure @4 :TirePressure;
  lowVoltBattery @5 :LowVoltBattery;
  ambient @6 :Ambient;
  vehicleMode @7 :VehicleMode;
  tune @8 :TuneState;
  evAlerts @9 :EvAlerts;
  charging @10 :Charging;

  # Traction battery and energy. Power sign convention: + = discharging (driving), - = charging/regen.
  struct EvBattery {
    dataAvailable @0 :Bool;
    socPercent @1 :Float32;          # displayed SOC, BattTracSoc2_Pc_Actl (0x24C)
    packVoltage @2 :Float32;         # V, BattTrac_U_Actl (0x07A)
    packCurrent @3 :Float32;         # A, + = discharge
    packCurrentSource @4 :CurrentSource;
    powerKw @5 :Float32;             # packVoltage * packCurrent / 1000
    regenKw @6 :Float32;             # max(0, -powerKw), for a regen meter
    packTempC @7 :Float32;           # BattTrac_Te_Actl (0x24C)
    coolantTempC @8 :Float32;        # BattTracClnt_Te_Actl (0x24B)
    packDeltaTempC @9 :Float32;      # BattTracDelta_Te_Actl (0x458)
    chargeLimitKw @10 :Float32;      # BattTrac2_Pw_LimChrg (0x24D)
    dischargeLimitKw @11 :Float32;   # BattTrac2_Pw_LimDchrg (0x24D)
    limitsAvailable @12 :Bool;
    rangeKm @13 :Float32;            # VehElRnge_L_Dsply (0x442), fallback VehElRngeNut_L_Dsply (0x352)
    rangeAvailable @14 :Bool;
    motorTorqueNm @15 :Float32;      # MtrTrac2_Tq_Actl (0x475)
    motorTorqueAvailable @16 :Bool;
    efficiencyWhPerKm @17 :Float32;  # smoothed live efficiency, 0 when stopped
    tripEnergyUsedKwh @18 :Float32;  # since this carState session started (ignition on)
    tripEnergyRegenKwh @19 :Float32;
    tripDistanceKm @20 :Float32;
    motorPowerKw @21 :Float32;       # MtrTrac2_U_Actl * MtrTrac2_I_Actl (0x441): one drive motor only, excludes HVAC/DC-DC
    motorPowerAvailable @22 :Bool;

    enum CurrentSource {
      none @0;
      battTracActl @1;    # BattTrac_I_Actl (0x07A), reads a constant -750 A on Lightning
      mtrTrac2Actl @2;    # MtrTrac2_I_Actl (0x441), last resort: one motor only
      battTracEstVsc @3;  # BattTrac_I_EstVsc (0x185), whole-pack estimate, preferred on Lightning
    }
  }

  struct TirePressure {
    dataAvailable @0 :Bool;
    frontLeftKpa @1 :Float32;
    frontRightKpa @2 :Float32;
    rearLeftKpa @3 :Float32;
    rearRightKpa @4 :Float32;
    lowThresholdKpa @5 :Float32;     # from BPTireLowPressureKpa
    lowPressure @6 :Bool;            # any tire below threshold
  }

  struct LowVoltBattery {
    dataAvailable @0 :Bool;
    voltage @1 :Float32;             # BattULoAux_U_Actl (0x42B), fallback pandaState voltage is up to the UI
    current @2 :Float32;             # A
    socPercent @3 :Float32;          # BattULoAuxSoc_Pc_Actl, fallback BSBattSOC (0x43C)
    tempC @4 :Float32;               # BattULo2_Te_Actl (0x43C)
    fault @5 :Bool;                  # BattULoAux_B_Falt
    low @6 :Bool;                    # voltage or SOC below alert threshold
  }

  struct Ambient {
    dataAvailable @0 :Bool;
    outsideTempC @1 :Float32;        # Outside_Air_Temp_Stat (0x41A), fallback AirAmb_Te_Actl (0x178), AirAmb_Te_ActlCld (0x308)
    rangeImpactPercent @2 :Float32;  # estimated range change from temperature (negative = less range)
  }

  struct VehicleMode {
    driveModeAvailable @0 :Bool;
    driveMode @1 :DriveMode;
    driveModeRaw @2 :UInt8;          # SelDrvMdePt_D_Rq (0x420)
    trailerAvailable @3 :Bool;
    trailerConnected @4 :Bool;       # TrlrLampCnnct_B_Actl (0x443) or TrlrBrkActCnnct_B_Actl (0x445), debounced
    onePedalActive @5 :Bool;
    onePedalSource @6 :OnePedalSource;

    enum DriveMode {
      unknown @0;
      normal @1;
      sport @2;
      tow @3;
      offroad @4;
      slippery @5;
      eco @6;
    }

    enum OnePedalSource {
      off @0;        # BPOnePedalMode = 0
      setting @1;    # BPOnePedalMode = 1 (driver says it is on)
      estimated @2;  # BPOnePedalMode = 2, inferred from coast-down deceleration
    }
  }

  struct TuneState {
    platformTuneActive @0 :Bool;     # Lightning tune selected by fingerprint and BPLightningTune
    profile @1 :Profile;
    accelMaxScale @2 :Float32;       # <= 1.0, applied under openpilot longitudinal only
    latAccelScale @3 :Float32;       # <= 1.0, scales the CAN FD lateral-accel cap

    enum Profile {
      stock @0;
      lightning @1;
      tow @2;
      sport @3;
      offroad @4;
      slippery @5;
    }
  }

  # Charging state for a charging screen. Only published while card runs (onroad / ignition on).
  struct Charging {
    dataAvailable @0 :Bool;          # a charge-status message is on the bus
    charging @1 :Bool;               # energy is flowing in (debounced 2 s)
    state @2 :State;
    stateRaw @3 :UInt8;              # ChrgStat_D2_Dsply (0x440), or ChrgStat_D_Dsply (0x312) when 0x440 is absent
    chargeType @4 :ChargeType;
    powerKw @5 :Float32;             # power into the pack, >= 0: -(pack V x pack current) while charging
    powerAvailable @6 :Bool;
    socPercent @7 :Float32;
    batteryTempC @8 :Float32;
    timeToFullHours @9 :Float32;     # ChargeNowDuration_St (0x352), unverified meaning
    timeToFullAvailable @10 :Bool;
    batteryConditioning @11 :Bool;   # PreCondBatt_B_Actl (0x478) or PreCondActv_B_Actl (0x185)
    coolantHeaterOn @12 :Bool;       # PtcHtr_D_Stat (0x478)
    thermalMode @13 :ThermalMode;    # inferred from heater, preconditioning, pump/flow and coolant vs pack temp
    coolantPumpOn @14 :Bool;         # BattTracClntPmp_D_Stat (0x458)
    coolantFlowPercent @15 :Float32; # BattTracClntFlw_Pc_Rq (0x185), requested flow
    coolantFlowAvailable @16 :Bool;

    enum State {
      unknown @0;
      notReady @1;
      chargingAc @2;
      chargingDc @3;
      chargingInductive @4;
      scheduled @5;
      evsePaused @6;
      evseNotDetected @7;
      evseNotCompatible @8;
      fault @9;
      targetReached @10;
      maintaining @11;
      cabinPreconditioning @12;
      driveConditioning @13;
      chargingUnknownType @14;       # 0x312 In_Progress without AC/DC detail
    }

    enum ChargeType {
      none @0;
      ac @1;
      dc @2;
      other @3;
    }

    enum ThermalMode {
      unknown @0;       # no thermal message on the bus
      off @1;
      cooling @2;       # coolant flowing and colder than the pack
      heating @3;       # coolant heater on, or coolant flowing and warmer than the pack
      conditioning @4;  # Ford reports battery preconditioning active
      circulating @5;   # coolant flowing, direction unclear (temps within 2 C)
    }
  }

  struct EvAlerts {
    lowSoc @0 :SocLevel;
    lowSocThresholdPercent @1 :Float32;
    criticalSocThresholdPercent @2 :Float32;
    tirePressureLow @3 :Bool;
    lowVoltBatteryLow @4 :Bool;
    alertText @5 :Text;              # short text for the highest-priority active alert, "" when none

    enum SocLevel {
      none @0;
      low @1;
      critical @2;
    }
  }
  # Custom: end

  struct HybridDrive {
    dataAvailable @0 :Bool;
    throttleDemandPercent @1 :Float32;
    throttleThresholdPercent @2 :Float32;
    powerFlowMode @3 :Text;
    powerFlowModeValue @5 :UInt8;  # Raw numeric value for PlotJuggler compatibility
    engineOnReason @4 :Text;
    engineOnReasonValue @6 :UInt8;  # Raw numeric value for PlotJuggler compatibility
  }

  struct HybridBattery {
    dataAvailable @0 :Bool;
    voltHighLimit @1 :Float32;
    voltLowLimit @2 :Float32;
    voltActual @3 :Float32;
    ampsActual @4 :Float32;
    socMinPerc @5 :Float32;
    socMaxPerc @6 :Float32;
    socActual @7 :Float32;
  }

  struct BrakeLightStatus {
    dataAvailable @0 :Bool;
    brakeLightsOn @1 :Bool;
  }
}

struct CustomReserved15 @0xbd443b539493bc68 {
}

struct CustomReserved16 @0xfc6241ed8877b611 {
}

struct CustomReserved17 @0xa30662f84033036c {
}

struct CustomReserved18 @0xc86a3d38d13eb3ef {
}

struct CustomReserved19 @0xa4f1eb3323f5f582 {
}
