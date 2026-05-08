---
trigger: always_on
---
## 1. 项目基础操作

### 进入虚拟环境
在执行任何操作之前，必须先进入项目虚拟环境：

```bash
source .venv/bin/activate
```
### 项目编译方法
```bash
./tools/op.sh build
```

### 模拟器运行方法
```bash
./tools/sim/launch_openpilot.sh #启动模拟器
./tools/sim/run_bridge.py #启动车辆模拟
```
### 项目启动方法
```bash
./launch_pc.sh
```

## 2. 驾驶数据存储路径

### 数据目录结构
- 主目录：`.comma/`
- 数据格式：`{route_id}/{qlog.zst|rlog.zst}`
- 示例路径：`.comma/00000036--0e9fc9a6d0--12/`

### 数据文件说明
- `qlog.zst`：包含高质量日志数据，包括radarState、controlsState、carState等
- `rlog.zst`：包含完整日志数据，包括CAN总线消息

