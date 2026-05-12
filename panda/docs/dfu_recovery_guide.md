# Panda DFU 模式恢复指南

## 问题描述

Panda 进入 DFU 模式（`0483:df11`）无法正常启动，通常由以下原因导致：

1. **刷入错误版本的固件**（如将 H7 固件刷入 F4 设备）
2. Flash 损坏或固件校验失败
3. Bootloader 异常

## 诊断方法

```bash
# 检查 USB 设备状态
lsusb | grep -i 0483
# 正常输出: Bus 001 Device XXX: ID 0483:df11 STMicroelectronics STM Device in DFU Mode

# 详细查看 DFU 描述符
lsusb -v -d 0483:df11
```

## 恢复步骤

### 步骤 1: 确认固件文件

确保已编译正确的固件：

```bash
source .venv/bin/activate
cd panda/board
ls -la obj/
# 确认以下文件存在:
# - bootstub.panda.bin      (F4 bootstub)
# - panda.bin.signed        (F4 应用固件)
# - bootstub.panda_h7.bin   (H7 bootstub, 仅 H7 设备需要)
# - panda_h7.bin.signed     (H7 应用固件, 仅 H7 设备需要)
```

### 步骤 2: 擦除 Flash 扇区

**方法一: Python 脚本（推荐，可处理异常状态）**

```python
import usb1
import struct
import time

DFU_DNLOAD = 1
DFU_GETSTATUS = 3
DFU_CLRSTATUS = 4
ZERO = b'\x00'

# F4 配置
F4_BOOTSTUB_ADDRESS = 0x08000000
F4_SECTOR_SIZES = [0x4000]*4 + [0x10000] + [0x20000]*11

def get_state(handle):
    dat = handle.controlRead(0x21, DFU_GETSTATUS, 0, 0, 6, timeout=10000)
    return dat[4]

def to_idle(handle):
    """强制 DFU 回到 idle 状态"""
    for _ in range(10):
        state = get_state(handle)
        if state == 0x02:  # dfuIDLE
            return True
        if state == 0x0a:  # dfuERROR
            handle.controlRead(0x21, DFU_CLRSTATUS, 0, 0, 0, timeout=3000)
        elif state == 0x05:  # dfuDNLOAD_SYNC
            handle.controlRead(0x21, DFU_CLRSTATUS, 0, 0, 0, timeout=3000)
        time.sleep(0.1)
    return False

context = usb1.USBContext()
context.open()

for device in context.getDeviceList(skip_on_error=True):
    if device.getVendorID() == 0x0483 and device.getProductID() == 0xdf11:
        handle = device.open()
        handle.setAutoDetachKernelDriver(True)
        handle.claimInterface(0)
        
        # 擦除所有 16 个扇区
        sector_addr = F4_BOOTSTUB_ADDRESS
        for i, size in enumerate(F4_SECTOR_SIZES):
            to_idle(handle)
            handle.controlWrite(0x21, DFU_DNLOAD, 0, 0,
                b"\x41" + struct.pack("I", sector_addr), timeout=5000)
            time.sleep(0.5 if size < 0x20000 else 1.0)
            try:
                handle.controlRead(0x21, DFU_CLRSTATUS, 0, 0, 0, timeout=3000)
            except:
                pass
            time.sleep(0.1)
            to_idle(handle)
            sector_addr += size
        
        handle.releaseInterface(0)
        handle.close()

context.close()
```

**方法二: dfu-util（正常状态时使用）**

```bash
# 擦除整个 Flash (mass erase 不支持时使用页面擦除)
sudo dfu-util -d 0483:df11 -a 0 -s 0x08000000:mass-erase:force
```

### 步骤 3: 刷入 Bootstub

使用 `dfu-util` 刷入 bootstub：

```bash
# F4 设备
sudo dfu-util -d 0483:df11 -a 0 -s 0x08000000:leave -D panda/board/obj/bootstub.panda.bin

# H7 设备
sudo dfu-util -d 0483:df11 -a 0 -s 0x08000000:leave -D panda/board/obj/bootstub.panda_h7.bin
```

> 注意: `:leave` 参数表示刷入后自动退出 DFU 模式并启动设备

### 步骤 4: 刷入应用固件

Bootstub 启动后，使用 Panda Python API 刷入应用固件：

```python
from panda import Panda

serials = Panda.list()
for s in serials:
    with Panda(serial=s) as p:
        if p.bootstub:
            print(f"Flashing panda {p.get_usb_serial()}...")
            p.flash()
            print("Flash complete!")
```

或命令行方式：

```bash
python3 -c "from panda import Panda; Panda().flash()"
```

### 步骤 5: 验证恢复

```bash
# 检查 USB 设备
lsusb | grep -i panda
# 正常: Bus 001 Device XXX: ID 3801:ddcc comma.ai panda

# 使用 Python API 验证
python3 -c "
from panda import Panda
p = Panda()
print(f'Serial: {p.get_usb_serial()}')
print(f'Bootstub: {p.bootstub}')
print(f'MCU: {p.get_mcu_type()}')
print(f'Version: {p.get_version()}')
print(f'Health: {p.health()}')
"
```

## 常见问题

### 1. dfu-util 报 `LIBUSB_ERROR_OVERFLOW`

**原因**: 设备 USB 字符串描述符损坏，dfu-util 读取时溢出。

**解决**: 使用上述 Python 脚本方法，直接通过 DFU 协议操作，不依赖字符串描述符。

### 2. dfu-util 报 `LIBUSB_ERROR_PIPE`

**原因**: DFU 状态机未正确流转，从 `dfuDNLOAD_SYNC` 状态发送新命令被拒绝。

**解决**: 先使用 `CLRSTATUS` 命令回到 `dfuIDLE` 状态，然后再发送下一个命令。

### 3. `PandaDFU.list()` 返回空列表

**原因**: Python usb1 库在读取设备序列号时遇到损坏的字符串描述符。

**解决**: 使用 `dfu-util` 命令行工具或上述 Python 脚本直接操作。

### 4. 不确定设备是 F4 还是 H7

**方法**: 
- F4 序列号通常是 24 字符（如 `560045001051333038373636`）
- H7 序列号通常是 12 字符（如 `367B37983033`）
- F4 Flash 容量 1MB，H7 Flash 容量 2MB

## 预防措施

1. **刷入前确认 MCU 类型**: 使用 `Panda.get_mcu_type()` 确认
2. **使用项目自带工具**: `panda/board/recover.py` 会自动处理大部分情况
3. **备份固件**: 在刷入新固件前记录当前固件版本
