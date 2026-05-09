# sensord_ch347 - CH347 USB-to-I2C LSM6DS3 IMU 传感器

通过 CH347 USB-to-I2C 适配器读取 LSM6DS3/LSM6DSM IMU 数据，为 openpilot 提供加速度计和陀螺仪服务。

使用 **aystarik/ch347_vcp** 开源内核驱动，通过标准 Linux smbus2 接口访问，无需专有库。

---

## 快速启动

```bash
cd /data/carrot2-v9-1215-acc
source .venv/bin/activate

# 自动检测总线，自动加载驱动，自动修复权限
python3 -m openpilot.system.sensord_ch347.sensord_ch347

# 手动指定总线号
python3 -m openpilot.system.sensord_ch347.sensord_ch347 --bus 7
```

程序会自动完成：
1. 加载内核模块 (`mfd_ch347`, `i2c_ch347`)
2. 绑定 USB 接口到驱动
3. 检测 I2C 总线号
4. 修复设备权限
5. 初始化传感器并以多线程轮询方式发布数据

---

## 命令行参数

```
--bus N        I2C 总线号（默认: 自动检测）
--verbose      启用调试日志
--no-accel     禁用加速度计
--no-gyro      禁用陀螺仪
--enable-temp  启用温度传感器（默认禁用）
```

---

## 硬件信息

| 项目 | 值 |
|------|------|
| I2C 驱动 | aystarik/ch347_vcp (mfd-ch347 + i2c-ch347) |
| 传感器 | LSM6DS3 (WHO_AM_I=0x6A) 或 LSM6DSM (WHO_AM_I=0x69) |
| I2C 地址 | 0x6B (SA0 拉高) |
| I2C 总线 | 自动检测（扫描 /sys/bus/i2c/devices/ 中的 ch347 适配器） |
| 采样率 | 104 Hz |
| 加速度计量程 | ±2g |
| 陀螺仪量程 | ±250 dps |

---

## 传感器坐标系

### 芯片物理轴方向（实测确认）

通过手动倾斜测试（`test_axis_direction.py`）确认，**芯片朝上水平安装**时：

```
                车辆前方
                  ↑
                  │ 芯片 Y- (前方)
                  │
            ┌─────┼─────┐
            │     │     │
  芯片 X+  ←┤     O     ├→  芯片 X- (右方)
  (左方)    │           │
            │  LSM6DS3  │
            │  芯片朝上  │
            └─────┬─────┘
                  │
                  │ 芯片 Z+ (上方)
                  ⊙ (朝向你)
```

**实测结论**:
- **X+** = 右方 (RIGHT)
- **Y+** = 前方 (FORWARD)
- **Z+** = 上方 (UP)
- **Z+ 旋转** = 左转/逆时针 (CCW, 右手定则)

芯片水平放置、芯片面朝上时的坐标系。

### 代码映射

openpilot `locationd.py` 的转换公式：
```
meas = [-v[2], -v[1], -v[0]]
meas[0] = 前进(forward), meas[1] = 左方(leftward), meas[2] = 上方(up, 静止=-9.81)
```

推导正确映射：
```python
# 需要: meas = [前, 左, 上(=-9.81)] = [y, -x, -z]
#   v[0]=z   → meas[2] = -v[0] = -z = -9.81 ✓ (Z+朝上,静止时z=+9.81)
#   v[1]=x   → meas[1] = -v[1] = -x = 左 ✓ (X+朝右,取反=左)
#   v[2]=-y  → meas[0] = -v[2] = y  = 前 ✓ (Y+朝前)

a.v = [z, x, -y]                          # 加速度计
xyz = [z * scale, x * scale, -y * scale]   # 陀螺仪
```

### 驾驶日志验证结果

使用路线 00000197(直道急加减速) 和 00000198(右转弯) 交叉验证：

| 测试场景 | meas 变化 | 物理期望 | 结果 |
|---------|----------|---------|------|
| 静止重力 | meas[2] = -9.82 | ≈ -9.81 | ✓ |
| 加速 | meas[0] > 0 | 前进(正) | ✓ (r=0.99) |
| 刹车 | meas[0] < 0 | 减速(负) | ✓ (sign=100%) |
| 右转 yaw | meas_gyro[2] < 0 | 右转=负 | ✓ (r=+0.99) |
| 右转横向 | meas[1] < 0 | 离心力向右=左轴负 | ✓ (r=+0.82) |

---

## 架构

```
sensord_ch347.py (主进程)
  ├── ensure_ch347_modules_loaded()   # 自动加载内核模块
  ├── ensure_ch347_driver_bound()     # 自动绑定 USB 接口
  ├── detect_ch347_bus()              # 自动检测 I2C 总线号
  ├── ensure_i2c_accessible()         # 自动修复权限
  │
  ├── Thread: poll_accelerometer      # 104Hz 轮询加速度计
  │     └── LSM6DS3_Accel.get_event() → PubMaster("accelerometer")
  │
  └── Thread: poll_gyroscope          # 104Hz 轮询陀螺仪
        └── LSM6DS3_Gyro.get_event()  → PubMaster("gyroscope")
```

所有传感器使用轮询模式（CH347 不暴露 INT1 GPIO 中断线）。

---

## 驱动安装

### 一键安装

```bash
sudo bash system/sensord_ch347/setup_ch347.sh
```

### 手动安装

```bash
# 下载驱动源码
git clone https://github.com/aystarik/ch347_vcp.git /data/soft/ch347_vcp

# 编译驱动
cd /data/soft/ch347_vcp && make

# 安装到系统
sudo cp *.ko /lib/modules/$(uname -r)/updates/
sudo depmod -a

# 配置开机加载
echo -e "mfd-ch347\ni2c-ch347" | sudo tee /etc/modules-load.d/ch347.conf

# 加载
sudo modprobe mfd-ch347 && sudo modprobe i2c-ch347
```

---

## 故障排查

### 找不到 I2C 总线

```bash
# 检查模块
lsmod | grep ch347

# 检查 USB 设备
lsusb | grep 1a86

# 列出 I2C 适配器
i2cdetect -l | grep ch347

# 查看内核日志
dmesg | grep -i ch347
```

### 权限问题

程序会自动尝试修复。手动修复：
```bash
sudo chmod 666 /dev/i2c-*
# 或运行安装脚本配置 udev 规则
sudo bash system/sensord_ch347/setup_ch347.sh
```

### 传感器未响应

```bash
# 扫描总线（替换 N 为实际总线号）
sudo i2cdetect -y N
# 应该在 0x6B 位置看到设备

# 读取 WHO_AM_I
sudo i2cget -y N 0x6b 0x0f
# 返回 0x69 (LSM6DSM) 或 0x6A (LSM6DS3TRC)
```

---

## 文件清单

### 核心代码
| 文件 | 说明 |
|------|------|
| `sensord_ch347.py` | 主守护进程（自动检测、多线程轮询） |
| `sensors/i2c_sensor.py` | I2C 传感器基类 (smbus2) |
| `sensors/lsm6ds3_accel.py` | 加速度计驱动 |
| `sensors/lsm6ds3_gyro.py` | 陀螺仪驱动 |

### 工具
| 文件 | 说明 |
|------|------|
| `test_axis_direction.py` | 交互式轴方向测试工具 |
| `check_orientation.py` | 安装方向快速检查 |
| `setup_ch347.sh` | 驱动一键安装脚本 |

---

**最后更新**: 2026-05-09
