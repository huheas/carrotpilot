import numpy as np
from opendbc.can.packer import CANPacker
from opendbc.car import Bus, apply_driver_steer_torque_limits, structs
from opendbc.car.interfaces import CarControllerBase
from opendbc.car.byd import bydcan
from opendbc.car.byd.values import CarControllerParams

VisualAlert = structs.CarControl.HUDControl.VisualAlert
ButtonType = structs.CarState.ButtonEvent.Type
LongCtrlState = structs.CarControl.Actuators.LongControlState


class CarController(CarControllerBase):
  def __init__(self, dbc_names, CP):
    super().__init__(dbc_names, CP)

    self.packer = CANPacker(dbc_names[Bus.pt])

    self.frame = 0
    self.last_steer_frame = 0
    self.last_acc_frame = 0

    self.apply_torque_last = 0

    self.mpc_lkas_counter = 0
    self.mpc_acc_counter = 0
    self.eps_fake318_counter = 0

    self.lkas_req_prepare = 0
    self.lkas_active = 0
    self.lat_safeoff = 0

    self.steer_softstart_limit = 0
    self.steerRateLimActive = False
    self.steerRateLim = 1.0

    self.first_start = True
    self.rfss = 0
    self.sss = 0

    self.apply_accel_last = 0

    self.last_pcm_counter = -1

    self.acc_enhance_active = False
    self.acc_enhance_ending = False
    self.acc_enhance_accel_cache = 0.0

    self.btn_inject_cmd = None
    self.btn_inject_frames_left = 0
    self.btn_cooldown_frames = 0

  def update(self, CC, CS, now_nanos):
    can_sends = []

    if (self.frame - self.last_steer_frame) >= CarControllerParams.STEER_STEP:
      if self.first_start:
        self.mpc_lkas_counter = int(CS.acc_mpc_state_counter + 1) & 0xF
        self.mpc_acc_counter = int(CS.acc_cmd_counter + 1) & 0xF
        self.eps_fake318_counter = int(CS.eps_state_counter + 1) & 0xF
        self.first_start = False

      apply_torque = 0

      if CC.latActive:
        if self.lkas_active:
          steer_desire = CC.actuators.torque

          if CarControllerParams.USE_STEERING_SPEED_LIMITER:
            rate_limit = np.interp(CS.out.aEgo, [8.3, 27.8], [132, 64])
            delta_rate = CS.steeringRateDegAbs - rate_limit

            if delta_rate < 0:
              self.steerRateLim -= 0.005 * delta_rate

              if delta_rate < -0.05:
                self.steerRateLimActive = False

              if self.steerRateLim > 1.0:
                self.steerRateLim = 1.0
                self.steerRateLimActive = False

            else:
              if self.steerRateLimActive:
                self.steerRateLim -= 0.005 * delta_rate
              else:
                self.steerRateLim = steer_desire
                self.steerRateLimActive = True

              if self.steerRateLim < 0:
                self.steerRateLim = 0

            new_steer_pu = np.clip(steer_desire, -self.steerRateLim, self.steerRateLim)
          else:
            new_steer_pu = steer_desire

          new_steer = int(round(new_steer_pu * CarControllerParams.STEER_MAX))

          if self.steer_softstart_limit < CarControllerParams.STEER_MAX:
            self.steer_softstart_limit = self.steer_softstart_limit + CarControllerParams.STEER_SOFTSTART_STEP
            new_steer = np.clip(new_steer, -self.steer_softstart_limit, self.steer_softstart_limit)

          apply_torque = apply_driver_steer_torque_limits(new_steer, self.apply_torque_last, CS.out.steeringTorque, CarControllerParams)

        else:
          if CS.lkas_prepared:
            self.lkas_active = 1.0
            self.steerRateLimActive = False
            self.steerRateLim = 1.0
            self.lkas_req_prepare = 0
            self.steer_softstart_limit = 0
            self.lat_safeoff = 1
          else:
            self.lkas_req_prepare = 1

      elif self.lat_safeoff:
        if self.apply_torque_last == 0:
          self.lat_safeoff = 0
        apply_torque = apply_driver_steer_torque_limits(0, self.apply_torque_last, CS.out.steeringTorque, CarControllerParams)

      else:
        self.lkas_req_prepare = 0
        self.steerRateLimActive = False
        self.steerRateLim = 1.0
        self.lkas_active = 0
        self.soft_start_torque_limit = 0
        self.steer_softstart_limit = 0

      self.apply_torque_last = apply_torque

      self.mpc_lkas_counter = int(self.mpc_lkas_counter + 1) & 0xF
      self.eps_fake318_counter = int(self.eps_fake318_counter + 1) & 0xF
      self.last_steer_frame = self.frame

      can_sends.append(
        bydcan.create_steering_control(
          self.packer, self.CP, CS.cam_lkas, self.apply_torque_last, self.lkas_req_prepare, self.lkas_active, CC.hudControl, self.mpc_lkas_counter
        )
      )

      can_sends.append(
        bydcan.create_fake_318(self.packer, self.CP, CS.esc_eps, CS.mpc_laks_output, CS.mpc_laks_reqprepare, CS.mpc_laks_active, True, self.eps_fake318_counter)
      )

    if (self.frame + 1 - self.last_acc_frame) >= CarControllerParams.ACC_STEP:
      cruise_enabled = CS.out.cruiseState.enabled

      if CS.acc_enhance_ending:
        self.acc_enhance_ending = True
        CS.acc_enhance_ending = False

      if CS.acc_enhance_request and cruise_enabled:
        if not self.acc_enhance_active:
          self.acc_enhance_active = True
        self.acc_enhance_accel_cache = CS.acc_enhance_accel
      elif not CS.acc_enhance_request and self.acc_enhance_active:
        self.acc_enhance_active = False
        self.acc_enhance_ending = True

      if not cruise_enabled:
        if self.acc_enhance_active:
          self.acc_enhance_active = False
          self.acc_enhance_ending = True

      should_send_acc_cmd = (cruise_enabled and self.acc_enhance_active) or self.acc_enhance_ending or (cruise_enabled and CC.longActive)

      accel_to_send = 0.0
      long_active = False

      if self.acc_enhance_ending:
        can_sends.append(bydcan.acc_cmd(self.packer, self.CP, CS.cam_acc, CS.mrr_leading_dist, 0, 0, 0, False))
        self.acc_enhance_ending = False
        self.acc_enhance_accel_cache = 0.0

      elif should_send_acc_cmd:
        if CC.longActive:
          accel_to_send = np.clip(CC.actuators.accel, CarControllerParams.ACCEL_MIN, CarControllerParams.ACCEL_MAX)
          long_active = True

          stopping = CC.actuators.longControlState == LongCtrlState.stopping
          starting = CC.actuators.longControlState == LongCtrlState.starting

          if stopping and accel_to_send < -0.1:
            self.rfss = 0
            self.sss = CS.out.standstill
          elif starting and accel_to_send > 0.1 and CS.out.vEgo < 0.8:
            self.rfss = CS.out.standstill
            self.sss = 0
          else:
            self.rfss = 0
            self.sss = 0

        elif self.acc_enhance_active:
          accel_to_send = np.clip(self.acc_enhance_accel_cache, CarControllerParams.ACCEL_MIN, CarControllerParams.ACCEL_MAX)
          long_active = True
          self.rfss = 0
          self.sss = CS.out.standstill if accel_to_send < -0.1 else 0

        if long_active:
          can_sends.append(bydcan.acc_cmd(self.packer, self.CP, CS.cam_acc, CS.mrr_leading_dist, accel_to_send, self.rfss, self.sss, True))
          self.apply_accel_last = accel_to_send

      self.last_acc_frame = self.frame + 1

    if CS.pcm_buttons_vals:
      cur_counter = CS.pcm_buttons_vals.get("Counter", -1)
      if cur_counter != self.last_pcm_counter:
        self.last_pcm_counter = cur_counter
        fwd_vals = dict(CS.pcm_buttons_vals)

        if self.btn_cooldown_frames > 0:
          self.btn_cooldown_frames -= 1

        if self.btn_inject_frames_left > 0:
          ud, cancel, dinc, ddec = self.btn_inject_cmd
          fwd_vals["BTN_AccUpDown_Cmd"] = ud
          fwd_vals["BTN_AccCancel"] = cancel
          fwd_vals["BTN_AccDistanceIncrease"] = dinc
          fwd_vals["BTN_AccDistanceDecrease"] = ddec
          self.btn_inject_frames_left -= 1
          if self.btn_inject_frames_left == 0:
            self.btn_cooldown_frames = 7
        else:
          inject = self._get_button_injection(CC, CS)
          if inject is not None:
            self.btn_inject_cmd = inject
            self.btn_inject_frames_left = 3
            ud, cancel, dinc, ddec = inject
            fwd_vals["BTN_AccUpDown_Cmd"] = ud
            fwd_vals["BTN_AccCancel"] = cancel
            fwd_vals["BTN_AccDistanceIncrease"] = dinc
            fwd_vals["BTN_AccDistanceDecrease"] = ddec

        can_sends.append(bydcan.create_button_fwd(self.packer, fwd_vals))

    new_actuators = CC.actuators.as_builder()
    new_actuators.torque = self.apply_torque_last / CarControllerParams.STEER_MAX
    new_actuators.torqueOutputCan = self.apply_torque_last
    new_actuators.accel = float(self.apply_accel_last)
    new_actuators.steeringAngleDeg = float(CS.out.steeringAngleDeg)

    self.frame += 1
    return new_actuators, can_sends

  def _get_button_injection(self, CC, CS):
    if CC.cruiseControl.cancel:
      self.btn_cooldown_frames = 0
      return (0, 1, 0, 0)

    if CS.btn_acc_set_reset != 0 or CS.btn_acc_cancel != 0:
      return None

    if self.btn_cooldown_frames > 0:
      return None

    if CC.cruiseControl.resume:
      return (3, 0, 0, 0)

    return None
