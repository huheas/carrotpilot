#!/usr/bin/env python3
"""
WT 传感器综合场景测试脚本
============================

用途：启动 ./sensord_wt --verbose，解析其标准错误输出中的传感器数据，
      按 locationd 转换公式验证轴方向是否符合 openpilot 设备坐标系预期。

输出格式（来自 verbose 模式）：
  wt_accel.cc: WT Accel: raw[X,Y,Z] -> scaled[ax,ay,az] m/s² (ts=...)
  wt_gyro.cc:  WT Gyro:  raw[X,Y,Z] -> scaled[gx,gy,gz] rad/s (ts=...)

坐标系说明：
  WT 传感器输出（scaled）: ax=WT_X, ay=WT_Y, az=WT_Z
  wt_accel.cc 映射:  v = [az, ax, +ay]  即 v[0]=+WT_Z, v[1]=+WT_X, v[2]=+WT_Y
  locationd 变换:    meas = [-v[2], -v[1], -v[0]] = [-WT_Y, -WT_X, -WT_Z]
  注意: WT_Y正 = 车辆后退方向（传感器反装），故 meas[0]=X前进=-WT_Y
  openpilot 设备坐标系:
    meas[0] (X轴) = 前进方向（正值=向前加速/下坡重力分量）
    meas[1] (Y轴) = 右方向（正值=向右加速/右倾重力分量）
    meas[2] (Z轴) = 向上方向（静止时重力 ≈ -9.81 m/s²）

  wt_gyro.cc 映射:   v = [-gz, gx, -gy]  即 v[0]=-WT_Z, v[1]=+WT_X, v[2]=-WT_Y
  locationd 变换:    meas = [-v[2], -v[1], -v[0]] = [WT_Y, -WT_X, WT_Z]
  陀螺仪坐标系:
    meas[0] (roll)  = 横滚角速度
    meas[1] (pitch) = 俯仰角速度
    meas[2] (yaw)   = 偏航角速度（左转为负）

测试场景（参考 test_sensor_all_scenarios.py）：
  场景1: 水平地面静止 - meas ≈ [0, 0, -9.81]
  场景2: 坡道车头朝上 - meas[0] < 0（重力向后分量）
  场景3: 坡道车头朝下 - meas[0] > 0（重力向前分量）
  场景4: 左倾斜       - meas[1] < 0（重力向左分量）
  场景5: 右倾斜       - meas[1] > 0（重力向右分量）
  场景6: 前进运动     - meas[0] > 0（向前加速）
  场景7: 倒车运动     - meas[0] < 0（向后加速）
  场景8: 左推运动     - meas[0] < 0（物理左推→WT_Y正向→X前进负值）
  场景9: 右推运动     - meas[0] > 0（物理右推→WT_Y负向→X前进正值）

使用方法：
  python3 test_sensord_wt_scenarios.py [选项]
  python3 test_sensord_wt_scenarios.py --device /dev/ttyUSB0
  python3 test_sensord_wt_scenarios.py --static
  python3 test_sensord_wt_scenarios.py --dynamic
  python3 test_sensord_wt_scenarios.py --scene 1
  python3 test_sensord_wt_scenarios.py --monitor   # 实时监控模式
"""

import argparse
import math
import os
import re
import statistics
import subprocess
import sys
import threading
import time
from collections import deque
from typing import List, Tuple, Optional

EARTH_G = 9.81
SENSORD_WT_BIN = os.path.join(os.path.dirname(__file__), "sensord_wt")

# 解析 verbose 输出的正则
# 注意：swaglog 输出可能在任意位置折行，只匹配 scaled[x,y,z] 三个数值即可
RE_ACCEL = re.compile(
    r"WT Accel:.*?scaled\[([-\d.]+),([-\d.]+),([-\d.]+)\]"
)
RE_GYRO = re.compile(
    r"WT Gyro:.*?scaled\[([-\d.]+),([-\d.]+),([-\d.]+)\]"
)


# ──────────────────────────────────────────────
# 坐标转换（与 locationd.py 保持一致）
# ──────────────────────────────────────────────

def accel_to_meas(ax: float, ay: float, az: float) -> List[float]:
    """
    WT scaled(ax, ay, az) → cereal v[] → locationd meas[]

    实车验证（坡道场景2/3）: WT_Y正 = 车辆后退方向（传感器反装）
    wt_accel.cc:  v[0]=+az, v[1]=+ax, v[2]=+ay
    locationd:    meas = [-v[2], -v[1], -v[0]] = [-ay, -ax, -az]

    验证（车头朝上坡道 ay≈+2.92增大）:
      meas[0] = -ay ≈ -2.92 < 0  ✓（X前进<0，上坡重力向后）
      meas[1] = -ax ≈ +0.62 ≈ 0  ✓（Y右侧）
      meas[2] = -az ≈ -9.87 ≈ -9.81  ✓（Z上，重力）
    """
    v = [az, ax, ay]
    return [-v[2], -v[1], -v[0]]  # [-ay, -ax, -az]


def gyro_to_meas(gx: float, gy: float, gz: float) -> List[float]:
    """
    WT scaled(gx, gy, gz) → cereal v[] → locationd meas[]

    实车验证: WT_Y正=后退，绕前进轴旋转=绕(-WT_Y)轴旋转
    wt_gyro.cc:   v[0]=-gz, v[1]=+gx, v[2]=+gy
    locationd:    meas = [-v[2], -v[1], -v[0]] = [-gy, -gx, gz]
      meas_gyro[0] = roll  = -WT_GY（绕前进轴旋转，WT_Y正=后退取反）
      meas_gyro[1] = pitch = -WT_GX（绕右侧轴旋转）
      meas_gyro[2] = yaw   = +WT_GZ（绕向上轴旋转）
    """
    v = [-gz, gx, gy]
    return [-v[2], -v[1], -v[0]]  # [-gy, -gx, gz]


# ──────────────────────────────────────────────
# sensord_wt 进程管理
# ──────────────────────────────────────────────

class SensordWTReader:
    """启动 sensord_wt --verbose 并实时解析输出"""

    def __init__(self, device: str = "/dev/ttyUSB0", baud: int = 115200):
        self.device = device
        self.baud = baud
        self._proc: Optional[subprocess.Popen] = None
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._accel_buf: deque = deque(maxlen=500)  # (meas, raw_scaled)
        self._gyro_buf: deque = deque(maxlen=500)
        self._running = False
        self._accel_total: int = 0  # 全局累计帧数，不受 maxlen 影响

    def start(self) -> bool:
        """启动进程"""
        if not os.path.isfile(SENSORD_WT_BIN):
            print(f"错误: 找不到 {SENSORD_WT_BIN}")
            print("  请先编译: cd /data/carrot2-v9-acc && ./tools/op.sh build")
            return False
        if not os.path.exists(self.device):
            print(f"错误: 串口设备不存在: {self.device}")
            return False

        cmd = [SENSORD_WT_BIN, "--verbose", "--device", self.device,
               "--baud", str(self.baud)]
        print(f"启动: {' '.join(cmd)}")
        # 设置超大列宽，防止 swaglog 输出折行导致正则匹配失败
        env = os.environ.copy()
        env["COLUMNS"] = "4096"
        env["TERM"] = "dumb"
        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                env=env,
            )
        except Exception as e:
            print(f"启动失败: {e}")
            return False

        self._running = True
        self._thread = threading.Thread(target=self._reader_loop, daemon=True)
        self._thread.start()
        return True

    def stop(self):
        self._running = False
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        if self._thread:
            self._thread.join(timeout=2)

    def _reader_loop(self):
        # 用于拼接被终端宽度折行的输出（swaglog 输出可能在数值中间换行）
        pending = ""
        for line in self._proc.stdout:
            if not self._running:
                break
            line = line.rstrip()
            # 尝试与上一行拼接（处理折行）
            combined = pending + line
            pending = ""

            # 先尝试匹配加速度
            m = RE_ACCEL.search(combined)
            if m:
                ax, ay, az = float(m.group(1)), float(m.group(2)), float(m.group(3))
                meas = accel_to_meas(ax, ay, az)
                with self._lock:
                    self._accel_buf.append((meas, (ax, ay, az)))
                    self._accel_total += 1
                continue

            # 再尝试匹配陀螺仪
            m = RE_GYRO.search(combined)
            if m:
                gx, gy, gz = float(m.group(1)), float(m.group(2)), float(m.group(3))
                meas = gyro_to_meas(gx, gy, gz)
                with self._lock:
                    self._gyro_buf.append((meas, (gx, gy, gz)))
                continue

            # 如果包含 WT Accel 或 WT Gyro 关键字但未匹配成功，
            # 说明可能是折行未结束，保留等待下一行拼接
            if ("WT Accel" in combined or "WT Gyro:" in combined) and "m/s" not in combined and "rad/s" not in combined:
                pending = combined

    def collect_accel(self, count: int = 100, timeout: float = 10.0) -> List:
        """采集 count 条加速度 meas 样本"""
        deadline = time.time() + timeout
        with self._lock:
            self._accel_buf.clear()
        while time.time() < deadline:
            with self._lock:
                if len(self._accel_buf) >= count:
                    return [item[0] for item in list(self._accel_buf)[-count:]]
            time.sleep(0.05)
        with self._lock:
            return [item[0] for item in self._accel_buf]

    def collect_gyro(self, count: int = 50, timeout: float = 5.0) -> List:
        """采集 count 条陀螺仪 meas 样本"""
        deadline = time.time() + timeout
        with self._lock:
            self._gyro_buf.clear()
        while time.time() < deadline:
            with self._lock:
                if len(self._gyro_buf) >= count:
                    return [item[0] for item in list(self._gyro_buf)[-count:]]
            time.sleep(0.05)
        with self._lock:
            return [item[0] for item in self._gyro_buf]

    def wait_trigger_accel(self, axis: int, direction: float,
                           threshold: float = 0.15 * EARTH_G,
                           timeout: float = 30.0) -> Optional[List[float]]:
        """等待某轴超过阈值，返回触发时的 meas

        遍历所有新增帧（而非只取最后一帧），防止瞬时冲击被跳过。
        """
        deadline = time.time() + timeout
        # 初始化时记录当前 buffer 长度，只检查此后的新帧（防止复用上一场景残留数据）
        with self._lock:
            last_seen = len(self._accel_buf)
        while time.time() < deadline:
            with self._lock:
                buf_len = len(self._accel_buf)
                if buf_len > last_seen:
                    # 检查所有新增帧，不只是最后一帧
                    new_items = list(self._accel_buf)[last_seen:]
                    last_seen = buf_len
                    for meas, _ in new_items:
                        if direction > 0 and meas[axis] > threshold:
                            return meas
                        if direction < 0 and meas[axis] < -threshold:
                            return meas
            time.sleep(0.02)
        return None


    def wait_trigger_any(self, threshold: float = 0.3 * EARTH_G,
                          timeout: float = 30.0,
                          pre_frames: int = 25) -> Optional[List]:
        """等待任意轴超过阈值（绝对值）。
        触发后等待 pre_frames 帧进入 buffer，
        返回触发帧附近窗口的样本列表（共约 2*pre_frames 帧）"""
        deadline = time.time() + timeout
        # 记录启动时的全局帧计数（不受 maxlen 影响，始终单调递增）
        with self._lock:
            last_total = self._accel_total
        trig_found = False
        while time.time() < deadline:
            with self._lock:
                cur_total = self._accel_total
                if cur_total > last_total:
                    # 取新入的帧（deque 内尾部）
                    new_count = cur_total - last_total
                    buf_snap = list(self._accel_buf)
                    new_items = buf_snap[max(0, len(buf_snap) - new_count):]
                    for meas, _ in new_items:
                        if abs(meas[0]) > threshold or abs(meas[1]) > threshold:
                            trig_found = True
                            break
                    last_total = cur_total
            if trig_found:
                break
            time.sleep(0.02)
        if not trig_found:
            return None
        # 等待 pre_frames 帧进入（覆盖冲击后回弹过程）
        t_wait = time.time() + (pre_frames * 0.012)  # ~12ms/帧
        while time.time() < t_wait:
            time.sleep(0.01)
        # 从 buf 末尾往前取最近 2*pre_frames 帧
        with self._lock:
            buf_list = list(self._accel_buf)
        buf_len = len(buf_list)
        end = buf_len
        start = max(0, end - pre_frames * 2 - 1)
        samples = [item[0] for item in buf_list[start:end]]
        return samples

class TestResult:
    def __init__(self):
        self.passed = True
        self.details = []

    def ok(self, msg: str):
        self.details.append(("PASS", msg))

    def warn(self, msg: str):
        self.details.append(("WARN", msg))

    def fail(self, msg: str):
        self.passed = False
        self.details.append(("FAIL", msg))

    def print_report(self, title: str):
        print(f"\n{'=' * 68}")
        print(f"场景: {title}")
        print(f"{'=' * 68}")
        for status, msg in self.details:
            sym = "✅" if status == "PASS" else ("⚠️ " if status == "WARN" else "❌")
            print(f"  {sym} {msg}")
        print(f"\n结果: {'✅ 通过' if self.passed else '❌ 失败'}")


# ──────────────────────────────────────────────
# 分析函数
# ──────────────────────────────────────────────

def print_meas_summary(samples: List, label: str = ""):
    n = len(samples)
    if n == 0:
        return
    avg = [sum(s[i] for s in samples) / n for i in range(3)]
    total_g = math.sqrt(sum(a**2 for a in avg)) / EARTH_G
    if label:
        print(f"\n{label} (n={n}, openpilot 设备坐标系):")
    print(f"  X(前进) = {avg[0]:+.4f} m/s²  ({avg[0]/EARTH_G:+.3f} g)")
    print(f"  Y(右)   = {avg[1]:+.4f} m/s²  ({avg[1]/EARTH_G:+.3f} g)")
    print(f"  Z(上)   = {avg[2]:+.4f} m/s²  ({avg[2]/EARTH_G:+.3f} g)")
    print(f"  总加速度 = {total_g:.4f} g")
    if n > 1:
        std = [statistics.stdev(s[i] for s in samples) for i in range(3)]
        print(f"  噪声std  X={std[0]:.4f}  Y={std[1]:.4f}  Z={std[2]:.4f} m/s²")
    return avg, total_g


def analyze_static(samples: List, result: TestResult, check_x=None, check_y=None):
    n = len(samples)
    if n < 10:
        result.fail(f"样本不足: 仅 {n} 个")
        return

    avg = [sum(s[i] for s in samples) / n for i in range(3)]
    total_g = math.sqrt(sum(a**2 for a in avg)) / EARTH_G

    # 总加速度应 ≈ 1g
    if 0.93 < total_g < 1.07:
        result.ok(f"总加速度合理: {total_g:.4f} g ≈ 1g")
    else:
        result.fail(f"总加速度异常: {total_g:.4f} g (应接近 1g)")

    # Z 轴应为负（重力向下）
    z_g = avg[2] / EARTH_G
    if z_g < -0.5:
        result.ok(f"Z轴方向正确: {z_g:+.3f} g (负值=重力向下 ✓)")
    else:
        result.fail(f"Z轴方向异常: {z_g:+.3f} g (应为负值！检查 v[0] 符号)")

    # 稳定性
    if n > 1:
        std = [statistics.stdev(s[i] for s in samples) for i in range(3)]
        if max(std) < 0.5:
            result.ok(f"数据稳定 (max std={max(std):.3f} m/s²)")
        else:
            result.warn(f"数据波动较大 (std X={std[0]:.3f} Y={std[1]:.3f} Z={std[2]:.3f})")

    # 附加方向检查
    if check_x is not None:
        x_g = avg[0] / EARTH_G
        if check_x == "near_zero":
            if abs(x_g) < 0.12:
                result.ok(f"X(前进) ≈ 0: {x_g:+.3f} g ✓")
            else:
                result.warn(f"X(前进)偏离零: {x_g:+.3f} g (车辆可能有纵向倾斜)")
        elif check_x == "negative":
            if x_g < -0.05:
                result.ok(f"X(前进) < 0: {x_g:+.3f} g (上坡重力后分量 ✓)")
            else:
                result.warn(f"X(前进) = {x_g:+.3f} g (期望 <0 上坡)")
        elif check_x == "positive":
            if x_g > 0.05:
                result.ok(f"X(前进) > 0: {x_g:+.3f} g (下坡重力前分量 ✓)")
            else:
                result.warn(f"X(前进) = {x_g:+.3f} g (期望 >0 下坡)")

    if check_y is not None:
        y_g = avg[1] / EARTH_G
        if check_y == "near_zero":
            if abs(y_g) < 0.12:
                result.ok(f"Y(右) ≈ 0: {y_g:+.3f} g ✓")
            else:
                result.warn(f"Y(右)偏离零: {y_g:+.3f} g (车辆可能有横向倾斜)")
        elif check_y == "negative":
            if y_g < -0.05:
                result.ok(f"Y(右) < 0: {y_g:+.3f} g (左倾重力向左分量 ✓)")
            else:
                result.warn(f"Y(右) = {y_g:+.3f} g (期望 <0 左倾)")
        elif check_y == "positive":
            if y_g > 0.05:
                result.ok(f"Y(右) > 0: {y_g:+.3f} g (右倾重力向右分量 ✓)")
            else:
                result.warn(f"Y(右) = {y_g:+.3f} g (期望 >0 右倾)")


# ──────────────────────────────────────────────
# 9 个测试场景
# ──────────────────────────────────────────────

class ScenarioTests:
    def __init__(self, reader: SensordWTReader):
        self.reader = reader

    def _wait_stable(self, secs: int = 3):
        for i in range(secs, 0, -1):
            print(f"  {i}...", end="\r", flush=True)
            time.sleep(1)
        print("  开始采集...   ")

    def scene1_horizontal(self) -> TestResult:
        """场景1: 水平地面静止 — 期望 meas ≈ [0, 0, -9.81]"""
        print("\n" + "=" * 68)
        print("场景 1: 水平地面静止")
        print("  请将传感器/车辆置于水平地面，保持静止")
        print("  期望: X≈0  Y≈0  Z≈-9.81 m/s²")
        self._wait_stable(3)
        samples = self.reader.collect_accel(100)
        print_meas_summary(samples, "加速度计 meas")
        result = TestResult()
        analyze_static(samples, result, check_x="near_zero", check_y="near_zero")
        result.print_report("水平地面静止")
        return result

    def scene2_uphill(self) -> TestResult:
        """场景2: 坡道车头朝上 — 期望 meas[0] < 0"""
        print("\n" + "=" * 68)
        print("场景 2: 坡道车头朝上")
        print("  请将传感器/车辆停在坡道上，车头朝上")
        print("  期望: X(前进) < 0（重力向后分量）")
        input("  准备就绪后按 Enter 开始采集...")
        samples = self.reader.collect_accel(100)
        print_meas_summary(samples, "加速度计 meas")
        result = TestResult()
        analyze_static(samples, result, check_x="negative")
        result.print_report("坡道车头朝上")
        return result

    def scene3_downhill(self) -> TestResult:
        """场景3: 坡道车头朝下 — 期望 meas[0] > 0"""
        print("\n" + "=" * 68)
        print("场景 3: 坡道车头朝下")
        print("  请将传感器/车辆停在坡道上，车头朝下")
        print("  期望: X(前进) > 0（重力向前分量）")
        input("  准备就绪后按 Enter 开始采集...")
        samples = self.reader.collect_accel(100)
        print_meas_summary(samples, "加速度计 meas")
        result = TestResult()
        analyze_static(samples, result, check_x="positive")
        result.print_report("坡道车头朝下")
        return result

    def scene4_left_tilt(self) -> TestResult:
        """场景4: 左倾斜 — 期望 meas[1] < 0"""
        print("\n" + "=" * 68)
        print("场景 4: 左倾斜")
        print("  请将传感器/车辆向左倾斜（左侧低）")
        print("  期望: Y(右) < 0（重力向左分量）")
        input("  准备就绪后按 Enter 开始采集...")
        samples = self.reader.collect_accel(100)
        print_meas_summary(samples, "加速度计 meas")
        result = TestResult()
        analyze_static(samples, result, check_y="negative")
        result.print_report("左倾斜")
        return result

    def scene5_right_tilt(self) -> TestResult:
        """场景5: 右倾斜 — 期望 meas[1] > 0"""
        print("\n" + "=" * 68)
        print("场景 5: 右倾斜")
        print("  请将传感器/车辆向右倾斜（右侧低）")
        print("  期望: Y(右) > 0（重力向右分量）")
        input("  准备就绪后按 Enter 开始采集...")
        samples = self.reader.collect_accel(100)
        print_meas_summary(samples, "加速度计 meas")
        result = TestResult()
        analyze_static(samples, result, check_y="positive")
        result.print_report("右倾斜")
        return result

    def scene6_forward(self) -> TestResult:
        """场景6: 前进运动 — 期望 meas[0] > 0"""
        print("\n" + "=" * 68)
        print("场景 6: 前进运动")
        print("  请向前推动/移动传感器（模拟前进加速）")
        print("  等待检测到 X > 0.15g 后自动采集...")
        result = TestResult()
        trig = self.reader.wait_trigger_accel(axis=0, direction=+1,
                                              threshold=0.15 * EARTH_G)
        if trig is None:
            result.fail("超时未检测到前进加速度 (X > 0.15g)")
            result.print_report("前进运动")
            return result
        print(f"  触发! X={trig[0]/EARTH_G:+.3f} g")
        # 触发帧本身就是峰值帧，直接用于判断
        with self.reader._lock:
            samples = [item[0] for item in list(self.reader._accel_buf)]
        print_meas_summary(samples, "加速度计 meas")
        x_peak = trig[0] / EARTH_G
        if x_peak > 0.1:
            result.ok(f"前进加速度峰值: X={x_peak:+.3f} g (> 0.1g ✓)")
        else:
            result.fail(f"前进加速度峰值不足: X={x_peak:+.3f} g")
        result.print_report("前进运动")
        return result

    def scene7_reverse(self) -> TestResult:
        """场景7: 倒车运动/制动 — 期望 meas[0] < 0

        操作方法：快速向前推传感器后突然停止（模拟制动减速），
        停止瞬间会产生 X 负值冲击。
        也可以直接向后拉传感器产生 X 负值。
        """
        print("\n" + "=" * 68)
        print("场景 7: 倒车/制动运动")
        print("  操作方法（两种任选其一）：")
        print("    ① 快速向前推传感器后【突然停止】（停止时 X 出现负值冲击）")
        print("    ② 直接向后快速拉/推传感器")
        print("  等待检测到 X < -0.15g 后自动采集...")
        result = TestResult()
        trig = self.reader.wait_trigger_accel(axis=0, direction=-1,
                                              threshold=0.15 * EARTH_G)
        if trig is None:
            result.fail("超时未检测到制动/倒车加速度 (X < -0.15g)")
            result.print_report("倒车/制动运动")
            return result
        print(f"  触发! X={trig[0]/EARTH_G:+.3f} g")
        # 触发帧本身就是峰值帧，直接用于判断
        with self.reader._lock:
            samples = [item[0] for item in list(self.reader._accel_buf)]
        print_meas_summary(samples, "加速度计 meas")
        x_peak = trig[0] / EARTH_G
        if x_peak < -0.1:
            result.ok(f"制动/倒车加速度峰值: X={x_peak:+.3f} g (< -0.1g ✓)")
        else:
            result.fail(f"制动/倒车加速度峰值不足: X={x_peak:+.3f} g")
        result.print_report("倒车/制动运动")
        return result

    def scene8_left_turn(self) -> TestResult:
        """场景8: 向前推运动 — 物理前推激励WT_Y正向 → meas[X前进] > 0

        新映射（实测确认）:
          wt_accel.cc: v[2] = -WT_Y
          meas[0] = -v[2] = +WT_Y = X前进
          向前推 → WT_Y增大(正) → meas[0]增大 → meas[0] > 0
        """
        print("\n" + "=" * 68)
        print("场景 8: 向前推运动")
        print("  操作方法：快速向前推动传感器（传感器前进方向）")
        print("  期望：meas[X前进] > 0（WT_Y正向 → X前进正值冲击）")
        print("  等待检测到运动冲击（任意轴 > 0.3g）后自动采集...")
        result = TestResult()
        samples = self.reader.wait_trigger_any(threshold=0.3 * EARTH_G)
        if samples is None:
            result.fail("超时未检测到运动冲击")
            result.print_report("左推运动")
            return result
        print_meas_summary(samples, "加速度计 meas")
        x_min = min(s[0] for s in samples) / EARTH_G if samples else 0
        x_max = max(s[0] for s in samples) / EARTH_G if samples else 0
        print(f"  X轴范围: min={x_min:+.3f}g  max={x_max:+.3f}g")
        if x_max > 0.1:
            result.ok(f"前推加速度峰值: X={x_max:+.3f} g (> 0.1g ✓)")
        else:
            result.fail(f"前推加速度峰值不足: X_max={x_max:+.3f} g（期望向前推 meas[0]>0.1g）")
        result.print_report("向前推运动")
        return result

    def scene9_right_turn(self) -> TestResult:
        """场景9: 向后推运动 — 物理后推激励WT_Y负向 → meas[X前进] < 0

        新映射（实测确认）:
          wt_accel.cc: v[2] = -WT_Y
          meas[0] = -v[2] = +WT_Y = X前进
          向后推 → WT_Y减小(负) → meas[0]减小 → meas[0] < 0
        """
        print("\n" + "=" * 68)
        print("场景 9: 向后推运动")
        print("  操作方法：快速向后推动传感器（与前进方向相反）")
        print("  期望：meas[X前进] < 0（WT_Y负向 → X前进负值冲击）")
        print("  等待检测到运动冲击（任意轴 > 0.3g）后自动采集...")
        result = TestResult()
        samples = self.reader.wait_trigger_any(threshold=0.3 * EARTH_G)
        if samples is None:
            result.fail("超时未检测到运动冲击")
            result.print_report("右推运动")
            return result
        print_meas_summary(samples, "加速度计 meas")
        x_min = min(s[0] for s in samples) / EARTH_G if samples else 0
        x_max = max(s[0] for s in samples) / EARTH_G if samples else 0
        print(f"  X轴范围: min={x_min:+.3f}g  max={x_max:+.3f}g")
        if x_min < -0.1:
            result.ok(f"后推加速度峰值: X={x_min:+.3f} g (< -0.1g ✓)")
        else:
            result.fail(f"后推加速度峰值不足: X_min={x_min:+.3f} g（期望向后推 meas[0]<-0.1g）")
        result.print_report("向后推运动")
        return result


# ──────────────────────────────────────────────
# 实时监控模式
# ──────────────────────────────────────────────

def monitor_mode(reader: SensordWTReader):
    """实时打印 locationd meas 值，Ctrl+C 退出"""
    print("\n实时监控模式 (Ctrl+C 退出)")
    print(f"{'时间':>8}  {'X(前进)':>10}  {'Y(右)':>10}  {'Z(上)':>10}  "
          f"{'总量':>8}  | {'Gyro_roll':>10}  {'pitch':>10}  {'yaw':>10}")
    print("-" * 90)

    last_accel = None
    last_gyro = None
    t0 = time.time()

    while True:
        now = f"{time.time() - t0:7.1f}s"
        with reader._lock:
            if reader._accel_buf:
                last_accel = reader._accel_buf[-1][0]
            if reader._gyro_buf:
                last_gyro = reader._gyro_buf[-1][0]

        if last_accel:
            m = last_accel
            g = math.sqrt(sum(v**2 for v in m)) / EARTH_G
            accel_str = (f"{m[0]:+10.4f}  {m[1]:+10.4f}  {m[2]:+10.4f}  {g:8.4f}g")
        else:
            accel_str = f"{'--':>10}  {'--':>10}  {'--':>10}  {'--':>8}"

        if last_gyro:
            g2 = last_gyro
            gyro_str = f"{g2[0]:+10.4f}  {g2[1]:+10.4f}  {g2[2]:+10.4f}"
        else:
            gyro_str = f"{'--':>10}  {'--':>10}  {'--':>10}"

        print(f"{now}  {accel_str}  | {gyro_str}", flush=True)
        time.sleep(0.1)


# ──────────────────────────────────────────────
# 总结打印
# ──────────────────────────────────────────────

def print_summary(results: dict):
    scene_names = {
        1: "水平地面静止",
        2: "坡道车头朝上",
        3: "坡道车头朝下",
        4: "左倾斜",
        5: "右倾斜",
        6: "前进运动",
        7: "倒车运动",
        8: "左推运动",
        9: "右推运动",
    }
    print("\n" + "=" * 68)
    print("测试总结")
    print("=" * 68)
    all_passed = True
    for num in sorted(results):
        r = results[num]
        name = scene_names.get(num, f"场景{num}")
        status = "✅ 通过" if r.passed else "❌ 失败"
        errs = sum(1 for s, _ in r.details if s == "FAIL")
        warns = sum(1 for s, _ in r.details if s == "WARN")
        print(f"  场景{num} {name:<10}  {status}   "
              f"(错误:{errs}  警告:{warns})")
        if not r.passed:
            all_passed = False
    print("=" * 68)
    passed_count = sum(1 for r in results.values() if r.passed)
    print(f"\n总计: {passed_count}/{len(results)} 场景通过")
    if all_passed:
        print("🎉 所有场景通过！坐标轴映射符合 locationd 预期。")
    else:
        print("⚠️  部分场景失败，请检查传感器安装方向或轴映射。")
    print("=" * 68)


# ──────────────────────────────────────────────
# 主入口
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="WT 传感器场景测试 (解析 ./sensord_wt --verbose 输出)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--device", default="/dev/ttyUSB0",
                        help="串口设备路径 (默认: /dev/ttyUSB0)")
    parser.add_argument("--baud", type=int, default=115200,
                        help="波特率 (默认: 115200)")
    parser.add_argument("--static", action="store_true",
                        help="仅运行静态场景 (1-5)，无需手动操作")
    parser.add_argument("--dynamic", action="store_true",
                        help="仅运行动态场景 (6-9)")
    parser.add_argument("--scene", type=int, nargs="+",
                        help="指定场景编号，例如: --scene 1 4 5")
    parser.add_argument("--monitor", action="store_true",
                        help="实时监控模式（持续打印 meas 值）")
    args = parser.parse_args()

    # 确定场景列表
    if args.scene:
        scenes = args.scene
    elif args.static:
        scenes = [1, 2, 3, 4, 5]
    elif args.dynamic:
        scenes = [6, 7, 8, 9]
    elif args.monitor:
        scenes = []
    else:
        scenes = list(range(1, 10))  # 默认运行全部场景 1-9

    print("=" * 68)
    print("WT 传感器场景测试 (基于 ./sensord_wt --verbose 输出)")
    print("坐标系：openpilot 设备坐标系（经 locationd 变换）")
    print("  X(前进) = meas[0] = -WT_Y   前进方向+  [实测: 物理左右推主要激励此轴]")
    print("  Y(横向) = meas[1] = -WT_X   右方向+  [实测: 物理前后推主要激励此轴]")
    print("  Z(上)   = meas[2] = -WT_Z   向上+（重力≈-9.81）")
    print("=" * 68)
    print(f"设备: {args.device}  波特率: {args.baud}")
    print(f"场景: {'监控模式' if args.monitor else (scenes if scenes else '全部 1-9')}")

    reader = SensordWTReader(device=args.device, baud=args.baud)
    if not reader.start():
        sys.exit(1)

    # 等待第一批数据
    print("\n等待传感器数据...", end="", flush=True)
    deadline = time.time() + 5
    while time.time() < deadline:
        with reader._lock:
            if reader._accel_buf:
                break
        time.sleep(0.1)
        print(".", end="", flush=True)
    print()

    with reader._lock:
        got = len(reader._accel_buf)
    if got == 0:
        print("错误: 5 秒内未收到任何加速度数据，请检查串口连接")
        reader.stop()
        sys.exit(1)
    print(f"已收到数据，开始测试\n")

    try:
        if args.monitor:
            monitor_mode(reader)
            return

        tests = ScenarioTests(reader)
        scene_funcs = {
            1: ("水平地面静止", tests.scene1_horizontal),
            2: ("坡道车头朝上", tests.scene2_uphill),
            3: ("坡道车头朝下", tests.scene3_downhill),
            4: ("左倾斜",       tests.scene4_left_tilt),
            5: ("右倾斜",       tests.scene5_right_tilt),
            6: ("前进运动",     tests.scene6_forward),
            7: ("倒车运动",     tests.scene7_reverse),
            8: ("左转运动",     tests.scene8_left_turn),
            9: ("右转运动",     tests.scene9_right_turn),
        }

        results = {}
        for num in sorted(scenes):
            if num not in scene_funcs:
                print(f"警告: 未知场景编号 {num}，跳过")
                continue
            _, func = scene_funcs[num]
            try:
                results[num] = func()
            except KeyboardInterrupt:
                print("\n用户中断，跳过剩余场景")
                break
            except Exception as e:
                r = TestResult()
                r.fail(f"异常: {e}")
                results[num] = r

        if results:
            print_summary(results)

    except KeyboardInterrupt:
        print("\n用户中断")
    finally:
        reader.stop()


if __name__ == "__main__":
    main()
