#!/usr/bin/env python3
"""
WT 传感器轴向识别工具
====================
通过静止、倾斜、冲击三种方式，逐轴确认 WT_X/Y/Z 对应哪个物理方向。

使用方法:
  python3 system/sensord_wt/identify_axes.py

测试步骤:
  步骤1: 静止放置 → 确认重力在哪个轴
  步骤2: 向前倾斜传感器 → 确认哪个轴响应
  步骤3: 向右倾斜传感器 → 确认哪个轴响应
  步骤4: 向前快推 → 确认哪个轴冲击
  步骤5: 向左快推 → 确认哪个轴冲击
  步骤6: 向上快推 → 确认哪个轴冲击（可选）
"""

import os
import re
import subprocess
import sys
import threading
import time
from collections import deque

SENSORD_WT_BIN = os.path.join(os.path.dirname(__file__), "sensord_wt")
RE_ACCEL = re.compile(
    r"WT Accel:.*?scaled\[([-\d.]+),([-\d.]+),([-\d.]+)\]"
)

# ──────────────────────────────────────────
# 数据采集器
# ──────────────────────────────────────────
class AxisReader:
    def __init__(self, device="/dev/ttyUSB0", baud=115200):
        self.device = device
        self.baud = baud
        self._proc = None
        self._thread = None
        self._lock = threading.Lock()
        self._buf = deque(maxlen=1000)
        self._total = 0
        self._running = False

    def start(self):
        if not os.path.isfile(SENSORD_WT_BIN):
            print(f"[错误] 找不到 {SENSORD_WT_BIN}，请先编译")
            return False
        env = os.environ.copy()
        env["COLUMNS"] = "400"
        self._proc = subprocess.Popen(
            [SENSORD_WT_BIN, "--verbose", "--device", self.device, "--baud", str(self.baud)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=env
        )
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        print(f"  ✓ sensord_wt 已启动 (PID={self._proc.pid})")
        return True

    def stop(self):
        self._running = False
        if self._proc:
            self._proc.terminate()
            try: self._proc.wait(timeout=2)
            except: self._proc.kill()

    def _loop(self):
        pending = ""
        for line in self._proc.stdout:
            if not self._running:
                break
            line = line.rstrip()
            combined = pending + line
            pending = ""
            m = RE_ACCEL.search(combined)
            if m:
                x, y, z = float(m.group(1)), float(m.group(2)), float(m.group(3))
                with self._lock:
                    self._buf.append((x, y, z))
                    self._total += 1
            elif "WT Accel" in combined and "m/s" not in combined:
                pending = combined

    def wait_stable(self, count=80, timeout=10.0):
        """等待采集到 count 帧，返回样本列表"""
        deadline = time.time() + timeout
        with self._lock:
            start_total = self._total
        while time.time() < deadline:
            with self._lock:
                if self._total - start_total >= count:
                    return list(self._buf)[-count:]
            time.sleep(0.05)
        with self._lock:
            buf = list(self._buf)
        return buf[-count:] if len(buf) >= count else buf

    def wait_shock(self, threshold=2.0, timeout=15.0, post_frames=30):
        """等待任意轴冲击 > threshold m/s²，返回冲击窗口样本"""
        deadline = time.time() + timeout
        with self._lock:
            last_total = self._total
        found = False
        while time.time() < deadline:
            with self._lock:
                cur = self._total
                if cur > last_total:
                    new_n = cur - last_total
                    snap = list(self._buf)
                    new_items = snap[max(0, len(snap) - new_n):]
                    for x, y, z in new_items:
                        if abs(x) > threshold or abs(y) > threshold or abs(z - 9.8) > threshold:
                            found = True
                            break
                    last_total = cur
            if found:
                break
            time.sleep(0.02)
        if not found:
            return None
        # 等待后续帧
        time.sleep(post_frames * 0.012)
        with self._lock:
            buf = list(self._buf)
        return buf[max(0, len(buf) - post_frames * 2):]


# ──────────────────────────────────────────
# 分析函数
# ──────────────────────────────────────────
def mean(vals):
    return sum(vals) / len(vals) if vals else 0.0

def fmt(v):
    bar = "█" * int(abs(v) / 9.81 * 20)
    sign = "+" if v >= 0 else "-"
    return f"{v:+7.3f} m/s² {sign}{bar}"

def analyze_static(samples, label):
    """分析静止样本，确认重力方向"""
    if not samples:
        print("  [无数据]")
        return
    mx = mean([s[0] for s in samples])
    my = mean([s[1] for s in samples])
    mz = mean([s[2] for s in samples])
    total = (mx**2 + my**2 + mz**2) ** 0.5

    print(f"\n  {label}（{len(samples)}帧均值）:")
    print(f"    WT_X: {fmt(mx)}")
    print(f"    WT_Y: {fmt(my)}")
    print(f"    WT_Z: {fmt(mz)}")
    print(f"    |合力|: {total:.3f} m/s²  (期望≈9.81)")

    # 找最大绝对值轴
    axes = [("WT_X", mx), ("WT_Y", my), ("WT_Z", mz)]
    dominant = max(axes, key=lambda a: abs(a[1]))
    print(f"  → 重力主轴: {dominant[0]} = {dominant[1]:+.3f} m/s²", end="")
    if dominant[1] > 5:
        print(f"  (该轴正方向朝上)")
    elif dominant[1] < -5:
        print(f"  (该轴负方向朝上，即正方向朝下)")
    else:
        print()

def analyze_tilt(samples_before, samples_after, label, expected_axis):
    """分析倾斜前后差值，确认哪个轴有响应"""
    if not samples_before or not samples_after:
        print("  [无数据]")
        return
    bx = mean([s[0] for s in samples_before])
    by = mean([s[1] for s in samples_before])
    bz = mean([s[2] for s in samples_before])
    ax = mean([s[0] for s in samples_after])
    ay = mean([s[1] for s in samples_after])
    az = mean([s[2] for s in samples_after])

    dx, dy, dz = ax - bx, ay - by, az - bz

    print(f"\n  {label} 倾斜响应（前后差值）:")
    print(f"    ΔWTY_X: {dx:+7.3f}  ΔWTY_Y: {dy:+7.3f}  ΔWTZ: {dz:+7.3f}")

    changes = [("WT_X", abs(dx)), ("WT_Y", abs(dy)), ("WT_Z", abs(dz))]
    dominant = max(changes, key=lambda a: a[1])
    print(f"  → 主要响应轴: {dominant[0]} (|Δ|={dominant[1]:.3f})")
    if dominant[1] > 0.3:
        print(f"    结论: 物理 [{expected_axis}] ≈ {dominant[0]}")
    else:
        print(f"    ⚠ 倾斜幅度太小，请重试")

def analyze_shock(samples, label, expected_axis):
    """分析冲击样本，找主激励轴"""
    if not samples:
        print("  [无数据]")
        return
    # 去除静止基线（WT_Z≈9.8），找冲击偏差
    # 找每轴绝对偏差最大帧
    max_dx = max(samples, key=lambda s: abs(s[0] - (-0.7)))
    max_dy = max(samples, key=lambda s: abs(s[1] - 0.3))
    max_dz = max(samples, key=lambda s: abs(s[2] - 9.86))

    dx_peak = abs(max_dx[0] - (-0.7))
    dy_peak = abs(max_dy[1] - 0.3)
    dz_peak = abs(max_dz[2] - 9.86)

    print(f"\n  {label} 冲击分析:")
    print(f"    WT_X 最大偏差: {dx_peak:+6.2f} m/s²  (峰值帧 WT_X={max_dx[0]:+.2f})")
    print(f"    WT_Y 最大偏差: {dy_peak:+6.2f} m/s²  (峰值帧 WT_Y={max_dy[1]:+.2f})")
    print(f"    WT_Z 最大偏差: {dz_peak:+6.2f} m/s²  (峰值帧 WT_Z={max_dz[2]:+.2f})")

    dominant_axis = max([("WT_X", dx_peak), ("WT_Y", dy_peak), ("WT_Z", dz_peak)],
                        key=lambda a: a[1])
    if dominant_axis[1] > 1.0:
        print(f"  → 主激励轴: {dominant_axis[0]} (偏差={dominant_axis[1]:.2f} m/s²)")
        print(f"    结论: 物理 [{expected_axis}] ≈ {dominant_axis[0]}")
    else:
        print(f"  ⚠ 冲击太弱（主轴偏差仅{dominant_axis[1]:.2f} m/s²），请更用力推")


# ──────────────────────────────────────────
# 主测试流程
# ──────────────────────────────────────────
def wait_enter(prompt):
    input(f"\n  [{prompt}] 准备好后按 Enter 开始...")

def main():
    import argparse
    parser = argparse.ArgumentParser(description="WT 传感器轴向识别工具")
    parser.add_argument("--device", default="/dev/ttyUSB0")
    parser.add_argument("--baud", type=int, default=115200)
    args = parser.parse_args()

    print("=" * 65)
    print("  WT 传感器轴向识别工具")
    print("=" * 65)
    print("  目标：通过实测确认 WT_X / WT_Y / WT_Z 分别对应哪个物理方向")
    print("  期望（安装正确时）:")
    print("    WT_X → 车辆前进方向")
    print("    WT_Y → 车辆右侧方向")
    print("    WT_Z → 垂直向上")
    print()

    reader = AxisReader(args.device, args.baud)
    if not reader.start():
        sys.exit(1)

    print("  等待传感器稳定（2秒）...")
    time.sleep(2)

    results = {}

    # ══════════════════════════════════════
    # 步骤1: 静止 → 重力轴
    # ══════════════════════════════════════
    print("\n" + "─" * 65)
    print("【步骤1】静止放置")
    print("  将传感器水平放置在桌面上，保持静止")
    wait_enter("静止采集")
    print("  采集中（2秒）...")
    samples_static = reader.wait_stable(count=150, timeout=5.0)
    analyze_static(samples_static, "静止状态")
    results["static"] = samples_static

    # ══════════════════════════════════════
    # 步骤2: 向前倾斜 → 前进轴
    # ══════════════════════════════════════
    print("\n" + "─" * 65)
    print("【步骤2】向前倾斜约30°")
    print("  将传感器前端抬高约30°（使传感器前端朝上）")
    print("  保持倾斜状态静止")
    wait_enter("倾斜采集-前倾")
    print("  采集中（2秒）...")
    samples_tilt_fwd = reader.wait_stable(count=100, timeout=5.0)
    analyze_tilt(samples_static, samples_tilt_fwd, "前倾30°", "前进(X)")
    results["tilt_fwd"] = samples_tilt_fwd

    # ══════════════════════════════════════
    # 步骤3: 向右倾斜 → 右侧轴
    # ══════════════════════════════════════
    print("\n" + "─" * 65)
    print("【步骤3】向右倾斜约30°")
    print("  将传感器右端压低约30°（传感器右侧朝下）")
    print("  保持倾斜状态静止")
    wait_enter("倾斜采集-右倾")
    print("  采集中（2秒）...")
    samples_tilt_right = reader.wait_stable(count=100, timeout=5.0)
    analyze_tilt(samples_static, samples_tilt_right, "右倾30°", "右侧(Y)")
    results["tilt_right"] = samples_tilt_right

    # ══════════════════════════════════════
    # 步骤4: 向前快推 → 前进轴冲击
    # ══════════════════════════════════════
    print("\n" + "─" * 65)
    print("【步骤4】向前快速推动")
    print("  快速向前推动传感器约10cm（力度要大，能感受到冲击）")
    print("  检测到冲击后自动采集，超时15秒")
    wait_enter("冲击测试-向前推")
    print("  等待冲击...")
    samples_shock_fwd = reader.wait_shock(threshold=2.0, timeout=15.0)
    if samples_shock_fwd:
        analyze_shock(samples_shock_fwd, "向前推冲击", "前进(X)")
    else:
        print("  ⚠ 超时未检测到冲击，请更用力推")
    results["shock_fwd"] = samples_shock_fwd

    # ══════════════════════════════════════
    # 步骤5: 向左快推 → 左右轴冲击
    # ══════════════════════════════════════
    print("\n" + "─" * 65)
    print("【步骤5】向左快速推动")
    print("  快速向左推动传感器约10cm（力度要大）")
    print("  检测到冲击后自动采集，超时15秒")
    wait_enter("冲击测试-向左推")
    print("  等待冲击...")
    samples_shock_left = reader.wait_shock(threshold=2.0, timeout=15.0)
    if samples_shock_left:
        analyze_shock(samples_shock_left, "向左推冲击", "左侧(-Y)")
    else:
        print("  ⚠ 超时未检测到冲击")
    results["shock_left"] = samples_shock_left

    # ══════════════════════════════════════
    # 汇总报告
    # ══════════════════════════════════════
    print("\n" + "=" * 65)
    print("  【汇总报告】WT 轴向识别结果")
    print("=" * 65)

    # 重力轴
    if results.get("static"):
        s = results["static"]
        mx = mean([x[0] for x in s])
        my = mean([x[1] for x in s])
        mz = mean([x[2] for x in s])
        grav = max([("WT_X", abs(mx)), ("WT_Y", abs(my)), ("WT_Z", abs(mz))], key=lambda a: a[1])
        print(f"\n  静止重力主轴: {grav[0]}  (WT_X={mx:+.2f}, WT_Y={my:+.2f}, WT_Z={mz:+.2f})")

    print()
    print("  步骤2/3 前倾/右倾响应（与静止差值最大轴 = 该物理方向）")
    print("  步骤4/5 向前/向左冲击响应（偏差最大轴 = 该物理方向）")
    print()
    print("  根据以上结果，请确认 wt_accel.cc 中的轴映射是否正确:")
    print("    正确映射应为:")
    print("      v[0] = 使 meas[2] = Z上 的 WT 轴（应=重力轴，带正确符号）")
    print("      v[1] = 使 meas[1] = Y右 的 WT 轴（前倾不变，右倾变化）")
    print("      v[2] = 使 meas[0] = X前 的 WT 轴（前倾变化，右倾不变）")
    print("=" * 65)

    reader.stop()


if __name__ == "__main__":
    main()
