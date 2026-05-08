# AGENTS.md - CarrotPilot Development Guidelines

## 项目概述
CarrotPilot 是基于 comma.ai openpilot 的自动驾驶系统，主要为韩国现代/起亚车辆提供 ACC 增强功能。项目包含 Python、C++ 和 C 代码。

## 构建和测试命令

### 基础环境设置
```bash
# 激活虚拟环境
source .venv/bin/activate

# 安装依赖
uv sync

# 构建项目
scons -j$(nproc)
```

### 测试命令
```bash
# 运行所有测试
pytest

# 运行特定模块的测试
pytest selfdrive/car/tests/test_car_interfaces.py
pytest common/transformations/tests/test_orientation.py

# 运行单个测试文件
pytest selfdrive/controls/tests/test_controls.py -v

# 运行特定测试函数
pytest selfdrive/controls/tests/test_controls.py::test_controls_init -v

# 跳过设备特定测试
pytest -m "not tici"

# 仅运行快速测试
pytest -m "not slow"

# 带覆盖率报告
pytest --cov --cov-report=html

# 并行测试
pytest -n auto
```

### CI/CD 测试
```bash
# 运行 selfdrive 测试套件
./selfdrive/test/docker_build.sh base
./selfdrive/test/test_on_device.py

# 运行硬件在环测试
bash selfdrive/test/jenkins_loop_test.sh
```

### 代码质量检查
```bash
# 代码格式化和检查
ruff check . --fix
ruff format .

# 类型检查
mypy .

# 拼写检查
codespell

# 静态分析
cppcheck --enable=all --suppress=missingIncludeSystem .
```

## 代码风格指南

### Python 代码风格

#### 导入顺序
1. 标准库
2. 第三方库
3. 本地模块
```python
import os
import sys
from typing import List, Optional

import numpy as np

from openpilot.common.prefix import OpenpilotPrefix
from openpilot.selfdrive.car.interfaces import CarInterface
```

#### 格式化规则
- 缩进: 2个空格
- 行长度: 160字符
- 引号风格: 保持现有风格
- 使用类型注解
```python
def calculate_steer_angle(
  current_angle: float,
  target_angle: float,
  max_rate: float = 5.0
) -> float:
  """计算转向角度变化"""
  angle_diff = target_angle - current_angle
  return np.clip(angle_diff, -max_rate, max_rate)
```

#### 命名约定
- 变量/函数: `snake_case`
- 类: `PascalCase`
- 常量: `UPPER_SNAKE_CASE`
- 私有成员: `_leading_underscore`

#### 错误处理
```python
try:
  result = process_sensor_data(data)
except SensorError as e:
  cloudlog.error(f"Sensor error: {e}")
  raise
except Exception:
  cloudlog.exception("Unexpected error in sensor processing")
  raise
```

### C++ 代码风格

#### 基础规则
- 遵循现有的 C++ 代码风格
- 使用 Google C++ 风格指南
- 指针和引用: `Type* var` 和 `Type& var`

#### 错误处理
```cpp
try {
  auto result = process_data(data);
  return result;
} catch (const std::exception& e) {
  LOGE("Processing failed: %s", e.what());
  return {};
}
```

### 类型注解
所有函数都应包含完整的类型注解：
```python
def process_can_message(
  msg: capnp.lib.capnp._DynamicStructReader,
  cp: car.CarParams
) -> tuple[CarControl, list[capnp.lib.capnp._DynamicStructBuilder]]:
  """处理CAN消息并返回控制指令"""
  # 实现逻辑
  return car_control, []
```

## 开发工作流

### 1. 分支策略
- `master`: 主分支，稳定版本
- `release3`: openpilot 发布分支
- `nightly`: 开发分支，包含最新功能
- 功能分支: `feature/xxx`, `fix/xxx`

### 2. 提交规范
```
type(scope): description

详细说明（可选）

- 要点1
- 要点2

Closes #123
```

类型包括:
- `feat`: 新功能
- `fix`: Bug修复
- `docs`: 文档更新
- `style`: 代码格式化
- `refactor`: 重构
- `test`: 测试相关
- `chore`: 构建/工具更新

### 3. 测试要求
- 新功能必须包含测试
- 修复 Bug 时添加回归测试
- 所有测试必须在 CI 中通过

### 4. 代码提交规范

#### 修改总结和 change.log 要求
每次代码修改后，必须：

1. **总结修改内容**：
   ```python
   # 修改内容总结格式
   [YYYY-MM-DD] - [修改类型] - [简要描述]
   - 改动了哪些文件
   - 解决了什么问题
   - 潜在影响或风险
   - 测试验证方法
   ```

2. **更新 change.log 文件**：
   ```bash
   # 将修改总结添加到 change.log
   echo "[$(date +%Y-%m-%d)] - [优化] - 改进横向控制稳定性分析" >> change.log
   echo "- 修改了 analyze_all_segments.py: 添加摆动检测算法" >> change.log
   echo "- 解决了方向盘高频摆动问题识别" >> change.log
   echo "- 需要验证分析结果的准确性" >> change.log
   echo "" >> change.log
   ```

3. **提交到本地仓库**：
   ```bash
   # 添加修改的文件
   git add .

   # 查看待提交的更改
   git status
   git diff --cached

   # 提交更改（遵循提交规范）
   git commit -m "feat(analysis): 添加方向盘摆动检测算法"

   # 不要推送到远程仓库
   # 注意：等待用户明确要求再执行 git push
   ```

#### 完整的提交流程示例
```bash
# 1. 完成代码修改后，首先运行测试
pytest selfdrive/controls/tests/test_controls.py

# 2. 代码质量检查
ruff check . --fix
mypy .

# 3. 添加修改总结到 change.log
cat >> change.log << 'EOF'
[2025-03-12] - [优化] - 增强横向控制稳定性分析
- 修改文件: analyze_all_segments.py
- 新增功能: 方向盘摆动检测算法
- 解决问题: 自动识别高频方向盘变化模式
- 测试验证: 运行测试并分析实际驾驶日志
- 风险说明: 需要确保算法阈值合理

EOF

# 4. 提交更改
git add .
git commit -m "feat(analysis): 增强横向控制稳定性分析算法"

# 5. 确认提交成功
git log --oneline -1
```

#### 注意事项
- **不要自动推送**：只提交到本地仓库，等待用户明确要求再推送到远程
- **详细记录**：在 change.log 中详细记录修改原因和影响
- **保持简洁**：提交消息简洁明了，change.log 中可以更详细
- **定期整理**：定期整理 change.log，合并相关修改

## 目录结构
```
carrot2-v9-acc/
├── selfdrive/           # 自动驾驶主逻辑
│   ├── controls/        # 控制算法
│   ├── car/            # 车辆接口
│   ├── modeld/         # 模型推理
│   └── test/           # 测试
├── system/             # 系统服务
│   ├── hardware/       # 硬件抽象
│   ├── camerad/        # 摄像头服务
│   └── sensord/        # 传感器服务
├── common/             # 通用工具
├── cereal/             # 消息协议
├── panda/              # CAN 接口
├── tools/              # 开发工具
└── tests/              # 集成测试
```

## 工具配置

### 编辑器配置 (.editorconfig)
```
[*]
end_of_line = lf
insert_final_newline = true
trim_trailing_whitespace = true

[*.py]
charset = utf-8
indent_style = space
indent_size = 2
```

### 预提交钩子
项目使用 pre-commit，运行 `pre-commit install` 安装钩子。

## 车辆特定开发

### 现代/起亚车辆支持
- CAN 车辆: 使用官方 Comma harness，连接到摄像头
- CAN FD 普通车辆: 使用官方 Comma harness
- CAN FD HDA2 车辆: 使用改装 harness，连接到 ADAS 模块

### BYD车辆支持
BYD车辆使用**原车ACC**通过openpilot协助控制，而非openpilot的纵向控制。

**关键特点**：
- `openpilotLongitudinalControl = False`
- 使用原车ACC系统
- openpilot通过 `acc_enhance` 机制发送减速请求

**核心代码位置**：
- `selfdrive/car/card.py`: `_update_acc_enhance()` 函数
- `opendbc_repo/opendbc/car/byd/carcontroller.py`: ACC_CMD发送逻辑

**ACC_CMD消息**：
- CAN地址：`0x32E` (十进制814)
- 字段：`AccelCmd` (加速度，m/s²), `AccControlActive` (激活标志)

**减速算法**：
```python
# 平滑减速公式：线性 + 平方根 + 二次项
accel = -(k_base * speed_diff + k_sqrt * sqrt(speed_diff) + k_quad * speed_diff^2)
# 参数：k_base=0.05, k_sqrt=0.08, k_quad=0.001
```

**详细分析文档**: `docs/byd_acc_analysis_guide.md` ⭐

### 添加新车支持
1. 在 `selfdrive/car/{brand}/` 中添加接口文件
2. 实现 `CarInterface` 和 `CarController`
3. 添加车型配置到 `selfdrive/car/{brand}/values.py`
4. 编写集成测试

## 调试和排错

### 常见命令
```bash
# 查看日志
tail -f /data/openpilot.log

# 重启服务
./restart.sh

# 检查 CAN 通信
cd panda && python -m panda.tests.lib.panda_explorer

# 模拟驾驶
tools/sim/run_sim.sh
```

### 性能分析
```python
# 使用 profiling
from openpilot.common.realtime import DT_CTRL
import cProfile

def profile_function():
    pr = cProfile.Profile()
    pr.enable()
    # 要分析的代码
    pr.disable()
    pr.print_stats(sort='time')
```

## 驾驶日志分析

### ⚠️ 重要原则

**🔴 核心原则1：驾驶日志分析必须使用整条路线的所有分段，不能只读取单个分段！**

**🔴 核心原则2：驾驶日志分析必须结合当前参数设置，这些参数会影响控制行为！**

#### 为什么必须分析整条路线？

1. **数据完整性**：分段边界可能导致事件不完整（如变道、刹车事件跨越分段边界）
2. **时间连续性**：某些分析需要连续的时间序列数据
3. **事件完整性**：路线的开始和结束可能在不同分段中
4. **统计准确性**：只有整条路线的数据才能提供准确的统计信息

#### 为什么必须结合参数设置？

参数设置直接影响控制行为：
- **横向控制参数**：影响转向响应、稳定性
- **纵向控制参数**：影响速度控制、跟车行为
- **自动功能参数**：影响启用逻辑、巡航控制

#### 相关文档参考

- **快速指南**: `docs/log_analysis_quick_guide.md` - 快速入门指南
- **字段参考**: `docs/message_fields_reference.md` - 所有消息类型的详细字段说明
- **完整参考**: `docs/driving_log_fields_reference.md` - 完整的日志分析方法
- **参数参考**: `docs/params_reference.md` - 参数设置详细说明 ⭐
- **BYD ACC分析**: `docs/byd_acc_analysis_guide.md` - BYD纵向控制分析方法 ⭐
- **BYD雷达排查**: `tools/byd_radar_troubleshooting_guide.md` - 雷达问题排查

### 参数设置位置

参数保存在 `params/d/` 目录下（符号链接到实际目录）：

```bash
# 查看参数位置
ls -la params/d

# 参数数量
ls params/d | wc -l  # 190+ 个参数

# 查看关键参数
cat params/d/CarName                    # 车型名称
cat params/d/LongitudinalPersonality    # 驾驶个性 (0-3)
cat params/d/LateralTorqueKpV           # 扭矩P增益
```

### 参数读取方法

```python
from openpilot.common.params import Params

params = Params()

# 读取关键参数
config = {
    # 车辆信息
    'car_name': params.get("CarName").decode() if params.get("CarName") else "Unknown",
    
    # 横向控制参数
    'lateral_kp': params.get_int("LateralTorqueKpV"),
    'lateral_ki': params.get_int("LateralTorqueKiV"),
    'lateral_kd': params.get_int("LateralTorqueKd"),
    'lateral_kf': params.get_int("LateralTorqueKf"),
    
    # 纵向控制参数
    'personality': params.get_int("LongitudinalPersonality"),
    
    # 自动功能
    'auto_engage': params.get_bool("AutoEngage"),
    'auto_cruise': params.get_int("AutoCruiseControl"),
}

print("当前参数设置:")
for key, value in config.items():
    print(f"  {key}: {value}")
```

### 日志存储位置
驾驶日志存储在 `.comma/` 目录中，按路线分段组织：
```
.comma/
├── 0000004d--8a69dde41a--0/      # 路线ID 0000004d--8a69dde41a 的第0个分段
│   ├── qlog.zst                  # 快速日志（小文件）
│   └── rlog.zst                  # 完整日志（大文件）
├── 0000004d--8a69dde41a--1/      # 同一路线的第1个分段
│   ├── qlog.zst
│   └── rlog.zst
└── ...
```

### 日志文件格式
- **rlog.zst**: 完整日志，包含所有消息类型，用于详细分析
- **qlog.zst**: 快速日志，包含关键消息，文件较小
- **文件格式**: Zstandard (.zst) 压缩的 Cap'n Proto 二进制格式

### 读取和分析方法

#### ❌ 错误示例：不要只读取单个分段

```python
# ❌ 错误：只读取一个分段会导致数据不完整
lr = LogReader("./.comma/0000004d--8a69dde41a--12/qlog.zst")  # 错误！
for msg in lr:
    # 这只包含一个分段的数据，可能遗漏重要事件
    pass
```

#### ✅ 正确方法：读取整条路线

```python
import os
import glob
from tools.lib.logreader import LogReader

def read_complete_route(route_id, data_dir=".comma", log_type="qlog"):
    """读取整条路线的所有分段"""
    # 1. 查找所有分段目录
    segment_dirs = sorted(
        glob.glob(f"{data_dir}/{route_id}--*"),
        key=lambda x: int(os.path.basename(x).split("--")[-1])
    )
    
    print(f"找到 {len(segment_dirs)} 个分段")
    
    # 2. 读取所有分段
    all_messages = []
    for seg_dir in segment_dirs:
        log_file = os.path.join(seg_dir, f"{log_type}.zst")
        if os.path.exists(log_file):
            lr = LogReader(log_file)
            all_messages.extend(list(lr))
    
    print(f"总共读取 {len(all_messages)} 条消息")
    return all_messages

# 使用示例
messages = read_complete_route("0000004d--8a69dde41a")
```


#### 完整路线分析脚本 (推荐)
```python
#!/usr/bin/env python3
"""
完整的路线日志分析工具
支持分析一条路线的所有分段，避免数据不完整问题
使用示例: python analyze_route_complete.py "0000000b--480d284fca"
"""

import os
import sys
from pathlib import Path
from collections import defaultdict
from typing import Dict, List, Any, Optional
from dataclasses import dataclass, field
from enum import Enum
from datetime import datetime

from openpilot.tools.lib.logreader import LogReader


class MessageFieldType(Enum):
    """消息字段类型枚举"""
    FLOAT = "float"
    INT = "int"
    BOOL = "bool"
    STRING = "string"
    LIST = "list"
    STRUCT = "struct"


@dataclass
class MessageFieldInfo:
    """消息字段信息"""
    name: str
    field_type: MessageFieldType
    description: str = ""
    sample_values: List[Any] = field(default_factory=list)


@dataclass
class MessageTypeInfo:
    """消息类型信息"""
    name: str
    description: str = ""
    fields: Dict[str, MessageFieldInfo] = field(default_factory=dict)
    sample_count: int = 0


class RouteAnalyzer:
    """完整的路线分析器"""

    def __init__(self, route_name: str, data_dir: str = ".comma"):
        """
        初始化路线分析器

        Args:
            route_name: 路线名称，如 "0000000b--480d284fca"
            data_dir: 日志数据目录，默认为 ".comma"
        """
        self.route_name = route_name
        self.data_dir = Path(data_dir)
        self.message_types: Dict[str, MessageTypeInfo] = {}
        self.segment_data: Dict[int, Dict] = {}

    def find_route_segments(self) -> List[Path]:
        """
        查找路线的所有分段目录
        """
        segment_dirs = []

        for item in self.data_dir.iterdir():
            if item.is_dir() and item.name.startswith(self.route_name + "--"):
                segment_dirs.append(item)

        def get_segment_num(path: Path) -> int:
            try:
                return int(path.name.split("--")[-1])
            except (ValueError, IndexError):
                return -1

        segment_dirs.sort(key=get_segment_num)
        return segment_dirs

    def analyze_route(self) -> Dict[str, Any]:
        """
        分析整条路线
        """
        print(f"开始分析路线: {self.route_name}")

        segment_dirs = self.find_route_segments()
        print(f"找到 {len(segment_dirs)} 个分段")

        if not segment_dirs:
            return {}

        route_stats = {
            'route_name': self.route_name,
            'total_segments': len(segment_dirs),
            'segments_analyzed': 0,
            'total_messages': 0,
            'total_duration': 0,
            'message_type_summary': defaultdict(int),
            'segment_results': {},
            'combined_data': defaultdict(list)
        }

        for i, segment_dir in enumerate(segment_dirs):
            print(f"分段 {i+1}/{len(segment_dirs)}: {segment_dir.name}")
            segment_result = self.analyze_segment(segment_dir)

            if segment_result:
                segment_num = int(segment_dir.name.split("--")[-1])
                route_stats['segment_results'][segment_num] = segment_result
                route_stats['segments_analyzed'] += 1
                route_stats['total_messages'] += segment_result['total_messages']
                route_stats['total_duration'] += segment_result['duration']

                for msg_type, count in segment_result['message_counts'].items():
                    route_stats['message_type_summary'][msg_type] += count

                for data_key, data_list in segment_result['data'].items():
                    route_stats['combined_data'][data_key].extend(data_list)

        return route_stats

    def analyze_segment(self, segment_path: Path) -> Optional[Dict]:
        """
        分析单个分段
        """
        log_path = None
        for log_file in ['rlog.zst', 'qlog.zst']:
            candidate = segment_path / log_file
            if candidate.exists():
                log_path = candidate
                break

        if not log_path:
            return None

        try:
            lr = LogReader(str(log_path))

            segment_stats = {
                'segment_name': segment_path.name,
                'total_messages': 0,
                'message_counts': defaultdict(int),
                'data': defaultdict(list),
                'timestamps': [],
                'duration': 0
            }

            for msg in lr:
                msg_type = msg.which()
                segment_stats['total_messages'] += 1
                segment_stats['message_counts'][msg_type] += 1

                ts = msg.logMonoTime / 1e9 if hasattr(msg, 'logMonoTime') else 0
                segment_stats['timestamps'].append(ts)

                self._extract_message_data(msg, msg_type, segment_stats)
                self._update_message_type_info(msg, msg_type)

            if segment_stats['timestamps']:
                segment_stats['duration'] = max(segment_stats['timestamps']) - min(segment_stats['timestamps'])

            return segment_stats

        except Exception as e:
            print(f"分析分段 {segment_path.name} 时出错: {e}")
            return None

    def _extract_message_data(self, msg, msg_type: str, segment_stats: Dict):
        """
        提取消息数据
        """
        try:
            msg_obj = getattr(msg, msg_type)

            if msg_type == 'carControl':
                if hasattr(msg_obj, 'actuators'):
                    segment_stats['data']['steering_angle'].append(msg_obj.actuators.steeringAngleDeg)
                    segment_stats['data']['steering_torque'].append(msg_obj.actuators.steeringTorque)

            elif msg_type == 'controlsState':
                segment_stats['data']['v_ego'].append(msg_obj.vEgo)
                segment_stats['data']['lateral_accel'].append(msg_obj.lateralAccel)
                segment_stats['data']['steering_angle_desired'].append(msg_obj.steeringAngleDesiredDeg)

            elif msg_type == 'carState':
                segment_stats['data']['gas_pressed'].append(msg_obj.gasPressed)
                segment_stats['data']['brake_pressed'].append(msg_obj.brakePressed)

        except Exception:
            pass

    def _update_message_type_info(self, msg, msg_type: str):
        """
        更新消息类型信息
        """
        if msg_type not in self.message_types:
            self.message_types[msg_type] = MessageTypeInfo(name=msg_type)

        msg_info = self.message_types[msg_type]
        msg_info.sample_count += 1

    def save_message_schema(self, output_file: str = "message_schema.txt"):
        """
        保存消息类型和字段结构
        """
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(f"# 基于路线: {self.route_name}\n")
            f.write(f"# 分析时间: {datetime.now()}\n")

            for msg_type, msg_info in sorted(self.message_types.items()):
                f.write(f"\n## {msg_type}\n")
                f.write(f"样本数: {msg_info.sample_count}\n")

        print(f"消息结构已保存到: {output_file}")


def main():
    if len(sys.argv) < 2:
        print("用法: python analyze_route_complete.py <路线名称>")
        sys.exit(1)

    route_name = sys.argv[1]
    analyzer = RouteAnalyzer(route_name)
    route_stats = analyzer.analyze_route()

    if route_stats:
        print(f"\n路线 {route_name} 分析完成!")
        print(f"总分段数: {route_stats['total_segments']}")
        print(f"总消息数: {route_stats['total_messages']:,}")
        print(f"总时长: {route_stats['total_duration']:.1f} 秒")

        analyzer.save_message_schema(f"message_schema_{route_name}.txt")
        print("✅ 分析完成！下次分析时可直接参考保存的消息结构文件")


if __name__ == "__main__":
    main()
```


### 关键消息类型

基于示例路线 0000000b--480d284fca 的实际分析结果：

#### 高频消息类型（前15种）：
1. **`logMessage`** (43.6%): 系统日志消息
2. **`controlsState`** (5.4%): 控制状态（车速、横向加速度等）
3. **`carControl`** (5.4%): 车辆控制指令（方向盘角度、扭矩等）
4. **`selfdriveState`** (4.9%): 自动驾驶状态
5. **`carOutput`** (4.9%): 车辆输出状态
6. **`carState`** (4.9%): 车辆状态（油门、刹车等）
7. **`sendcan`** (4.9%): CAN消息发送
8. **`can`** (4.8%): CAN消息接收
9. **`accelerometer`** (4.2%): 加速度计数据
10. **`navInstructionCarrot`** (1.0%): Carrot导航指令
11. **`roadCameraState`** (1.0%): 道路摄像头状态
12. **`uiDebug`** (1.0%): UI调试信息
13. **`modelV2`** (1.0%): 视觉模型数据（替代 modelDataV2）
14. **`cameraOdometry`** (1.0%): 摄像头里程计
15. **`drivingModelData`** (1.0%): 驾驶模型数据

#### 消息类型总数：38种
完整列表还包括：`radarState`, `livePose`, `liveParameters`, `lateralPlan`, `longitudinalPlan`, `driverAssistance`, `carrotMan`, `gyroscope`, `liveTracks`, `pandaStates`, `liveCalibration`, `liveTorqueParameters`, `liveDelay`, `deviceState`, `managerState`, `peripheralState`, `navInstruction`, `onroadEvents`, `procLog`

#### 重要字段示例：

**`carControl`** 关键字段：
- `actuators.steeringAngleDeg`: 方向盘角度（度）
- `actuators.steeringTorque`: 方向盘扭矩
- `actuators.gas`: 油门位置
- `actuators.brake`: 刹车压力

**`controlsState`** 关键字段：
- `vEgo`: 车速（m/s）
- `lateralAccel`: 横向加速度
- `lateralAccelError`: 横向加速度误差
- `steeringAngleDesiredDeg`: 期望转向角度

**`carState`** 关键字段：
- `gasPressed`: 油门是否踩下
- `brakePressed`: 刹车是否踩下
- `steeringTorqueEps`: EPS扭矩
- `aEgo`: 纵向加速度

**`modelV2`** 关键字段：
- `laneLines`: 车道线检测结果
- `lead`: 前车检测结果
- `pose`: 车辆姿态
- `meta`: 模型元数据

#### 保存消息结构文件：
每次完整路线分析后，工具会自动生成 `message_schema_{route_name}.txt` 文件，包含所有消息类型的字段结构和示例值，避免每次重新分析。

## 安全注意事项

### 代码安全
1. 所有输入验证必须严格
2. CAN 消息必须验证 CRC
3. 控制指令必须包含安全限制
4. 错误处理必须防止系统失效

### 车辆安全
1. ACC 控制必须符合车辆安全限制
2. 转向控制必须有速率限制
3. 紧急情况必须能安全退出
4. 系统必须能处理传感器失效

## 贡献指南

### 1. 代码审查要求
- 所有 PR 必须通过 CI 测试
- 需要至少一位核心开发者审查
- 代码必须符合项目风格指南
- 必须有适当的测试覆盖

### 2. 文档要求
- 新功能需要更新 README
- API 变更需要更新文档
- 配置变更需要更新注释

### 3. 发布流程
1. 在 `nightly` 分支开发
2. 通过 CI 测试
3. 合并到 `release3` 分支
4. 创建发布标签

---

*最后更新: 2026-04-13*
*基于 openpilot commit: $(cat git_src_commit)*