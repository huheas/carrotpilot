#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <dlfcn.h>
#include <stdint.h>

int main() {
    printf("CH347 最小测试程序\n");
    printf("==================\n\n");

    // 加载动态库
    void* lib = dlopen("/usr/lib/libch347.so", RTLD_LAZY);
    if (!lib) {
        printf("✗ 加载库失败: %s\n", dlerror());
        return 1;
    }
    printf("✓ 库加载成功\n\n");

    // 获取库信息
    void* (*CH347GetLibInfo)(void) = dlsym(lib, "CH347GetLibInfo");
    if (CH347GetLibInfo) {
        printf("库信息: %s\n\n", (char*)CH347GetLibInfo());
    }

    // 尝试打开设备
    unsigned int (*CH347OpenDevice)(unsigned int) = dlsym(lib, "CH347OpenDevice");
    if (!CH347OpenDevice) {
        printf("✗ 找不到 CH347OpenDevice\n");
        dlclose(lib);
        return 1;
    }

    printf("尝试打开设备 0...\n");
    fflush(stdout);

    unsigned int handle = CH347OpenDevice(0);
    printf("打开设备返回: 0x%08X\n", handle);

    if (handle == 0xFFFFFFFF || handle == 0) {
        printf("✗ 打开设备失败\n");
        dlclose(lib);
        return 1;
    }

    printf("✓ 设备打开成功，句柄: %u\n\n", handle);

    // 获取设备信息
    unsigned int (*CH347GetDeviceInfor)(unsigned int, char*, unsigned int) = dlsym(lib, "CH347GetDeviceInfor");
    if (CH347GetDeviceInfor) {
        char buf[256];
        memset(buf, 0, sizeof(buf));
        unsigned int ret = CH347GetDeviceInfor(0, buf, sizeof(buf));
        printf("设备信息 (ret=%u): %s\n\n", ret, buf);
    }

    // 尝试读取 LSM6DS3 WHO_AM_I
    unsigned int (*CH347StreamI2C)(unsigned int, unsigned int, unsigned int, unsigned char*, unsigned int, unsigned char*) = dlsym(lib, "CH347StreamI2C");
    if (CH347StreamI2C) {
        printf("读取 LSM6DS3 WHO_AM_I 寄存器...\n");

        unsigned char write_buf[1] = {0x0F};  // 寄存器地址
        unsigned char read_buf[1] = {0};

        unsigned int ret = CH347StreamI2C(
            handle,
            0x6A,      // LSM6DS3 I2C 地址
            1,         // 写入 1 字节
            write_buf,
            1,         // 读取 1 字节
            read_buf
        );

        if (ret == 1) {
            printf("✓ WHO_AM_I = 0x%02X\n", read_buf[0]);
            if (read_buf[0] == 0x6A) {
                printf("✓ LSM6DS3 传感器已识别\n");
            }
        } else {
            printf("✗ I2C 读取失败 (ret=%u)\n", ret);
        }
    }

    // 关闭设备
    unsigned int (*CH347CloseDevice)(unsigned int) = dlsym(lib, "CH347CloseDevice");
    if (CH347CloseDevice) {
        CH347CloseDevice(handle);
        printf("\n✓ 设备已关闭\n");
    }

    dlclose(lib);
    printf("\n测试完成\n");
    return 0;
}
