#!/usr/bin/env python3
"""
传感器轴方向手动测试工具 - 立式安装版本

使用方法:
  1. 将传感器立式安装（就像装在设备里那样）
  2. 运行此脚本
  3. 按照提示依次沿各方向晃动/倾斜传感器
  4. 脚本会自动判断每个芯片轴对应的物理方向

前提: CH347 I2C 总线已经可用 (已加载驱动)
运行: cd /data/carrot2-v9-1215-acc && source .venv/bin/activate && python3 system/sensord_ch347/test_axis_direction.py
"""

import sys
import time
import ctypes
import numpy as np

sys.path.insert(0, '/data/carrot2-v9-1215-acc')


def find_i2c_bus():
  """自动查找 CH347 I2C 总线"""
  import glob
  import os

  for path in glob.glob("/sys/bus/i2c/devices/i2c-*/name"):
    try:
      with open(path) as f:
        if "ch347" in f.read().lower():
          bus_num = int(os.path.basename(os.path.dirname(path)).split("-")[1])
          return bus_num
    except Exception:
      pass
  for bus in [1, 2, 3, 4, 5, 6, 7, 8]:
    try:
      import smbus2

      b = smbus2.SMBus(bus)
      chip_id = b.read_byte_data(0x6B, 0x0F)
      b.close()
      if chip_id in [0x69, 0x6A]:
        return bus
    except Exception:
      pass
    try:
      import smbus2

      b = smbus2.SMBus(bus)
      chip_id = b.read_byte_data(0x6A, 0x0F)
      b.close()
      if chip_id in [0x69, 0x6A]:
        return bus
    except Exception:
      pass
  return None


def init_sensor(bus, addr):
  """初始化 LSM6DS3 加速度计"""
  import smbus2

  b = smbus2.SMBus(bus)
  b.write_byte_data(addr, 0x12, 0x01)
  time.sleep(0.1)
  b.write_byte_data(addr, 0x12, 0x04)
  b.write_byte_data(addr, 0x10, 0b01000000)
  time.sleep(0.05)
  return b


def read_accel_raw(bus_handle, addr):
  """读取原始加速度 (x, y, z) 单位 m/s^2"""
  scale = 9.81 * 2.0 / (1 << 15)
  data = bytes(bus_handle.read_i2c_block_data(addr, 0x28, 6))
  x = ctypes.c_int16((data[1] << 8) | data[0]).value * scale
  y = ctypes.c_int16((data[3] << 8) | data[2]).value * scale
  z = ctypes.c_int16((data[5] << 8) | data[4]).value * scale
  return x, y, z


def read_gyro_raw(bus_handle, addr):
  """读取原始陀螺仪 (x, y, z) 单位 deg/s"""
  scale = 8.75 / 1000.0
  data = bytes(bus_handle.read_i2c_block_data(addr, 0x22, 6))
  x = ctypes.c_int16((data[1] << 8) | data[0]).value * scale
  y = ctypes.c_int16((data[3] << 8) | data[2]).value * scale
  z = ctypes.c_int16((data[5] << 8) | data[4]).value * scale
  return x, y, z


def collect_samples(bus_handle, addr, duration=2.0, sensor='accel'):
  """采集一段时间的数据"""
  samples = []
  t_end = time.time() + duration
  while time.time() < t_end:
    if sensor == 'accel':
      samples.append(read_accel_raw(bus_handle, addr))
    else:
      samples.append(read_gyro_raw(bus_handle, addr))
    time.sleep(0.02)
  return np.array(samples)


def main():
  print("=" * 60)
  print("  LSM6DS3 传感器轴方向手动测试工具 - 立式安装版")
  print("=" * 60)
  print()

  bus_num = find_i2c_bus()
  if bus_num is None:
    print("ERROR: 找不到 CH347 I2C 总线或 LSM6DS3 芯片!")
    print("请确认:")
    print("  1. CH347 USB 已连接")
    print("  2. 驱动已加载 (ls /dev/i2c-*)")
    sys.exit(1)

  print(f"找到 I2C 总线: /dev/i2c-{bus_num}")

  addr = 0x6B
  try:
    b = init_sensor(bus_num, addr)
    x, y, z = read_accel_raw(b, addr)
    print(f"传感器地址: 0x{addr:02X}, 读数正常: x={x:.2f} y={y:.2f} z={z:.2f}")
  except Exception:
    addr = 0x6A
    try:
      b = init_sensor(bus_num, addr)
      x, y, z = read_accel_raw(b, addr)
      print(f"传感器地址: 0x{addr:02X}, 读数正常: x={x:.2f} y={y:.2f} z={z:.2f}")
    except Exception as e:
      print(f"ERROR: 无法读取传感器: {e}")
      sys.exit(1)

  b.write_byte_data(addr, 0x11, 0b01000000)
  time.sleep(0.05)

  print()
  print("-" * 60)
  print("立式安装测试开始！请按照提示操作传感器。")
  print("立式安装：传感器像装在设备里一样竖立着")
  print("-" * 60)

  results = {}

  # ====== Step 1: 确定"上"方向 ======
  print()
  print("[Step 1] 确定重力方向（相当于平躺时的Z+）")
  print("  将传感器立式放置，保持静止")
  print("  观察哪个轴读数最大（绝对值）")
  input("  准备好后按 Enter...")
  print("  采集中 (2秒)...")
  baseline = collect_samples(b, addr, 2.0, 'accel')
  bx, by, bz = baseline.mean(axis=0)
  print(f"  基准读数: X={bx:.3f}, Y={by:.3f}, Z={bz:.3f} m/s^2")

  abs_vals = [abs(bx), abs(by), abs(bz)]
  max_idx = np.argmax(abs_vals)
  max_val = [bx, by, bz][max_idx]
  axis_names = ['X', 'Y', 'Z']

  print(f"  -> {axis_names[max_idx]} 轴绝对值最大 ({abs_vals[max_idx]:.2f})")

  # 确定"上"方向（重力方向）
  if max_val > 0:
    up_axis = f'+{axis_names[max_idx]}'
    up_sign = +1
  else:
    up_axis = f'-{axis_names[max_idx]}'
    up_sign = -1

  print(f"  -> 立式安装的'上' = 芯片 {up_axis}")
  results['UP'] = (up_axis, max_val)

  print()
  print("  现在保持传感器立式，放置稳固")
  input("  按 Enter 继续...")

  # ====== Step 2: 确定"前"方向 ======
  print()
  print("[Step 2] 确定前方向（车辆前进方向）")
  print("  将传感器沿前进方向倾斜约30-45度")
  print("  (相当于测试哪个轴对应前进方向)")
  input("  倾斜后保持住，按 Enter...")
  print("  采集中 (2秒)...")
  forward_tilt = collect_samples(b, addr, 2.0, 'accel')
  fx, fy, fz = forward_tilt.mean(axis=0)
  print(f"  读数: X={fx:.3f}, Y={fy:.3f}, Z={fz:.3f}")

  # 计算变化
  dx = fx - bx
  dy = fy - by
  dz = fz - bz
  print(f"  变化: dX={dx:.3f}, dY={dy:.3f}, dZ={dz:.3f}")

  # 找变化最大的水平轴（排除已经识别为"上"的轴）
  candidates = []
  for i, name in enumerate(['X', 'Y', 'Z']):
    if name != axis_names[max_idx]:
      candidates.append((abs([dx, dy, dz][i]), name, [dx, dy, dz][i]))
  candidates.sort(reverse=True)

  best = candidates[0]
  print(f"  -> 变化最大: {best[1]}轴, 变化={best[2]:.3f}")

  if best[2] < -0.5:
    fwd_axis = f'+{best[1]}'
    print(f"  -> 结论: 芯片 {best[1]}+ = 前方 (FWD)")
  elif best[2] > 0.5:
    fwd_axis = f'-{best[1]}'
    print(f"  -> 结论: 芯片 {best[1]}- = 前方")
  else:
    print(f"  -> 变化太小，请倾斜大一点再试!")
    fwd_axis = '???'

  results['FORWARD'] = (fwd_axis, best[2])

  print()
  print("  恢复传感器到立式正立状态")
  input("  恢复后按 Enter...")

  # ====== Step 3: 确定"右"方向 ======
  print()
  print("[Step 3] 确定右方向（车辆右侧）")
  print("  将传感器沿右侧方向倾斜约30-45度")
  input("  倾斜后保持住，按 Enter...")
  print("  采集中 (2秒)...")
  right_tilt = collect_samples(b, addr, 2.0, 'accel')
  rx, ry, rz = right_tilt.mean(axis=0)
  print(f"  读数: X={rx:.3f}, Y={ry:.3f}, Z={rz:.3f}")

  dx2 = rx - bx
  dy2 = ry - by
  dz2 = rz - bz
  print(f"  变化: dX={dx2:.3f}, dY={dy2:.3f}, dZ={dz2:.3f}")

  # 找变化最大的水平轴
  candidates2 = []
  for i, name in enumerate(['X', 'Y', 'Z']):
    if name != axis_names[max_idx]:
      candidates2.append((abs([dx2, dy2, dz2][i]), name, [dx2, dy2, dz2][i]))
  candidates2.sort(reverse=True)

  best2 = candidates2[0]
  print(f"  -> 变化最大: {best2[1]}轴, 变化={best2[2]:.3f}")

  if best2[2] < -0.5:
    right_axis = f'+{best2[1]}'
    print(f"  -> 结论: 芯片 {best2[1]}+ = 右侧 (RIGHT)")
  elif best2[2] > 0.5:
    right_axis = f'-{best2[1]}'
    print(f"  -> 结论: 芯片 {best2[1]}- = 右侧")
  else:
    print(f"  -> 变化太小，请倾斜大一点再试!")
    right_axis = '???'

  results['RIGHT'] = (right_axis, best2[2])

  print()
  print("  恢复传感器到立式正立状态")
  input("  按 Enter 继续...")

  # ====== Step 4: 陀螺仪测试 ======
  print()
  print("[Step 4] 测试陀螺仪偏航方向 (可选)")
  print("  保持传感器立式，用手沿顺时针方向旋转（向右转）")
  input("  开始转动时按 Enter (持续转2秒)...")
  print("  采集中 (2秒)...")
  yaw_right = collect_samples(b, addr, 2.0, 'gyro')
  gx, gy, gz = yaw_right.mean(axis=0)
  print(f"  陀螺仪读数: gX={gx:.2f}, gY={gy:.2f}, gZ={gz:.2f} deg/s")

  gyro_vals = [abs(gx), abs(gy), abs(gz)]
  max_gyro_idx = np.argmax(gyro_vals)
  max_gyro_val = [gx, gy, gz][max_gyro_idx]
  print(f"  -> 变化最大: {axis_names[max_gyro_idx]}轴 = {max_gyro_val:.2f} deg/s")

  if abs(max_gyro_val) > 5:
    if max_gyro_val > 0:
      results['YAW_CW'] = (f'+{axis_names[max_gyro_idx]}', max_gyro_val)
      print(f"  -> 结论: 顺时针(CW)时 {axis_names[max_gyro_idx]} 为正")
    else:
      results['YAW_CW'] = (f'-{axis_names[max_gyro_idx]}', max_gyro_val)
      print(f"  -> 结论: 顺时针(CW)时 {axis_names[max_gyro_idx]} 为负")
  else:
    print(f"  -> 转速太小，请转快一点")
    results['YAW_CW'] = ('???', max_gyro_val)

  # ====== 总结 ======
  print()
  print("=" * 60)
  print("  测试结果总结")
  print("=" * 60)
  print()
  for direction, (axis, val) in results.items():
    print(f"  {direction:12s} = 芯片 {axis:4s} (测量值: {val:.3f})")
  print()

  # 推导正确映射
  print("-" * 60)
  print("  正确的代码映射推导")
  print("-" * 60)
  print()
  print("  openpilot locationd 期望:")
  print("    meas = [-v[2], -v[1], -v[0]]")
  print("    meas[0] = 后方(backward)")
  print("    meas[1] = 左方(leftward)")
  print("    meas[2] = 下方(downward)")
  print()

  if 'FORWARD' in results and 'RIGHT' in results and 'UP' in results:
    up_axis = results['UP'][0]
    fwd_axis = results['FORWARD'][0]
    right_axis = results['RIGHT'][0]

    print(f"  物理方向 → 芯片轴:")
    print(f"    上(UP)    = {up_axis}")
    print(f"    前(FWD)   = {fwd_axis}")
    print(f"    右(RIGHT) = {right_axis}")
    print()

    def axis_to_expr(direction_result, negate=False):
      """将 '+X' 或 '-Y' 转为代码表达式"""
      sign = direction_result[0]
      name = direction_result[1].lower()
      if negate:
        sign = '-' if sign == '+' else '+'
      if sign == '+':
        return name
      else:
        return f'-{name}'

    backward = axis_to_expr(fwd_axis, negate=True)
    leftward = axis_to_expr(right_axis, negate=True)
    downward = axis_to_expr(up_axis, negate=True)

    v0 = axis_to_expr(up_axis, negate=False)
    v1 = axis_to_expr(right_axis, negate=False)
    v2 = axis_to_expr(fwd_axis, negate=False)

    print(f"  ┌─────────────────────────────────────────────┐")
    print(f"  │ 正确映射 (加速度计):                         │")
    print(f"  │   a.v = [{v0}, {v1}, {v2}]")
    print(f"  └─────────────────────────────────────────────┘")
    print()
    print(f"  验证: meas = [-v[2], -v[1], -v[0]]")
    print(f"       = [-({v2}), -({v1}), -({v0})]")
    print(f"       = [{backward}, {leftward}, {downward}]")
    print(f"       = [后, 左, 下] ✓")

    # 陀螺仪映射
    if 'YAW_CW' in results and results['YAW_CW'][0] != '???':
      yaw_axis = results['YAW_CW'][0]
      # 陀螺仪需要确保旋转方向正确
      print()
      print(f"  ┌─────────────────────────────────────────────┐")
      print(f"  │ 陀螺仪映射 (如果需要调整):                    │")
      print(f"  │ 当前: xyz = [{v0}*scale, {v1}*scale, {v2}*scale]")
      print(f"  │ 可能需要交换X/Y或添加负号来匹配              │")
      print(f"  └─────────────────────────────────────────────┘")

  b.close()
  print()
  print("测试完成！")


if __name__ == "__main__":
  main()
