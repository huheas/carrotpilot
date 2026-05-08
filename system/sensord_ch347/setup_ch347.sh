#!/bin/bash
# CH347 驱动和 sensord_ch347 安装配置脚本
# 用于开机自动加载驱动和设置权限

set -e

echo "========================================="
echo "CH347 驱动和传感器配置脚本"
echo "========================================="
echo ""

# 1. 安装驱动到系统
echo "1. 安装 CH347 驱动到系统..."
cd /data/soft/ch347_vcp
sudo cp *.ko /lib/modules/$(uname -r)/updates/
sudo depmod -a
echo "   ✓ 驱动安装完成"
echo ""

# 2. 配置开机自动加载
echo "2. 配置开机自动加载驱动..."
sudo tee /etc/modules-load.d/ch347.conf > /dev/null << 'EOF'
# CH347 USB-to-I2C adapter (aystarik/ch347_vcp)
mfd-ch347
i2c-ch347
EOF
echo "   ✓ 开机自动加载配置完成"
echo ""

# 3. 配置 udev 规则（设置 I2C 设备权限）
echo "3. 配置 I2C 设备权限..."
sudo tee /etc/udev/rules.d/99-ch347-i2c.rules > /dev/null << 'EOF'
# CH347 I2C bus permissions
SUBSYSTEM=="i2c-dev", KERNEL=="i2c-10", MODE="0666", GROUP="plugdev"
EOF
echo "   ✓ I2C 权限配置完成"
echo ""

# 4. 重新加载 udev 规则
echo "4. 重新加载 udev 规则..."
sudo udevadm control --reload-rules
sudo udevadm trigger
echo "   ✓ udev 规则已重载"
echo ""

# 5. 测试驱动
echo "5. 测试驱动..."
# 卸载现有驱动
sudo rmmod spi-ch347 2>/dev/null || true
sudo rmmod gpio-ch347 2>/dev/null || true
sudo rmmod i2c-ch347 2>/dev/null || true
sudo rmmod mfd-ch347 2>/dev/null || true

# 重新加载
sudo modprobe mfd-ch347
sudo modprobe i2c-ch347

sleep 2

# 检查驱动
if lsmod | grep -q "mfd_ch347"; then
    echo "   ✓ 驱动加载成功"
    lsmod | grep ch347
else
    echo "   ✗ 驱动加载失败"
    exit 1
fi
echo ""

# 6. 检查 I2C 设备
echo "6. 检查 I2C 设备..."
if [ -e "/dev/i2c-10" ]; then
    echo "   ✓ /dev/i2c-10 已创建"
    ls -la /dev/i2c-10
else
    echo "   ✗ /dev/i2c-10 不存在"
    exit 1
fi
echo ""

# 7. 测试传感器
echo "7. 测试 LSM6DS3 传感器..."
cd /data/carrot2-v9-acc
source .venv/bin/activate

python3 -c "
from openpilot.system.sensord_ch347.sensors.lsm6ds3_accel import LSM6DS3_Accel
from openpilot.system.sensord_ch347.sensors.lsm6ds3_gyro import LSM6DS3_Gyro

accel = LSM6DS3_Accel(10)
accel.init()
evt = accel.get_event()
print(f'   ✓ 加速度计: X={evt.acceleration.v[0]:.3f}g, Y={evt.acceleration.v[1]:.3f}g, Z={evt.acceleration.v[2]:.3f}g')
accel.bus.close()

gyro = LSM6DS3_Gyro(10)
gyro.init()
evt = gyro.get_event()
g = evt.gyroUncalibrated if evt.which() == 'gyroUncalibrated' else evt.gyro
print(f'   ✓ 陀螺仪: X={g.v[0]:.3f}dps, Y={g.v[1]:.3f}dps, Z={g.v[2]:.3f}dps')
gyro.bus.close()
"

echo ""
echo "========================================="
echo "✅ 配置完成！"
echo "========================================="
echo ""
echo "下次重启后驱动将自动加载。"
echo ""
echo "手动启动 sensord_ch347:"
echo "  cd /data/carrot2-v9-acc"
echo "  source .venv/bin/activate"
echo "  python3 -m openpilot.system.sensord_ch347.sensord_ch347"
echo ""
echo "查看传感器数据:"
echo "  python3 system/sensord_ch347/test_lsm6ds3_ch347.py"
echo ""
