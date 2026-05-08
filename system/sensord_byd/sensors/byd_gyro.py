import math
import time
from typing import Optional

from cereal import log


class BYDGyro:
  """
  BYD CAN bus gyroscope sensor bridge.

  Reads yawRate / aEgo / aEgoY from carState and synthesises a 3-axis
  gyroUncalibrated SensorEventData message compatible with locationd.

  Coordinate mapping (locationd applies meas = [-v[2], -v[1], -v[0]]):
    v[0] = yaw_rate   -> meas[2] = -yaw_rate  (sign is handled by caller)
    v[1] = pitch_rate -> meas[1] = -pitch_rate
    v[2] = roll_rate  -> meas[0] = -roll_rate

  pitch_rate and roll_rate are estimated from longitudinal/lateral jerk
  using simple proportional + low-pass filter, matching the original C++
  implementation in universal_can_sensor.cc.
  """

  SENSOR_ID   = 5   # SENSOR_GYRO_UNCALIBRATED
  SENSOR_TYPE = 16  # SENSOR_TYPE_GYROSCOPE_UNCALIBRATED

  # Suspension-dynamics proportional coefficients:
  # 10 m/s³ long-jerk -> ~0.02 rad/s pitch  => K_PITCH ≈ 0.002
  # 10 m/s³ lat-jerk  -> ~0.015 rad/s roll  => K_ROLL  ≈ 0.0015
  K_PITCH = 0.002
  K_ROLL  = 0.0015

  # First-order low-pass alpha (~2.4 Hz cutoff @ 100 Hz)
  ALPHA    = 0.15
  MAX_RATE = 0.1  # rad/s clamp for pitch/roll

  def __init__(self):
    self._prev_aEgo      = 0.0
    self._prev_aEgoY     = 0.0
    self._prev_ts        = 0
    self._filtered_pitch = 0.0
    self._filtered_roll  = 0.0

  def get_event(self, car_state) -> Optional[log.SensorEventData]:
    """
    Build a SensorEventData for the gyroscope service.

    Args:
      car_state: carState capnp reader (from SubMaster['carState'])

    Returns:
      log.SensorEventData or None if data is invalid.
    """
    yaw_rate = car_state.yawRate
    if math.isnan(yaw_rate) or math.isinf(yaw_rate):
      return None

    aEgo  = car_state.aEgo
    aEgoY = car_state.aEgoY
    if math.isnan(aEgo)  or math.isinf(aEgo):
      aEgo = 0.0
    if math.isnan(aEgoY) or math.isinf(aEgoY):
      aEgoY = 0.0

    now = time.monotonic_ns()
    pitch_rate = 0.0
    roll_rate  = 0.0

    if self._prev_ts > 0:
      dt = (now - self._prev_ts) * 1e-9
      if 0.001 < dt < 0.1:
        long_jerk = (aEgo  - self._prev_aEgo)  / dt
        lat_jerk  = (aEgoY - self._prev_aEgoY) / dt

        # braking jerk -> nose-down (negative pitch_rate)
        raw_pitch = -self.K_PITCH * long_jerk
        # left-turn lat_accel increase -> right-lean (positive roll_rate)
        raw_roll  =  self.K_ROLL  * lat_jerk

        self._filtered_pitch = self.ALPHA * raw_pitch + (1.0 - self.ALPHA) * self._filtered_pitch
        self._filtered_roll  = self.ALPHA * raw_roll  + (1.0 - self.ALPHA) * self._filtered_roll

        pitch_rate = max(-self.MAX_RATE, min(self.MAX_RATE, self._filtered_pitch))
        roll_rate  = max(-self.MAX_RATE, min(self.MAX_RATE, self._filtered_roll))

    self._prev_aEgo  = aEgo
    self._prev_aEgoY = aEgoY
    self._prev_ts    = now

    event = log.SensorEventData.new_message()
    event.timestamp = now  # 使用单调时间，与 msg.logMonoTime 一致
    event.version   = 1
    event.sensor    = self.SENSOR_ID
    event.type      = self.SENSOR_TYPE
    event.source    = log.SensorEventData.SensorSource.android
    g = event.init('gyroUncalibrated')
    g.v      = [yaw_rate, pitch_rate, roll_rate]
    g.status = 1
    return event
