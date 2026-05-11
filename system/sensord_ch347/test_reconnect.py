#!/usr/bin/env python3
"""
test_reconnect.py - 测试 CH347 设备丢失后的自动重连功能

使用方法:
  # 正常运行测试 (模拟设备丢失)
  python3 test_reconnect.py

  # 只测试 reconnect() 方法
  python3 test_reconnect.py --test-reconnect-only

  # 指定总线号
  python3 test_reconnect.py --bus 7
"""

import argparse
import sys
import time

from openpilot.system.sensord_ch347.sensors.lsm6ds3_accel import LSM6DS3_Accel
from openpilot.system.sensord_ch347.sensors.lsm6ds3_gyro import LSM6DS3_Gyro


def test_reconnect_method(bus: int):
  """测试 reconnect() 方法是否能正确重建连接"""
  print("=" * 60)
  print("测试 1: reconnect() 方法")
  print("=" * 60)

  sensor = LSM6DS3_Accel(bus)

  try:
    # 初始化传感器
    print("\n[步骤 1] 初始化传感器...")
    sensor.init()
    print("✓ 传感器初始化成功")

    # 读取一次数据
    print("\n[步骤 2] 读取传感器数据...")
    # 可能需要等待数据就绪
    for i in range(5):
      try:
        evt = sensor.get_event()
        print(f"✓ 数据读取成功: accel={evt.acceleration.v}")
        break
      except sensor.DataNotReady:
        if i < 4:
          time.sleep(0.1)
        else:
          print("✗ 数据未就绪 (超时)")
          raise

    # 测试重连 (正常情况下应该成功)
    print("\n[步骤 3] 测试重连...")
    success = sensor.reconnect()
    print(f"{'✓' if success else '✗'} 重连{'成功' if success else '失败'}")

    if success:
      # 重连后需要重新初始化
      print("\n[步骤 4] 重连后重新初始化...")
      sensor.init()
      evt = sensor.get_event()
      print(f"✓ 重连后数据读取成功: accel={evt.acceleration.v}")

  except Exception as e:
    print(f"\n✗ 测试失败: {e}")
    import traceback

    traceback.print_exc()
  finally:
    try:
      sensor.shutdown()
    except Exception:
      pass
    try:
      sensor.bus.close()
    except Exception:
      pass

  print("\n" + "=" * 60)


def simulate_reconnect_from_error(bus: int):
  """模拟从设备丢失状态恢复"""
  print("=" * 60)
  print("测试 2: 模拟设备丢失后恢复")
  print("=" * 60)

  sensor = LSM6DS3_Gyro(bus)

  print("\n[步骤 1] 初始化陀螺仪...")
  sensor.init()
  print("✓ 初始化成功")

  # 模拟关闭连接 (模拟设备丢失)
  print("\n[步骤 2] 模拟设备丢失 (关闭 I2C 连接)...")
  sensor.bus.close()

  # 尝试读取 (应该失败)
  print("\n[步骤 3] 尝试读取 (预期失败)...")
  try:
    sensor.get_event()
    print("✗ 预期应该失败但却成功了")
  except (OSError, TypeError) as e:
    # OSError: 设备节点不存在
    # TypeError: bus.fd 已关闭 (fileno() 无效)
    print(f"✓ 如预期失败: {type(e).__name__}: {e}")

  # 测试重连
  print("\n[步骤 4] 测试自动重连...")
  reconnect_success = sensor.reconnect()

  if reconnect_success:
    print("✓ 重连成功")

    # 重新初始化
    print("\n[步骤 5] 重新初始化传感器...")
    sensor.init()

    # 验证可以正常读取
    print("\n[步骤 6] 验证数据读取...")
    evt = sensor.get_event()
    print(f"✓ 数据读取成功: gyro={evt.gyroUncalibrated.v}")
  else:
    print("✗ 重连失败 (设备可能真的不在了)")

  try:
    sensor.shutdown()
  except Exception:
    pass
  try:
    sensor.bus.close()
  except Exception:
    pass

  print("\n" + "=" * 60)


def main():
  parser = argparse.ArgumentParser(description="测试自动重连功能")
  parser.add_argument("--bus", type=int, default=None, help="I2C 总线号")
  parser.add_argument("--test-reconnect-only", action="store_true", help="只测试 reconnect() 方法")
  args = parser.parse_args()

  # 自动检测总线
  if args.bus is None:
    from openpilot.system.sensord_ch347.sensord_ch347 import detect_ch347_bus

    args.bus = detect_ch347_bus()
    if args.bus is None:
      print("✗ 错误: 未找到 CH347 设备，请指定 --bus 参数")
      sys.exit(1)

  print(f"使用 I2C 总线: {args.bus}\n")

  if args.test_reconnect_only:
    test_reconnect_method(args.bus)
  else:
    test_reconnect_method(args.bus)
    print()
    simulate_reconnect_from_error(args.bus)

  print("\n✓ 所有测试完成")


if __name__ == "__main__":
  main()
