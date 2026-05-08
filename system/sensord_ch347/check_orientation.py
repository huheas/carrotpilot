#!/usr/bin/env python3
"""
检查 CH347 LSM6DSM 传感器安装方向和坐标系
"""
import time
import sys

# 添加项目路径
sys.path.insert(0, '/data/carrot2-v9-acc')

from openpilot.system.sensord_ch347.sensors.lsm6ds3_accel import LSM6DS3_Accel


def main():
    print("=" * 60)
    print("CH347 LSM6DSM 传感器坐标系检查工具")
    print("=" * 60)

    # 初始化传感器
    print("\n[1/4] 初始化传感器...")
    accel = LSM6DS3_Accel(10)
    accel.init()
    print("✓ 传感器初始化成功")

    # 预热
    print("\n[2/4] 传感器预热 (2秒)...")
    print("请将车辆停在水平地面，保持静止")
    for i in range(2, 0, -1):
        print(f"  {i}...")
        time.sleep(1)

    # 采集数据
    print("\n[3/4] 采集数据 (100 个样本)...")
    samples = []
    for i in range(100):
        evt = accel.get_event()
        samples.append(evt.acceleration.v)
        if (i + 1) % 20 == 0:
            print(f"  已采集 {i + 1}/100")
        time.sleep(0.01)

    # 计算平均值
    print("\n[4/4] 分析结果...")
    avg_x = sum(s[0] for s in samples) / len(samples)
    avg_y = sum(s[1] for s in samples) / len(samples)
    avg_z = sum(s[2] for s in samples) / len(samples)

    # 转换为 g (传感器输出是 m/s²)
    avg_x_g = avg_x / 9.81
    avg_y_g = avg_y / 9.81
    avg_z_g = avg_z / 9.81

    print(f"\n{'=' * 60}")
    print(f"平均加速度 (m/s²):")
    print(f"{'=' * 60}")
    print(f"  X = {avg_x:+.3f} m/s²")
    print(f"  Y = {avg_y:+.3f} m/s²")
    print(f"  Z = {avg_z:+.3f} m/s²")
    print(f"\n平均加速度 (g):")
    print(f"{'=' * 60}")
    print(f"  X = {avg_x_g:+.3f} g")
    print(f"  Y = {avg_y_g:+.3f} g")
    print(f"  Z = {avg_z_g:+.3f} g")
    print(f"{'=' * 60}")

    # 判断安装方向（使用 g 单位）
    print("\n📐 安装方向分析:")
    print("-" * 60)

    # Z 轴检查
    if abs(avg_z_g) > 0.8:
        print("✓ Z 轴垂直（正确安装）")
        if avg_z_g > 0:
            print("  → Z 轴朝上 ✅")
        else:
            print("  → Z 轴朝下 ❌（需要翻转传感器）")
    else:
        print("❌ 传感器倾斜角度过大")
        print(f"  → Z 轴读数 {avg_z_g:.2f}g，预期 ≈ 1.0g")

    # X/Y 轴检查
    tilt_x = abs(avg_x_g)
    tilt_y = abs(avg_y_g)

    if tilt_x < 0.2 and tilt_y < 0.2:
        print("✓ 传感器基本水平 ✅")
    else:
        print(f"⚠ 传感器有倾斜")
        if tilt_x >= 0.2:
            print(f"  → X 轴偏移 {avg_x_g:+.2f}g（建议 < 0.2g）")
        if tilt_y >= 0.2:
            print(f"  → Y 轴偏移 {avg_y_g:+.2f}g（建议 < 0.2g）")

    # 安装方向建议
    print("\n💡 安装建议:")
    print("-" * 60)
    if abs(avg_z) > 0.8 and tilt_x < 0.2 and tilt_y < 0.2:
        print("✅ 传感器安装正确！")
        print("   - 水平放置")
        print("   - Z 轴朝上")
        print("   - 与车辆坐标系对齐")
    else:
        print("推荐安装方式:")
        print("  1. 将传感器水平放置在仪表台上")
        print("  2. USB 口朝向车辆前方或后方")
        print("  3. 传感器长边与车辆纵向平行")
        print("  4. 重新运行此脚本验证")

    # 坐标系对应关系
    print("\n📊 传感器轴与车辆方向对应关系:")
    print("-" * 60)
    print("  传感器 X 轴 → 车辆横向（右+ 左-）")
    print("  传感器 Y 轴 → 车辆纵向（前+ 后-）")
    print("  传感器 Z 轴 → 车辆垂直（上+ 下-）")

    print("\n🚗 动态测试验证:")
    print("-" * 60)
    print("  直行加速 → Y 轴应该增加（正向）")
    print("  刹车减速 → Y 轴应该减小（负向）")
    print("  左转弯   → X 轴应该增加（正向）")
    print("  右转弯   → X 轴应该减小（负向）")

    print(f"\n{'=' * 60}")
    print("检查完成！")
    print(f"{'=' * 60}")

    # 关闭传感器
    accel.bus.close()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
