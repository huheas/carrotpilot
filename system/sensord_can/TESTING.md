# BYD CAN传感器服务测试指南

## 快速测试

### 1. 编译服务
```bash
cd f:\github\carrot2-v9
scons system/sensord_can
```

### 2. 准备CAN接口
```bash
# 加载CAN驱动 (如果使用虚拟CAN用于测试)
sudo modprobe vcan
sudo ip link add dev can0 type vcan
sudo ip link set up can0

# 或者使用真实CAN接口
sudo ip link set can0 up type can bitrate 500000
```

### 3. 运行服务
```bash
cd system/sensord_can
./sensord_can --can-device can0 --verbose
```

### 4. 发送测试CAN消息
```bash
# 发送YAW_RATE测试消息 (CAN ID: 546)
cansend can0 222#1234567890ABCDEF

# 发送AXAY测试消息 (CAN ID: 547)
cansend can0 223#FEDCBA0987654321
```

### 5. 验证消息发布
```bash
# 监听cereal消息
cereal-log gyroscope accelerometer

# 或者使用Python脚本验证
python3 -c "
import cereal.messaging as messaging
sm = messaging.SubMaster(['gyroscope', 'accelerometer'])
while True:
    sm.update()
    if sm.updated['gyroscope']:
        print('Gyro:', sm['gyroscope'])
    if sm.updated['accelerometer']:
        print('Accel:', sm['accelerometer'])
"
```

## 服务配置

### 命令行选项
- `--can-device DEV`: CAN设备名称 (默认: can0)
- `--no-yaw`: 禁用偏航率传感器
- `--no-accel`: 禁用加速度传感器
- `--verbose`: 详细输出
- `--help`: 显示帮助

### DBC信号映射

#### YAW_RATE (CAN ID: 546 = 0x222)
- **YawRate**: 0|12@1+ → (raw * 0.002133) - 2.094 rad/s
- **YawRateOffset**: 12|12@1+ → (raw * 0.002133) - 0.13 rad/s
- **Counter**: 48|4@1+ → raw

#### AXAY (CAN ID: 547 = 0x223)
- **Ax**: 0|12@1+ → (raw * 0.027167) - 21.593 m/s²
- **AxOffset**: 12|12@1+ → (raw * 0.027127) - 21.593 m/s²
- **Counter**: 48|4@1+ → raw

## 故障排除

### CAN接口问题
```bash
# 检查CAN接口状态
ip link show can0

# 查看CAN消息
candump can0

# 检查CAN错误
cat /sys/class/net/can0/statistics/rx_errors
```

### 权限问题
```bash
# 添加用户到dialout组 (访问CAN设备)
sudo usermod -a -G dialout $USER

# 或者使用sudo运行
sudo ./sensord_can
```

### 调试日志
```bash
# 启用详细日志
LOGPRINT=debug ./sensord_can --verbose

# 查看系统日志
journalctl -f | grep sensord_can
```