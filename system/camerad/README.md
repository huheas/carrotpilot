# Camerad Thread 参数说明

## 概述

`camerad` 是一个高性能的摄像头采集服务，使用 C++ 实现，可以完全替代 `tools/webcam` 中使用 Python 的方式启动摄像头。

### 与 Python 版本对比

| 特性 | Python 版本 (tools/webcam) | C++ 版本 (camerad) |
|-----|--------------------------|-------------------|
| 性能 | 较慢 | **更优** |
| 语言 | Python | **C++** |
| MIPI 摄像头支持 | ❌ | ✅ |
| USB 摄像头支持 | ✅ | ✅ |
| 性能优化 | 基础 | **接近最优解** |

### 技术优势

1. **性能更优**: C++ 实现相比 Python 有显著的性能提升
2. **支持 MIPI 摄像头**: 除了 USB 摄像头，还支持 MIPI 摄像头
3. **性能最优解**:
   - **MIPI 摄像头**: 直接通过 V4L2 读取 NV12 格式，零拷贝，性能最优
   - **USB 摄像头**: 通过 libyuv 直接将 MJPEG 转换为 NV12。CPU指令集优化，无需GPU参与，GPU可更专注推理

### 使用前准备

**重要**: 使用 USB 摄像头前需要先自行编译 libyuv，相关脚本third_party/libyuv/build.sh已修改。

### 说明

当前版本支持 `ROAD_CAM`、`DRIVER_CAM` 和 `WIDE_ROAD_CAM`，支持混合使用 MIPI 和 USB 摄像头。

---

本文档说明 `camerad_thread.cc` 中使用的各个环境变量参数及其作用。

## 环境变量参数

### CAMERAD_DEBUG
- **类型**: 字符串
- **可选值**: `1`, `true`, `0`, `false`
- **默认值**: `false` (关闭)
- **作用**: 启用调试模式，输出详细的调试信息，包括：
  - 摄像头初始化信息
  - 设备路径选择过程
  - 分辨率和帧率设置
  - 实际帧率统计
  - 帧处理时间
- **示例**:
  ```bash
  export CAMERAD_DEBUG=1
  ```

### USE_WEBCAM
- **类型**: 字符串
- **可选值**: `1`, `true`, `0`, `false`
- **默认值**: `false` (使用MIPI摄像头)
- **作用**: 指定所有摄像头的默认模式（USB还是MIPI）
  - `true`: 默认使用USB摄像头
  - `false`: 默认使用MIPI摄像头
- **说明**: 可以被每个摄像头的独立配置覆盖
- **示例**:
  ```bash
  export USE_WEBCAM=1
  ```

### ROAD_CAM_USE_WEBCAM
- **类型**: 字符串
- **可选值**: `1`, `true`, `0`, `false`
- **默认值**: 使用全局 `USE_WEBCAM` 参数
- **作用**: 指定道路摄像头使用USB还是MIPI模式
  - `true`: 使用USB摄像头
  - `false`: 使用MIPI摄像头
- **优先级**: 高于全局 `USE_WEBCAM` 参数
- **示例**:
  ```bash
  export ROAD_CAM_USE_WEBCAM=1
  ```

### DRIVER_CAM_USE_WEBCAM
- **类型**: 字符串
- **可选值**: `1`, `true`, `0`, `false`
- **默认值**: 使用全局 `USE_WEBCAM` 参数
- **作用**: 指定驾驶员摄像头使用USB还是MIPI模式
  - `true`: 使用USB摄像头
  - `false`: 使用MIPI摄像头
- **优先级**: 高于全局 `USE_WEBCAM` 参数
- **示例**:
  ```bash
  export DRIVER_CAM_USE_WEBCAM=1
  ```

### WIDE_ROAD_CAM_USE_WEBCAM
- **类型**: 字符串
- **可选值**: `1`, `true`, `0`, `false`
- **默认值**: 使用全局 `USE_WEBCAM` 参数
- **作用**: 指定广角摄像头使用USB还是MIPI模式
  - `true`: 使用USB摄像头
  - `false`: 使用MIPI摄像头
- **优先级**: 高于全局 `USE_WEBCAM` 参数
- **示例**:
  ```bash
  export WIDE_ROAD_CAM_USE_WEBCAM=1
  ```

### ROAD_CAM_PATH
- **类型**: 字符串
- **默认值**: 无
- **优先级**: 最高
- **作用**: 直接指定摄像头设备的完整路径
- **说明**: 当设置此参数时，将忽略 `ROAD_CAM` 参数
- **示例**:
  ```bash
  export ROAD_CAM_PATH=/dev/video0
  ```

### ROAD_CAM
- **类型**: 字符串
- **默认值**: 无
- **优先级**: 中等 (低于 `ROAD_CAM_PATH`)
- **作用**: 指定摄像头设备编号，系统会自动拼接为 `/dev/video{ROAD_CAM}`
- **说明**: 当 `ROAD_CAM_PATH` 未设置时使用此参数
- **示例**:
  ```bash
  export ROAD_CAM=0  # 使用 /dev/video0
  ```

### ROAD_CAM_WIDTH
- **类型**: 字符串 (整数)
- **默认值**: `1920`
- **作用**: 设置摄像头采集的图像宽度
- **单位**: 像素
- **示例**:
  ```bash
  export ROAD_CAM_WIDTH=1920
  ```

### ROAD_CAM_HEIGHT
- **类型**: 字符串 (整数)
- **默认值**: `1080`
- **作用**: 设置摄像头采集的图像高度
- **单位**: 像素
- **示例**:
  ```bash
  export ROAD_CAM_HEIGHT=1080
  ```

### ROAD_CAM_FRAMERATE
- **类型**: 字符串 (整数)
- **默认值**: `20`
- **作用**: 设置摄像头采集的帧率
- **单位**: FPS (帧/秒)
- **说明**: 所有摄像头共用此帧率设置，系统会根据此值计算帧间隔，并控制帧采集频率
- **示例**:
  ```bash
  export ROAD_CAM_FRAMERATE=30
  ```

### DRIVER_CAM_PATH
- **类型**: 字符串
- **默认值**: 无
- **优先级**: 最高
- **作用**: 直接指定驾驶员摄像头设备的完整路径
- **说明**: 当设置此参数时，将忽略 `DRIVER_CAM` 参数
- **示例**:
  ```bash
  export DRIVER_CAM_PATH=/dev/video2
  ```

### DRIVER_CAM
- **类型**: 字符串
- **默认值**: 无
- **优先级**: 中等 (低于 `DRIVER_CAM_PATH`)
- **作用**: 指定驾驶员摄像头设备编号，系统会自动拼接为 `/dev/video{DRIVER_CAM}`
- **说明**: 当 `DRIVER_CAM_PATH` 未设置时使用此参数
- **示例**:
  ```bash
  export DRIVER_CAM=2  # 使用 /dev/video2
  ```

### DRIVER_CAM_WIDTH
- **类型**: 字符串 (整数)
- **默认值**: `1920`
- **作用**: 设置驾驶员摄像头采集的图像宽度
- **单位**: 像素
- **示例**:
  ```bash
  export DRIVER_CAM_WIDTH=1280
  ```

### DRIVER_CAM_HEIGHT
- **类型**: 字符串 (整数)
- **默认值**: `1080`
- **作用**: 设置驾驶员摄像头采集的图像高度
- **单位**: 像素
- **示例**:
  ```bash
  export DRIVER_CAM_HEIGHT=720
  ```

### WIDE_ROAD_CAM_PATH
- **类型**: 字符串
- **默认值**: 无
- **优先级**: 最高
- **作用**: 直接指定广角摄像头设备的完整路径
- **说明**: 当设置此参数时，将忽略 `WIDE_CAM` 参数
- **示例**:
  ```bash
  export WIDE_ROAD_CAM_PATH=/dev/video1
  ```

### WIDE_CAM
- **类型**: 字符串
- **默认值**: 无
- **优先级**: 中等 (低于 `WIDE_ROAD_CAM_PATH`)
- **作用**: 指定广角摄像头设备编号，系统会自动拼接为 `/dev/video{WIDE_CAM}`
- **说明**: 当 `WIDE_ROAD_CAM_PATH` 未设置时使用此参数
- **示例**:
  ```bash
  export WIDE_CAM=1  # 使用 /dev/video1
  ```

### WIDE_ROAD_CAM_WIDTH
- **类型**: 字符串 (整数)
- **默认值**: `1920`
- **作用**: 设置广角摄像头采集的图像宽度
- **单位**: 像素
- **示例**:
  ```bash
  export WIDE_ROAD_CAM_WIDTH=1920
  ```

### WIDE_ROAD_CAM_HEIGHT
- **类型**: 字符串 (整数)
- **默认值**: `1080`
- **作用**: 设置广角摄像头采集的图像高度
- **单位**: 像素
- **示例**:
  ```bash
  export WIDE_ROAD_CAM_HEIGHT=1080
  ```

## 默认设备路径

当未设置 `ROAD_CAM_PATH` 和 `ROAD_CAM` 时，系统根据 `USE_WEBCAM` 参数选择默认设备路径：

| USE_WEBCAM | 默认设备路径 | 摄像头类型 |
|-----------|-------------|-----------|
| `true` | `/dev/video45` | USB摄像头 |
| `false` | `/dev/video0` | MIPI摄像头 |

## 使用示例

### 示例1: 使用MIPI摄像头，默认配置
```bash
# 无需设置任何环境变量，使用默认配置
```

### 示例2: 使用USB摄像头，自定义分辨率
```bash
export USE_WEBCAM=1
export ROAD_CAM_WIDTH=1280
export ROAD_CAM_HEIGHT=720
export ROAD_CAM_FRAMERATE=30
```

### 示例3: 使用指定设备路径，开启调试模式
```bash
export ROAD_CAM_PATH=/dev/video2
export CAMERAD_DEBUG=1
export ROAD_CAM_FRAMERATE=25
```

### 示例4: 使用设备编号
```bash
export ROAD_CAM=1  # 使用 /dev/video1
export ROAD_CAM_WIDTH=1920
export ROAD_CAM_HEIGHT=1080
export ROAD_CAM_FRAMERATE=20
```

### 示例5: 混合使用MIPI和USB摄像头
```bash
# 道路摄像头使用 MIPI（默认）
# 驾驶员摄像头使用 USB
export DRIVER_CAM=2
export DRIVER_CAM_USE_WEBCAM=1
# 广角摄像头使用 MIPI
export WIDE_CAM=1
```

### 示例6: 保持现有配置（向后兼容）
```bash
# 所有摄像头使用 USB
export USE_WEBCAM=1
export ROAD_CAM=0
export DRIVER_CAM=2
export WIDE_CAM=1
```

### 示例7: 部分独立配置
```bash
# 全局默认使用 MIPI
export USE_WEBCAM=0
# 仅道路摄像头使用 USB
export ROAD_CAM_USE_WEBCAM=1
export ROAD_CAM=45
```

### 示例8: 启用驾驶员和广角摄像头
```bash
# 启用驾驶员摄像头
export DRIVER_CAM=2
export DRIVER_CAM_WIDTH=1280
export DRIVER_CAM_HEIGHT=720
# 启用广角摄像头
export WIDE_CAM=1
export WIDE_ROAD_CAM_WIDTH=1920
export WIDE_ROAD_CAM_HEIGHT=1080
```

## 调试输出

当 `CAMERAD_DEBUG=1` 时，系统会输出以下信息：

1. **初始化信息**:
   - Debug模式启用状态
   - 每个摄像头的USB/MIPI使用状态
   - 每个摄像头的设备路径选择过程
   - 每个摄像头的分辨率和帧率设置

2. **运行时信息**:
   - 每个摄像头的实际帧率统计 (每30帧输出一次)
   - 每个摄像头的帧处理时间
   - 每个摄像头的帧ID和采集时间戳

3. **性能监控**:
   - Expected FPS: 期望帧率
   - Actual FPS: 实际帧率
   - Processing time: 帧处理时间 (纳秒)

## 注意事项

1. **设备路径优先级**: `{CAM}_PATH` > `{CAM}` > 默认路径
2. **分辨率自适应**: 系统会使用摄像头的实际分辨率，可能与设置值不同
3. **帧率控制**: 所有摄像头共用 `ROAD_CAM_FRAMERATE` 参数，系统通过睡眠控制帧率，确保不超过设定值
4. **信号处理**: 支持 Ctrl+C 优雅退出
5. **缓冲区管理**: 使用循环缓冲区机制管理帧数据
6. **多摄像头支持**: 支持同时启用多个摄像头，每个摄像头独立运行在各自的线程中
7. **混合模式**: 支持在同一系统中混合使用MIPI和USB摄像头，每个摄像头可以独立配置