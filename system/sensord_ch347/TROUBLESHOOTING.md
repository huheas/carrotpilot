# CH347 设备丢失问题排查指南

## 问题现象

运行 `sensord_ch347` 时频繁出现以下错误：

```
OSError: [Errno 19] No such device
```

## 已实施的自动修复

**代码已添加自动重连机制**，现在设备丢失时会自动尝试恢复：
- 指数退避重试 (0.5s → 1s → 2s → 4s → 5s)
- 重新初始化传感器配置
- 无需重启进程

如果问题仍然频繁发生，请按以下步骤排查根本原因。

---

## 排查步骤

### 1. 检查 USB 物理连接 (最常见原因)

```bash
# 实时监控 USB 设备状态
watch -n 1 'lsusb | grep 1a86'

# 查看内核日志中的 USB 断开/重连事件
dmesg | grep -i usb | tail -50

# 检查 USB 供电状态
cat /sys/bus/usb/devices/*/power/control
```

**预期结果**：
- 应该持续看到 `1a86:55db` 或 `1a86:55da` (CH347)
- 不应该有频繁的 `USB disconnect` / `new USB device` 消息

**如果发现问题**：
- 重新插拔 CH347 适配器
- 更换 USB 线缆或端口
- 尝试使用带电源的 USB Hub

---

### 2. 禁用 USB 自动挂起

Linux 可能会自动挂起 USB 设备以节省电源。

```bash
# 查看当前 USB 设备的电源控制设置
ls /sys/bus/usb/devices/*/power/control

# 临时禁用所有 USB 自动挂起 (立即生效，重启后失效)
for i in /sys/bus/usb/devices/*/power/control; do
  echo on | sudo tee $i
done

# 验证设置
cat /sys/bus/usb/devices/$(lsusb | grep 1a86 | awk '{print $6}')/power/control
# 应该输出 "on"
```

**永久禁用** (推荐)：

```bash
# 创建 udev 规则
sudo tee /etc/udev/rules.d/99-ch347-usb-power.rules << 'EOF'
# 禁用 CH347 USB 自动挂起
ACTION=="add", SUBSYSTEM=="usb", ATTRS{idVendor}=="1a86", ATTR{idProduct}=="55db", ATTR{power/control}="on"
ACTION=="add", SUBSYSTEM=="usb", ATTRS{idVendor}=="1a86", ATTR{idProduct}=="55da", ATTR{power/control}="on"
EOF

# 重载规则
sudo udevadm control --reload-rules
sudo udevadm trigger
```

---

### 3. 检查内核模块稳定性

```bash
# 查看驱动加载状态
lsmod | grep ch347

# 监控内核日志
dmesg -w | grep -i ch347

# 检查是否有模块崩溃或重启
journalctl -k | grep -i "ch347\|i2c" | tail -100
```

**预期输出**：
```
mfd_ch347    20480  0
i2c_ch347    16384  0
gpio_ch347   16384  0
spi_ch347    16384  0
```

**如果模块频繁重新加载**：
- 可能是驱动 Bug，考虑更新到最新版本
- 检查内核版本是否兼容 (`uname -r`，推荐 6.11+)

---

### 4. 检查 I2C 总线冲突

```bash
# 查看当前 I2C 适配器
i2cdetect -l

# 扫描总线上的设备 (替换 N 为实际总线号)
sudo i2cdetect -y N

# 检查是否有其他进程占用 I2C 总线
sudo lsof /dev/i2c-*
```

**预期结果**：
- 应该看到 `i2c-N  ch347-i2c  I2C adapter`
- `0x6B` 位置应该显示 `UU` (已被驱动占用) 或 `6B` (设备存在)

**如果发现冲突**：
- 关闭其他访问 I2C 的程序
- 确保没有多个 `sensord_ch347` 进程同时运行

---

### 5. 检查系统资源限制

```bash
# 查看文件描述符限制
ulimit -n

# 查看进程打开的文件数
ls -l /proc/$(pgrep -f sensord_ch347)/fd | wc -l

# 检查系统 dmesg 是否有资源不足
dmesg | grep -i "out of memory\|file descriptor"
```

**如果文件描述符耗尽**：
```bash
# 临时增加限制
ulimit -n 65536

# 永久修改 (添加到 /etc/security/limits.conf)
* soft nofile 65536
* hard nofile 65536
```

---

### 6. 启用详细日志调试

```bash
# 启动 sensord_ch347 时启用调试日志
python3 -m openpilot.system.sensord_ch347.sensord_ch347 --verbose

# 实时监控 openpilot 日志
tail -f /data/openpilot.log | grep sensord_ch347
```

**关键日志关键词**：
- `I2C device lost` - 设备丢失
- `Attempting reconnect` - 正在重连
- `Reconnected successfully` - 重连成功
- `Reinitialized` - 传感器重新初始化

---

## 常见解决方案总结

| 问题 | 症状 | 解决方案 |
|------|------|----------|
| **USB 接触不良** | 频繁断开/重连 | 更换线缆/端口，使用 USB Hub |
| **USB 自动挂起** | 空闲一段时间后断开 | 禁用 USB autosuspend (见步骤2) |
| **驱动不稳定** | 内核日志有 ch347 错误 | 更新驱动或内核版本 |
| **权限问题** | Permission denied | 运行 `setup_ch347.sh` 修复 |
| **总线冲突** | 多进程访问 I2C | 确保只有一个 sensord_ch347 运行 |

---

## 监控脚本

创建一个监控脚本来持续跟踪设备状态：

```bash
#!/bin/bash
# monitor_ch347.sh - 监控 CH347 设备状态

echo "=== CH347 监控 (Ctrl+C 退出) ==="

while true; do
  timestamp=$(date '+%Y-%m-%d %H:%M:%S')
  
  # 检查 USB 设备
  usb_status=$(lsusb | grep -c 1a86)
  
  # 检查 I2C 设备
  i2c_status=$(i2cdetect -l 2>/dev/null | grep -c ch347)
  
  # 检查进程状态
  proc_status=$(pgrep -f sensord_ch347 | wc -l)
  
  # 输出状态
  if [ "$usb_status" -gt 0 ] && [ "$i2c_status" -gt 0 ] && [ "$proc_status" -gt 0 ]; then
    echo "[$timestamp] ✓ USB: $usb_status, I2C: $i2c_status, Process: $proc_status"
  else
    echo "[$timestamp] ✗ USB: $usb_status, I2C: $i2c_status, Process: $proc_status"
    dmesg | tail -5
  fi
  
  sleep 5
done
```

使用方法：
```bash
chmod +x monitor_ch347.sh
./monitor_ch347.sh
```

---

## 联系支持

如果问题仍然无法解决，请收集以下信息：

```bash
# 生成诊断报告
{
  echo "=== System Info ==="
  uname -a
  echo ""
  
  echo "=== USB Devices ==="
  lsusb
  echo ""
  
  echo "=== CH347 Kernel Modules ==="
  lsmod | grep ch347
  echo ""
  
  echo "=== I2C Adapters ==="
  i2cdetect -l
  echo ""
  
  echo "=== Recent dmesg (CH347) ==="
  dmesg | grep -i ch347 | tail -50
  echo ""
  
  echo "=== sensord_ch347 Logs ==="
  journalctl -u sensord_ch347 --no-pager -n 100 2>/dev/null || echo "No systemd service"
} > ch347_diagnostic_$(date +%Y%m%d_%H%M%S).txt

echo "诊断报告已生成: ch347_diagnostic_$(date +%Y%m%d_%H%M%S).txt"
```

将生成的 `.txt` 文件提供给技术支持。

---

**最后更新**: 2026-05-11
**相关代码**: [sensord_ch347.py](sensord_ch347.py), [i2c_sensor.py](sensors/i2c_sensor.py)
