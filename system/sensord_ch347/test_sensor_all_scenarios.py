#!/usr/bin/env python3
"""
CH347 LSM6DS3 传感器综合测试脚本
==================================

用途：验证传感器经 openpilot locationd 变换后，轴方向是否符合预期

坐标系说明：
  传感器原始: X=左方向+, Y=后方+, Z=垂直上+（静止时 z≈+9.81）
  lsm6ds3_accel.py 映射: v = [z, x, y]
  locationd.py 变换:   meas = [-v[2], -v[1], -v[0]] = [-y, -x, -z]
  openpilot 设备坐标系:
    meas[0] (X轴) = 前进方向（正值=向前加速/上坡重力前分量）
    meas[1] (Y轴) = 右方向（正值=向右加速/右倾重力分量）
    meas[2] (Z轴) = 上方向（正值=向上加速，重力=-9.81）

测试场景：
1. 水平地面静止 - meas≈[0, 0, -9.81]
2. 坡道车头朝上 - meas[0]<0（重力向后分量）
3. 坡道车头朝下 - meas[0]>0（重力向前分量）
4. 左倾斜       - meas[1]<0（重力向左分量）
5. 右倾斜       - meas[1]>0（重力向右分量）
6. 前进运动     - meas[0]>0（向前加速）
7. 倒车运动     - meas[0]<0（向后加速）
8. 左转运动     - meas[1]<0（向左向心加速度）
9. 右转运动     - meas[1]>0（向右向心加速度）

使用方法：
  python3 test_sensor_all_scenarios.py          # 运行所有测试
  python3 test_sensor_all_scenarios.py --static  # 仅静态测试
  python3 test_sensor_all_scenarios.py --dynamic # 仅动态测试
  python3 test_sensor_all_scenarios.py --scene 1 # 仅测试场景1
"""

import argparse
import math
import statistics
import time
import sys
from typing import List, Tuple, Dict

# 导入传感器和自动检测
sys.path.insert(0, '/data/carrot2-v9-acc')
from openpilot.system.sensord_ch347.sensors.lsm6ds3_accel import LSM6DS3_Accel
from openpilot.system.sensord_ch347.sensord_ch347 import (
    ensure_ch347_modules_loaded, ensure_ch347_driver_bound,
    detect_ch347_bus, ensure_i2c_accessible,
)

EARTH_G = 9.81


def v_to_meas(v: List[float]) -> List[float]:
  """将传感器 v[] 转换为 openpilot 设备坐标系 meas[]。

  与 locationd.py L109 一致: meas = [-v[2], -v[1], -v[0]]
  结果: meas[0]=前进(X), meas[1]=右(Y), meas[2]=上(Z)
  """
  return [-v[2], -v[1], -v[0]]


class SensorTestResult:
    """测试结果"""
    def __init__(self):
        self.passed = True
        self.details = []
        self.warnings = []
        self.errors = []

    def add_pass(self, msg: str):
        self.details.append(("PASS", msg))

    def add_warn(self, msg: str):
        self.warnings.append(msg)
        self.details.append(("WARN", msg))

    def add_fail(self, msg: str):
        self.passed = False
        self.errors.append(msg)
        self.details.append(("FAIL", msg))

    def print_report(self, title: str):
        print(f"\n{'=' * 70}")
        print(f"测试场景: {title}")
        print(f"{'=' * 70}")

        for status, msg in self.details:
            symbol = "✅" if status == "PASS" else ("⚠️ " if status == "WARN" else "❌")
            print(f"  {symbol} {msg}")

        print(f"\n结果: {'✅ 通过' if self.passed else '❌ 失败'}")
        if self.warnings:
            print(f"警告: {len(self.warnings)} 个")
        if self.errors:
            print(f"错误: {len(self.errors)} 个")


class SensorTestSuite:
    """传感器测试套件（基于 openpilot 设备坐标系）"""

    def __init__(self, i2c_bus: int | None = None):
        self.i2c_bus = i2c_bus
        self.accel = None

    def _auto_detect_bus(self) -> int | None:
        """自动检测 CH347 I2C 总线号"""
        ensure_ch347_modules_loaded()
        ensure_ch347_driver_bound()
        return detect_ch347_bus(wait_secs=3)

    def init_sensor(self) -> bool:
        """初始化传感器"""
        if self.i2c_bus is None:
            self.i2c_bus = self._auto_detect_bus()
        if self.i2c_bus is None:
            print("FAIL: Cannot detect CH347 I2C bus")
            return False
        if not ensure_i2c_accessible(self.i2c_bus):
            print(f"FAIL: /dev/i2c-{self.i2c_bus} not accessible")
            return False
        try:
            self.accel = LSM6DS3_Accel(self.i2c_bus)
            self.accel.init()
            print(f"OK: 传感器初始化成功 (bus={self.i2c_bus})\n")
            return True
        except Exception as e:
            print(f"FAIL: 传感器初始化失败: {e}")
            return False

    def cleanup(self):
        """清理资源"""
        if self.accel and self.accel.bus:
            self.accel.bus.close()

    def collect_meas_samples(self, count: int = 100, interval: float = 0.05) -> Tuple[List, int]:
        """采集样本并转换为 openpilot 设备坐标系 meas[]"""
        samples = []
        failed = 0

        for _ in range(count * 2):  # 尝试两倍次数
            try:
                evt = self.accel.get_event()
                v = evt.acceleration.v
                meas = v_to_meas(v)
                samples.append(meas)

                if len(samples) >= count:
                    break
            except:
                failed += 1

            time.sleep(interval)

        return samples, failed

    def analyze_static(self, samples: List, scene_name: str) -> SensorTestResult:
        """分析静态场景数据（openpilot 设备坐标系）"""
        result = SensorTestResult()

        if len(samples) < 10:
            result.add_fail(f"数据不足，仅采集到 {len(samples)} 个样本")
            return result

        # 计算 meas 平均值
        # meas[0]=前进(X), meas[1]=右(Y), meas[2]=上(Z)
        avg_x = sum(s[0] for s in samples) / len(samples)  # 前进方向
        avg_y = sum(s[1] for s in samples) / len(samples)  # 右方向
        avg_z = sum(s[2] for s in samples) / len(samples)  # 上方向

        # 转换为 g
        avg_x_g = avg_x / EARTH_G
        avg_y_g = avg_y / EARTH_G
        avg_z_g = avg_z / EARTH_G

        # 总加速度
        total_g = math.sqrt(avg_x**2 + avg_y**2 + avg_z**2) / EARTH_G

        # 标准差
        std_x = statistics.stdev(s[0] for s in samples)
        std_y = statistics.stdev(s[1] for s in samples)
        std_z = statistics.stdev(s[2] for s in samples)

        # 打印数据（openpilot 设备坐标系）
        print(f"\n传感器数据 (openpilot 设备坐标系, 经 locationd 变换):")
        print(f"  X (前进) = {avg_x:+.3f} m/s^2 ({avg_x_g:+.3f} g)")
        print(f"  Y (右)   = {avg_y:+.3f} m/s^2 ({avg_y_g:+.3f} g)")
        print(f"  Z (上)   = {avg_z:+.3f} m/s^2 ({avg_z_g:+.3f} g)")
        print(f"  总加速度 = {total_g:.3f} g")
        print(f"  数据波动: X={std_x:.3f}, Y={std_y:.3f}, Z={std_z:.3f} m/s^2")

        # 验证总加速度 ≈ 1g
        if 0.95 < total_g < 1.05:
            result.add_pass(f"总加速度合理: {total_g:.3f}g (接近 1g)")
        else:
            result.add_fail(f"总加速度异常: {total_g:.3f}g (应该接近 1g)")

        # 验证 Z 轴为负值（重力方向朝下，倾斜时 |Z|<1g）
        if avg_z_g < -0.5:
            result.add_pass(f"Z轴重力方向正确: {avg_z_g:+.3f}g (负值=重力向下)")
        else:
            result.add_fail(f"Z轴重力方向异常: {avg_z_g:+.3f}g (应为负值，确认轴映射)")

        # 验证数据稳定性
        if std_x < 0.5 and std_y < 0.5 and std_z < 0.5:
            result.add_pass(f"数据稳定 (波动小)")
        else:
            result.add_warn(f"数据波动较大 (X={std_x:.3f}, Y={std_y:.3f}, Z={std_z:.3f})")

        return result

    def analyze_dynamic(self, samples: List, motion_type: str) -> SensorTestResult:
        """分析动态场景数据（openpilot 设备坐标系）"""
        result = SensorTestResult()

        if len(samples) < 10:
            result.add_fail(f"数据不足，仅采集到 {len(samples)} 个样本")
            return result

        avg_x = sum(s[0] for s in samples) / len(samples)  # 前进方向
        avg_y = sum(s[1] for s in samples) / len(samples)  # 右方向
        avg_z = sum(s[2] for s in samples) / len(samples)  # 上方向

        avg_x_g = avg_x / EARTH_G
        avg_y_g = avg_y / EARTH_G
        avg_z_g = avg_z / EARTH_G

        total_g = math.sqrt(avg_x**2 + avg_y**2 + avg_z**2) / EARTH_G

        std_x = statistics.stdev(s[0] for s in samples)
        std_y = statistics.stdev(s[1] for s in samples)
        std_z = statistics.stdev(s[2] for s in samples)

        print(f"\n传感器数据 (openpilot 设备坐标系, 经 locationd 变换):")
        print(f"  X (前进) = {avg_x:+.3f} m/s^2 ({avg_x_g:+.3f} g)")
        print(f"  Y (右)   = {avg_y:+.3f} m/s^2 ({avg_y_g:+.3f} g)")
        print(f"  Z (上)   = {avg_z:+.3f} m/s^2 ({avg_z_g:+.3f} g)")
        print(f"  总加速度 = {total_g:.3f} g")
        print(f"  数据波动: X={std_x:.3f}, Y={std_y:.3f}, Z={std_z:.3f} m/s^2")

        # 验证总加速度
        if 0.5 < total_g < 2.5:
            result.add_pass(f"总加速度合理: {total_g:.3f}g")
        else:
            result.add_fail(f"总加速度异常: {total_g:.3f}g")

        # 验证运动方向（X轴=前进方向）
        # meas[0] = y_raw = sensor_Y = 纵向前+
        # 前进加速时：meas[0] > 0 表示向前加速
        if motion_type == "forward":
            if avg_x_g > -0.05:
                result.add_pass(f"前进方向正确: X={avg_x_g:+.3f}g (正值或接近0)")
            else:
                result.add_fail(f"前进方向异常: X={avg_x_g:+.3f}g (应该为正值)")
        elif motion_type == "reverse":
            if avg_x_g < 0.05:
                result.add_pass(f"倒车方向正确: X={avg_x_g:+.3f}g (负值或接近0)")
            else:
                result.add_fail(f"倒车方向异常: X={avg_x_g:+.3f}g (应该为负值)")

        # 验证数据连续性
        if std_x < 2.0:
            result.add_pass(f"数据连续性好 (波动合理)")
        else:
            result.add_warn(f"数据波动较大 (可能剧烈加减速)")

        return result

    # ==================== 测试场景 ====================

    def test_scene1_horizontal(self) -> SensorTestResult:
        """场景1: 水平地面静止 - 期望 meas ≈ [0, 0, -9.81]"""
        print("\n" + "=" * 70)
        print("场景 1: 水平地面静止测试")
        print("=" * 70)
        print("请将车辆停在水平地面，保持静止")
        print("期望: X(前进)≈0, Y(右)≈0, Z(上)≈-9.81 m/s^2")

        for i in range(3, 0, -1):
            print(f"  {i}...")
            time.sleep(1)

        print("\n[采集数据...]")
        samples, failed = self.collect_meas_samples(100)
        print(f"  采集到 {len(samples)} 个样本，失败 {failed} 次")

        result = self.analyze_static(samples, "水平地面")

        # 额外检查：X和Y应接近0（水平状态）
        avg_x_g = sum(s[0] for s in samples) / len(samples) / EARTH_G
        avg_y_g = sum(s[1] for s in samples) / len(samples) / EARTH_G

        if abs(avg_x_g) < 0.1 and abs(avg_y_g) < 0.1:
            result.add_pass(f"车辆基本水平 (X={avg_x_g:+.3f}g, Y={avg_y_g:+.3f}g)")
        else:
            result.add_warn(f"车辆有轻微倾斜 (X={avg_x_g:+.3f}g, Y={avg_y_g:+.3f}g)")

        return result

    def test_scene2_uphill(self) -> SensorTestResult:
        """场景2: 坡道车头朝上 - 期望 meas[0] < 0（重力向后分量）"""
        print("\n" + "=" * 70)
        print("场景 2: 坡道车头朝上测试")
        print("=" * 70)
        print("请将车辆停在坡道上，车头朝上")
        print("期望: X(前进)<0 (重力向后分量), Z(上)<-9.81")
        input("准备就绪后按 Enter 继续...")

        print("\n[采集数据...]")
        samples, failed = self.collect_meas_samples(100)
        print(f"  采集到 {len(samples)} 个样本，失败 {failed} 次")

        result = self.analyze_static(samples, "车头朝上")

        # 车头朝上时，重力在前进方向(X)有负分量
        avg_x_g = sum(s[0] for s in samples) / len(samples) / EARTH_G
        if avg_x_g < -0.05:
            result.add_pass(f"检测到上坡: X(前进)={avg_x_g:+.3f}g (负值=重力向后)")
        else:
            result.add_warn(f"X轴读数: {avg_x_g:+.3f}g (预期负值=重力向后分量)")

        return result

    def test_scene3_downhill(self) -> SensorTestResult:
        """场景3: 坡道车头朝下 - 期望 meas[0] > 0（重力向前分量）"""
        print("\n" + "=" * 70)
        print("场景 3: 坡道车头朝下测试")
        print("=" * 70)
        print("请将车辆停在坡道上，车头朝下")
        print("期望: X(前进)>0 (重力向前分量), Z(上)<-9.81")
        input("准备就绪后按 Enter 继续...")

        print("\n[采集数据...]")
        samples, failed = self.collect_meas_samples(100)
        print(f"  采集到 {len(samples)} 个样本，失败 {failed} 次")

        result = self.analyze_static(samples, "车头朝下")

        # 车头朝下时，重力在前进方向(X)有正分量
        avg_x_g = sum(s[0] for s in samples) / len(samples) / EARTH_G
        if avg_x_g > 0.05:
            result.add_pass(f"检测到下坡: X(前进)={avg_x_g:+.3f}g (正值=重力向前)")
        else:
            result.add_warn(f"X轴读数: {avg_x_g:+.3f}g (预期正值=重力向前分量)")

        return result

    def test_scene4_left_tilt(self) -> SensorTestResult:
        """场景4: 左倾斜 - 期望 meas[1] < 0（重力向左分量）"""
        print("\n" + "=" * 70)
        print("场景 4: 左倾斜测试")
        print("=" * 70)
        print("请将车辆停在向左倾斜的路面上（左侧低、右侧高）")
        print("期望: Y(右)<0 (重力向左分量)")
        input("准备就绪后按 Enter 继续...")

        print("\n[采集数据...]")
        samples, failed = self.collect_meas_samples(100)
        print(f"  采集到 {len(samples)} 个样本，失败 {failed} 次")

        result = self.analyze_static(samples, "左倾斜")

        # 左倾斜时，重力在右方向(Y)有负分量（重力向左）
        avg_y_g = sum(s[1] for s in samples) / len(samples) / EARTH_G
        if avg_y_g < -0.05:
            result.add_pass(f"检测到左倾斜: Y(右)={avg_y_g:+.3f}g (负值=重力向左)")
        else:
            result.add_warn(f"Y轴读数: {avg_y_g:+.3f}g (预期负值=重力向左分量)")

        return result

    def test_scene5_right_tilt(self) -> SensorTestResult:
        """场景5: 右倾斜 - 期望 meas[1] > 0（重力向右分量）"""
        print("\n" + "=" * 70)
        print("场景 5: 右倾斜测试")
        print("=" * 70)
        print("请将车辆停在向右倾斜的路面上（右侧低、左侧高）")
        print("期望: Y(右)>0 (重力向右分量)")
        input("准备就绪后按 Enter 继续...")

        print("\n[采集数据...]")
        samples, failed = self.collect_meas_samples(100)
        print(f"  采集到 {len(samples)} 个样本，失败 {failed} 次")

        result = self.analyze_static(samples, "右倾斜")

        # 右倾斜时，重力在右方向(Y)有正分量（重力向右）
        avg_y_g = sum(s[1] for s in samples) / len(samples) / EARTH_G
        if avg_y_g > 0.05:
            result.add_pass(f"检测到右倾斜: Y(右)={avg_y_g:+.3f}g (正值=重力向右)")
        else:
            result.add_warn(f"Y轴读数: {avg_y_g:+.3f}g (预期正值=重力向右分量)")

        return result

    def test_scene6_forward(self) -> SensorTestResult:
        """场景6: 前进运动 - 期望 meas[0] > 0（向前加速）"""
        print("\n" + "=" * 70)
        print("场景 6: 前进运动测试")
        print("=" * 70)
        print("请驾驶车辆前进（直线或转弯均可）")
        print("期望: X(前进)有正向加速度")
        input("准备就绪后按 Enter 开始采集...")

        print("\n[采集数据...]")
        samples, failed = self.collect_meas_samples(100, 0.05)
        print(f"  采集到 {len(samples)} 个样本，失败 {failed} 次")

        result = self.analyze_dynamic(samples, "forward")
        return result

    def test_scene7_reverse(self) -> SensorTestResult:
        """场景7: 倒车运动 - 期望 meas[0] < 0（向后加速）"""
        print("\n" + "=" * 70)
        print("场景 7: 倒车运动测试")
        print("=" * 70)
        print("请驾驶车辆倒车（直线或转弯均可）")
        print("期望: X(前进)有负向加速度")
        input("准备就绪后按 Enter 开始采集...")

        print("\n[采集数据...]")
        samples, failed = self.collect_meas_samples(100, 0.05)
        print(f"  采集到 {len(samples)} 个样本，失败 {failed} 次")

        result = self.analyze_dynamic(samples, "reverse")
        return result

    def test_scene8_left_turn(self) -> SensorTestResult:
        """场景8: 左转运动 - 期望 meas[1] < 0（向左向心加速度）"""
        print("\n" + "=" * 70)
        print("场景 8: 左转运动测试")
        print("=" * 70)
        print("请将传感器水平放好，然后向左侧推动（模拟左转）")
        print("期望: Y(右)有负向加速度峰值（向左向心加速度）")
        print()

        # 等待检测到左向加速度后自动采集
        print("等待运动（请向左推传感器）...")
        triggered = False
        for _ in range(600):  # 最多等30秒
            try:
                evt = self.accel.get_event()
                v = evt.acceleration.v
                meas = [-v[2], -v[1], -v[0]]
                if meas[1] / EARTH_G < -0.15:
                    triggered = True
                    break
            except:
                pass
            time.sleep(0.05)

        if not triggered:
            result = SensorTestResult()
            result.add_fail("超时未检测到左向加速度")
            return result

        print(f"检测到左向加速度! Y={meas[1]/EARTH_G:+.3f}g")
        print("采集数据中...")

        samples = []
        for _ in range(300):
            try:
                evt = self.accel.get_event()
                v = evt.acceleration.v
                meas = [-v[2], -v[1], -v[0]]
                samples.append(meas)
                if len(samples) >= 100:
                    break
            except:
                pass
            time.sleep(0.01)

        result = SensorTestResult()
        if len(samples) < 10:
            result.add_fail(f"数据不足，仅采集到 {len(samples)} 个样本")
            return result

        n = len(samples)
        avg_y_g = sum(s[1] for s in samples) / n / EARTH_G
        peak_left = min(s[1] for s in samples) / EARTH_G

        print(f"  Y(右) avg={avg_y_g:+.3f}g  peak={peak_left:+.3f}g")

        if peak_left < -0.2:
            result.add_pass(f"检测到左转加速度峰值: {peak_left:+.3f}g < -0.2g")
        else:
            result.add_fail(f"左转加速度峰值不足: {peak_left:+.3f}g (需要<-0.2g)")

        if avg_y_g < 0.05:
            result.add_pass(f"左转平均方向正确: avg_Y={avg_y_g:+.3f}g")
        else:
            result.add_warn(f"左转平均值为正: avg_Y={avg_y_g:+.3f}g")

        return result

    def test_scene9_right_turn(self) -> SensorTestResult:
        """场景9: 右转运动 - 期望 meas[1] > 0（向右向心加速度）"""
        print("\n" + "=" * 70)
        print("场景 9: 右转运动测试")
        print("=" * 70)
        print("请将传感器水平放好，然后向右侧推动（模拟右转）")
        print("期望: Y(右)有正向加速度峰值（向右向心加速度）")
        print()

        # 等待检测到右向加速度后自动采集
        print("等待运动（请向右推传感器）...")
        triggered = False
        for _ in range(600):  # 最多等30秒
            try:
                evt = self.accel.get_event()
                v = evt.acceleration.v
                meas = [-v[2], -v[1], -v[0]]
                if meas[1] / EARTH_G > 0.15:
                    triggered = True
                    break
            except:
                pass
            time.sleep(0.05)

        if not triggered:
            result = SensorTestResult()
            result.add_fail("超时未检测到右向加速度")
            return result

        print(f"检测到右向加速度! Y={meas[1]/EARTH_G:+.3f}g")
        print("采集数据中...")

        samples = []
        for _ in range(300):
            try:
                evt = self.accel.get_event()
                v = evt.acceleration.v
                meas = [-v[2], -v[1], -v[0]]
                samples.append(meas)
                if len(samples) >= 100:
                    break
            except:
                pass
            time.sleep(0.01)

        result = SensorTestResult()
        if len(samples) < 10:
            result.add_fail(f"数据不足，仅采集到 {len(samples)} 个样本")
            return result

        n = len(samples)
        avg_y_g = sum(s[1] for s in samples) / n / EARTH_G
        peak_right = max(s[1] for s in samples) / EARTH_G

        print(f"  Y(右) avg={avg_y_g:+.3f}g  peak={peak_right:+.3f}g")

        if peak_right > 0.2:
            result.add_pass(f"检测到右转加速度峰值: {peak_right:+.3f}g > 0.2g")
        else:
            result.add_fail(f"右转加速度峰值不足: {peak_right:+.3f}g (需要>0.2g)")

        if avg_y_g > -0.05:
            result.add_pass(f"右转平均方向正确: avg_Y={avg_y_g:+.3f}g")
        else:
            result.add_warn(f"右转平均值为负: avg_Y={avg_y_g:+.3f}g")

        return result

    def run_all_tests(self, scenes: List[int] = None):
        """运行所有测试"""
        if not self.init_sensor():
            return

        if scenes is None:
            scenes = [1, 2, 3, 4, 5, 6, 7, 8, 9]

        test_funcs = {
            1: ("水平地面静止", self.test_scene1_horizontal),
            2: ("坡道车头朝上", self.test_scene2_uphill),
            3: ("坡道车头朝下", self.test_scene3_downhill),
            4: ("左倾斜", self.test_scene4_left_tilt),
            5: ("右倾斜", self.test_scene5_right_tilt),
            6: ("前进运动", self.test_scene6_forward),
            7: ("倒车运动", self.test_scene7_reverse),
            8: ("左转运动", self.test_scene8_left_turn),
            9: ("右转运动", self.test_scene9_right_turn),
        }

        results = {}

        for scene_num in sorted(scenes):
            if scene_num in test_funcs:
                name, func = test_funcs[scene_num]
                try:
                    results[scene_num] = func()
                except Exception as e:
                    result = SensorTestResult()
                    result.add_fail(f"测试异常: {e}")
                    results[scene_num] = result

        # 打印总结
        self.print_summary(results)

        self.cleanup()

    def print_summary(self, results: Dict[int, SensorTestResult]):
        """打印测试总结"""
        print("\n" + "=" * 70)
        print("测试总结")
        print("=" * 70)

        scene_names = {
            1: "水平地面静止",
            2: "坡道车头朝上",
            3: "坡道车头朝下",
            4: "左倾斜",
            5: "右倾斜",
            6: "前进运动",
            7: "倒车运动",
            8: "左转运动",
            9: "右转运动",
        }

        print(f"\n{'场景':<20} {'结果':<10} {'详细':<40}")
        print("-" * 70)

        all_passed = True
        for scene_num in sorted(results.keys()):
            result = results[scene_num]
            name = scene_names.get(scene_num, f"场景{scene_num}")
            status = "✅ 通过" if result.passed else "❌ 失败"
            detail = f"{len(result.errors)}错误, {len(result.warnings)}警告"

            print(f"{name:<20} {status:<10} {detail:<40}")

            if not result.passed:
                all_passed = False

        print("=" * 70)
        print(f"\n总计: {sum(1 for r in results.values() if r.passed)}/{len(results)} 通过")

        if all_passed:
            print("\n🎉 所有测试通过！传感器工作正常！")
        else:
            print("\n⚠️  部分测试失败，请检查传感器状态")

        print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description='CH347 LSM6DS3 传感器综合测试 (openpilot 设备坐标系)')
    parser.add_argument('--bus', type=int, default=None,
                        help='I2C总线号 (默认: 自动检测)')
    parser.add_argument('--static', action='store_true', help='仅运行静态测试')
    parser.add_argument('--dynamic', action='store_true', help='仅运行动态测试')
    parser.add_argument('--scene', type=int, nargs='+', help='指定测试场景编号 (1-9)')

    args = parser.parse_args()

    suite = SensorTestSuite(i2c_bus=args.bus)

    # 确定要运行的场景
    if args.scene:
        scenes = args.scene
    elif args.static:
        scenes = [1, 2, 3, 4, 5]
    elif args.dynamic:
        scenes = [6, 7, 8, 9]
    else:
        scenes = None  # 运行所有

    print("=" * 70)
    print("CH347 LSM6DS3 传感器综合测试")
    print("坐标系: openpilot 设备坐标系 (经 locationd 变换)")
    print("  X(前进) = meas[0] = -sensor_Y = 前进方向+")
    print("  Y(右)   = meas[1] = -sensor_X = 右方向+")
    print("  Z(上)   = meas[2] = -sensor_Z = 垂直上+ (重力=-9.81)")
    print("=" * 70)
    print(f"\nI2C 总线: {'自动检测' if args.bus is None else args.bus}")
    print(f"测试场景: {scenes if scenes else '全部 (1-9)'}")

    suite.run_all_tests(scenes)


if __name__ == "__main__":
    main()
