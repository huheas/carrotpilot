#!/usr/bin/env python3
"""
测试 CH347 + LSM6DS3 传感器
使用 ch347_vcp 驱动创建的 I2C 总线
"""
import sys
import time
import smbus2

# I2C 配置
I2C_BUS = 10  # CH347 创建的 I2C 总线
LSM6DS3_ADDR = 0x6B  # 传感器 I2C 地址

# LSM6DS3 寄存器地址
WHO_AM_I = 0x0F
CTRL1_XL = 0x10  # 加速度计控制
CTRL2_G = 0x11   # 陀螺仪控制
STATUS_REG = 0x1E
OUTX_L_XL = 0x28 # 加速度计数据
OUTX_L_G = 0x22  # 陀螺仪数据

def read_who_am_i(bus):
    """读取 WHO_AM_I 寄存器"""
    chip_id = bus.read_byte_data(LSM6DS3_ADDR, WHO_AM_I)
    return chip_id

def init_sensor(bus):
    """初始化传感器"""
    # 启用加速度计: ODR=100Hz, 2g 满量程
    bus.write_byte_data(LSM6DS3_ADDR, CTRL1_XL, 0x60)

    # 启用陀螺仪: ODR=100Hz, 250dps 满量程
    bus.write_byte_data(LSM6DS3_ADDR, CTRL2_G, 0x60)

    print("✓ 传感器初始化完成")
    print("  加速度计: 100Hz, 2g")
    print("  陀螺仪: 100Hz, 250dps")

def read_accelerometer(bus):
    """读取加速度计数据"""
    # 读取 6 个字节 (X, Y, Z 各 2 字节)
    data = bus.read_i2c_block_data(LSM6DS3_ADDR, OUTX_L_XL, 6)

    # 转换为有符号 16 位整数
    def to_int16(low, high):
        val = (high << 8) | low
        if val >= 0x8000:
            val -= 0x10000
        return val

    x = to_int16(data[0], data[1])
    y = to_int16(data[2], data[3])
    z = to_int16(data[4], data[5])

    # 转换为 g (2g 满量程, 灵敏度 = 0.061 mg/LSB)
    x_g = x * 0.000061
    y_g = y * 0.000061
    z_g = z * 0.000061

    return x_g, y_g, z_g

def read_gyroscope(bus):
    """读取陀螺仪数据"""
    # 读取 6 个字节
    data = bus.read_i2c_block_data(LSM6DS3_ADDR, OUTX_L_G, 6)

    # 转换为有符号 16 位整数
    def to_int16(low, high):
        val = (high << 8) | low
        if val >= 0x8000:
            val -= 0x10000
        return val

    x = to_int16(data[0], data[1])
    y = to_int16(data[2], data[3])
    z = to_int16(data[4], data[5])

    # 转换为 dps (250dps 满量程, 灵敏度 = 8.75 mdps/LSB)
    x_dps = x * 0.00875
    y_dps = y * 0.00875
    z_dps = z * 0.00875

    return x_dps, y_dps, z_dps

def main():
    print("=" * 60)
    print("CH347 + LSM6DS3 传感器测试")
    print("=" * 60)
    print()

    # 打开 I2C 总线
    try:
        bus = smbus2.SMBus(I2C_BUS)
        print(f"✓ I2C 总线 {I2C_BUS} 打开成功")
    except Exception as e:
        print(f"✗ 无法打开 I2C 总线 {I2C_BUS}: {e}")
        return 1

    # 读取 WHO_AM_I
    try:
        chip_id = read_who_am_i(bus)
        print(f"✓ WHO_AM_I = 0x{chip_id:02X}")

        if chip_id == 0x69:
            print("  传感器型号: LSM6DSM")
        elif chip_id == 0x6A:
            print("  传感器型号: LSM6DS3")
        else:
            print(f"  ⚠ 未知传感器 (期望 0x69 或 0x6A)")
            return 1
    except Exception as e:
        print(f"✗ 无法读取 WHO_AM_I: {e}")
        bus.close()
        return 1

    # 初始化传感器
    try:
        init_sensor(bus)
    except Exception as e:
        print(f"✗ 初始化失败: {e}")
        bus.close()
        return 1

    # 持续读取数据
    print()
    print("开始读取传感器数据 (按 Ctrl+C 停止)...")
    print("-" * 60)

    try:
        while True:
            accel = read_accelerometer(bus)
            gyro = read_gyroscope(bus)

            print(f"\r加速度 (g): X={accel[0]:+.4f}  Y={accel[1]:+.4f}  Z={accel[2]:+.4f}  | "
                  f"陀螺仪 (dps): X={gyro[0]:+.3f}  Y={gyro[1]:+.3f}  Z={gyro[2]:+.3f}",
                  end='', flush=True)

            time.sleep(0.01)  # 100Hz

    except KeyboardInterrupt:
        print("\n\n停止读取")
    except Exception as e:
        print(f"\n✗ 读取错误: {e}")
    finally:
        bus.close()
        print("✓ I2C 总线已关闭")

    return 0

if __name__ == "__main__":
    sys.exit(main())
