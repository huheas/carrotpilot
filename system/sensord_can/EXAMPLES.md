# 通用CAN传感器服务使用示例

## 快速开始

### 1. 编译服务
```bash
cd f:\github\carrot2-v9
scons system/sensord_can
```

### 2. 查看支持的车型
```bash
cd system/sensord_can
./sensord_can --list-vehicles
```

输出：
```
Supported vehicle types:
  byd_han - BYD Han
  toyota_prius - Toyota Prius
  honda_civic - Honda Civic
```

### 3. 运行不同车型

#### BYD汉（默认）
```bash
./sensord_can --can-device can0 --verbose
```

#### Toyota Prius
```bash
./sensord_can --can-device can0 --vehicle-type toyota_prius --verbose
```

#### Honda Civic
```bash
./sensord_can --can-device can0 --vehicle-type honda_civic --verbose
```

### 4. 发送测试CAN消息

#### BYD汉测试
```bash
# YAW_RATE (CAN ID: 546 = 0x222)
cansend can0 222#1234567890ABCDEF

# AXAY (CAN ID: 547 = 0x223)
cansend can0 223#FEDCBA0987654321
```

#### Toyota Prius测试
```bash
# YAW_RATE (CAN ID: 37 = 0x25)
cansend can0 025#1234567890ABCDEF

# LONG_ACCEL (CAN ID: 552 = 0x228)
cansend can0 228#FEDCBA0987654321
```

#### Honda Civic测试
```bash
# YAW_RATE (CAN ID: 1086 = 0x43E)
cansend can0 43E#1234567890ABCDEF

# LONG_ACCEL (CAN ID: 1088 = 0x440)
cansend can0 440#FEDCBA0987654321
```

## 添加新车型示例

### 1. 编辑配置文件
编辑 `config/can_signals.json`，添加新车型：

```json
{
  "vehicle_configs": {
    "tesla_model3": {
      "name": "Tesla Model 3",
      "signals": {
        "yaw_rate": {
          "can_id": 904,
          "signal_name": "YAW_RATE",
          "start_bit": 39,
          "length": 12,
          "is_signed": true,
          "scale": 0.1,
          "offset": 0,
          "unit": "rad/s",
          "min": -50.0,
          "max": 50.0
        },
        "longitudinal_accel": {
          "can_id": 905,
          "signal_name": "ACCEL_X",
          "start_bit": 23,
          "length": 16,
          "is_signed": true,
          "scale": 0.01,
          "offset": -20,
          "unit": "m/s^2",
          "min": -18.0,
          "max": 18.0
        }
      }
    }
  }
}
```

### 2. 测试新车型
```bash
# 重新编译
scons system/sensord_can

# 验证配置
./sensord_can --list-vehicles

# 运行Tesla配置
./sensord_can --can-device can0 --vehicle-type tesla_model3 --verbose

# 发送测试消息
cansend can0 388#1234567890ABCDEF  # YAW_RATE (904 = 0x388)
cansend can0 389#FEDCBA0987654321  # ACCEL_X (905 = 0x389)
```

## 实际部署示例

### 自动启动配置
服务已集成到系统管理器，会自动启动：

```python
# 在 system/manager/process_config.py 中
NativeProcess("sensord_can", "system/sensord_can", ["./sensord_can"], only_onroad, enabled=PC)
```

### 运行时车型选择
可以通过环境变量或配置文件指定默认车型：

```bash
# 设置环境变量
export CAN_VEHICLE_TYPE=toyota_prius

# 或者修改默认配置
./sensord_can --can-device can0 --vehicle-type $CAN_VEHICLE_TYPE
```

### 集成验证
```bash
# 监听cereal消息
cereal-log gyroscope accelerometer

# Python验证脚本
python3 -c "
import cereal.messaging as messaging
sm = messaging.SubMaster(['gyroscope', 'accelerometer'])
while True:
    sm.update()
    if sm.updated['gyroscope']:
        gyro = sm['gyroscope'].gyroUncalibrated.v
        print(f'Gyro Z (yaw): {gyro[2]:.6f} rad/s')
    if sm.updated['accelerometer']:
        accel = sm['accelerometer'].acceleration.v
        print(f'Accel X (long): {accel[0]:.6f} m/s²')
"
```

## 性能监控

### CAN总线监控
```bash
# 实时CAN流量
candump can0 -c

# 过滤特定ID
candump can0,222:7FF,223:7FF

# 统计信息
canbusload can0@500000
```

### 服务监控
```bash
# 进程状态
ps aux | grep sensord_can

# 资源使用
top -p $(pgrep sensord_can)

# 日志监控
tail -f /tmp/sensord_can.log | grep "yaw_rate\|longitudinal_accel"
```

## 故障排除

### 常见问题

1. **车型不支持**
```bash
Error: Vehicle type 'unknown_car' is not supported.
解决：使用 --list-vehicles 查看支持的车型
```

2. **CAN接口错误**
```bash
Failed to get interface index for can0
解决：检查CAN接口状态，确保已启动
```

3. **权限问题**
```bash
Failed to create CAN socket: Permission denied
解决：使用sudo运行或添加用户到dialout组
```

### 调试技巧

1. **启用详细日志**
```bash
LOGPRINT=debug ./sensord_can --verbose
```

2. **验证配置加载**
```bash
# 检查JSON语法
python3 -m json.tool config/can_signals.json
```

3. **模拟CAN数据**
```bash
# 创建虚拟CAN接口
sudo modprobe vcan
sudo ip link add dev vcan0 type vcan
sudo ip link set up vcan0

# 使用虚拟接口测试
./sensord_can --can-device vcan0 --vehicle-type byd_han
```