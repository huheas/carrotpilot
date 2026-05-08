# 通用CAN传感器服务 (sensord_can)

## 概述

`sensord_can` 是专为PC环境设计的通用CAN传感器服务，完全参照 `system/sensord` 的实现方式。该服务使用纯C++实现，通过CAN总线接收多种车型的传感器信号，将其转换为标准传感器数据并通过cereal消息系统发布。

## 项目结构

```
system/sensord_can/
├── config/              # 配置文件
│   └── can_signals.json # 多车型CAN信号配置
├── sensors/             # 传感器实现
│   ├── can_sensor.h     # CAN传感器基类接口
│   ├── can_sensor.cc    # CAN传感器基类实现
│   ├── universal_can_sensor.h  # 通用CAN传感器类声明
│   └── universal_can_sensor.cc # 通用CAN传感器类实现
├── sensord_can.cc       # 主服务程序
├── SConscript           # 构建配置
└── README.md            # 说明文档
```

## 技术特性

- **纯C++实现**: 避免Python和C混用的复杂性
- **多车型支持**: 通过JSON配置文件支持不同车型
- **CAN总线通信**: 接收各种车型的CAN信号
- **模块化设计**: 基于继承的传感器类架构
- **cereal集成**: 与openpilot消息系统无缝集成
- **SCons构建**: 集成到项目构建系统
- **简单管理**: 完全按照sensord的方式管理，无额外配置文件
- **配置驱动**: 通过JSON配置支持新车型，无需代码修改

## 支持的车型和CAN信号

### BYD 汉 (byd_han)
- **YAW_RATE (CAN ID: 546)**: 偏航角速度 (rad/s)
- **AXAY (CAN ID: 547)**: 纵向加速度 (m/s²)

### Toyota Prius (toyota_prius)
- **YAW_RATE (CAN ID: 37)**: 偏航角速度 (rad/s)
- **LONG_ACCEL (CAN ID: 552)**: 纵向加速度 (m/s²)

### Honda Civic (honda_civic)
- **YAW_RATE (CAN ID: 1086)**: 偏航角速度 (rad/s)
- **LONG_ACCEL (CAN ID: 1088)**: 纵向加速度 (m/s²)

### 添加新车型
编辑 `config/can_signals.json` 文件，按照现有格式添加新车型的CAN信号配置。

## 服务管理

服务完全按照原来sensord的方式在 `system/manager/process_config.py` 中管理：

```python
# 通用CAN传感器服务（仅PC环境）
NativeProcess("sensord_can", "system/sensord_can", ["./sensord_can"], only_onroad, enabled=PC)
```

## 编译和运行

### 编译

```bash
# 在项目根目录下编译
scons -j8
```

### 运行

服务会自动通过manager启动，也可以手动启动：

```bash
cd system/sensord_can

# 使用默认车型（BYD汉）
./sensord_can --can-device can0

# 指定车型
./sensord_can --can-device can0 --vehicle-type toyota_prius

# 查看支持的车型
./sensord_can --list-vehicles

# 详细输出
./sensord_can --can-device can0 --vehicle-type honda_civic --verbose
```

### 命令行选项

- `--can-device DEV`: CAN设备名称 (默认: can0)
- `--vehicle-type TYPE`: 车型类型 (默认: byd_han)
- `--no-yaw`: 禁用偏航率传感器
- `--no-accel`: 禁用加速度传感器
- `--list-vehicles`: 列出支持的车型
- `--verbose`: 详细输出
- `--help`: 显示帮助

## 消息发布

服务发布以下cereal消息：

- `sensorEvents`: 包含陀螺仪和加速度计数据
- `gyroscope`: 偏航率数据 (来自各车型YAW_RATE信号)
- `accelerometer`: 纵向加速度数据 (来自各车型加速度信号)

## 配置文件格式

`config/can_signals.json` 文件结构：

```json
{
  "vehicle_configs": {
    "your_vehicle": {
      "name": "Your Vehicle Name",
      "signals": {
        "yaw_rate": {
          "can_id": 123,
          "signal_name": "YAW_RATE",
          "start_bit": 0,
          "length": 12,
          "is_signed": true,
          "scale": 0.1,
          "offset": 0,
          "unit": "rad/s",
          "min": -40.0,
          "max": 40.0
        },
        "longitudinal_accel": {
          "can_id": 456,
          "signal_name": "LONG_ACCEL",
          "start_bit": 16,
          "length": 16,
          "is_signed": true,
          "scale": 0.01,
          "offset": -20,
          "unit": "m/s^2",
          "min": -15.0,
          "max": 15.0
        }
      }
    }
  }
}
```

## 开发说明

### 添加新车型

1. 在 `config/can_signals.json` 中添加车型配置
2. 重新编译服务
3. 使用 `--vehicle-type your_vehicle` 参数运行

### 调试

```bash
# 查看日志
tail -f /tmp/sensord_can.log

# 查看CAN消息
candump can0

# 查看cereal消息
cereal-log sensorEvents

# 验证车型配置
./sensord_can --list-vehicles
```

## 架构优势

相比原来的BYD专用实现，通用架构提供：

1. **可扩展性**: 新车型只需配置文件，无需代码修改
2. **维护性**: 统一的代码库，减少重复代码
3. **标准化**: 统一的信号处理流程
4. **灵活性**: 支持不同的CAN信号格式和参数
5. **复用性**: 其他项目可以轻松复用这个通用框架