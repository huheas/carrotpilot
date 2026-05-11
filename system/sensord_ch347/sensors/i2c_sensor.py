import time
import smbus2
import ctypes
from collections.abc import Iterable

from cereal import log


class Sensor:
  class SensorException(Exception):
    pass

  class DataNotReady(SensorException):
    pass

  def __init__(self, bus: int) -> None:
    self.bus_num = bus
    self.bus = smbus2.SMBus(bus)
    self.source = log.SensorEventData.SensorSource.velodyne
    self.start_ts = 0.0

  def __del__(self):
    if hasattr(self, 'bus'):
      self.bus.close()

  def reconnect(self) -> bool:
    """
    重新建立 I2C 连接。
    关闭旧的 bus 句柄,等待设备重新可用,然后创建新连接。
    返回是否成功。
    """
    import os
    
    try:
      # 1. 关闭旧连接
      if hasattr(self, 'bus'):
        try:
          self.bus.close()
        except Exception:
          pass
      
      # 2. 等待设备重新枚举
      time.sleep(0.2)
      
      # 3. 检查设备节点是否存在
      dev_path = f"/dev/i2c-{self.bus_num}"
      if not os.path.exists(dev_path):
        # 设备节点不存在,可能需要重新绑定驱动
        return False
      
      # 4. 尝试创建新连接
      self.bus = smbus2.SMBus(self.bus_num)
      
      # 5. 验证设备是否响应 (读取 WHO_AM_I)
      try:
        chip_id = self.read(0x0F, 1)[0]
        if chip_id in [0x69, 0x6A]:  # LSM6DSM or LSM6DS3TRC
          return True
        return False
      except Exception:
        # 设备不响应,关闭连接
        try:
          self.bus.close()
        except Exception:
          pass
        return False
        
    except Exception as e:
      return False

  def read(self, addr: int, length: int) -> bytes:
    return bytes(self.bus.read_i2c_block_data(self.device_address, addr, length))

  def write(self, addr: int, data: int) -> None:
    self.bus.write_byte_data(self.device_address, addr, data)

  def writes(self, writes: Iterable[tuple[int, int]]) -> None:
    for addr, data in writes:
      self.write(addr, data)

  def verify_chip_id(self, address: int, expected_ids: list[int]) -> int:
    chip_id = self.read(address, 1)[0]
    assert chip_id in expected_ids
    return chip_id

  # Abstract methods that must be implemented by subclasses
  @property
  def device_address(self) -> int:
    raise NotImplementedError

  def reset(self) -> None:
    # optional.
    # not part of init due to shared registers
    pass

  def init(self) -> None:
    raise NotImplementedError

  def get_event(self, ts: int | None = None) -> log.SensorEventData:
    raise NotImplementedError

  def shutdown(self) -> None:
    raise NotImplementedError

  def is_data_valid(self) -> bool:
    if self.start_ts == 0:
      self.start_ts = time.monotonic()

    # unclear whether we need this...
    return (time.monotonic() - self.start_ts) > 0.5

  # *** helpers ***
  @staticmethod
  def wait():
    # a standard small sleep
    time.sleep(0.005)

  @staticmethod
  def parse_16bit(lsb: int, msb: int) -> int:
    return ctypes.c_int16((msb << 8) | lsb).value

  @staticmethod
  def parse_20bit(b2: int, b1: int, b0: int) -> int:
    combined = ctypes.c_uint32((b0 << 16) | (b1 << 8) | b2).value
    return ctypes.c_int32(combined).value // (1 << 4)
