# LSM6DSM 传感器坐标系与车辆方向对应关系

## 📐 传感器物理坐标系

根据 LSM6DSM 数据手册和 Android 传感器标准：

### LSM6DSM 芯片轴定义

```
         Y 轴
          ↑
          │
          │
          │
    Z 轴 ←┼──→ X 轴
   (向上)  │  (向右)
          │
          │
          │
          O  (芯片中心)
```

**俯视图（从芯片顶部看）**：
- **X 轴**：从芯片中心指向右侧
- **Y 轴**：从芯片中心指向前方
- **Z 轴**：从芯片底部指向顶部（垂直于芯片表面）

---

## 🚗 车辆坐标系（openpilot 标准）

openpilot 使用 **右前上 (RFU)** 坐标系：

```
              车辆前方
                ↑
                │ Y 轴 (前向)
                │
          ┌─────┼─────┐
          │     │     │
    左 ←──┤     O     ├──→ 右
    X 轴  │           │  X 轴
    (负)  │           │  (正)
          │           │
          └─────┬─────┘
                │
                │ Z 轴 (上)
                ↓
              车辆下方
```

**定义**：
- **X 轴**：车辆横向，向右为正，向左为负
- **Y 轴**：车辆纵向，向前为正，向后为负
- **Z 轴**：垂直方向，向上为正，向下为负

---

## 🔄 传感器安装方向与轴对应关系

### 情况 1：传感器 PCB 水平安装（推荐）

如果 CH347 + LSM6DSM 模块**水平放置**在仪表台上：

```
         车辆前方 (Y+)
              ↑
              │
    ┌─────────┼─────────┐
    │                    │
    │    CH347 模块      │
    │   ┌──────────┐     │
    ←──┤─  X-  X+ ─├──→  ← 车辆横向 (X)
    │   │  USB口   │     │
    │   └──────────┘     │
    │         │          │
    │         ↓ Y+       │
    └─────────┼─────────┘
              │
           车辆右侧 (X+)
```

**对应关系**：
- **传感器 Y 轴** → **车辆 Y 轴**（前向）
- **传感器 X 轴** → **车辆 X 轴**（右向）
- **传感器 Z 轴** → **车辆 Z 轴**（上向）

**静态读数（车辆水平停放）**：
```
加速度:
  X ≈ 0g    (横向无加速度)
  Y ≈ 0g    (纵向无加速度)
  Z ≈ +1g   (重力向上，与 Z 轴正方向相反)

注意：加速度计测量的是反作用力，所以 Z 轴读数为 +1g
```

### 情况 2：传感器旋转 90 度安装

如果模块旋转了 90 度：

```
         车辆前方 (Y+)
              ↑
              │
    ┌─────────┼─────────┐
    │         │          │
    │    ┌────┴────┐     │
    │    │         │     │
    ←───┤  USB口  ├──→   ← 车辆横向 (X)
    │    │         │     │
    │    └────┬────┘     │
    │         │          │
    └─────────┼─────────┘
              │
           车辆右侧 (X+)
```

**对应关系**：
- **传感器 X 轴** → **车辆 -Y 轴**（后向）
- **传感器 Y 轴** → **车辆 -X 轴**（左向）
- **传感器 Z 轴** → **车辆 Z 轴**（上向）

---

## 📊 实际测试数据分析

从之前的测试数据：
```
加速度: X=-3.530g, Y=-3.665g, Z=8.404g
```

**分析**：
1. Z 轴 ≈ +8.4g → 接近 +1g（重力），说明 Z 轴朝上 ✅
2. X 和 Y 都有较大负值 → 传感器可能有倾斜或安装角度

**建议**：
- 将车辆停在水平地面
- 重新读取静态数据
- 计算传感器的安装角度偏移

---

## 🔧 如何确定你的安装方向

### 步骤 1：静态测试

将车辆停在**水平地面**，运行：

```bash
cd /data/carrot2-v9-acc
source .venv/bin/activate
python3 -c "
from openpilot.system.sensord_ch347.sensors.lsm6ds3_accel import LSM6DS3_Accel
import time

accel = LSM6DS3_Accel(10)
accel.init()

print('静止状态加速度 (g):')
for i in range(10):
    evt = accel.get_event()
    x, y, z = evt.acceleration.v
    print(f'  X={x:+.3f}g, Y={y:+.3f}g, Z={z:+.3f}g')
    time.sleep(0.1)

accel.bus.close()
"
```

### 步骤 2：分析结果

**理想水平安装**：
```
X ≈ 0g
Y ≈ 0g
Z ≈ +1g
```

**实际情况**：
- 如果 X 或 Y 不为 0 → 传感器有倾斜
- 如果 Z 不是 +1g → 传感器倾斜角度较大

### 步骤 3：动态测试

开车直行加速：
- **Y 轴应该增加**（正向加速度）
- X 和 Z 基本不变

刹车减速：
- **Y 轴应该减小**（负向加速度）

转弯：
- **X 轴变化**（左转 X 正，右转 X 负）

---

## 📝 坐标系校准

如果传感器安装方向不标准，需要在代码中添加旋转矩阵：

### 示例：传感器旋转 90 度

```python
# 在 get_event() 中添加旋转变换
def get_event(self, ts: int | None = None) -> log.SensorEventData:
    raw_data = self.read_sensor()

    # 旋转矩阵（传感器 90 度旋转）
    x_vehicle = -raw_data.y  # 传感器 Y → 车辆 -X
    y_vehicle = -raw_data.x  # 传感器 X → 车辆 -Y
    z_vehicle = raw_data.z   # 传感器 Z → 车辆 Z

    event = log.SensorEventData.new_message()
    event.acceleration.v = [x_vehicle, y_vehicle, z_vehicle]
    return event
```

---

## 🎯 推荐安装方式

### 最佳实践

1. **水平放置**在仪表台上
2. **USB 口朝向车辆前方**或**后方**（保持一致）
3. **传感器长边与车辆纵向平行**

```
推荐安装（USB 口朝前）:

         车辆前方
            ↑
       ┌────────┐
       │  USB口 │  ← USB 线
       │        │
       │ CH347  │
       │  模块  │
       │        │
       └────────┘

传感器轴：
  Y+ → 车辆前方 ✅
  X+ → 车辆右方 ✅
  Z+ → 车辆上方 ✅
```

---

## 📌 总结

| 传感器轴 | 车辆方向 | 物理意义 | 静态值（水平） |
|---------|---------|---------|--------------|
| **X** | 横向（右+） | 左右加速度 | ≈ 0g |
| **Y** | 纵向（前+） | 前后加速度 | ≈ 0g |
| **Z** | 垂直（上+） | 重力加速度 | ≈ +1g |

**注意**：
- 加速度计测量的是**反作用力**，不是纯加速度
- 静止时 Z 轴读数为 +1g（重力的反作用力）
- 需要确认你的传感器实际安装方向
- 如有偏差，可通过软件校准

---

## 🔍 快速检查脚本

创建 `check_orientation.py`：

```python
#!/usr/bin/env python3
"""检查传感器安装方向"""
from openpilot.system.sensord_ch347.sensors.lsm6ds3_accel import LSM6DS3_Accel
import time

accel = LSM6DS3_Accel(10)
accel.init()

print("请将车辆停在水平地面")
print("等待 5 秒采集数据...")
time.sleep(5)

# 采集 100 个样本
samples = []
for _ in range(100):
    evt = accel.get_event()
    samples.append(evt.acceleration.v)
    time.sleep(0.01)

# 计算平均值
avg_x = sum(s[0] for s in samples) / len(samples)
avg_y = sum(s[1] for s in samples) / len(samples)
avg_z = sum(s[2] for s in samples) / len(samples)

print(f"\n平均加速度 (g):")
print(f"  X = {avg_x:+.3f}")
print(f"  Y = {avg_y:+.3f}")
print(f"  Z = {avg_z:+.3f}")

# 判断安装方向
if abs(avg_z) > 0.8:
    print("\n✓ Z 轴垂直（正确安装）")
    if avg_z > 0:
        print("  Z 轴朝上 ✅")
    else:
        print("  Z 轴朝下 ❌（需要翻转）")
else:
    print("\n❌ 传感器倾斜角度过大")

if abs(avg_x) < 0.2 and abs(avg_y) < 0.2:
    print("✓ 传感器基本水平 ✅")
else:
    print(f"⚠ 传感器有倾斜 (X={avg_x:.2f}, Y={avg_y:.2f})")

accel.bus.close()
```

运行：
```bash
python3 system/sensord_ch347/check_orientation.py
```
