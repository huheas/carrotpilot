# CH347 + LSM6DS3 传感器集成状态

## ✅ 成功！传感器已正常工作

**测试时间**: 2025-04-30
**状态**: 成功

---

## 解决方案

### 问题
1. ✗ libch347.so V1.6 调用 CH347OpenDevice 段错误
2. ✗ ch34x_mphsi_master 驱动无法在 kernel 6.11 编译
3. ✗ 没有可用的 I2C 总线访问 LSM6DS3

### 最终方案
使用 **aystarik/ch347_vcp** 开源驱动（https://github.com/aystarik/ch347_vcp）

**优势**：
- ✅ 完美支持 kernel 6.11.0-21-generic
- ✅ 编译无错误
- ✅ 创建标准 I2C 总线 (`/dev/i2c-10`)
- ✅ 可使用 `smbus2` 库直接访问传感器
- ✅ 支持 i2c-tools（i2cdetect, i2cget, i2cset）

---

## 驱动安装

### 1. 驱动源码
```bash
cd /data/soft
git clone https://github.com/aystarik/ch347_vcp.git
```

### 2. 编译驱动
```bash
cd /data/soft/ch347_vcp
make
```

**编译结果**: ✅ 成功（4个模块）
- `mfd-ch347.ko` - 多功能设备基础驱动
- `i2c-ch347.ko` - I2C 主控制器驱动
- `gpio-ch347.ko` - GPIO 驱动（可选）
- `spi-ch347.ko` - SPI 驱动（可选）

### 3. 加载驱动
```bash
sudo insmod mfd-ch347.ko
sudo insmod i2c-ch347.ko
sudo insmod gpio-ch347.ko  # 可选
sudo insmod spi-ch347.ko   # 可选
```

**加载结果**: ✅ 全部成功

### 4. 验证驱动
```bash
lsmod | grep ch347
```

**输出**:
```
spi_ch347              12288  0
gpio_ch347             12288  0
i2c_ch347              16384  0
mfd_ch347              24576  3 gpio_ch347,i2c_ch347,spi_ch347
```

---

## 传感器检测

### I2C 总线扫描
```bash
sudo i2cdetect -y 10
```

**结果**: 在地址 `0x6B` 检测到设备

### WHO_AM_I 读取
```bash
sudo i2cget -y 10 0x6b 0x0f
```

**结果**: `0x69` = **LSM6DSM**（与 LSM6DS3 兼容）

---

## 传感器测试

### 测试脚本
```bash
cd /data/carrot2-v9-acc
source .venv/bin/activate
sudo chmod 666 /dev/i2c-10
python3 system/sensord_ch347/test_lsm6ds3_ch347.py
```

### 测试结果
```
============================================================
CH347 + LSM6DS3 传感器测试
============================================================

✓ I2C 总线 10 打开成功
✓ WHO_AM_I = 0x69
  传感器型号: LSM6DSM
✓ 传感器初始化完成
  加速度计: 100Hz, 2g
  陀螺仪: 100Hz, 250dps

开始读取传感器数据...

加速度 (g): X=+0.3740  Y=+0.612  Z=+0.8634  | 陀螺仪 (dps): X=+3.579  Y=-9.756  Z=-1.846
```

**✅ 传感器数据读取成功！**

---

## 硬件连接

### CH347 (QFN28_4X4)
- **I2C SCL**: PIN 11
- **I2C SDA**: PIN 12
- **USB**: 连接到主机 USB 端口

### LSM6DSM
- **I2C 地址**: 0x6B（SA0 引脚拉高）
- **WHO_AM_I**: 0x69
- **VDD**: 3.3V
- **GND**: GND

---

## 下一步工作

### 1. 设置开机自动加载
```bash
# 创建 /etc/modules-load.d/ch347.conf
sudo tee /etc/modules-load.d/ch347.conf << EOF
mfd-ch347
i2c-ch347
EOF

# 安装驱动到系统
cd /data/soft/ch347_vcp
sudo make modules_install
sudo depmod -a
```

### 2. 修改 sensord_ch347 代码
将 sensord_ch347 从使用 libch347.so 改为使用 smbus2：

```python
# 旧的代码（使用 libch347.so）
from ch347_i2c import CH347I2C
i2c = CH347I2C()

# 新的代码（使用 smbus2）
import smbus2
bus = smbus2.SMBus(10)  # I2C 总线 10
data = bus.read_i2c_block_data(0x6B, 0x28, 6)
```

### 3. 设置 udev 规则
```bash
# 创建 /etc/udev/rules.d/99-ch347-i2c.rules
sudo tee /etc/udev/rules.d/99-ch347-i2c.rules << EOF
SUBSYSTEM=="i2c-dev", KERNEL=="i2c-10", MODE="0666"
EOF

sudo udevadm control --reload-rules
```

### 4. 集成到 openpilot
修改 `sensord_ch347/sensord_ch347.py`：
- 移除 libch347.so 相关代码
- 使用 smbus2 读取传感器
- 保持 cereal 消息发布逻辑不变

---

## 驱动仓库信息

**仓库**: https://github.com/aystarik/ch347_vcp
**许可证**: GPL
**支持内核**: 5.x, 6.x
**模块**:
- mfd-ch347 (基础)
- i2c-ch347 (I2C 主控制器)
- gpio-ch347 (GPIO，可选)
- spi-ch347 (SPI，可选)

**文档**: README.md 包含详细的使用说明

---

## 相关文件

- **驱动源码**: `/data/soft/ch347_vcp/`
- **测试脚本**: `/data/carrot2-v9-acc/system/sensord_ch347/test_lsm6ds3_ch347.py`
- **原 sensord 代码**: `/data/carrot2-v9-acc/system/sensord_ch347/sensord_ch347.py`
- **传感器驱动**: `/data/carrot2-v9-acc/system/sensord_ch347/sensors/`

---

## 总结

✅ **CH347 I2C 适配器工作正常**
✅ **LSM6DSM 传感器识别成功**
✅ **数据读取成功（100Hz）**
✅ **可以开始集成到 openpilot 系统**

下一步需要修改 sensord_ch347 代码，使用 smbus2 替代 libch347.so。
