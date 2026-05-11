#!/usr/bin/env python3
"""
sensord_ch347 - LSM6DS3 IMU daemon for CH347 USB-to-I2C adapter

Uses aystarik/ch347_vcp open source driver (https://github.com/aystarik/ch347_vcp)
which creates standard I2C bus on kernel 6.11+. The bus number is auto-detected
by scanning /sys/bus/i2c/devices/ for ch347-i2c entries.

This daemon reads from that bus using standard smbus2, no special CH347 library required.
Driver binding, permission fixes, and bus detection are all handled automatically.

Usage:
  python3 -m openpilot.system.sensord_ch347.sensord_ch347 [--bus N] [--verbose]

  --bus N        I2C bus number (auto-detected from ch347-i2c if not specified).
  --verbose      Enable debug logging.
  --no-accel     Disable accelerometer.
  --no-gyro      Disable gyroscope.
  --enable-temp  Enable temperature sensor (disabled by default).
  --help         Show this help.
"""
import argparse
import glob
import os
import subprocess
import time
import threading

import cereal.messaging as messaging
from cereal.services import SERVICE_LIST
from openpilot.common.realtime import Ratekeeper
from openpilot.common.swaglog import cloudlog

from openpilot.system.sensord_ch347.sensors.i2c_sensor import Sensor
from openpilot.system.sensord_ch347.sensors.lsm6ds3_accel import LSM6DS3_Accel
from openpilot.system.sensord_ch347.sensors.lsm6ds3_gyro import LSM6DS3_Gyro
from openpilot.system.sensord_ch347.sensors.lsm6ds3_temp import LSM6DS3_Temp

# CH347 USB vendor/product ID
CH347_VENDOR_ID = "1a86"
CH347_PRODUCT_IDS = {"55db", "55da", "55d9"}  # CH347T/F variants


def _write_sysfs(path: str, value: str) -> bool:
  """
  向 sysfs 文件写入值。
  先尝试直接写（进程是 root 时）；失败则用 sudo -n bash -c 'echo VALUE > PATH'。
  返回是否成功。
  """
  # 方法1：直接写（root 进程）
  try:
    with open(path, "w") as f:
      f.write(value)
    return True
  except PermissionError:
    pass
  except Exception as e:
    cloudlog.error(f"[sensord_ch347] _write_sysfs {path}: {e}")
    return False

  # 方法2：sudo -n bash -c（需要免密 sudo，常见开发机已配置）
  try:
    # 用 bash -c 是因为 echo > 是 shell 重定向，不能直接作为 argv 传给 sudo
    cmd = f"echo {value!r} > {path}"
    result = subprocess.run(
      ["sudo", "-n", "bash", "-c", cmd],
      capture_output=True, timeout=5
    )
    if result.returncode == 0:
      return True
    cloudlog.warning(
      f"[sensord_ch347] sudo bash -c '{cmd}' failed: {result.stderr.decode().strip()}"
    )
  except Exception as e:
    cloudlog.error(f"[sensord_ch347] sudo write {path}: {e}")

  return False


def find_ch347_usb_interfaces() -> list[str]:
  """
  查找所有 CH347 USB 接口路径（/sys/bus/usb/devices/X-Y:1.Z）。
  只返回 vendor=1a86 且 product 在 CH347_PRODUCT_IDS 中的设备的接口列表。
  """
  interfaces = []
  for dev_path in glob.glob("/sys/bus/usb/devices/*/idVendor"):
    try:
      vendor = open(dev_path).read().strip()
      if vendor != CH347_VENDOR_ID:
        continue
      dev_dir = os.path.dirname(dev_path)
      product = open(os.path.join(dev_dir, "idProduct")).read().strip()
      if product not in CH347_PRODUCT_IDS:
        continue
      dev_name = os.path.basename(dev_dir)
      for intf in glob.glob(f"/sys/bus/usb/devices/{dev_name}:*/"):
        interfaces.append(intf.rstrip("/"))
    except Exception:
      continue
  return interfaces


def ensure_ch347_driver_bound() -> bool:
  """
  确保 CH347 所有 USB 接口绑定到驱动。
  如果某接口尚无 driver 符号链接，写入 /sys/bus/usb/drivers/ch347/bind 触发内核绑定。
  返回：是否有绑定操作发生（调用方需要等待 i2c 子设备注册）。
  """
  interfaces = find_ch347_usb_interfaces()
  if not interfaces:
    cloudlog.warning("[sensord_ch347] No CH347 USB device found. Check: lsusb | grep 1a86")
    return False

  bind_path = "/sys/bus/usb/drivers/ch347/bind"
  if not os.path.exists(bind_path):
    cloudlog.error(f"[sensord_ch347] {bind_path} not found. Is mfd_ch347 module loaded?")
    return False

  bound_any = False
  for intf_path in interfaces:
    driver_link = os.path.join(intf_path, "driver")
    if os.path.exists(driver_link):
      continue  # 已绑定，跳过

    intf_name = os.path.basename(intf_path)
    cloudlog.warning(f"[sensord_ch347] {intf_name} not bound, writing to {bind_path} ...")

    if _write_sysfs(bind_path, intf_name):
      cloudlog.info(f"[sensord_ch347] Successfully bound {intf_name} to ch347 driver")
      bound_any = True
    else:
      cloudlog.error(
        f"[sensord_ch347] Cannot bind {intf_name}. "
        f"Fix: sudo bash -c 'echo {intf_name!r} > {bind_path}'"
      )

  return bound_any


def _run_cmd_sudo(cmd: list[str]) -> bool:
  """用 sudo -n 执行普通命令（非 sysfs 写），返回是否成功。"""
  try:
    result = subprocess.run(["sudo", "-n"] + cmd, capture_output=True, timeout=5)
    return result.returncode == 0
  except Exception:
    return False


def ensure_ch347_modules_loaded() -> bool:
  """确保 CH347 内核模块已加载。返回是否需要等待。"""
  modules = ["mfd_ch347", "i2c_ch347", "gpio_ch347", "spi_ch347"]
  loaded = set()
  try:
    lsmod = subprocess.run(["lsmod"], capture_output=True, text=True).stdout
    for mod in modules:
      if mod.replace("-", "_") in lsmod or mod.replace("_", "-") in lsmod:
        loaded.add(mod)
  except Exception:
    pass

  missing = [m for m in ["mfd_ch347", "i2c_ch347"] if m not in loaded]
  if not missing:
    return False  # 已全部加载

  cloudlog.warning(f"[sensord_ch347] Missing kernel modules: {missing}, trying to load...")
  for mod in missing:
    ok = _run_cmd_sudo(["modprobe", mod])
    if not ok:
      ok = _run_cmd_sudo(["insmod", f"/lib/modules/{os.uname().release}/updates/{mod}.ko"])
    if ok:
      cloudlog.info(f"[sensord_ch347] Loaded module {mod}")
    else:
      cloudlog.error(f"[sensord_ch347] Cannot load module {mod}. Run: sudo modprobe {mod}")
  return True


def detect_ch347_bus(wait_secs: float = 3.0) -> int | None:
  """
  自动检测 CH347 I2C 总线号。
  先扫描 /sys/bus/i2c/devices/，找名称含 ch347 的适配器。
  若未找到，等待 wait_secs 秒后重试（驱动刚绑定时需要时间注册）。
  """
  deadline = time.monotonic() + wait_secs
  while True:
    for path in glob.glob("/sys/bus/i2c/devices/i2c-*"):
      name_file = os.path.join(path, "name")
      try:
        with open(name_file) as f:
          name = f.read().strip()
        if "ch347" in name.lower():
          bus_num = int(os.path.basename(path).split("-")[1])
          cloudlog.info(f"[sensord_ch347] Auto-detected CH347 on I2C bus {bus_num} (adapter={name})")
          return bus_num
      except (OSError, ValueError, IndexError):
        continue

    if time.monotonic() >= deadline:
      break
    time.sleep(0.3)

  return None


def ensure_i2c_accessible(bus: int) -> bool:
  """
  确保 /dev/i2c-{bus} 可访问。
  按顺序尝试：直接访问 → chmod（自身权限） → sudo chmod → udev rule。
  返回是否最终可访问。
  """
  dev_path = f"/dev/i2c-{bus}"

  if not os.path.exists(dev_path):
    cloudlog.error(f"[sensord_ch347] {dev_path} does not exist")
    return False

  # 测试实际权限（用 open() 而非 os.access()，前者正确检查补充组）
  def _can_open() -> bool:
    try:
      with open(dev_path, "rb"):
        pass
      return True
    except PermissionError:
      return False

  if _can_open():
    return True

  cloudlog.warning(f"[sensord_ch347] {dev_path} not accessible, attempting permission fix...")

  # 1. 尝试直接 chmod（仅当进程是 root 或设备属主时成功）
  try:
    os.chmod(dev_path, 0o666)
    if _can_open():
      cloudlog.info(f"[sensord_ch347] Fixed permissions via os.chmod: {dev_path}")
      return True
  except PermissionError:
    pass

  # 2. sudo chmod（需要免密 sudo 配置）
  if _run_cmd_sudo(["chmod", "666", dev_path]):
    if _can_open():
      cloudlog.info(f"[sensord_ch347] Fixed permissions via sudo chmod: {dev_path}")
      # 同时写入 udev 规则防止下次重现
      _install_udev_rule()
      return True

  # 3. 提示用户
  cloudlog.error(
    f"[sensord_ch347] Cannot access {dev_path}. Choose a fix:\n"
    f"  A) Add user to i2c group (permanent, needs re-login):\n"
    f"       sudo usermod -aG i2c $USER\n"
    f"  B) Install udev rule (permanent, takes effect on next plug):\n"
    f"       sudo bash {os.path.dirname(__file__)}/ch347_setup.sh\n"
    f"  C) Quick fix (until reboot):\n"
    f"       sudo chmod 666 {dev_path}"
  )
  return False


def _install_udev_rule() -> None:
  """尝试自动写入 udev 规则，使 CH347 I2C 设备对 i2c 组可读写。"""
  rule = (
    'SUBSYSTEM=="i2c-dev", '
    'ATTRS{idVendor}=="1a86", '
    'ATTRS{idProduct}=="55db", '
    'MODE="0660", GROUP="i2c"\n'
    'SUBSYSTEM=="i2c-dev", '
    'ATTRS{idVendor}=="1a86", '
    'ATTRS{idProduct}=="55da", '
    'MODE="0660", GROUP="i2c"\n'
  )
  rule_path = "/etc/udev/rules.d/99-ch347-i2c.rules"
  if os.path.exists(rule_path):
    return  # 已安装

  try:
    # 尝试直接写（root 运行时）
    with open(rule_path, "w") as f:
      f.write(rule)
    _run_cmd_sudo(["udevadm", "control", "--reload-rules"])
    cloudlog.info(f"[sensord_ch347] Installed udev rule: {rule_path}")
  except PermissionError:
    # sudo tee
    proc = subprocess.run(
      ["sudo", "-n", "tee", rule_path],
      input=rule, capture_output=True, text=True, timeout=5
    )
    if proc.returncode == 0:
      _run_cmd_sudo(["udevadm", "control", "--reload-rules"])
      cloudlog.info(f"[sensord_ch347] Installed udev rule via sudo: {rule_path}")
    else:
      cloudlog.warning("[sensord_ch347] Cannot install udev rule (no sudo). Run ch347_setup.sh manually.")
  except Exception as e:
    cloudlog.warning(f"[sensord_ch347] udev rule install failed: {e}")


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(
    description="LSM6DS3 IMU daemon for CH347 USB-to-I2C adapter",
    formatter_class=argparse.RawDescriptionHelpFormatter,
  )
  parser.add_argument("--bus", type=int, default=None,
                      help="I2C bus number (auto-detected from ch347-i2c if not specified)")
  parser.add_argument("--no-accel", action="store_true",
                      help="Disable accelerometer")
  parser.add_argument("--no-gyro", action="store_true",
                      help="Disable gyroscope")
  parser.add_argument("--enable-temp", action="store_true",
                      help="Enable temperature sensor")
  parser.add_argument("--verbose", action="store_true",
                      help="Enable debug logging")
  return parser.parse_args()


def polling_loop(sensor: Sensor, service: str, event: threading.Event) -> None:
  """Polling loop for a single sensor. All sensors use polling since CH347
  does not expose a GPIO line for the LSM6DS3 INT1 interrupt pin."""
  pm = messaging.PubMaster([service])
  rk = Ratekeeper(SERVICE_LIST[service].frequency, print_delay_threshold=None)

  cloudlog.info(f"[sensord_ch347] Starting polling loop: {service} @ {SERVICE_LIST[service].frequency}Hz")

  reconnect_attempts = 0
  max_reconnect_delay = 5.0  # 最大重连间隔(秒)

  while not event.is_set():
    try:
      evt = sensor.get_event()
      if not sensor.is_data_valid():
        rk.keep_time()
        continue
      msg = messaging.new_message(service, valid=True)
      setattr(msg, service, evt)
      pm.send(service, msg)
      
      # 成功读取后重置重连计数器
      reconnect_attempts = 0
    except Sensor.DataNotReady:
      pass  # data not ready yet, will retry next cycle
    except OSError as e:
      # I2C 设备丢失 (Errno 19: No such device)
      cloudlog.warning(f"[sensord_ch347] I2C device lost for {service}: {e}")
      reconnect_attempts += 1
      
      # 指数退避重连
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

  cloudlog.info(f"[sensord_ch347] Stopped polling loop: {service}")


def main() -> None:
  args = parse_args()

  if args.verbose:
    os.environ["LOGPRINT"] = "debug"

  # ── 步骤1：确保内核模块已加载 ──────────────────────────────────────
  modules_just_loaded = ensure_ch347_modules_loaded()
  if modules_just_loaded:
    time.sleep(1.0)  # 等待模块完成初始化

  # ── 步骤2：确保 USB 接口已绑定到驱动 ─────────────────────────────
  driver_just_bound = ensure_ch347_driver_bound()
  if driver_just_bound:
    cloudlog.info("[sensord_ch347] Driver binding triggered, waiting for I2C device registration...")
    time.sleep(2.0)  # 等待 platform 子设备注册并创建 /dev/i2c-N

  # ── 步骤3：自动检测总线号 ──────────────────────────────────────────
  bus = args.bus
  if bus is None:
    # 驱动刚绑定时给额外等待时间
    wait = 5.0 if driver_just_bound else 2.0
    bus = detect_ch347_bus(wait_secs=wait)
    if bus is None:
      cloudlog.error(
        "[sensord_ch347] Cannot find CH347 I2C bus after auto-setup.\n"
        "  Diagnostics:\n"
        "    lsmod | grep ch347\n"
        "    lsusb | grep 1a86\n"
        "    i2cdetect -l | grep ch347\n"
        "  If modules are missing, run: sudo bash system/sensord_ch347/ch347_setup.sh"
      )
      return
  else:
    cloudlog.info(f"[sensord_ch347] Using user-specified I2C bus {bus}")

  # ── 步骤4：确保设备权限正确 ───────────────────────────────────────
  if not ensure_i2c_accessible(bus):
    return

  cloudlog.info(f"[sensord_ch347] Starting LSM6DS3 daemon on I2C bus {bus} (/dev/i2c-{bus})")
  cloudlog.info(f"[sensord_ch347] accel={not args.no_accel}, gyro={not args.no_gyro}, temp={args.enable_temp}")

  # Build sensor list - all sensors use polling mode (interrupt=False)
  # because CH347 USB adapter does not wire the INT1 GPIO line
  sensors_cfg: list[tuple[Sensor, str]] = []

  if not args.no_accel:
    sensors_cfg.append((LSM6DS3_Accel(bus), "accelerometer"))
  if not args.no_gyro:
    sensors_cfg.append((LSM6DS3_Gyro(bus), "gyroscope"))
  if args.enable_temp:
    sensors_cfg.append((LSM6DS3_Temp(bus), "temperatureSensor"))

  if not sensors_cfg:
    cloudlog.error("[sensord_ch347] No sensors enabled, exiting")
    return

  # Reset all sensors before init (shared CTRL3_C register)
  for sensor, service in sensors_cfg:
    try:
      sensor.reset()
    except Exception:
      cloudlog.exception(f"[sensord_ch347] Error resetting sensor for {service}")

  # Initialize sensors and start polling threads
  exit_event = threading.Event()
  threads: list[threading.Thread] = []

  for sensor, service in sensors_cfg:
    try:
      sensor.init()
      cloudlog.info(f"[sensord_ch347] Initialized {service}")
      t = threading.Thread(
        target=polling_loop,
        args=(sensor, service, exit_event),
        daemon=True,
        name=f"poll_{service}",
      )
      threads.append(t)
    except Exception:
      cloudlog.exception(f"[sensord_ch347] Failed to initialize {service}")

  if not threads:
    cloudlog.error("[sensord_ch347] No sensors initialized successfully, exiting")
    return

  try:
    for t in threads:
      t.start()
    cloudlog.info(f"[sensord_ch347] {len(threads)} sensor thread(s) running")
    while any(t.is_alive() for t in threads):
      time.sleep(1)
  except KeyboardInterrupt:
    cloudlog.info("[sensord_ch347] Interrupted, shutting down")
  finally:
    exit_event.set()
    for t in threads:
      if t.is_alive():
        t.join(timeout=2.0)

    for sensor, service in sensors_cfg:
      try:
        sensor.shutdown()
      except Exception:
        cloudlog.exception(f"[sensord_ch347] Error shutting down {service}")

  cloudlog.info("[sensord_ch347] Daemon stopped")


if __name__ == "__main__":
  main()
