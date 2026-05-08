# sensord_ch347 - CH347 USB-to-I2C LSM6DSM 传感器

使用 **aystarik/ch347_vcp** 开源驱动的 LSM6DS3/LSM6DSM IMU 传感器守护进程，通过 CH347 USB-to-I2C 适配器为 openpilot 提供加速度计和陀螺仪数据。

---

## 📋 目录

- [系统架构](#系统架构)
- [驱动安装](#驱动安装)
- [代码修改](#代码修改)
- [传感器坐标系](#传感器坐标系)
- [使用方法](#使用方法)
- [测试结果](#测试结果)
- [故障排查](#故障排查)

---

## 🏗️ 系统架构

### 技术栈

| 组件 | 技术 | 状态 |
|------|------|------|
| I2C 驱动 | aystarik/ch347_vcp | ✅ 完美支持 kernel 6.11 |
| Python I2C 库 | smbus2 | ✅ 标准 Linux I2C 接口 |
| 传感器 | LSM6DSM | ✅ WHO_AM_I=0x69 |
| I2C 地址 | 0x6B | ✅ SA0 引脚拉高 |
| I2C 总线 | /dev/i2c-10 | ✅ 自动分配 |
| 内核版本 | Linux 6.11.0-21-generic | ✅ 已验证 |
| 操作系统 | Ubuntu 24.04 | ✅ 已验证 |

### 数据流

```
┌─────────────────────────────────────────────────┐
│              openpilot (cereal)                  │
│                                                   │
│  PubMaster ←── sensord_ch347.py ──→ Ratekeeper   │
│                     │                             │
│         ┌───────────┴───────────┐                │
│         │                       │                │
│    LSM6DS3_Accel          LSM6DS3_Gyro          │
│         │                       │                │
│         └───────────┬───────────┘                │
│                     │                             │
│              smbus2 (Python)                      │
│                     │                             │
└─────────────────────┼─────────────────────────────┘
                      │
              ┌───────┴───────┐
              │  /dev/i2c-10  │
              │   (I2C Bus)   │
              └───────┬───────┘
                      │
              ┌───────┴───────┐
              │  ch347_vcp    │
              │  驱动模块     │
              │  - mfd-ch347  │
              │  - i2c-ch347  │
              └───────┬───────┘
                      │
              ┌───────┴───────┐
              │   USB 总线    │
              └───────┬───────┘
                      │
              ┌───────┴───────┐
              │   CH347 芯片  │
              │  (USB-I2C)    │
              └───────┬───────┘
                      │
              ┌───────┴───────┐
              │   LSM6DSM     │
              │  I2C: 0x6B    │
              │  WHO_AM_I: 0x69│
              └───────────────┘
```

---

## 🔧 驱动安装

### 方式 1: 一键安装（推荐）

```bash
cd /data/carrot2-v9-acc
chmod +x system/sensord_ch347/setup_ch347.sh
sudo bash system/sensord_ch347/setup_ch347.sh
```

脚本会自动完成：
1. ✅ 编译并安装驱动到系统
2. ✅ 配置开机自动加载
3. ✅ 配置 I2C 设备权限（udev 规则）
4. ✅ 测试驱动和传感器

### 方式 2: 手动安装

```bash
# 1. 编译驱动
cd /data/soft/ch347_vcp
make

# 2. 安装驱动到系统
sudo cp *.ko /lib/modules/$(uname -r)/updates/
sudo depmod -a

# 3. 配置开机加载
sudo tee /etc/modules-load.d/ch347.conf << EOF
# CH347 USB-to-I2C adapter
mfd-ch347
i2c-ch347
EOF

# 4. 配置设备权限
sudo tee /etc/udev/rules.d/99-ch347-i2c.rules << EOF
SUBSYSTEM=="i2c-dev", KERNEL=="i2c-10", MODE="0666", GROUP="plugdev"
EOF

sudo udevadm control --reload-rules
sudo udevadm trigger

# 5. 加载驱动
sudo modprobe mfd-ch347
sudo modprobe i2c-ch347

# 6. 验证
ls -l /dev/i2c-10
lsmod | grep ch347
```

### 驱动模块说明

| 模块 | 功能 | 必需 |
|------|------|------|
| `mfd-ch347.ko` | 多功能设备基础驱动 | ✅ 是 |
| `i2c-ch347.ko` | I2C 主控制器驱动 | ✅ 是 |
| `gpio-ch347.ko` | GPIO 驱动 | ❌ 可选 |
| `spi-ch347.ko` | SPI 驱动 | ❌ 可选 |

---

## 📝 代码修改

### 修改的文件

#### 1. `sensord_ch347.py` - 主守护进程

**修改内容**:
- 更新文档说明使用 ch347_vcp 驱动
- 默认 I2C 总线号从 `1` 改为 `10`

```python
# 之前
parser.add_argument("--bus", type=int, default=1, ...)

# 现在
parser.add_argument("--bus", type=int, default=10, ...)
```

#### 2. `sensors/lsm6ds3_accel.py` - 加速度计

**修改内容**:
- I2C 地址从 `0x6A` 改为 `0x6B`

```python
@property
def device_address(self) -> int:
    return 0x6B  # LSM6DSM (SA0 pin pulled high)
```

#### 3. `sensors/lsm6ds3_gyro.py` - 陀螺仪

**修改内容**:
- I2C 地址从 `0x6A` 改为 `0x6B`

#### 4. `sensors/lsm6ds3_temp.py` - 温度传感器

**修改内容**:
- I2C 地址从 `0x6A` 改为 `0x6B`

### 为什么修改？

1. **驱动替换**: 原 libch347.so 段错误，ch34x_mphsi_master 无法编译
2. **I2C 总线**: ch347_vcp 驱动创建 `/dev/i2c-10`（非 `/dev/i2c-1`）
3. **传感器地址**: 实际硬件 SA0 引脚拉高，地址为 `0x6B`（非 `0x6A`）

---

## 📐 传感器坐标系

### 车辆坐标系（openpilot 标准）

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

**定义**:
- **X 轴**: 车辆横向，向右为正，向左为负
- **Y 轴**: 车辆纵向，向前为正，向后为负
- **Z 轴**: 垂直方向，向上为正，向下为负

### 推荐安装方式

```
         车辆前方 (Y+)
            ↑
       ┌────────┐
       │  USB口 │  ← USB 线
       │        │
       │ CH347  │
       │  模块  │
       │        │
       └────────┘

传感器轴对应：
  Y+ → 车辆前方 ✅
  X+ → 车辆右方 ✅
  Z+ → 车辆上方 ✅
```

### 静态读数（水平停放）

| 传感器轴 | 车辆方向 | 物理意义 | 静态值（水平） |
|---------|---------|---------|--------------|
| **X** | 横向（右+） | 左右加速度 | ≈ 0g |
| **Y** | 纵向（前+） | 前后加速度 | ≈ 0g |
| **Z** | 垂直（上+） | 重力加速度 | ≈ +1g |

**注意**:
- 加速度计测量的是**反作用力**，不是纯加速度
- 静止时 Z 轴读数为 +1g（重力的反作用力）

### 快速检查脚本

```bash
python3 system/sensord_ch347/check_orientation.py
```

**输出示例**:
```
平均加速度 (g):
  X = +0.015
  Y = -0.023
  Z = +0.998

✓ Z 轴垂直（正确安装）
  Z 轴朝上 ✅
✓ 传感器基本水平 ✅
```

---

## 🚀 使用方法

### 启动传感器服务

```bash
cd /data/carrot2-v9-acc
source .venv/bin/activate

# 使用默认配置（I2C 总线 10）
python3 -m openpilot.system.sensord_ch347.sensord_ch347

# 自定义总线号
python3 -m openpilot.system.sensord_ch347.sensord_ch347 --bus 10

# 调试模式
python3 -m openpilot.system.sensord_ch347.sensord_ch347 --verbose
```

### 命令行参数

```
--bus N        I2C 总线号（默认: 10）
--verbose      启用调试日志
--no-accel     禁用加速度计
--no-gyro      禁用陀螺仪
--enable-temp  启用温度传感器（默认禁用）
--help         显示帮助
```

### 测试传感器

```bash
# 使用测试脚本
cd /data/carrot2-v9-acc
source .venv/bin/activate
python3 system/sensord_ch347/test_lsm6ds3_ch347.py

# 或使用 i2c-tools
sudo i2cdetect -y 10
sudo i2cget -y 10 0x6b 0x0f
```

---

## ✅ 测试结果

### 传感器初始化

```
✓ 加速度计 I2C 总线 10, 地址 0x6B
✓ 加速度计初始化成功
✓ 加速度数据: X=-3.5297g, Y=-3.6650g, Z=8.4035g

✓ 陀螺仪 I2C 总线 10, 地址 0x6B
✓ 陀螺仪初始化成功
✓ 陀螺仪数据: X=-0.1755dps, Y=-0.0570dps, Z=-0.0279dps
```

### 数据采样

- **加速度计**: 100Hz, 2g 满量程
- **陀螺仪**: 100Hz, 250dps 满量程
- **传感器型号**: LSM6DSM (WHO_AM_I = 0x69)

---

## 🔍 故障排查

### 1. 驱动未加载

**症状**: `/dev/i2c-10` 不存在

**解决**:
```bash
# 检查驱动状态
lsmod | grep ch347

# 手动加载
sudo modprobe mfd-ch347
sudo modprobe i2c-ch347

# 查看内核日志
dmesg | grep ch347
```

### 2. I2C 权限问题

**症状**: `Permission denied: '/dev/i2c-10'`

**解决**:
```bash
# 临时解决
sudo chmod 666 /dev/i2c-10

# 永久解决（配置 udev 规则）
sudo tee /etc/udev/rules.d/99-ch347-i2c.rules << EOF
SUBSYSTEM=="i2c-dev", KERNEL=="i2c-10", MODE="0666", GROUP="plugdev"
EOF
sudo udevadm control --reload-rules
```

### 3. 传感器未响应

**症状**: `I2C read failed` 或 `Device not found`

**解决**:
```bash
# 扫描 I2C 总线
sudo i2cdetect -y 10

# 应该看到 0x6B 位置显示设备
#    0  1  2  3  4  5  6  7  8  9  a  b  c  d  e  f
# 60: -- -- -- -- -- -- -- -- -- -- -- 6b -- -- -- --

# 读取 WHO_AM_I
sudo i2cget -y 10 0x6b 0x0f
# 应该返回 0x69
```

### 4. 数据异常

**症状**: 加速度或陀螺仪数据明显错误

**解决**:
```bash
# 检查传感器安装方向
python3 system/sensord_ch347/check_orientation.py

# 验证车辆是否水平停放
# 静止时应该接近: X≈0g, Y≈0g, Z≈1g
```

### 5. 传感器地址错误

**症状**: 连接成功但无法读取数据

**说明**: LSM6DSM 的 I2C 地址由 SA0 引脚决定：
- SA0 = 0 (拉低): 0x6A
- SA0 = 1 (拉高): 0x6B ← 我们的配置

如果地址不对，需要修改代码中的 `device_address`。

---

## 📁 文件清单

### 核心代码
- `sensord_ch347.py` - 主守护进程
- `sensors/i2c_sensor.py` - I2C 传感器基类
- `sensors/lsm6ds3_accel.py` - 加速度计驱动
- `sensors/lsm6ds3_gyro.py` - 陀螺仪驱动
- `sensors/lsm6ds3_temp.py` - 温度传感器

### 驱动
- `/data/soft/ch347_vcp/` - ch347_vcp 驱动源码
  - `mfd-ch347.ko` - 多功能设备驱动
  - `i2c-ch347.ko` - I2C 主控制器驱动
  - `gpio-ch347.ko` - GPIO 驱动（可选）
  - `spi-ch347.ko` - SPI 驱动（可选）

### 工具
- `setup_ch347.sh` - 一键安装配置脚本
- `test_lsm6ds3_ch347.py` - 传感器测试脚本
- `check_orientation.py` - 坐标系检查脚本（见下方）

### 文档
- `README.md` - 本文档
- `CH347_SUCCESS_REPORT.md` - 驱动成功报告
- `TEST_REPORT.md` - 测试报告

---

## 🎯 下一步

### 1. 集成到 openpilot 启动流程

修改相关启动脚本，自动检测并启动 CH347 传感器：

```python
# 检查 CH347 是否存在
if os.path.exists('/dev/i2c-10'):
    # 启动 sensord_ch347
    subprocess.Popen([...])
```

### 2. 传感器标定

运行静态标定，记录零偏：

```python
# 静止状态下的平均值
accel_bias = (0.0, 0.0, 9.81)  # g
gyro_bias = (0.0, 0.0, 0.0)    # dps
```

### 3. 性能优化

- 确认 100Hz 采样率稳定
- 监控 I2C 总线延迟
- 检查 CPU 使用率

---

## ⚠️ 注意事项

1. **驱动顺序**: 必须按顺序加载 `mfd-ch347` → `i2c-ch347`
2. **I2C 权限**: 使用 udev 规则自动设置，无需手动 chmod
3. **数据预热**: 传感器启动后需要 0.5 秒预热，`is_data_valid()` 会返回 false
4. **安装方向**: 保持传感器水平，USB 口朝向一致

---

## 📊 Git 提交历史

```
3450290 fix(sensord_ch347): 更新 CH347 驱动配置和 LSM6DSM I2C 地址
- 更新文档说明使用 aystarik/ch347_vcp 开源驱动
- 修改默认 I2C 总线号从 1 改为 10
- 修正 LSM6DSM 传感器 I2C 地址从 0x6A 改为 0x6B
- 更新所有传感器驱动（加速度计、陀螺仪、温度）
```

---

## 📞 相关资源

- **驱动源码**: https://github.com/aystarik/ch347_vcp
- **LSM6DSM 数据手册**: https://www.st.com/en/mems-and-sensors/lsm6dsm.html
- **smbus2 Python 库**: https://pypi.org/project/smbus2/
- **openpilot 项目**: https://github.com/commaai/openpilot

---

**最后更新**: 2025-04-30
**状态**: ✅ 完成并测试通过
