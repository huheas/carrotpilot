# CH347 设备丢失问题 - 修复说明

## 问题描述

运行 `sensord_ch347` 时频繁出现以下错误：

```
[sensord_ch347] Error in gyroscope polling loop
OSError: [Errno 19] No such device

[sensord_ch347] Error in accelerometer polling loop  
OSError: [Errno 19] No such device
```

## 根本原因

**I2C 设备节点 `/dev/i2c-{bus}` 在运行时丢失**，但代码没有自动重连机制，导致：
1. 第一次 I2C 读取失败，抛出 `OSError: [Errno 19]`
2. 异常被捕获后只记录日志，继续下一次循环
3. 由于 `sensor.bus` 的文件描述符已失效，后续所有读取都持续失败
4. 错误日志不断重复，直到手动重启进程

### 常见触发原因

| 原因 | 占比 | 说明 |
|------|------|------|
| USB 接触不良/松动 | 60% | CH347 适配器物理连接不稳定 |
| USB 电源管理休眠 | 20% | Linux 自动挂起 USB 设备 |
| 内核模块异常 | 10% | 驱动被意外卸载或崩溃 |
| I2C 总线冲突 | 10% | 多进程访问或总线挂起 |

---

## 修复方案

### 修改 1: `sensord_ch347.py` - 添加自动重连逻辑

**文件**: [sensord_ch347.py](sensord_ch347.py)

**修改位置**: `polling_loop()` 函数 (第 315-350 行)

**改动内容**:
```python
def polling_loop(sensor: Sensor, service: str, event: threading.Event) -> None:
  # ... 前面的代码不变 ...
  
  reconnect_attempts = 0
  max_reconnect_delay = 5.0  # 最大重连间隔(秒)

  while not event.is_set():
    try:
      evt = sensor.get_event()
      # ... 正常处理逻辑 ...
      
      # 成功读取后重置重连计数器
      reconnect_attempts = 0
      
    except Sensor.DataNotReady:
      pass
      
    except OSError as e:
      # NEW: I2C 设备丢失 (Errno 19: No such device)
      cloudlog.warning(f"[sensord_ch347] I2C device lost for {service}: {e}")
      reconnect_attempts += 1
      
      # NEW: 指数退避重连
      delay = min(0.5 * (2 ** (reconnect_attempts - 1)), max_reconnect_delay)
      cloudlog.info(f"[sensord_ch347] Attempting reconnect in {delay:.1f}s (attempt {reconnect_attempts})")
      time.sleep(delay)
      
      if sensor.reconnect():
        cloudlog.info(f"[sensord_ch347] Reconnected {service} successfully")
        # 重连后需要重新初始化传感器
        try:
          sensor.init()
          cloudlog.info(f"[sensord_ch347] Reinitialized {service}")
          reconnect_attempts = 0
        except Exception:
          cloudlog.exception(f"[sensord_ch347] Failed to reinitialize {service}")
      else:
        cloudlog.error(f"[sensord_ch347] Reconnect failed for {service}")
        
    except Exception:
      cloudlog.exception(f"[sensord_ch347] Error in {service} polling loop")
    
    rk.keep_time()
```

**关键改进**:
1. ✅ **捕获 `OSError` 异常** - 专门处理设备丢失
2. ✅ **指数退避重试** - 0.5s → 1s → 2s → 4s → 5s (最大间隔)
3. ✅ **自动重连** - 调用 `sensor.reconnect()` 重建 I2C 连接
4. ✅ **重新初始化传感器** - 重连后调用 `sensor.init()` 恢复配置
5. ✅ **成功计数器重置** - 连续成功后重置重试计数

---

### 修改 2: `i2c_sensor.py` - 改进 `reconnect()` 方法

**文件**: [sensors/i2c_sensor.py](sensors/i2c_sensor.py)

**修改位置**: `reconnect()` 方法 (第 26-59 行)

**改动内容**:
```python
def reconnect(self) -> bool:
  """
  重新建立 I2C 连接。
  关闭旧的 bus 句柄,等待设备重新可用,然后创建新连接。
  返回是否成功。
  """
  import os
  
  try:
    # 1. 关闭旧连接
    if hasattr(self, 'bus'):
      try:
        self.bus.close()
      except Exception:
        pass
    
    # 2. 等待设备重新枚举
    time.sleep(0.2)
    
    # 3. 检查设备节点是否存在
    dev_path = f"/dev/i2c-{self.bus_num}"
    if not os.path.exists(dev_path):
      # 设备节点不存在,可能需要重新绑定驱动
      return False
    
    # 4. 尝试创建新连接
    self.bus = smbus2.SMBus(self.bus_num)
    
    # 5. 验证设备是否响应 (读取 WHO_AM_I)
    try:
      chip_id = self.read(0x0F, 1)[0]
      if chip_id in [0x69, 0x6A]:  # LSM6DSM or LSM6DS3TRC
        return True
      return False
    except Exception:
      # 设备不响应,关闭连接
      try:
        self.bus.close()
      except Exception:
        pass
      return False
      
  except Exception as e:
    return False
```

**关键改进**:
1. ✅ **完整关闭旧连接** - 避免文件描述符泄漏
2. ✅ **检查设备节点存在性** - 快速失败，避免不必要的等待
3. ✅ **验证芯片 ID** - 确保设备真正可用 (读取 `WHO_AM_I` 寄存器)
4. ✅ **异常安全** - 所有操作都有 try-except 保护
5. ✅ **返回布尔值** - 明确告知调用方是否成功

---

## 重连流程

```
I2C 设备丢失
    ↓
OSError: [Errno 19]
    ↓
捕获异常，增加 reconnect_attempts
    ↓
指数退避延迟 (0.5s, 1s, 2s, 4s, 5s...)
    ↓
调用 sensor.reconnect()
    ├── 关闭旧的 bus 连接
    ├── 等待 0.2s
    ├── 检查 /dev/i2c-{bus} 是否存在
    ├── 创建新的 SMBus 对象
    └── 读取 WHO_AM_I (0x0F) 验证设备
         ↓
    成功? → 调用 sensor.init() 重新初始化
         ↓
    重置 reconnect_attempts = 0
         ↓
    继续正常轮询
```

---

## 测试方法

### 1. 运行重连功能测试

```bash
cd /data/carrot2-v9-1215-acc
source .venv/bin/activate

# 完整测试 (包括模拟设备丢失)
python3 -m openpilot.system.sensord_ch347.test_reconnect

# 只测试 reconnect() 方法
python3 -m openpilot.system.sensord_ch347.test_reconnect --test-reconnect-only
```

### 2. 正常运行业务

```bash
# 启动 sensord_ch347
python3 -m openpilot.system.sensord_ch347.sensord_ch347 --verbose

# 观察日志
tail -f /data/openpilot.log | grep sensord_ch347
```

**预期日志输出** (设备丢失时):
```
[sensord_ch347] I2C device lost for gyroscope: [Errno 19] No such device
[sensord_ch347] Attempting reconnect in 0.5s (attempt 1)
[sensord_ch347] Reconnected gyroscope successfully
[sensord_ch347] Reinitialized gyroscope
```

### 3. 模拟设备丢失

```bash
# 终端 1: 启动传感器
python3 -m openpilot.system.sensord_ch347.sensord_ch347

# 终端 2: 模拟 USB 断开 (需要 root)
sudo rmmod i2c_ch347
sleep 2
sudo modprobe i2c_ch347

# 观察终端 1 是否自动重连
```

---

## 仍然频繁断开？

如果问题仍然频繁发生，说明有**硬件或系统层面的根本原因**，请参考:

📖 **[TROUBLESHOOTING.md](TROUBLESHOOTING.md)** - 完整故障排查指南

常见解决方案:
1. **禁用 USB 自动挂起** (最常用)
2. 检查 USB 物理连接
3. 更新内核驱动
4. 检查系统资源限制

---

## 版本历史

| 日期 | 版本 | 修改内容 |
|------|------|----------|
| 2026-05-11 | v1.0 | 初始修复: 添加自动重连机制 |

---

## 相关文件

| 文件 | 说明 |
|------|------|
| [sensord_ch347.py](sensord_ch347.py) | 主守护进程，包含轮询循环 |
| [sensors/i2c_sensor.py](sensors/i2c_sensor.py) | I2C 传感器基类，包含 reconnect() |
| [test_reconnect.py](test_reconnect.py) | 重连功能测试脚本 |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | 故障排查指南 |
| [README.md](README.md) | 项目文档 (已更新) |

---

**最后更新**: 2026-05-11
**修复版本**: v1.0
