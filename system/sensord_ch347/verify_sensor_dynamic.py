#!/usr/bin/env python3
"""
传感器动态验证脚本 - 手动晃动测试
用于离线验证 locationd 输出的物理合理性

物理预期:
- 静止时: X≈0, Y≈0, Z≈-9.81
- 向前加速: X>0, Z 减小 (重力向后)
- 向前急刹: X<0, Z 增大 (重力向前)
- 静止水平: X≈0, Y≈0, Z≈-9.81
"""

import sys
import time

sys.path.insert(0, '/data/carrot2-v9-acc')
from openpilot.system.sensord_ch347.sensors.lsm6ds3_accel import LSM6DS3_Accel
from openpilot.system.sensord_ch347.sensors.lsm6ds3_gyro import LSM6DS3_Gyro


def main():
  BUS = 7  # CH347 I2C 总线

  print("=" * 60)
  print("传感器动态验证 - 手动晃动测试")
  print("=" * 60)
  print(f"\nI2C 总线: {BUS}")
  print("\n物理预期:")
  print("  静止时: X≈0, Y≈0, Z≈-9.81")
  print("  向前加速: X>0  向前急刹: X<0")
  print("  向左转: Y>0  向右转: Y<0")
  print("\n开始监控... (Ctrl+C 退出)\n")

  accel = LSM6DS3_Accel(BUS)
  accel.init()
  gyro = LSM6DS3_Gyro(BUS)
  gyro.init()
  time.sleep(0.5)

  print("-" * 60)

  try:
    while True:
      try:
        a_evt = accel.get_event()
        a_v = a_evt.acceleration.v
        a_meas = [-a_v[2], -a_v[1], -a_v[0]]

        g_evt = gyro.get_event()
        g_v = g_evt.gyroUncalibrated.v
        g_meas = [-g_v[2], -g_v[1], -g_v[0]]

        # 状态判断
        states = []
        if abs(a_meas[2] + 9.81) < 1.5:
          states.append("Z✓")
        if abs(a_meas[0]) < 2.0:
          states.append("X静")
        if abs(a_meas[1]) < 2.0:
          states.append("Y静")

        status = " ".join(states) if states else "⚠️"

        print(
          f"\r[{status}] accel: [{a_meas[0]:7.2f}, {a_meas[1]:7.2f}, {a_meas[2]:7.2f}]  gyro: [{g_meas[0]:6.2f}, {g_meas[1]:6.2f}, {g_meas[2]:6.2f}]     ",
          end="",
          flush=True,
        )

      except Exception as e:
        print(f"\n错误: {e}")

      time.sleep(0.08)  # ~12Hz 刷新

  except KeyboardInterrupt:
    print("\n\n" + "=" * 60)
    print("测试完成")
    print("=" * 60)
    print("\n验证标准:")
    print("  ✓ Z轴 应在 -9.81 附近 (重力向上)")
    print("  ✓ 晃动时 X轴 会有明显变化")
    print("  ✓ 转向时 Y轴 会有明显变化")


if __name__ == "__main__":
  main()
