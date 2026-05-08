#!/usr/bin/env python3
"""
CH347 I2C Interface for LSM6DS3 sensor

Uses libch347.so to communicate with LSM6DS3 via CH347 USB-to-I2C adapter.
"""
import ctypes
import ctypes.util
import time
from typing import Optional

class CH347I2C:
  """CH347 I2C interface wrapper"""

  # I2C speed constants
  I2C_SPEED_LOW = 0x00
  I2C_SPEED_STANDARD = 0x01
  I2C_SPEED_FAST = 0x02

  def __init__(self, device_index: int = 0):
    self.device_index = device_index
    self.handle = -1
    self.lib = None
    self._load_library()

  def _load_library(self):
    """Load libch347.so"""
    lib_path = ctypes.util.find_library('ch347')
    if not lib_path:
      lib_path = '/usr/lib/libch347.so'

    try:
      self.lib = ctypes.cdll.LoadLibrary(lib_path)
      print(f"✓ Loaded CH347 library: {lib_path}")

      # Get library info - be careful with this call
      try:
        self.lib.CH347GetLibInfo.restype = ctypes.c_void_p
        info_ptr = self.lib.CH347GetLibInfo()
        if info_ptr:
          info = ctypes.cast(info_ptr, ctypes.c_char_p).value
          print(f"  Library info: {info.decode()}")
      except Exception as e:
        print(f"  (Skipping library info: {e})")

    except Exception as e:
      raise RuntimeError(f"Failed to load libch347.so: {e}")

  def open(self) -> bool:
    """Open CH347 device"""
    try:
      self.lib.CH347OpenDevice.restype = ctypes.c_int
      self.lib.CH347OpenDevice.argtypes = [ctypes.c_uint32]

      self.handle = self.lib.CH347OpenDevice(self.device_index)
      if self.handle >= 0:
        print(f"✓ Opened CH347 device (handle: {self.handle})")
        return True
      else:
        print(f"✗ Failed to open CH347 device (error: {self.handle})")
        return False
    except Exception as e:
      print(f"✗ Error opening device: {e}")
      return False

  def close(self):
    """Close CH347 device"""
    if self.handle >= 0:
      try:
        self.lib.CH347CloseDevice(self.handle)
        print(f"✓ Closed CH347 device")
        self.handle = -1
      except Exception as e:
        print(f"✗ Error closing device: {e}")

  def i2c_set(self, speed: int = I2C_SPEED_STANDARD) -> bool:
    """Configure I2C interface"""
    try:
      self.lib.CH347I2C_Set.restype = ctypes.c_int
      self.lib.CH347I2C_Set.argtypes = [ctypes.c_uint32, ctypes.c_uint32]

      result = self.lib.CH347I2C_Set(self.handle, speed)
      if result == 0:
        print(f"✓ I2C configured (speed: {speed})")
        return True
      else:
        print(f"✗ I2C config failed (error: {result})")
        return False
    except Exception as e:
      print(f"✗ Error configuring I2C: {e}")
      return False

  def i2c_read(self, device_addr: int, reg_addr: int, length: int) -> Optional[bytes]:
    """Read from I2C device"""
    try:
      # CH347StreamI2C function signature
      # int CH347StreamI2C(HANDLE handle, UINT devAddr, UINT writeLen, PUCHAR writeBuf,
      #                    UINT readLen, PUCHAR readBuf)
      self.lib.CH347StreamI2C.restype = ctypes.c_int
      self.lib.CH347StreamI2C.argtypes = [
        ctypes.c_uint32,  # handle
        ctypes.c_uint32,  # devAddr
        ctypes.c_uint32,  # writeLen
        ctypes.POINTER(ctypes.c_ubyte),  # writeBuf
        ctypes.c_uint32,  # readLen
        ctypes.POINTER(ctypes.c_ubyte),  # readBuf
      ]

      # Prepare write buffer (register address)
      write_buf = (ctypes.c_ubyte * 1)(reg_addr)

      # Prepare read buffer
      read_buf = (ctypes.c_ubyte * length)()

      # Execute I2C transaction
      result = self.lib.CH347StreamI2C(
        self.handle,
        device_addr,
        1,  # write 1 byte (register address)
        write_buf,
        length,  # read N bytes
        read_buf
      )

      if result == 0:
        return bytes(read_buf[:length])
      else:
        print(f"✗ I2C read failed (addr: 0x{device_addr:02X}, reg: 0x{reg_addr:02X}, error: {result})")
        return None

    except Exception as e:
      print(f"✗ Error in I2C read: {e}")
      return None

  def i2c_write(self, device_addr: int, reg_addr: int, data: int) -> bool:
    """Write to I2C device"""
    try:
      self.lib.CH347StreamI2C.restype = ctypes.c_int
      self.lib.CH347StreamI2C.argtypes = [
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_ubyte),
        ctypes.c_uint32,
        ctypes.POINTER(ctypes.c_ubyte),
      ]

      # Prepare write buffer (register address + data)
      write_buf = (ctypes.c_ubyte * 2)(reg_addr, data)

      # No read
      read_buf = (ctypes.c_ubyte * 1)()

      result = self.lib.CH347StreamI2C(
        self.handle,
        device_addr,
        2,  # write 2 bytes (reg + data)
        write_buf,
        0,  # read 0 bytes
        read_buf
      )

      if result == 0:
        return True
      else:
        print(f"✗ I2C write failed (addr: 0x{device_addr:02X}, reg: 0x{reg_addr:02X}, error: {result})")
        return False

    except Exception as e:
      print(f"✗ Error in I2C write: {e}")
      return False

  def __enter__(self):
    self.open()
    return self

  def __exit__(self, exc_type, exc_val, exc_tb):
    self.close()


def test_ch347_i2c():
  """Test CH347 I2C with LSM6DS3 sensor"""
  print("\n" + "="*60)
  print("Testing CH347 I2C with LSM6DS3")
  print("="*60)

  LSM6DS3_ADDR = 0x6A
  CHIP_ID_REG = 0x0F

  try:
    with CH347I2C(device_index=0) as i2c:
      # Configure I2C
      if not i2c.i2c_set(CH347I2C.I2C_SPEED_STANDARD):
        print("✗ Failed to configure I2C")
        return False

      print("\nReading LSM6DS3 chip ID...")
      chip_id = i2c.i2c_read(LSM6DS3_ADDR, CHIP_ID_REG, 1)

      if chip_id:
        chip_id_value = chip_id[0]
        print(f"✓ Chip ID: 0x{chip_id_value:02X}")

        if chip_id_value in [0x69, 0x6A]:
          print(f"✓ LSM6DS3 detected!")
          return True
        else:
          print(f"✗ Unknown chip ID: 0x{chip_id_value:02X}")
          return False
      else:
        print("✗ Failed to read chip ID")
        return False

  except Exception as e:
    print(f"✗ Test failed: {e}")
    import traceback
    traceback.print_exc()
    return False


def main():
  print("\nCH347 I2C Test for LSM6DS3 Sensor")
  print("="*60)

  success = test_ch347_i2c()

  print("\n" + "="*60)
  print("TEST RESULT")
  print("="*60)

  if success:
    print("✓ CH347 I2C communication successful!")
    print("✓ LSM6DS3 sensor detected")
    print("\nNext step: Run full sensor test")
    print("  python3 system/sensord_ch347/test_sensord_ch347_ch347.py --verbose")
    return 0
  else:
    print("✗ CH347 I2C test failed")
    print("\nPossible issues:")
    print("  1. LSM6DS3 not connected to CH347 I2C pins")
    print("  2. Wrong I2C address (expected 0x6A)")
    print("  3. CH347 I2C not enabled in hardware")
    print("  4. Library version incompatibility")
    return 1


if __name__ == "__main__":
  exit(main())
