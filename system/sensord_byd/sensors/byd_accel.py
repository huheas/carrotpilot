import math
import time
from typing import Optional

from cereal import log


class BYDAccel:
  """
  BYD CAN bus accelerometer sensor bridge.

  Reads aEgo (longitudinal) and aEgoY (lateral) from carState and
  synthesises a 3-axis acceleration SensorEventData message compatible
  with locationd.

  Coordinate mapping (locationd applies meas = [-v[2], -v[1], -v[0]]):
    v[0] = -9.81          -> meas[2] =  9.81  (vertical gravity, Z-axis)
    v[1] = -aEgoY         -> meas[1] =  aEgoY (lateral, Y-axis)
    v[2] = -aEgo          -> meas[0] =  aEgo  (longitudinal, X-axis)
  """

  SENSOR_ID   = 1  # SENSOR_ACCELEROMETER
  SENSOR_TYPE = 1  # SENSOR_TYPE_ACCELEROMETER

  def get_event(self, car_state) -> Optional[log.SensorEventData]:
    """
    Build a SensorEventData for the accelerometer service.

    Args:
      car_state: carState capnp reader (from SubMaster['carState'])

    Returns:
      log.SensorEventData or None if data is invalid.
    """
    aEgo  = car_state.aEgo
    aEgoY = car_state.aEgoY

    if math.isnan(aEgo) or math.isinf(aEgo) or math.isnan(aEgoY) or math.isinf(aEgoY):
      return None

    now = time.monotonic_ns()  # 使用单调时间，与 msg.logMonoTime 一致
    event = log.SensorEventData.new_message()
    event.timestamp = now
    event.version   = 1
    event.sensor    = self.SENSOR_ID
    event.type      = self.SENSOR_TYPE
    event.source    = log.SensorEventData.SensorSource.android
    a = event.init('acceleration')
    # locationd: meas = [-v[2], -v[1], -v[0]]
    # v[0]=-9.81     -> meas[2] = 9.81  (gravity on vertical Z-axis)
    # v[1]=-aEgoY    -> meas[1] = aEgoY (lateral)
    # v[2]=-aEgo     -> meas[0] = aEgo  (longitudinal)
    a.v      = [-9.81, -aEgoY, -aEgo]
    a.status = 1
    return event
