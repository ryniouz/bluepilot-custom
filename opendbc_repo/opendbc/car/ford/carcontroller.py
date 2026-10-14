import math
import numpy as np
from opendbc.can import CANPacker
from opendbc.car import ACCELERATION_DUE_TO_GRAVITY, Bus, DT_CTRL, apply_hysteresis, structs
from opendbc.car.lateral import AVERAGE_ROAD_ROLL, ISO_LATERAL_ACCEL, apply_std_steer_angle_limits
from opendbc.car.ford import fordcan
from opendbc.car.ford.values import CarControllerParams, FordFlags, CAR
from opendbc.car.interfaces import CarControllerBase, V_CRUISE_MAX
from openpilot.common.params import Params

# BluePilot: extension imports for lateral, longitudinal, and HUD control
from opendbc.sunnypilot.car.ford.lateral_curv_ext import LateralCurvExt, PrimaryLateralControl
from opendbc.sunnypilot.car.ford.lateral_angle_ext import LateralAngleExt
from opendbc.sunnypilot.car.ford.longitudinal_ext import LongitudinalExt
from opendbc.sunnypilot.car.ford.hud_ext import HudExt
from opendbc.sunnypilot.car.ford import fordcan_ext
from opendbc.sunnypilot.car.ford.icbm import IntelligentCruiseButtonManagementInterface
# Custom: Lightning tune, tow and drive-mode profiles
from opendbc.sunnypilot.car.ford.lightning import STOCK_TUNE, TuneBlender, TuneSettings, select_profile
# Custom: end

LongCtrlState = structs.CarControl.Actuators.LongControlState
VisualAlert = structs.CarControl.HUDControl.VisualAlert

# CAN FD limits:
# Limit to average banked road since safety doesn't have the roll, higher actual roll lowers lateral acceleration
MAX_LATERAL_ACCEL = ISO_LATERAL_ACCEL - (ACCELERATION_DUE_TO_GRAVITY * AVERAGE_ROAD_ROLL)  # ~2.4 m/s^2


def anti_overshoot(apply_curvature, apply_curvature_last, v_ego):
  diff = 0.1
  tau = 5  # 5s smooths over the overshoot
  dt = DT_CTRL * CarControllerParams.STEER_STEP
  alpha = 1 - np.exp(-dt / tau)

  lataccel = apply_curvature * (v_ego ** 2)
  last_lataccel = apply_curvature_last * (v_ego ** 2)
  last_lataccel = apply_hysteresis(lataccel, last_lataccel, diff)
  last_lataccel = alpha * lataccel + (1 - alpha) * last_lataccel

  output_curvature = last_lataccel / (max(v_ego, 1) ** 2)

  return float(np.interp(v_ego, [5, 10], [apply_curvature, output_curvature]))

<<<<<<< ours

def apply_ford_curvature_limits(apply_curvature, apply_curvature_last, current_curvature, v_ego_raw, steering_angle, lat_active, CP):
=======
def apply_ford_curvature_limits(apply_curvature, apply_curvature_last, current_curvature, v_ego_raw, steering_angle, lat_active, CP,
                                lat_accel_scale=1.0):  # Custom: lat_accel_scale (<= 1, profile)
  max_curvature = 1 # large initial value
>>>>>>> theirs
  # No blending at low speed due to lack of torque wind-up and inaccurate current curvature
  if v_ego_raw > 9:
    apply_curvature = np.clip(apply_curvature, current_curvature - CarControllerParams.CURVATURE_ERROR,
                              current_curvature + CarControllerParams.CURVATURE_ERROR)

  # Curvature rate limit after driver torque limit
  apply_curvature = apply_std_steer_angle_limits(apply_curvature, apply_curvature_last, v_ego_raw, steering_angle, lat_active, CarControllerParams.ANGLE_LIMITS)

  # Ford Q4/CAN FD has more torque available compared to Q3/CAN so we limit it based on lateral acceleration.
  # Safety is not aware of the road roll so we subtract a conservative amount at all times
  if CP.flags & FordFlags.CANFD:
    # Limit curvature to conservative max lateral acceleration
    # Custom: profiles may only lower the cap
    curvature_accel_limit = MAX_LATERAL_ACCEL * min(lat_accel_scale, 1.0) / (max(v_ego_raw, 1) ** 2)
    apply_curvature = float(np.clip(apply_curvature, -curvature_accel_limit, curvature_accel_limit))

  return apply_curvature


def apply_creep_compensation(accel: float, v_ego: float, creep_max: float = 0.6) -> float:  # Custom: creep_max
  creep_accel = np.interp(v_ego, [1., 3.], [creep_max, 0.])
  creep_accel = np.interp(accel, [0., 0.2], [creep_accel, 0.])
  accel -= creep_accel
  return float(accel)


# BluePilot: CarController inherits from LateralCurvExt, LateralAngleExt, LongitudinalExt, HudExt,
# and ICBM for 4-signal lateral control (curvature- or angle-primary), follow-aware longitudinal,
# and enhanced HUD messaging.
# Init order: CarControllerBase first (sets self.CP, self.frame), then ext classes.
class CarController(CarControllerBase, LateralCurvExt, LateralAngleExt, LongitudinalExt, HudExt,
                    IntelligentCruiseButtonManagementInterface):
  def __init__(self, dbc_names, CP, CP_SP):
    CarControllerBase.__init__(self, dbc_names, CP, CP_SP)
    # BluePilot: initialize extension classes
    LateralCurvExt.__init__(self, CP, CP_SP)
    LateralAngleExt.__init__(self, CP, CP_SP)
    LongitudinalExt.__init__(self, CP, CP_SP)
    HudExt.__init__(self, CP, CP_SP)
    # ICBM: base class sets state used at runtime, init for robustness
    # IntelligentCruiseButtonManagementInterface.__init__(self, CP, CP_SP)

    self.params = Params()
    self.packer = CANPacker(dbc_names[Bus.pt])
    self.CAN = fordcan.CanBus(CP)

    self.apply_curvature_last = 0
    self.anti_overshoot_curvature_last = 0
    self.disable_BP_lat_UI = False
    self.accel = 0.0
    self.gas = 0.0
<<<<<<< ours
    self.last_button_frame = 0  # BluePilot: ICBM button press tracking
    # Note: main_on_last, lkas_enabled_last, steer_alert_last, lead_distance_bars_last,
    # distance_bar_frame are initialized by HudExt.__init__() above
=======
    self.accel_pred = -5.0  # AccPrpl_A_Pred: safe inactive until we send; avoids cruise fault on crank
    self.main_on_last = False
    self.lkas_enabled_last = False
    self.steer_alert_last = False
    self.fcw_alert_last = False  # previous status of collision alert
    self.send_ui_last = False  # previous state of ui elements
    self.send_bars_ts_last = 0  # previous state of ui elements
    self.send_bars_last = False  # previous state of ACC Gap elements
    self.lead_distance_bars_last = None
    self.distance_bar_frame = 0
    self.last_button_frame = 0  # Track last ICBM button press frame
    self.lateralUncertainty = 0.0

    self.target_speed_multiplier = 1.0

    ################################## lateral control parameters ##############################################

    # Toggles
    self.enable_human_turn_detection = True
    self.enable_lane_positioning = True

    # Variables to initialize (these get updated every scan as part of the control code)
    self.precision_type = 1  # precise or comfort
    self.human_turn = False  # have we detected a human override in a turn
    self.post_reset_ramp_active = False  # track if we're ramping after a steering reset
    self.reset_steering_last = False  # track previous reset_steering state
    self.enable_lane_positioning = False # Updated from UI: enable Advanced Lane Positioning
    self.custom_profile = 0 # updated from UI
    self.pc_blend_ratio = 0.5
    self.disable_BP_lat_UI = False   # updated from UI: disable BP lateral control
    self.disable_BP_long_UI = False  # updated from UI: bypass BP longitudinal (use stock logic)
    self.anti_overshoot_curvature_last = 0.0 # initialize anti_overshoot_curvature_last
    self._bp_long_active_last = False  # True if we sent BP long values last frame (for clean transition off BP long)
    self.bp_gas_last = 0.0
    self.bp_accel_last = 0.0
    self.bpSpeedAllow = False # initialize to false

    # Long Control Variables
    self.MAX_URBAN_SPEED_MPH = 45.0
    self.following_accel_ROC = 0.002  # max accel change per scan when in following mode
    self.brake_actuate_target = -0.14 # at what accel value do we engage brakes
    self.brake_actuate_release = -0.06 # at what accel value do we release brakes
    self.precharge_actuate_target = -0.12 # at what accel value do we engage precharge
    self.precharge_actuate_release = -0.06 # at what accel value do we release precharge
    self.op_brake_actuate_last = False # init the value for our hysteresis
    self.disable_downhill_comp_UI = True #flag to disable downhill pitch compensation

    # # Curvature variables
    self.curvature_lookup_time = 0.42 # from lagd (how far into the future we pull curvature)
    self.lane_change_factor_bp = [4.4, 40.23] # what speeds to adjust lane_change_factor
    self.lane_change_factor_low = 0.95 # lane_change_factor at 4.4 m/s
    self.lane_change_factor_high = 0.85 # updated from UI: lane_change_factor at 40.23 m/s
    self.pc_blend_ratio_low = 0.40 # Default %-Predicted Curvature on straights
    self.pc_blend_ratio_high = 0.40 # Default %-Predicted Curvature in curves
    self.pc_blend_ratio_low_C = 0.40   # used in pc_blend_ratio_v (from UI when custom_profile == 1)
    self.pc_blend_ratio_high_C = 0.40 # used in pc_blend_ratio_v (from UI when custom_profile == 1)
    self.pc_blend_ratio_bp = [0.0, 0.001] # curvature breakpoints in 1/m

    # Curvature rate variables
    self.curvature_rate_delta_t = 0.3  # [s] used in denominator for curvature rate calculation
    self.curvature_rate_deque = deque(maxlen=int(round(self.curvature_rate_delta_t / 0.05)))  # 0.3 seconds at 20Hz
    self.curvature_rate_speed_bp = [0.0, 14.5, 15.5]  # speed breakpoints in m/s
    self.curvature_rate_speed_v = [1.0, 1.0, 0.0]  # corresponding k_p values
    self.curvature_rate_PC_bp = [0.0, 0.008,0.01] # curvature breakpoints in 1/m
    self.curvature_rate_PC_v = [0.0, 0.0, 1.0] # corresponding k_p values
    self.large_curve_factor_low = 1.0 # factor to reduce curvature for small curves
    self.large_curve_factor_high = 0.80 # factor to reduce curvature for large curves
    self.large_curve_factor_bp = [0.001, 0.02] # curvature breakpoints in 1/m
    self.large_curve_factor_v = [self.large_curve_factor_low, self.large_curve_factor_high]



    # path offset variables
    self.custom_path_offset = 0.0 # updated from UI: applies a custom offset to help with in-lane positioning
    self.path_offset_lookup_time = 0.2 # in seconds (from bp-2.1)
    self.min_laneline_confidence_bp = [0.6, 0.8]
    self.enable_lanefull_mode = True

    #path angle shared variables
    self.path_angle_filter_samples = 3 # number of samples to use for the moving average filter
    self.path_angle_deque = deque(maxlen=self.path_angle_filter_samples) # deque to hold the samples

    # path angle low curvature variables
    self.LC_PID_gain_UI = 0.0  # gain for UI tuning (from params)
    self.LC_PID_gain = 3.0  # effective gain (LC_PID_GAIN or from UI when custom_profile == 1)
    self.LC_PID_k_p = 0.25
    self.LC_PID_k_i = 0.05
    self.LC_PID_controller = PIDController(k_p=self.LC_PID_k_p, k_i=self.LC_PID_k_i, rate=20)
    self.LC_PID_speed_bp = [0.0, 9.0, 15.0]  # speed breakpoints in m/s
    self.LC_PID_speed_v = [0.0, 0.0, 1.0]  # corresponding k_p values
    self.LC_path_angle_ROC_bp = [5, 15, 25]  # speed breakpoints in m/s
    self.LC_path_angle_ROC_v = [0.003, 0.0015, 0.002]  # match panda limits
    self.LC_path_angle_reset_counter = 0
    self.LC_path_angle_reset_duration = 1.5 # in seconds

    # max absolute values for all four signals
    self.path_angle_max = 0.5  # from dbc files
    self.path_offset_max = 2.0  # too much path offset causes issues
    self.curvature_max = 0.02  # 0.02 is max from dbc files
    self.curvature_rate_max = 0.001023  # from dbc files

    # values from previous frame
    self.curvature_rate_last = 0.0
    self.path_offset_last = 0.0
    self.path_angle_last = 0.0
    self.curvature_rate = 0  # initialize curvature_rate

    # Logging variables
    #debug(f'Car Fingerprint (CarController): {CP.carFingerprint}', True)

    # Lane change transition tracking
    self.post_lane_change_timer = 0
    self.post_lane_change_active = False
    self.lane_change = False  # True when model indicates lane change active
    self.lane_change_last = False  # Track previous lane change state
    self.pre_lane_change_values = {
        'path_angle': 0.0,
        'path_offset': 0.0,
        'desired_curvature_rate': 0.0
    }

    # Maximum allowed changes per frame
    self.max_path_angle_change = 0.00125
    self.max_path_offset_change = 0.00125
    self.max_curvature_rate_change = 0.0001

    self.sm = messaging.SubMaster(['modelV2', 'liveParameters', 'selfdriveState', 'radarState'])
    self.VM = VehicleModel(self.CP)
    self.curvature_lookup_time = 0.2

    self.model = None
    self.lp = None
    self.ss = None
    self.send_driver_monitor_can_msg = False
    self.send_lane_depart_can_msg = False
    self.tja_msg = 0
    self.tja_warn = 0
    self.hands = 0
    self._update_params()

    # Custom: Lightning tune profile, selected by fingerprint; tow/drive-mode profiles blend in over 3 s
    self.tune_settings = TuneSettings()
    self.tune_blender = TuneBlender()
    self.tune = STOCK_TUNE
    self._update_tune_params()
    # Custom: end

  # Custom: tune settings are read once a second
  def _update_tune_params(self):
    try:
      self.tune_settings = TuneSettings(
        lightning_tune=bool(self.params.get("BPLightningTune", return_default=True)),
        tow_profile=int(self.params.get("BPTowProfile", return_default=True)),
        drive_mode_tune=bool(self.params.get("BPDriveModeTune", return_default=True)),
      )
    except (TypeError, ValueError):
      self.tune_settings = TuneSettings()

  def _update_tune(self, CS):
    if self.frame % 100 == 0:
      self._update_tune_params()
    profile = select_profile(self.CP.carFingerprint, self.tune_settings,
                             getattr(CS, "bp_drive_mode", "unknown"), getattr(CS, "bp_trailer_connected", False))
    self.tune = self.tune_blender.update(profile, DT_CTRL)
    t = self.tune
    self.following_accel_ROC = t.following_accel_roc
    self.brake_actuate_target = t.brake_actuate_target
    self.brake_actuate_release = t.brake_actuate_release
    self.precharge_actuate_target = t.precharge_actuate_target
    self.precharge_actuate_release = t.precharge_actuate_release
    CS.bp_tune_state = (profile != "stock", profile, float(t.accel_max_scale), float(t.lat_accel_scale))
  # Custom: end

  def _update_params(self):
    self.send_hands_free_cluster_msg = self.params.get_bool("send_hands_free_cluster_msg")
    # Block hands-free UI on CAN vehicles - only CAN-FD supports the cluster message
    if not (self.CP.flags & FordFlags.CANFD):
      self.send_hands_free_cluster_msg = False
    self.enable_human_turn_detection = self.params.get_bool("enable_human_turn_detection")
    # updated from UI: lane_change_factor at 40.23 m/s
    self.lane_change_factor_high = float(self.params.get("lane_change_factor_high", return_default=True))
    self.pc_blend_ratio_high_C_UI = float(self.params.get("pc_blend_ratio_high_C_UI", return_default=True))
    self.pc_blend_ratio_low_C_UI = float(self.params.get("pc_blend_ratio_low_C_UI", return_default=True))
    self.enable_lane_positioning = self.params.get_bool("enable_lane_positioning")
    # updated from UI: applies a custom offset to help with in-lane positioning
    self.custom_path_offset = float(self.params.get("custom_path_offset", return_default=True))
    self.enable_lanefull_mode = self.params.get_bool("enable_lane_full_mode")
    self.custom_profile = int(self.params.get("custom_profile", return_default=True))
    self.LC_PID_gain_UI = float(self.params.get("LC_PID_gain_UI", return_default=True))
    # Ford long: bypass BP longitudinal toggle (gas/accel ROC use __init__ defaults only)
    self.disable_BP_long_UI = self.params.get_bool("disable_BP_long_UI")
    self.disable_downhill_comp_UI = self.params.get_bool("disable_downhill_comp_UI")

  def handle_post_lane_change_transition(self, path_angle, path_offset, desired_curvature_rate):
    """
    Manages smooth transition of control variables after lane change
    Returns: Tuple of (path_angle, path_offset, desired_curvature_rate)
    """
    # Detect lane change completion (transition from True to False)
    if self.lane_change_last and not self.lane_change:
        self.post_lane_change_active = True
        self.post_lane_change_timer = 0
        # Store current values as starting point
        self.pre_lane_change_values = {
            'path_angle': 0.0,  # Start from zero since we're coming out of lane change
            'path_offset': 0.0,
            'desired_curvature_rate': 0.0
        }

    # Update previous lane change state
    self.lane_change_last = self.lane_change

    # If we're in post-lane change state
    if self.post_lane_change_active:
        self.post_lane_change_timer += 1

        # Apply smooth transition using rate limiting
        new_path_angle = clip(
            path_angle,
            self.pre_lane_change_values['path_angle'] - self.max_path_angle_change,
            self.pre_lane_change_values['path_angle'] + self.max_path_angle_change
        )

        new_path_offset = clip(
            path_offset,
            self.pre_lane_change_values['path_offset'] - self.max_path_offset_change,
            self.pre_lane_change_values['path_offset'] + self.max_path_offset_change
        )

        new_curvature_rate = clip(
            desired_curvature_rate,
            self.pre_lane_change_values['desired_curvature_rate'] - self.max_curvature_rate_change,
            self.pre_lane_change_values['desired_curvature_rate'] + self.max_curvature_rate_change
        )

        # Update stored values
        self.pre_lane_change_values = {
            'path_angle': new_path_angle,
            'path_offset': new_path_offset,
            'desired_curvature_rate': new_curvature_rate
        }

        # Exit transition state after 40 frames
        if self.post_lane_change_timer >= 160:
            self.post_lane_change_active = False

        return (new_path_angle, new_path_offset, new_curvature_rate)

    return (path_angle, path_offset, desired_curvature_rate)

  def calculate_lateral_uncertainty(self, requested_curvature, apply_curvature, max_curvature):
    max_curvature = np.clip(max_curvature, apply_curvature, self.curvature_max)  # ensure max_curvature is within reasonable bounds
    return float(requested_curvature / max_curvature)
>>>>>>> theirs

  def update(self, CC, CC_SP, CS, now_nanos):
    can_sends = []

    # BluePilot: update SubMaster (modelV2, liveParameters, selfdriveState, radarState) and vehicle model
    LateralCurvExt.update_sm(self)

<<<<<<< ours
    # BluePilot: read runtime params from UI
    LateralCurvExt.update_lateral_params(self, self.params)
    LateralAngleExt.update_angle_params(self, self.params)
    self.disable_BP_lat_UI = self.params.get_bool("disable_BP_lat_UI")
    LongitudinalExt.update_long_params(self, self.params)
    HudExt.update_hud_params(self, self.params, self.CP)
=======
    if self.lp is not None:
      x = max(self.lp.stiffnessFactor, 0.1)
      sr = max(self.lp.steerRatio, 0.1)
      self.VM.update_params(x, sr)

    self._update_params()
    self._update_tune(CS)  # Custom
>>>>>>> theirs

    actuators = CC.actuators
    hud_control = CC.hudControl
    main_on = CS.out.cruiseState.available
    steer_alert = hud_control.visualAlert in (VisualAlert.steerRequired, VisualAlert.ldw)
    fcw_alert = hud_control.visualAlert == VisualAlert.fcw

    # BluePilot: compute DM state (TJA message, warning, hands level)
    HudExt.update_dm(self, hud_control, main_on, CS.out.cruiseState.standstill, self.frame)

    ### acc buttons ###
    if CC.cruiseControl.cancel:
      can_sends.append(fordcan.create_button_msg(self.packer, self.CAN.camera, CS.buttons_stock_values, cancel=True))
      can_sends.append(fordcan.create_button_msg(self.packer, self.CAN.main, CS.buttons_stock_values, cancel=True))
    elif CC.cruiseControl.resume and (self.frame % CarControllerParams.BUTTONS_STEP) == 0:
      can_sends.append(fordcan.create_button_msg(self.packer, self.CAN.camera, CS.buttons_stock_values, resume=True))
      can_sends.append(fordcan.create_button_msg(self.packer, self.CAN.main, CS.buttons_stock_values, resume=True))
    # if stock lane centering isn't off, send a button press to toggle it off
    # the stock system checks for steering pressed, and eventually disengages cruise control
    elif CS.acc_tja_status_stock_values["Tja_D_Stat"] != 0 and (self.frame % CarControllerParams.ACC_UI_STEP) == 0:
      can_sends.append(fordcan.create_button_msg(self.packer, self.CAN.camera, CS.buttons_stock_values, tja_toggle=True))

    # BluePilot: Intelligent Cruise Button Management (ICBM)
    icbm_can_sends, self.last_button_frame = IntelligentCruiseButtonManagementInterface.update(
      self, CC_SP, CS, self.packer, self.CAN, self.frame, self.last_button_frame
    )
    can_sends.extend(icbm_can_sends)

    ### lateral control ###
    # BluePilot: keep stock lateral path in carcontroller, and run BP 4-signal lateral
    # only when bypass is disabled.
    if (self.frame % CarControllerParams.STEER_STEP) == 0:
<<<<<<< ours
      current_curvature = -CS.out.yawRate / max(CS.out.vEgoRaw, 0.1)
      # BluePilot: bypass flag is owned by stock carcontroller path.
      bypass_bp_lat = self.disable_BP_lat_UI
      if bypass_bp_lat:
        # Stock curvature-only path only. Anti-overshoot is not used when BP lateral is active (disable_BP_lat_UI off).
        if self.CP.carFingerprint in (CAR.FORD_BRONCO_SPORT_MK1, CAR.FORD_F_150_MK14):
          self.anti_overshoot_curvature_last = anti_overshoot(actuators.curvature, self.anti_overshoot_curvature_last, CS.out.vEgoRaw)
          apply_curvature = self.anti_overshoot_curvature_last
=======
      # Custom: no BP lateral until the first modelV2 arrives (it reads model meta, lanes and orientation)
      if CC.latActive and self.model is not None:
        self.precision_type = 1
        steeringPressed = CS.out.steeringPressed
        steeringAngleDeg_PV = CS.out.steeringAngleDeg

        # determine tuning profile
        if self.custom_profile == 1: # custom tuning profile
          self.pc_blend_ratio_low_C =  self.pc_blend_ratio_low_C_UI
          self.pc_blend_ratio_high_C =  self.pc_blend_ratio_high_C_UI
          self.LC_PID_gain = self.LC_PID_gain_UI
        else:
          self.pc_blend_ratio_low_C = self.pc_blend_ratio_low_C
          self.pc_blend_ratio_high_C = self.pc_blend_ratio_high_C
          self.LC_PID_gain = self.LC_PID_gain

        self.pc_blend_ratio_v = [self.pc_blend_ratio_low_C, self.pc_blend_ratio_high_C] # %-Predicted Curvature

        # calculate current curvature and model desired curvature
        current_curvature = -CS.out.yawRate / max(CS.out.vEgoRaw, 0.1)  # use canbus data to calculate current_curvature
        desired_curvature = actuators.curvature  # get desired curvature from model

        # extract predicted curvature from modelV2
        if self.model is not None and len(self.model.orientation.x) >= 17:
          # compute curvature from model predicted orientationRate, and blend with desired curvature based on max predicted curvature magnitude
          curvatures = np.array(self.model.orientationRate.z) / max(0.01, CS.out.vEgoRaw)
          predicted_curvature = interp(self.curvature_lookup_time, ModelConstants.T_IDXS, curvatures)
        else:
          predicted_curvature = 0.0

        # calculate blend ratio
        self.pc_blend_ratio = interp(abs(desired_curvature), self.pc_blend_ratio_bp, self.pc_blend_ratio_v)

        # equate requested_curvature to a blend of desired and predicted_curvature and apply curvature limits
        requested_curvature = (predicted_curvature * self.pc_blend_ratio) + (desired_curvature * (1 - self.pc_blend_ratio))

        # determine if a lane change is active
        if (self.model.meta.laneChangeState == 1 or self.model.meta.laneChangeState == 2 or self.model.meta.laneChangeState == 3):
            self.lane_change = True
        else:
            self.lane_change = False

        # determine lane_change_factor based on speed
        lane_change_factor = interp(CS.out.vEgoRaw, self.lane_change_factor_bp, [self.lane_change_factor_low, self.lane_change_factor_high])
        lane_change_factor *= min(self.tune.lane_change_factor_scale, 1.0)  # Custom: profile

        # if changing lanes, modify curvature to smooth out the lane change
        if self.lane_change and (self.model.meta.laneChangeDirection == 1): # if we are changing lanes to the left
          if requested_curvature < 0: # and the curvature is taking us to the left
              requested_curvature = requested_curvature * lane_change_factor # reduce the curvature to smooth out the lane change
          else:
              requested_curvature = requested_curvature # if we are moving back right to correct for over travel, do not reduce curvature

          self.precision_type = 0 # use comfort mode

        if self.lane_change and (self.model.meta.laneChangeDirection == 2): # if we are changing lanes to the right
          if requested_curvature > 0: # and the curvature is taking us to the right
              requested_curvature = requested_curvature * lane_change_factor # reduce the curvature to smooth out the lane change
          else:
              requested_curvature = requested_curvature # if we are moving back left to correct for over travel, do not reduce curvature

          self.precision_type = 0 # use comfort mode

        # Determine if a human is making a turn and trap the value
        # if a human turn is active, reset steering to prevent windup
        if steeringPressed and abs(steeringAngleDeg_PV) > 45:
          self.human_turn = True
        else:
          self.human_turn = False

        # Determine when to reset steering
        if ((self.human_turn) and self.enable_human_turn_detection) or (CS.out.vEgoRaw < 0.1):
          reset_steering = 1
        else:
          reset_steering = 0

        #if reset_steering is 1, set requested_curvature to 0
        if reset_steering == 1:
          requested_curvature = 0.0

        # apply curvature limits
        apply_curvature, max_curvature = apply_ford_curvature_limits(requested_curvature,
                                                                self.apply_curvature_last,
                                                                current_curvature,
                                                                CS.out.vEgoRaw,
                                                                0,
                                                                CC.latActive,
                                                                self.CP,
                                                                self.tune.lat_accel_scale)  # Custom

        # lateral uncertianty is needed for the torque bar on curvature vehicles.
        lateralUncertainty = self.calculate_lateral_uncertainty(requested_curvature, apply_curvature, max_curvature)

        #if reset_steering is 1, set apply_curvature to 0
        if reset_steering == 1:
          apply_curvature = 0.0
          self.post_reset_ramp_active = False  # Cancel any active ramp when resetting
>>>>>>> theirs
        else:
          apply_curvature = actuators.curvature

        self.apply_curvature_last = apply_ford_curvature_limits(
          apply_curvature, self.apply_curvature_last, current_curvature,
          CS.out.vEgoRaw, 0., CC.latActive, self.CP)
        if self.CP.flags & FordFlags.CANFD:
          mode = 1 if CC.latActive else 0
          counter = (self.frame // CarControllerParams.STEER_STEP) % 0x10
          can_sends.append(fordcan.create_lat_ctl2_msg(self.packer, self.CAN, mode, 0., 0., -self.apply_curvature_last, 0., counter))
        else:
<<<<<<< ours
          can_sends.append(fordcan.create_lat_ctl_msg(self.packer, self.CAN, CC.latActive, 0., 0., -self.apply_curvature_last, 0.))
      else:
        # BluePilot: select the BP lateral strategy by primary control variable.
        #   1 (angle)     -> LateralAngleExt: κ → path_angle (c1), apply_curvature held at 0.
        #   0 (curvature) -> LateralCurvExt: full 4-signal curvature-primary (default).
        # Both return a LateralResult packed identically below.
        # Do not run apply_ford_curvature_limits here or overwrite apply_curvature_last before the
        # strategy runs. Panda rate-checks desired_curvature vs the last TX on the bus; that must match
        # the prior frame's lat.apply_curvature only (not an intermediate stock-limited value).
        if self.primary_lateral_control == PrimaryLateralControl.angle:
          lat = LateralAngleExt.update_angle_strategy(self, CC, CS, actuators, self.CP)
        else:
          lat = LateralCurvExt.update(self, CC, CS, actuators, self.apply_curvature_last, self.CP)
        self.apply_curvature_last = lat.apply_curvature
        self.lateralUncertainty = lat.lateralUncertainty
        # BluePilot: rate-limit diagnostics for controllerStateBP. update_angle_strategy sets these on
        # self (angle mode); curvature mode leaves them False (the path_angle ROC / sim aren't run there).
        _angle_mode = self.primary_lateral_control == PrimaryLateralControl.angle
        self.angleRateLimited = getattr(self, 'bp_angle_rate_limited', False) if _angle_mode else False
        self.curvatureRateLimited = getattr(self, 'bp_curvature_rate_limited', False) if _angle_mode else False
        # BluePilot: current-curvature deviation-clip diagnostic. Set by whichever strategy just ran
        # (both lateral_curv_ext.update and lateral_angle_ext.update_angle_strategy set this), so it's
        # meaningful in both modes -- not gated by _angle_mode like the two above.
        self.curvatureDeviationLimited = getattr(self, 'bp_curvature_deviation_limited', False)
        self.humanTurnLateralPaused = self.angle_human_turn_active if _angle_mode else False
        self.stallBlipActive = self.angle_stall_blip_active if _angle_mode else False

        # BluePilot: angle-mode human-turn override -- send lateral inactive (mode 0) while the
        # driver manually turns, so the PSCM releases cleanly instead of stalling 2-3 s on
        # re-engage (observed on Mach-E). Panda-clean: every ford.h check has a legitimate
        # !steer_control_enabled branch for the zeroed frames; on release, path_angle ramps back
        # from 0 through the soft ROC (no reset-bypass latch involvement). Curvature mode keeps
        # its own reset_steering path (zeroed signals with mode still active) in LateralCurvExt.
        # The stall blip (lateral_angle_ext.py) rides the same mode-0 path: a short pulse that
        # resets the PSCM's post-override attenuation when the deviation clip deadlocks hands-free.
        lat_active = CC.latActive and not (_angle_mode and (self.angle_human_turn_active or self.angle_stall_blip_active))
        if self.CP.flags & FordFlags.CANFD:
          mode = 1 if lat_active else 0
          counter = (self.frame // CarControllerParams.STEER_STEP) % 0x10
          can_sends.append(fordcan_ext.create_lat_ctl2_msg(
            self.packer, self.CAN, mode, lat.ramp_type, lat.precision_type,
            -lat.path_offset, -lat.path_angle, -lat.apply_curvature, -lat.curvature_rate, counter
          ))
=======
          desired_curvature_rate = 0.0

        # calculate curvature rate PC factor
        curvature_rate_PC_factor = interp(abs(predicted_curvature), self.curvature_rate_PC_bp, self.curvature_rate_PC_v)
        desired_curvature_rate = desired_curvature_rate * curvature_rate_PC_factor

        # calcualte curvature rate speed factor
        curvature_rate_speed_factor = interp(CS.out.vEgoRaw, self.curvature_rate_speed_bp, self.curvature_rate_speed_v)
        desired_curvature_rate = desired_curvature_rate * curvature_rate_speed_factor

        # determine large curve factor
        large_curve_factor = interp(abs(requested_curvature), self.large_curve_factor_bp, self.large_curve_factor_v)

        # apply large curve factor to desired_curvature_rate
        desired_curvature_rate = desired_curvature_rate * large_curve_factor

        #no large curve factor in lane changes
        if self.lane_change:
          large_curve_factor = 1.0

        # if we are in a lane change, set the desired_curvature_rate to 0
        if self.lane_change:
          desired_curvature_rate = 0.0

        # get path offset from model.position.y
        path_offset_position = interp(self.path_offset_lookup_time, ModelConstants.T_IDXS, self.model.position.y)

        # now get path offset from lanelines
        path_offset_lanelines = (self.model.laneLines[1].y[0] + self.model.laneLines[2].y[0]) / 2

        # determinie laneline width tolerance scaling factor (this is to prevent the vehicle from jumping when two lanes start to merge or diverge)
        laneline_width = self.model.laneLines[2].y[0] + (-self.model.laneLines[1].y[0]) # laneLines[1] is a negative value because it is left of the vehicle.
        laneline_width_tolerance = interp(laneline_width, [3.75,4.25], [0.81, 0.59]) # 3.7 is the width of standard US lane in meters

        # determine laneline confidence
        laneline_confidence = min(self.model.laneLineProbs[1], self.model.laneLineProbs[2], laneline_width_tolerance)
        if not self.enable_lanefull_mode: # if lanefull mode is off, a 0 confidence will make the lane lines ignored.
          laneline_confidence = 0.0

        # determine laneline path offset scale
        laneline_path_offset_scale = interp(laneline_confidence, self.min_laneline_confidence_bp, [0.0, 1.0]) # this interp basically sets how much influence the lane lines have.

        # get the total path_offset combining model and lanelines by blending them based on confidence level.
        path_offset = (path_offset_position * (1-laneline_path_offset_scale) + (path_offset_lanelines * laneline_path_offset_scale)) + self.custom_path_offset

        # no path_offset during lane changes (it will fight you until it swaps to new lane if you don't set to zero)
        if self.lane_change:
          path_offset = 0

        # Use the UI variable for adjustable Gain because the PID gain is set to a fixed number, UI variable divided by 100 to make UI variable an easier to adjust number
        path_offset_error = (path_offset * (self.LC_PID_gain_UI/100))

        # Begin path_angle logic.  In this situation, path_angle is being used to drive our offset to zero.
        # determine speed factor (less PID action needed at higher speeds)
        LC_PID_speed_factor = interp(CS.out.vEgoRaw, self.LC_PID_speed_bp, self.LC_PID_speed_v)

        # apply speed factor to path_offset_error
        path_offset_error_adj = path_offset_error * LC_PID_speed_factor

        # if not using lane positioning, zero out path_offset_error_adj
        if not self.enable_lane_positioning:
          path_offset_error_adj = 0.0

        # Use path_angle to help with centering vehicle in lane, Use PID controller to calculate path_angle
        path_angle_low_c = self.LC_PID_controller.update(path_offset_error_adj)

        # if not using lane positioning, zero out path_angle_low_c (should be zeroed out in the PID controller, but just in case)
        if not self.enable_lane_positioning:
          path_angle_low_c = 0.0

        # reset path angle if steering reset is active
        # During post-reset ramp, path_angle can ramp normally (latch in ford.h handles bypass)
        if reset_steering == 1:
          path_angle_low_c = 0.0

        # rate limit path_angle_low_c for comfort
        path_angle_roc = interp(abs(CS.out.vEgoRaw), self.LC_path_angle_ROC_bp, self.LC_path_angle_ROC_v)
        path_angle_roc *= min(self.tune.path_angle_roc_scale, 1.0)  # Custom: profile
        path_angle_low_c = clip(path_angle_low_c, self.path_angle_last - path_angle_roc, self.path_angle_last + path_angle_roc)

        # if the driver is applying consistent pressure to the steering wheel, reset the path_angle_low_c PID controller
        if steeringPressed:
          self.LC_path_angle_reset_counter = self.LC_path_angle_reset_counter + 1
        else:
          self.LC_path_angle_reset_counter = 0
        if self.LC_path_angle_reset_counter > self.LC_path_angle_reset_duration * 20: #20 scans per second
          self.LC_PID_controller.reset()

        # path_angle_high_c is not used in the current implementation
        path_angle_high_c = 0.0

        # sum path_angle_low_c and path_angle_high_c
        path_angle = path_angle_low_c + path_angle_high_c

        # Apply post lane change transition logic
        path_angle, path_offset, desired_curvature_rate = self.handle_post_lane_change_transition(
            path_angle, path_offset, desired_curvature_rate
        )

        # reset path angle if steering reset is active
        # During post-reset ramp, path_angle can ramp normally (latch in ford.h handles bypass)
        if reset_steering == 1:
          path_angle = 0.0

        # clip all values to max.
        apply_curvature = clip(apply_curvature, -self.curvature_max, self.curvature_max)
        desired_curvature_rate = clip(desired_curvature_rate, -self.curvature_rate_max, self.curvature_rate_max)
        path_offset = clip(path_offset, -self.path_offset_max, self.path_offset_max)
        path_angle = clip(path_angle, -self.path_angle_max, self.path_angle_max)


        # if path_offset and path_angle disagree, it can result in a very uncomortable ride, since path_angle is so strong, zero out path_offset signal before it is sent over canbus
        path_offset = 0.0

        if self.disable_BP_lat_UI:
          reset_steering = 0
          path_offset = 0
          path_angle = 0
          desired_curvature_rate = 0
          ramp_type = 1

          self.anti_overshoot_curvature_last = anti_overshoot(desired_curvature, self.anti_overshoot_curvature_last, CS.out.vEgoRaw)
          apply_curvature = self.anti_overshoot_curvature_last

          current_curvature = -CS.out.yawRate / max(CS.out.vEgoRaw, 0.1)

          self.apply_curvature_last, max_curvature = apply_ford_curvature_limits(apply_curvature, self.apply_curvature_last, current_curvature,
                                                              CS.out.vEgoRaw, 0., CC.latActive, self.CP,
                                                              self.tune.lat_accel_scale)  # Custom

          #rem bluepilot sends apply_curvature, and at some point openpilot swapped to sending apply_curvature_last.
          apply_curvature = self.apply_curvature_last

          lateralUncertainty = self.calculate_lateral_uncertainty(requested_curvature, apply_curvature, max_curvature)

        # reset steering by setting all values to 0 (handle where each variable is calcualted) and ramp_type to immediate.  Also clear filters and PID controllers
        if reset_steering == 1:
          ramp_type = 3
          self.path_angle_deque.clear()
          self.LC_PID_controller.reset()
>>>>>>> theirs
        else:
          can_sends.append(fordcan_ext.create_lat_ctl_msg(
            self.packer, self.CAN, lat_active, lat.ramp_type, lat.precision_type,
            -lat.path_offset, -lat.path_angle, -lat.apply_curvature, -lat.curvature_rate
          ))

    # send lka msg at 33Hz
    if (self.frame % CarControllerParams.LKA_STEP) == 0:
      # BluePilot: tell ford.h whether angle mode is engaged, out-of-band from LMC/LMC2, packed into
      # Lane_Assist_Data1's unused bits (read synchronously in ford_tx_hook, no separate CAN ID/RX
      # needed). bypass_bp_lat means BP lateral is off entirely, so angle mode can't be engaged then.
      # shadow_curvature is only meaningful in angle mode (self.bp_kappa_cmd is stale/unused CurvExt
      # state otherwise, so force it to 0 there).
      # Negated to match the sign convention path_angle/apply_curvature use on the wire (see
      # -lat.path_angle/-lat.apply_curvature just above) -- ford.h's angle_meas (measured curvature,
      # from raw yaw rate with no negation) is calibrated against that wire convention, not
      # bp_kappa_cmd's internal one. Confirmed via safety_replay against a real route (2026-07-10):
      # un-negated, shadow_curvature and angle_meas were consistently opposite-signed, so the
      # deviation check found a "divergence" on every frame once speed crossed angle_error_min_speed.
      angle_mode_engaged = (not self.disable_BP_lat_UI) and (self.primary_lateral_control == PrimaryLateralControl.angle)
      shadow_curvature = -self.bp_kappa_cmd if angle_mode_engaged else 0.0
      can_sends.append(fordcan_ext.create_lka_msg(
        self.packer, self.CAN, CC.latActive, hud_control, angle_mode_engaged, shadow_curvature
      ))

    ### longitudinal control ###
    # send acc msg at 50Hz
    if self.CP.openpilotLongitudinalControl and (self.frame % CarControllerParams.ACC_CONTROL_STEP) == 0:
      # Stock creep compensation and rate limiting (upstream-identical)
      op_accel = actuators.accel
      op_gas = op_accel

      if CC.longActive:
<<<<<<< ours
        op_accel = apply_creep_compensation(op_accel, CS.out.vEgo)
=======
        # Compensate for engine creep at low speed.
        # Either the ABS does not account for engine creep, or the correction is very slow
        # TODO: verify this applies to EV/hybrid
        # Custom: Lightning creep amount; no creep compensation with One-Pedal Drive (the truck does not creep)
        creep_max = 0.0 if getattr(CS, "bp_one_pedal", False) else self.tune.creep_comp_max
        op_accel = apply_creep_compensation(op_accel, CS.out.vEgo, creep_max)

        # The stock system has been seen rate limiting the brake accel to 5 m/s^3,
        # however even 3.5 m/s^3 causes some overshoot with a step response.
>>>>>>> theirs
        op_accel = max(op_accel, self.accel - (3.5 * CarControllerParams.ACC_CONTROL_STEP * DT_CTRL))

      op_accel = float(np.clip(op_accel, CarControllerParams.ACCEL_MIN, CarControllerParams.ACCEL_MAX))
      op_gas = float(np.clip(op_gas, CarControllerParams.ACCEL_MIN, CarControllerParams.ACCEL_MAX))

      if not CC.longActive or op_gas < CarControllerParams.MIN_GAS:
        op_gas = CarControllerParams.INACTIVE_GAS

      # Pitch compensation (upstream-identical)
      accel_due_to_pitch = 0.0
      if len(CC.orientationNED) == 3:
        accel_due_to_pitch = math.sin(CC.orientationNED[1]) * ACCELERATION_DUE_TO_GRAVITY

      # BluePilot: downhill compensation disable
      if self.disable_downhill_comp_UI:
        if accel_due_to_pitch < 0:
          accel_due_to_pitch = 0

      stopping = CC.actuators.longControlState == LongCtrlState.stopping
      target_speed = V_CRUISE_MAX
      v_ego_mph = CS.out.vEgo * 2.23694

<<<<<<< ours
      # BluePilot: longitudinal follow control via LongitudinalExt
      # Classifies lead vehicle state (gaining/pacing/trailing) and applies gas/accel limits,
      # rate-limited braking, and split brake/precharge hysteresis.
      lng = LongitudinalExt.update(self, CC, CS, op_accel, op_gas, accel_due_to_pitch,
                                    v_ego_mph, stopping, target_speed)

      can_sends.append(fordcan_ext.create_acc_msg(
        self.packer, self.CAN, CC.longActive, lng.gas, lng.accel, lng.accel_pred_send,
        lng.stopping, lng.brake_actuate, lng.precharge_actuate, v_ego_kph=lng.target_speed
=======
      # TODO return to this signal later, it might help with highway control, but sending values ford doesn't like causes ACC to cancel.
      self.accel_pred = -5.0  # same as BluePilot branch until safe logic is confirmed

      # Speed deadband for BP long: engage above 50 mph, disallow below 45 mph; 45–50 keeps current state to avoid oscillation.
      bpSpeedTooSlow = v_ego_mph < self.MAX_URBAN_SPEED_MPH
      bpSpeedHighEnough = v_ego_mph > self.MAX_URBAN_SPEED_MPH + 5
      if bpSpeedHighEnough:
        self.bpSpeedAllow = True
      if bpSpeedTooSlow:
        self.bpSpeedAllow = False

      # BluePilot longitudinal: gas limits when following + rate-limited accel/brake to avoid stomping.
      if not self.disable_BP_long_UI:

        # Lead time (s) and lead state. leadOne.status: 0 = no lead, 1 = lead.
        v_ego = max(CS.out.vEgo, 0.5)
        lead_time_sec = 999.0  # no lead: treat as far
        lead = None
        v_rel = 0.0
        v_lead = 0.0
        if self.sm.valid.get('radarState', False):
          rs = self.sm['radarState']
          lead = getattr(rs, 'leadOne', None)
          if lead is not None and getattr(lead, 'status', 0) != 1:
            lead = None
          if lead:
            d_rel = float(getattr(lead, 'dRel', 0))
            v_rel = float(getattr(lead, 'vRel', 0))
            v_lead = float(getattr(lead, 'vLead', 0))  # m/s; schema is vLead (camelCase)
            if d_rel > 0:
              lead_time_sec = d_rel / v_ego
        lead_time_sec = float(np.clip(lead_time_sec, 0.0, 999.0))
        v_lead_mph = v_lead * 2.23694  # for apply_bp_long: only optimize when lead > 40 mph (don't coast into traffic jam)

        ttc_sec = 120.0
        if self.sm.valid.get('radarState', False):
          rs = self.sm['radarState']
          lead = getattr(rs, 'leadOne', None)
          if lead is not None and getattr(lead, 'status', 0) != 1:
            lead = None
          if lead:
            d_rel = float(getattr(lead, 'dRel', 0))
            v_rel = float(getattr(lead, 'vRel', 0))
            if d_rel > 0 and v_rel < 0:
              ttc_sec = d_rel / (-v_rel)
            else:
              ttc_sec = 60.0
        ttc_sec = float(np.clip(ttc_sec, 0.2, 120.0))

        # Defaults: pass through op_* when no lead or no mode; brake/precharge off until thresholds
        gaining = False
        pacing = False
        trailing = False
        max_follow_gas = op_gas
        min_follow_gas = op_gas
        max_follow_accel = op_accel
        min_follow_accel = op_accel
        bp_brake_actuate = False
        bp_precharge_actuate = False

        # Gaining on lead, pacing, or trailing away
        if lead:
          if v_rel < -0.1:
            gaining = True
          elif v_rel > 0.1:
            trailing = True
          else:
            pacing = True

        # limits when gaining
        if gaining:
          if lead_time_sec < self.tune.lead_gas_cut_s:  # Custom: profile (stock 1.5 s)
              max_follow_gas = 0.0 # if we are within 1.5 seconds and gaining, why press the gas?
              min_follow_gas = 0.0
          else:
             max_follow_gas = op_gas
             min_follow_gas = op_gas
          max_follow_accel = op_accel
          min_follow_accel = op_accel # following braking for our primary target


        # limits when pacing
        if pacing:
          max_follow_gas = 0.2 + accel_due_to_pitch # don't get too happy with the gas when pacing.
          min_follow_gas = 0.0
          max_follow_accel = op_accel
          min_follow_accel = op_accel # we will always target op_accel for braking

        # limits when trailing
        if trailing:
          max_follow_gas = op_gas
          min_follow_gas = op_gas
          max_follow_accel = op_accel
          min_follow_accel = op_accel

        # limits with no lead
        if lead is None:
          max_follow_gas = op_gas
          min_follow_gas = op_gas
          max_follow_accel = 0
          min_follow_accel = 0


        # apply our bp gas and accel targets
        bp_gas = clip(op_gas, min_follow_gas, max_follow_gas)
        bp_accel = clip(op_accel, min_follow_accel, max_follow_accel)

        # now let's apply some rate limits, not much, just try to dampen the initial hit when braking
        # but only apply the limits if there is no imminent chance of a collision
        if ttc_sec > 8.0 and lead_time_sec > 0.5:
          bp_accel = clip(bp_accel, self.bp_accel_last - self.following_accel_ROC, 999) #only limit the downward change of braking

        # Set brake_actuate and precharge_actuate flags (initialized False above)
        if bp_accel < self.brake_actuate_target:
          bp_brake_actuate = True
        if bp_accel > self.brake_actuate_release:
          bp_brake_actuate = False
        if bp_accel < self.precharge_actuate_target:
          bp_precharge_actuate = True
        if bp_accel > self.precharge_actuate_release:
          bp_precharge_actuate = False

        # Determine if we will use bp smoothing (bpSpeedAllow deadband updated above, outside this block)
        gasPressed = CS.out.gasPressed
        brakePressed = CS.out.brakePressed

        # When we have a lead, require lead speed > 40 mph so we don't coast into a traffic jam; when no lead, allow BP long
        apply_bp_long = (self.disable_BP_long_UI == False) and (self.bpSpeedAllow) and (gasPressed == False) and (brakePressed == False) and (lead is None or v_lead_mph > 40.0)

        if apply_bp_long and CC.longActive:
          accel = bp_accel
          gas = bp_gas
          brake_actuate = bp_brake_actuate
          precharge_actuate = bp_precharge_actuate
        else:
          accel = op_accel
          gas = op_gas
          brake_actuate = op_brake_actuate
          precharge_actuate = op_brake_actuate

        self.bp_gas_last = bp_gas
        self.bp_accel_last = bp_accel
        bp_long_used = apply_bp_long
      else:
        accel = op_accel
        gas = op_gas
        brake_actuate = op_brake_actuate
        precharge_actuate = op_brake_actuate
        bp_long_used = False

      # no brake and gas at the same timne
      if brake_actuate:
        gas = CarControllerParams.INACTIVE_GAS

      # Clip to ford.h ACCDATA safety limits
      # Custom: profiles may lower the positive limit (tow, off-road, slippery), never raise it
      accel_max = CarControllerParams.ACCEL_MAX * float(np.clip(self.tune.accel_max_scale, 0.1, 1.0))
      accel = float(clip(accel, CarControllerParams.ACCEL_MIN, accel_max))
      if gas != CarControllerParams.INACTIVE_GAS:
        gas = float(clip(gas, CarControllerParams.MIN_GAS, accel_max))
      accel_pred_send = CarControllerParams.INACTIVE_GAS

      can_sends.append(fordcan.create_acc_msg(
        self.packer, self.CAN, CC.longActive, gas, accel, accel_pred_send, stopping,
        brake_actuate, precharge_actuate, v_ego_kph=target_speed
>>>>>>> theirs
      ))

      self.accel = lng.accel
      self.gas = lng.gas

    ### ui ###
    # BluePilot: HUD message generation via HudExt
    # Handles LKAS UI (1Hz), ACC UI (5Hz), bar persistence, and TJA/hands-free messaging.
    hud_can_sends = HudExt.update_hud(self, CC, CS, hud_control, main_on, fcw_alert,
                                       self.frame, self.packer, self.CAN, self.CP)
    can_sends.extend(hud_can_sends)

    new_actuators = actuators.as_builder()
    new_actuators.curvature = float(self.apply_curvature_last)
    new_actuators.accel = float(self.accel)
    new_actuators.gas = float(self.gas)

    self.frame += 1
    return new_actuators, can_sends
