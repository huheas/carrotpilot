# CH347 + LSM6DS3 传感器集成状态报告

## 日期
2026-04-30

## 当前状态

### ✅ 已完成
1. **CH347 驱动安装**
   - 内核模块: `ch34x_pis` 已加载
   - 设备文件: `/dev/ch34x_pis1` 已创建
   - 权限: 666 (可读写)
   - 库文件: `/usr/lib/libch347.so` (V1.6)

2. **代码逻辑验证**
   - ✅ 仿真测试全部通过 (6/6)
   - ✅ Cereal 消息结构正确
   - ✅ 100Hz 定时精度准确
   - ✅ 传感器数据处理逻辑正确

3. **测试工具**
   - ✅ 仿真测试脚本: `test_sensord_ch347_simulated.py`
   - ✅ 硬件测试脚本: `test_sensord_ch347.py` (待驱动修复)
   - ✅ CH347 诊断脚本: `diagnose_ch347.py`

### ❌ 当前问题

#### 主要问题：CH347 库段错误

**现象**:
- 调用 `CH347OpenDevice(0)` 时发生段错误 (SIGSEGV)
- 设备信息返回空字符串
- libch347.so V1.6 可能存在兼容性问题

**已尝试的方法**:
1. ❌ 标准 I2C 接口 (smbus2) - CH347 不支持
2. ❌ CH347OpenDevice - 段错误
3. ❌ CH347GetDeviceInfor - 返回空
4. ❌ 直接读写 /dev/ch34x_pis1 - 需要 ioctl 命令

**可能原因**:
1. CH347 库与当前系统不兼容 (Ubuntu 24.04, kernel 6.11.0-21-generic)
2. CH347 I2C 功能未在硬件上启用
3. LSM6DS3 传感器连接问题 (SDA/SCL 引脚)
4. 库版本 bug (V1.6 2025.04)

## 硬件连接确认

- ✅ CH347 USB 设备已识别 (ID 1a86:55db)
- ✅ LSM6DS3 传感器已连接到 CH347 的 I2C 引脚
- ❓ I2C 地址: 0x6A (待验证)
- ❓ 上拉电阻: 未知 (I2C 需要 4.7kΩ 上拉)

## 下一步解决方案

### 方案 1: 使用 C 语言测试程序 (推荐)

Python ctypes 可能有 ABI 兼容性问题。建议先用 C 程序验证 CH347 库是否正常工作。

```c
// test_ch347.c
#include <stdio.h>
#include <ch347.h>

int main() {
    // Get device info
    char info[256];
    int ret = CH347GetDeviceInfor(0, info, sizeof(info));
    printf("Device info: %s\n", info);

    // Open device
    HANDLE handle = CH347OpenDevice(0);
    if (handle < 0) {
        printf("Failed to open: %d\n", handle);
        return 1;
    }
    printf("Opened: %d\n", handle);

    // Configure I2C
    ret = CH347I2C_Set(handle, 1);  // 100kHz
    printf("I2C set: %d\n", ret);

    // Read chip ID
    unsigned char reg = 0x0F;
    unsigned char chip_id;
    ret = CH347StreamI2C(handle, 0x6A, 1, &reg, 1, &chip_id);
    printf("Chip ID: 0x%02X (ret=%d)\n", chip_id, ret);

    CH347CloseDevice(handle);
    return 0;
}
```

编译运行:
```bash
gcc -o test_ch347 test_ch347.c -lch347
./test_ch347
```

### 方案 2: 检查 CH347 硬件配置

CH347 可能需要配置引脚功能复用：

1. **确认 I2C 功能已启用**
   - CH347 有多个功能模式 (UART/SPI/I2C/GPIO)
   - 可能需要调用 `CH347_FUNC_SWITCH` 切换到 I2C 模式

2. **检查硬件连接**
   ```
   CH347 引脚    ->  LSM6DS3
   ---------------------------
   SDA (I2C数据)  ->  SDA (引脚 3)
   SCL (I2C时钟)  ->  SCL (引脚 4)
   VCC (3.3V)     ->  VDD (引脚 1)
   GND            ->  GND (引脚 6)
   ```

3. **添加上拉电阻**
   - I2C 总线需要 4.7kΩ 上拉电阻到 3.3V
   - SDA 和 SCL 各需要一个

### 方案 3: 使用厂商测试工具

WCH 可能提供了 CH347 的测试程序：

```bash
# 检查是否安装了测试工具
find /usr -name "*ch347*test*" -o -name "ch347_demo"

# 或者从 CSDN 下载示例代码
# 访问: https://blog.csdn.net/WCH_TechGroup/article/details/132173756
```

### 方案 4: 替代方案 - 使用其他 IMU

如果 CH347 I2C 无法工作，可以考虑：

1. **JY901B IMU** (项目中已有记录)
   - 通过串口 (UART) 通信
   - 不需要 CH347 的 I2C 功能
   - 标称频率 100-200Hz

2. **直接使用 I2C 总线** (如果主板有)
   - 绕过 CH347
   - 需要修改 `i2c_sensor.py` 使用正确的 I2C bus

## 代码准备状态

### 就绪的代码 (需要驱动修复后即可使用)

1. **CH347 I2C 包装器**: `ch347_i2c.py`
   - 完整的 libch347.so ctypes 绑定
   - 支持 I2C 读写
   - 需要修复段错误问题

2. **传感器驱动**: `sensors/lsm6ds3_*.py`
   - ✅ 加速度计: `lsm6ds3_accel.py`
   - ✅ 陀螺仪: `lsm6ds3_gyro.py`
   - ✅ 温度: `lsm6ds3_temp.py`
   - ✅ 基础类: `sensors/i2c_sensor.py`

3. **主服务**: `sensord_ch347.py`
   - ✅ 多线程轮询
   - ✅ Cereal 消息发布
   - ✅ 错误处理

## 测试命令 (待修复后使用)

```bash
# 1. 快速测试
cd /data/carrot2-v9-acc
python3 system/sensord_ch347/test_sensord_ch347.py --bus N --count 10

# 2. 详细测试
python3 system/sensord_ch347/test_sensord_ch347.py --bus N --verbose --freq-duration 5

# 3. 运行服务
python3 -m openpilot.system.sensord_ch347.sensord_ch347 --bus N

# 4. 查看数据
python3 -c "
import cereal.messaging as messaging
sm = messaging.SubMaster(['accelerometer', 'gyroscope'])
for _ in range(10):
    sm.update()
    if sm.updated['accelerometer']:
        a = sm['accelerometer'].acceleration
        print(f'Accel: [{a.v[0]:.2f}, {a.v[1]:.2f}, {a.v[2]:.2f}]')
"
```

## 建议行动

### 立即执行
1. ✅ 运行 C 语言测试程序验证 CH347 库
2. ✅ 检查 CH347 硬件连接和 I2C 配置
3. ✅ 确认是否需要调用 `CH347_FUNC_SWITCH` 启用 I2C

### 短期 (1-2天)
4. 修复 CH347 库调用问题
5. 成功读取 LSM6DS3 chip ID
6. 验证加速度计和陀螺仪数据

### 中期 (1周)
7. 集成到 openpilot 传感器服务
8. 测试 100Hz 数据流稳定性
9. 验证与 lateral control 的集成

## 联系信息

- CH347 驱动文档: https://blog.csdn.net/WCH_TechGroup/article/details/132173756
- WCH 官网: http://www.wch-ic.com/
- 库版本: V1.6 On 2025.04

---

**报告生成**: AI Assistant
**状态**: 等待 CH347 库问题诊断
**优先级**: 高 (阻塞传感器集成)
