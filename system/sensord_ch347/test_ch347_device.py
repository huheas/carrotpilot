#!/usr/bin/env python3
"""
Test CH347 I2C functionality using the vendor driver

According to WCH documentation, CH347 provides I2C access through:
- Device: /dev/ch34x_pis1 (or similar)
- Interface: ioctl calls or direct file I/O

This test attempts to communicate with LSM6DS3 sensor via CH347 I2C.
"""
import os
import sys
import time
import struct
import fcntl

# CH347 I2C device
CH347_DEVICE = "/dev/ch34x_pis1"
LSM6DS3_ADDRESS = 0x6A
LSM6DS3_CHIP_ID_REG = 0x0F

def test_device_access():
  """Test if we can open and access the CH347 device"""
  print("="*60)
  print("CH347 I2C Device Test")
  print("="*60)

  # Check device exists
  if not os.path.exists(CH347_DEVICE):
    print(f"✗ Device {CH347_DEVICE} not found")
    print("\nPossible issues:")
    print("  1. CH347 driver not loaded")
    print("  2. Device permissions (need root or dialout group)")
    print("  3. Wrong device path")
    return False

  print(f"✓ Device found: {CH347_DEVICE}")

  # Check permissions
  if not os.access(CH347_DEVICE, os.R_OK | os.W_OK):
    print(f"✗ No read/write permission for {CH347_DEVICE}")
    print("  Try: sudo chmod 666 /dev/ch34x_pis1")
    print("  Or:  sudo usermod -aG dialout $USER")
    return False

  print(f"✓ Device permissions OK")
  return True


def test_basic_io():
  """Test basic I/O operations"""
  print("\n" + "="*60)
  print("Testing Basic I/O Operations")
  print("="*60)

  try:
    fd = os.open(CH347_DEVICE, os.O_RDWR)
    print(f"✓ Successfully opened {CH347_DEVICE}")
    os.close(fd)
    return True
  except Exception as e:
    print(f"✗ Failed to open device: {e}")
    return False


def test_i2c_scan():
  """Scan I2C bus for devices"""
  print("\n" + "="*60)
  print("Scanning I2C Bus for Devices")
  print("="*60)
  print("\nNote: CH347 uses proprietary interface, not standard I2C ioctl")
  print("Attempting to read from LSM6DS3 (0x6A)...")

  # CH347 driver typically uses ioctl or specific I/O commands
  # Let's try different approaches

  # Method 1: Try standard I2C ioctl (might not work with CH347)
  try:
    import smbus2
    print("\nTrying smbus2 (standard I2C interface)...")

    # CH347 might not register as standard I2C bus
    # We need to check if there's a corresponding /dev/i2c-N
    for bus_num in range(10):
      try:
        bus = smbus2.SMBus(bus_num)
        try:
          chip_id = bus.read_byte_data(LSM6DS3_ADDRESS, LSM6DS3_CHIP_ID_REG)
          if chip_id in [0x69, 0x6A]:
            print(f"✓ Found LSM6DS3 on I2C bus {bus_num} (chip ID: 0x{chip_id:02X})")
            bus.close()
            return bus_num
        except Exception:
          pass
        bus.close()
      except Exception:
        pass

    print("✗ LSM6DS3 not found on any standard I2C bus")

  except ImportError:
    print("✗ smbus2 not available")

  return None


def test_ch347_interface():
  """Test CH347 specific interface"""
  print("\n" + "="*60)
  print("Testing CH347 Proprietary Interface")
  print("="*60)

  # According to CH347 documentation, it might use:
  # 1. ioctl with specific commands
  # 2. Direct read/write for I2C

  # Let's check if there are any header files or documentation
  print("\nChecking for CH347 documentation...")

  locations = [
    "/usr/include/ch347.h",
    "/usr/local/include/ch347.h",
    "/lib/modules/$(uname -r)/build/include/linux/ch347.h",
  ]

  for loc in locations:
    if os.path.exists(loc):
      print(f"✓ Found header: {loc}")

  # Check kernel messages for CH347 info
  print("\nChecking dmesg for CH347 messages...")
  try:
    result = os.popen("dmesg 2>/dev/null | grep -i ch34 | tail -10").read()
    if result:
      print("CH347 kernel messages:")
      print(result)
    else:
      print("  No CH347 messages in dmesg (or no permission)")
  except Exception:
    print("  Cannot read dmesg")


def test_with_sudo():
  """Try accessing device with sudo"""
  print("\n" + "="*60)
  print("Testing with Root Privileges")
  print("="*60)

  import subprocess

  # Try to read chip ID using sudo and Python
  test_script = f"""
import os
import time

device = "{CH347_DEVICE}"
try:
  fd = os.open(device, os.O_RDWR)
  print(f"✓ Opened device with root privileges")

  # Try to read from LSM6DS3
  # CH347 might need specific I2C commands via ioctl
  # For now, just test device access
  os.close(fd)
  print("✓ Device access successful")
except Exception as e:
  print(f"✗ Error: {{e}}")
"""

  result = subprocess.run(
    ["sudo", ".venv/bin/python3", "-c", test_script],
    capture_output=True,
    text=True
  )

  print(result.stdout)
  if result.stderr:
    print("Errors:", result.stderr)

  return result.returncode == 0


def list_alternative_devices():
  """List all possible I2C devices"""
  print("\n" + "="*60)
  print("Searching for I2C Devices")
  print("="*60)

  # Check /dev/i2c-*
  print("\nStandard I2C buses (/dev/i2c-*):")
  for i in range(20):
    dev = f"/dev/i2c-{i}"
    if os.path.exists(dev):
      print(f"  {dev}")

  # Check CH347 devices
  print("\nCH347 devices (/dev/ch34x_*):")
  for dev in os.listdir("/dev"):
    if dev.startswith("ch34x_"):
      full_path = f"/dev/{dev}"
      perms = "rw" if os.access(full_path, os.R_OK | os.W_OK) else "no-access"
      print(f"  {full_path} ({perms})")

  # Check USB devices
  print("\nUSB devices (CH347):")
  result = os.popen("lsusb | grep -i 1a86").read()
  if result:
    print(f"  {result.strip()}")


def main():
  print("\nCH347 I2C Interface Test Suite")
  print("="*60)

  # Test 1: Device access
  if not test_device_access():
    print("\n✗ Cannot access CH347 device")
    print("\nRecommended actions:")
    print("  1. Check permissions: sudo chmod 666 /dev/ch34x_pis1")
    print("  2. Add user to dialout group: sudo usermod -aG dialout $USER")
    print("  3. Verify driver: lsmod | grep ch34")
    list_alternative_devices()
    return 1

  # Test 2: Basic I/O
  if not test_basic_io():
    print("\n✗ Basic I/O test failed")
    return 1

  # Test 3: I2C scan
  bus_num = test_i2c_scan()

  # Test 4: CH347 interface
  test_ch347_interface()

  # Test 5: Try with sudo
  test_with_sudo()

  # Summary
  print("\n" + "="*60)
  print("TEST SUMMARY")
  print("="*60)

  if bus_num is not None:
    print(f"✓ LSM6DS3 found on I2C bus {bus_num}")
    print(f"\nTo test sensor:")
    print(f"  python3 system/sensord_ch347/test_sensord_ch347.py --bus {bus_num} --verbose")
    return 0
  else:
    print("✗ LSM6DS3 not found via standard I2C interface")
    print("\nCH347 might require:")
    print("  1. Vendor-specific library (libch347.so)")
    print("  2. Custom ioctl commands")
    print("  3. Different device interface")
    print("\nPlease check CH347 driver documentation for I2C API details")
    return 1


if __name__ == "__main__":
  exit(main())
