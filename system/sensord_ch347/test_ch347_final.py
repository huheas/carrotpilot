#!/usr/bin/env python3
"""
CH347 传感器完整测试 - 修复版本
测试 CH347 I2C 接口和 LSM6DS3 传感器读取
"""
import sys
import os
import ctypes
import time

# 确保在项目根目录运行
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_step(step_name, func):
    """测试步骤并打印结果"""
    print(f"\n{'='*60}")
    print(f"测试: {step_name}")
    print(f"{'='*60}")
    try:
        result = func()
        print(f"✓ 成功")
        return result
    except Exception as e:
        print(f"✗ 失败: {e}")
        import traceback
        traceback.print_exc()
        return None

def main():
    print("CH347 传感器测试")
    print("=" * 60)

    # 检查库文件
    lib_path = '/usr/lib/libch347.so'
    if not os.path.exists(lib_path):
        print(f"✗ 库文件不存在: {lib_path}")
        return 1

    print(f"✓ 库文件存在: {lib_path}")

    # 加载库
    try:
        lib = ctypes.cdll.LoadLibrary(lib_path)
        print("✓ 库加载成功")
    except Exception as e:
        print(f"✗ 库加载失败: {e}")
        return 1

    # 获取库信息
    print(f"\n{'='*60}")
    print("获取库信息")
    print(f"{'='*60}")
    try:
        lib.CH347GetLibInfo.restype = ctypes.c_void_p
        info_ptr = lib.CH347GetLibInfo()
        if info_ptr:
            info = ctypes.cast(info_ptr, ctypes.c_char_p).value.decode('gbk', errors='ignore')
            print(f"库信息: {info}")
    except Exception as e:
        print(f"获取库信息失败: {e}")

    # 尝试打开设备
    print(f"\n{'='*60}")
    print("打开设备")
    print(f"{'='*60}")
    try:
        # 先设置函数签名
        lib.CH347OpenDevice.argtypes = [ctypes.c_uint32]
        lib.CH347OpenDevice.restype = ctypes.c_uint32

        # 尝试打开设备 0
        handle = lib.CH347OpenDevice(0)
        if handle == 0xFFFFFFFF or handle == 0:
            print("✗ 打开设备失败")
            print("  可能原因:")
            print("  1. 设备被其他进程占用")
            print("  2. 权限不足")
            print("  3. 设备未正确初始化")
            return 1
        print(f"✓ 设备打开成功，句柄: {hex(handle)}")
    except Exception as e:
        print(f"✗ 打开设备异常: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # 获取设备信息
    print(f"\n{'='*60}")
    print("获取设备信息")
    print(f"{'='*60}")
    try:
        lib.CH347GetDeviceInfor.argtypes = [
            ctypes.c_uint32,
            ctypes.c_char_p,
            ctypes.c_uint32
        ]
        lib.CH347GetDeviceInfor.restype = ctypes.c_uint32

        buf = ctypes.create_string_buffer(256)
        ret = lib.CH347GetDeviceInfor(0, buf, 256)
        if ret == 1:
            info = buf.value.decode('utf-8', errors='ignore')
            print(f"设备信息: {info}")
        else:
            print("✗ 获取设备信息失败")
    except Exception as e:
        print(f"获取设备信息失败: {e}")
        import traceback
        traceback.print_exc()

    # 初始化 I2C
    print(f"\n{'='*60}")
    print("初始化 I2C")
    print(f"{'='*60}")
    try:
        lib.CH347StreamI2C.argtypes = [
            ctypes.c_uint32,  # iIndex
            ctypes.c_uint32,  # devAddr
            ctypes.c_uint32,  # writeLen
            ctypes.POINTER(ctypes.c_uint8),  # writeBuf
            ctypes.c_uint32,  # readLen
            ctypes.POINTER(ctypes.c_uint8),  # readBuf
        ]
        lib.CH347StreamI2C.restype = ctypes.c_uint32

        # 读取 LSM6DS3 WHO_AM_I 寄存器
        # LSM6DS3 地址: 0x6A
        # WHO_AM_I 寄存器: 0x0F
        # 期望值: 0x6A

        write_buf = (ctypes.c_uint8 * 1)(0x0F)  # 寄存器地址
        read_buf = (ctypes.c_uint8 * 1)(0)       # 读取缓冲区

        print("读取 LSM6DS3 WHO_AM_I 寄存器 (0x0F)...")
        print(f"设备地址: 0x6A")

        ret = lib.CH347StreamI2C(
            handle,
            0x6A,      # LSM6DS3 I2C 地址
            1,         # 写入 1 字节（寄存器地址）
            write_buf,
            1,         # 读取 1 字节
            read_buf
        )

        if ret == 1:
            who_am_i = read_buf[0]
            print(f"✓ WHO_AM_I 读取成功: 0x{who_am_i:02X}")
            if who_am_i == 0x6A:
                print("✓ LSM6DS3 传感器已识别")
            else:
                print(f"⚠ 期望值: 0x6A，实际值: 0x{who_am_i:02X}")
        else:
            print(f"✗ I2C 读取失败，返回值: {ret}")
    except Exception as e:
        print(f"✗ I2C 读取失败: {e}")
        import traceback
        traceback.print_exc()

    # 关闭设备
    print(f"\n{'='*60}")
    print("关闭设备")
    print(f"{'='*60}")
    try:
        lib.CH347CloseDevice.argtypes = [ctypes.c_uint32]
        lib.CH347CloseDevice.restype = ctypes.c_uint32

        ret = lib.CH347CloseDevice(handle)
        if ret == 1:
            print("✓ 设备关闭成功")
        else:
            print("✗ 设备关闭失败")
    except Exception as e:
        print(f"✗ 关闭设备失败: {e}")

    print(f"\n{'='*60}")
    print("测试完成")
    print(f"{'='*60}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
