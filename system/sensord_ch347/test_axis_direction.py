#!/usr/bin/env python3
"""
传感器轴方向手动测试工具

使用方法:
  1. 将传感器平放在桌面上（芯片朝上）
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
  # 尝试从 /sys/bus/i2c/devices 找 ch347
  for path in glob.glob("/sys/bus/i2c/devices/i2c-*/name"):
    try:
      with open(path) as f:
        if "ch347" in f.read().lower():
          bus_num = int(os.path.basename(os.path.dirname(path)).split("-")[1])
          return bus_num
    except Exception:
      pass
  # 尝试常见总线号
  for bus in [1, 2, 3, 4, 5, 6, 7, 8]:
    try:
      import smbus2
      b = smbus2.SMBus(bus)
      # 尝试读取 LSM6DS3 WHO_AM_I
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
  # Reset
  b.write_byte_data(addr, 0x12, 0x01)
  time.sleep(0.1)
  # Enable IF_INC
  b.write_byte_data(addr, 0x12, 0x04)
  # ODR 104Hz, ±2g
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
  scale = 8.75 / 1000.0  # deg/s per LSB at ±250dps
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
  print("  LSM6DS3 传感器轴方向手动测试工具")
  print("=" * 60)
  print()

  # 查找总线
  bus_num = find_i2c_bus()
  if bus_num is None:
    print("ERROR: 找不到 CH347 I2C 总线或 LSM6DS3 芯片!")
    print("请确认:")
    print("  1. CH347 USB 已连接")
    print("  2. 驱动已加载 (ls /dev/i2c-*)")
    sys.exit(1)

  print(f"找到 I2C 总线: /dev/i2c-{bus_num}")

  # 确定地址
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

  # 也初始化陀螺仪 (ODR 104Hz)
  b.write_byte_data(addr, 0x11, 0b01000000)
  time.sleep(0.05)

  print()
  print("-" * 60)
  print("测试开始！请按照提示操作传感器。")
  print("每步操作后按 Enter 确认。")
  print("-" * 60)

  results = {}

  # ====== Step 1: 静止基准 ======
  print()
  print("[Step 1] 将传感器平放在桌面上（芯片/元件面朝上），保持静止")
  input("  准备好后按 Enter...")
  print("  采集中 (2秒)...")
  baseline = collect_samples(b, addr, 2.0, 'accel')
  bx, by, bz = baseline.mean(axis=0)
  print(f"  基准读数: X={bx:.3f}, Y={by:.3f}, Z={bz:.3f} m/s^2")
  print(f"  (Z轴应约为 +9.81)")

  # 确定Z轴方向
  max_axis = np.argmax(np.abs([bx, by, bz]))
  max_val = [bx, by, bz][max_axis]
  axis_names = ['X', 'Y', 'Z']
  print(f"  -> {axis_names[max_axis]} 轴读数最大 ({max_val:.2f})")

  if max_axis == 2 and max_val > 9.0:
    print(f"  -> 确认: 芯片 Z+ 朝上 (重力方向)")
    results['UP'] = ('+Z', bz)
  elif max_axis == 2 and max_val < -9.0:
    print(f"  -> 确认: 芯片 Z- 朝上 (Z+朝下)")
    results['UP'] = ('-Z', bz)
  elif max_axis == 0:
    if max_val > 0:
      results['UP'] = ('+X', bx)
    else:
      results['UP'] = ('-X', bx)
    print(f"  -> 注意: 重力在X轴! 传感器可能不是平放的")
  elif max_axis == 1:
    if max_val > 0:
      results['UP'] = ('+Y', by)
    else:
      results['UP'] = ('-Y', by)
    print(f"  -> 注意: 重力在Y轴! 传感器可能不是平放的")

  # ====== Step 2: 测试前后方向 ======
  print()
  print("[Step 2] 确定前后(Y)方向")
  print("  将传感器的【车辆前进方向】那一端缓慢抬起约30-45度")
  print("  (后端保持在桌面上，前端翘起)")
  input("  抬起后保持住，按 Enter...")
  print("  采集中 (2秒)...")
  forward_up = collect_samples(b, addr, 2.0, 'accel')
  fx, fy, fz = forward_up.mean(axis=0)
  print(f"  读数: X={fx:.3f}, Y={fy:.3f}, Z={fz:.3f}")

  # 前端抬起时，重力在前方向的分量增加(正值=前端高)
  # 比较与基准的差异
  dx = fx - bx
  dy = fy - by
  dz = fz - bz
  print(f"  变化: dX={dx:.3f}, dY={dy:.3f}, dZ={dz:.3f}")

  # 找XY平面中变化最大的轴（Z轴变化主要是因为倾斜后Z分量减小）
  # 前端抬起时，水平面分量中应该有一个轴读数明显变负（重力向后方投影）
  # 或者说：前端抬起 → 重力有向后的分量 → 朝后的轴读正值
  candidates = [(abs(dx), 'X', dx), (abs(dy), 'Y', dy)]
  candidates.sort(reverse=True)
  best = candidates[0]
  print(f"  -> 水平面变化最大: {best[1]}轴, 变化={best[2]:.3f}")

  if best[2] < -0.5:
    # 该轴变负 = 重力在该轴负方向 = 该轴正方向为前方
    results['FORWARD'] = (f'+{best[1]}', best[2])
    print(f"  -> 结论: 芯片 {best[1]}+ = 前方 (FORWARD)")
  elif best[2] > 0.5:
    results['FORWARD'] = (f'-{best[1]}', best[2])
    print(f"  -> 结论: 芯片 {best[1]}- = 前方 (即 {best[1]}+ = 后方)")
  else:
    print(f"  -> 变化太小，请抬高一点再试!")
    results['FORWARD'] = ('???', best[2])

  print()
  print("  现在放平传感器")
  input("  放平后按 Enter...")

  # ====== Step 3: 测试左右方向 ======
  print()
  print("[Step 3] 确定左右(X)方向")
  print("  将传感器的【车辆右侧】缓慢抬起约30-45度")
  print("  (左侧保持在桌面，右侧翘起)")
  input("  抬起后保持住，按 Enter...")
  print("  采集中 (2秒)...")
  right_up = collect_samples(b, addr, 2.0, 'accel')
  rx, ry, rz = right_up.mean(axis=0)
  print(f"  读数: X={rx:.3f}, Y={ry:.3f}, Z={rz:.3f}")

  dx2 = rx - bx
  dy2 = ry - by
  dz2 = rz - bz
  print(f"  变化: dX={dx2:.3f}, dY={dy2:.3f}, dZ={dz2:.3f}")

  candidates2 = [(abs(dx2), 'X', dx2), (abs(dy2), 'Y', dy2)]
  candidates2.sort(reverse=True)
  best2 = candidates2[0]
  print(f"  -> 水平面变化最大: {best2[1]}轴, 变化={best2[2]:.3f}")

  if best2[2] < -0.5:
    results['RIGHT'] = (f'+{best2[1]}', best2[2])
    print(f"  -> 结论: 芯片 {best2[1]}+ = 右方 (RIGHT)")
  elif best2[2] > 0.5:
    results['RIGHT'] = (f'-{best2[1]}', best2[2])
    print(f"  -> 结论: 芯片 {best2[1]}- = 右方 (即 {best2[1]}+ = 左方)")
  else:
    print(f"  -> 变化太小，请抬高一点再试!")
    results['RIGHT'] = ('???', best2[2])

  print()
  print("  现在放平传感器")
  input("  放平后按 Enter...")

  # ====== Step 4: 陀螺仪偏航测试 ======
  print()
  print("[Step 4] 测试陀螺仪偏航方向 (可选)")
  print("  保持传感器平放，用手沿桌面向【左转】(逆时针旋转)")
  input("  开始转动时按 Enter (持续转2秒)...")
  print("  采集中 (2秒)...")
  yaw_left = collect_samples(b, addr, 2.0, 'gyro')
  gx, gy, gz = yaw_left.mean(axis=0)
  print(f"  陀螺仪读数: gX={gx:.2f}, gY={gy:.2f}, gZ={gz:.2f} deg/s")

  max_gyro_axis = np.argmax(np.abs([gx, gy, gz]))
  max_gyro_val = [gx, gy, gz][max_gyro_axis]
  print(f"  -> 变化最大: {axis_names[max_gyro_axis]}轴 = {max_gyro_val:.2f} deg/s")
  if max_gyro_val > 5:
    results['YAW_CCW'] = (f'+{axis_names[max_gyro_axis]}', max_gyro_val)
    print(f"  -> 结论: 左转(CCW)时 {axis_names[max_gyro_axis]} 为正")
  elif max_gyro_val < -5:
    results['YAW_CCW'] = (f'-{axis_names[max_gyro_axis]}', max_gyro_val)
    print(f"  -> 结论: 左转(CCW)时 {axis_names[max_gyro_axis]} 为负")
  else:
    print(f"  -> 转速太小，请转快一点")
    results['YAW_CCW'] = ('???', max_gyro_val)

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

  # 根据结果推导
  if 'FORWARD' in results and 'RIGHT' in results and 'UP' in results:
    up_axis = results['UP'][0]     # e.g. '+Z'
    fwd_axis = results['FORWARD'][0]  # e.g. '+Y'
    right_axis = results['RIGHT'][0]  # e.g. '+X'

    print(f"  物理方向 → 芯片轴:")
    print(f"    上(UP)    = {up_axis}")
    print(f"    前(FWD)   = {fwd_axis}")
    print(f"    右(RIGHT) = {right_axis}")
    print()
    print(f"  meas 需要: [后, 左, 下]")
    print(f"    后  = -{fwd_axis.replace('+','').replace('-','+' if '-' in fwd_axis else '-')}")
    print(f"    左  = -{right_axis.replace('+','').replace('-','+' if '-' in right_axis else '-')}")
    print(f"    下  = -{up_axis.replace('+','').replace('-','+' if '-' in up_axis else '-')}")
    print()

    # 构建映射
    def axis_to_expr(direction_result, negate=False):
      """将 '+X' 或 '-Y' 转为代码表达式"""
      sign = direction_result[0]  # '+' or '-'
      name = direction_result[1].lower()  # 'x', 'y', 'z'
      if negate:
        sign = '-' if sign == '+' else '+'
      if sign == '+':
        return name
      else:
        return f'-{name}'

    # 后 = -forward, 左 = -right, 下 = -up
    backward = axis_to_expr(fwd_axis, negate=True)
    leftward = axis_to_expr(right_axis, negate=True)
    downward = axis_to_expr(up_axis, negate=True)

    # meas[0]=后=-v[2] → v[2]=前=forward_expr
    # meas[1]=左=-v[1] → v[1]=右=right_expr
    # meas[2]=下=-v[0] → v[0]=上=up_expr
    v0 = axis_to_expr(up_axis, negate=False)
    v1 = axis_to_expr(right_axis, negate=False)
    v2 = axis_to_expr(fwd_axis, negate=False)

    print(f"  ┌─────────────────────────────────────────────┐")
    print(f"  │ 正确映射:                                    │")
    print(f"  │   a.v = [{v0}, {v1}, {v2}]")
    print(f"  │   g.v = [{v0}*scale, {v1}*scale, {v2}*scale]")
    print(f"  └─────────────────────────────────────────────┘")
    print()
    print(f"  验证: meas = [-v[2], -v[1], -v[0]]")
    print(f"       = [-({v2}), -({v1}), -({v0})]")
    print(f"       = [{backward}, {leftward}, {downward}]")
    print(f"       = [后, 左, 下] ✓")

  b.close()
  print()
  print("测试完成！")


if __name__ == "__main__":
  main()
