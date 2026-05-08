#!/usr/bin/env python3
"""
Test script for sensord_ch347 - LSM6DS3 IMU sensor data validation

This script tests:
1. I2C bus accessibility
2. Chip ID verification
3. Accelerometer data reading
4. Gyroscope data reading
5. Data validity and frequency check

Usage:
  python3 test_sensord_ch347.py [--bus N] [--count N] [--verbose]
"""
import argparse
import time
import sys

from openpilot.system.sensord_ch347.sensors.lsm6ds3_accel import LSM6DS3_Accel
from openpilot.system.sensord_ch347.sensors.lsm6ds3_gyro import LSM6DS3_Gyro


def test_acceleration(sensor: LSM6DS3_Accel, count: int = 10, verbose: bool = False):
  """Test accelerometer data reading"""
  print("\n" + "="*60)
  print("Testing Accelerometer")
  print("="*60)

  success_count = 0
  fail_count = 0
  timestamps = []

  for i in range(count):
    try:
      ts_before = time.time_ns()
      event = sensor.get_event()
      ts_after = time.time_ns()

      accel = event.acceleration
      timestamps.append((ts_after - ts_before) / 1e6)  # Convert to ms

      if verbose:
        print(f"[{i+1:3d}] ax={accel.v[0]:8.3f} m/s²  "
              f"ay={accel.v[1]:8.3f} m/s²  "
              f"az={accel.v[2]:8.3f} m/s²  "
              f"latency={(ts_after - ts_before)/1e6:.2f}ms")

      success_count += 1
      time.sleep(0.01)  # 10ms delay between reads

    except sensor.DataNotReady:
      if verbose:
        print(f"[{i+1:3d}] Data not ready, skipping...")
      fail_count += 1
      time.sleep(0.01)
    except Exception as e:
      print(f"[{i+1:3d}] ERROR: {e}")
      fail_count += 1
      time.sleep(0.01)

  # Summary
  print(f"\nResults: {success_count}/{count} successful, {fail_count} failed")

  if timestamps:
    avg_latency = sum(timestamps) / len(timestamps)
    max_latency = max(timestamps)
    min_latency = min(timestamps)
    print(f"Latency: avg={avg_latency:.2f}ms, min={min_latency:.2f}ms, max={max_latency:.2f}ms")

  # Check gravity magnitude (should be ~9.81 m/s² when stationary)
  if success_count > 0:
    try:
      event = sensor.get_event()
      accel = event.acceleration
      gravity_mag = (accel.v[0]**2 + accel.v[1]**2 + accel.v[2]**2) ** 0.5
      print(f"Gravity magnitude: {gravity_mag:.3f} m/s² (expected ~9.81)")

      if 8.0 < gravity_mag < 11.0:
        print("✓ Gravity check PASSED")
      else:
        print("✗ Gravity check FAILED - sensor may be moving or malfunctioning")
    except Exception as e:
      print(f"✗ Could not verify gravity: {e}")

  return success_count > 0


def test_gyroscope(sensor: LSM6DS3_Gyro, count: int = 10, verbose: bool = False):
  """Test gyroscope data reading"""
  print("\n" + "="*60)
  print("Testing Gyroscope")
  print("="*60)

  success_count = 0
  fail_count = 0
  timestamps = []

  for i in range(count):
    try:
      ts_before = time.time_ns()
      event = sensor.get_event()
      ts_after = time.time_ns()

      gyro = event.gyroUncalibrated
      timestamps.append((ts_after - ts_before) / 1e6)  # Convert to ms

      if verbose:
        print(f"[{i+1:3d}] wx={gyro.v[0]:10.6f} rad/s  "
              f"wy={gyro.v[1]:10.6f} rad/s  "
              f"wz={gyro.v[2]:10.6f} rad/s  "
              f"latency={(ts_after - ts_before)/1e6:.2f}ms")

      success_count += 1
      time.sleep(0.01)  # 10ms delay between reads

    except sensor.DataNotReady:
      if verbose:
        print(f"[{i+1:3d}] Data not ready, skipping...")
      fail_count += 1
      time.sleep(0.01)
    except Exception as e:
      print(f"[{i+1:3d}] ERROR: {e}")
      fail_count += 1
      time.sleep(0.01)

  # Summary
  print(f"\nResults: {success_count}/{count} successful, {fail_count} failed")

  if timestamps:
    avg_latency = sum(timestamps) / len(timestamps)
    max_latency = max(timestamps)
    min_latency = min(timestamps)
    print(f"Latency: avg={avg_latency:.2f}ms, min={min_latency:.2f}ms, max={max_latency:.2f}ms")

  # Check if gyroscope values are near zero when stationary
  if success_count > 0:
    try:
      event = sensor.get_event()
      gyro = event.gyroUncalibrated
      gyro_mag = (gyro.v[0]**2 + gyro.v[1]**2 + gyro.v[2]**2) ** 0.5
      print(f"Gyroscope magnitude: {gyro_mag:.6f} rad/s (expected ~0 when stationary)")

      # Convert to deg/s for easier reading
      gyro_mag_dps = gyro_mag * 180.0 / 3.14159
      print(f"Gyroscope magnitude: {gyro_mag_dps:.3f} °/s")

      if gyro_mag_dps < 5.0:
        print("✓ Stationary check PASSED")
      else:
        print("⚠ Gyroscope shows movement - sensor may be vibrating")
    except Exception as e:
      print(f"✗ Could not verify gyroscope: {e}")

  return success_count > 0


def test_data_frequency(sensor, sensor_type: str, duration: float = 5.0, verbose: bool = False):
  """Test actual data output frequency"""
  print(f"\n{'='*60}")
  print(f"Testing {sensor_type} Output Frequency ({duration:.1f}s)")
  print(f"{'='*60}")

  start_time = time.monotonic()
  data_count = 0
  error_count = 0

  while time.monotonic() - start_time < duration:
    try:
      sensor.get_event()
      data_count += 1
    except sensor.DataNotReady:
      pass
    except Exception as e:
      error_count += 1
      if verbose:
        print(f"ERROR: {e}")

  actual_duration = time.monotonic() - start_time
  frequency = data_count / actual_duration if actual_duration > 0 else 0

  print(f"Data points collected: {data_count}")
  print(f"Duration: {actual_duration:.2f}s")
  print(f"Actual frequency: {frequency:.1f} Hz")
  print(f"Errors: {error_count}")

  # Check if frequency is reasonable (LSM6DS3 configured at 104Hz)
  if frequency > 50:
    print(f"✓ Frequency check PASSED (>{50}Hz)")
  elif frequency > 20:
    print(f"⚠ Frequency lower than expected (<{50}Hz) - may indicate I2C bus issues")
  else:
    print(f"✗ Frequency too low (<{20}Hz) - sensor or I2C bus may have problems")

  return frequency


def main():
  parser = argparse.ArgumentParser(description="Test LSM6DS3 IMU sensors via CH347 I2C adapter")
  parser.add_argument("--bus", type=int, default=1,
                      help="I2C bus number (default: 1)")
  parser.add_argument("--count", type=int, default=10,
                      help="Number of samples to collect (default: 10)")
  parser.add_argument("--freq-duration", type=float, default=5.0,
                      help="Duration in seconds for frequency test (default: 5.0)")
  parser.add_argument("--verbose", action="store_true",
                      help="Enable verbose output")
  args = parser.parse_args()

  print("LSM6DS3 IMU Sensor Test Suite")
  print(f"I2C Bus: {args.bus} (/dev/i2c-{args.bus})")
  print("="*60)

  # Initialize sensors
  print("\nInitializing sensors...")
  try:
    accel = LSM6DS3_Accel(args.bus)
    print(f"✓ Accelerometer created (I2C address: 0x{accel.device_address:02X})")
  except Exception as e:
    print(f"✗ Failed to create accelerometer: {e}")
    sys.exit(1)

  try:
    gyro = LSM6DS3_Gyro(args.bus)
    print(f"✓ Gyroscope created (I2C address: 0x{gyro.device_address:02X})")
  except Exception as e:
    print(f"✗ Failed to create gyroscope: {e}")
    sys.exit(1)

  # Reset sensors
  print("\nResetting sensors...")
  try:
    accel.reset()
    gyro.reset()
    print("✓ Sensors reset successfully")
  except Exception as e:
    print(f"✗ Failed to reset sensors: {e}")
    sys.exit(1)

  # Initialize sensors (this verifies chip ID)
  print("\nInitializing sensors (chip ID verification)...")
  try:
    accel.init()
    print(f"✓ Accelerometer initialized (source: {accel.source})")
  except Exception as e:
    print(f"✗ Failed to initialize accelerometer: {e}")
    sys.exit(1)

  try:
    gyro.init()
    print(f"✓ Gyroscope initialized (source: {gyro.source})")
  except Exception as e:
    print(f"✗ Failed to initialize gyroscope: {e}")
    sys.exit(1)

  # Run tests
  accel_ok = test_acceleration(accel, count=args.count, verbose=args.verbose)
  gyro_ok = test_gyroscope(gyro, count=args.count, verbose=args.verbose)

  # Test frequency
  freq_accel = test_data_frequency(accel, "Accelerometer",
                                    duration=args.freq_duration,
                                    verbose=args.verbose)
  freq_gyro = test_data_frequency(gyro, "Gyroscope",
                                   duration=args.freq_duration,
                                   verbose=args.verbose)

  # Shutdown
  print("\n" + "="*60)
  print("Shutting down sensors...")
  try:
    accel.shutdown()
    gyro.shutdown()
    print("✓ Sensors shut down successfully")
  except Exception as e:
    print(f"✗ Error during shutdown: {e}")

  # Final summary
  print("\n" + "="*60)
  print("TEST SUMMARY")
  print("="*60)
  print(f"Accelerometer: {'✓ PASSED' if accel_ok else '✗ FAILED'}")
  print(f"Gyroscope:     {'✓ PASSED' if gyro_ok else '✗ FAILED'}")
  print(f"Accel Freq:    {freq_accel:.1f} Hz {'✓' if freq_accel > 50 else '⚠' if freq_accel > 20 else '✗'}")
  print(f"Gyro Freq:     {freq_gyro:.1f} Hz {'✓' if freq_gyro > 50 else '⚠' if freq_gyro > 20 else '✗'}")
  print("="*60)

  if accel_ok and gyro_ok and freq_accel > 20 and freq_gyro > 20:
    print("\n✓ All tests PASSED - Sensors are working correctly")
    sys.exit(0)
  else:
    print("\n✗ Some tests FAILED - Check I2C connection and sensor hardware")
    sys.exit(1)


if __name__ == "__main__":
  main()
