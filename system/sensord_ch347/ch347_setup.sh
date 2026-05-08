#!/bin/bash
# ch347_setup.sh - 一键配置 CH347 USB-to-I2C 环境
# 功能：安装 udev 规则、用户加组、模块开机自动加载
# 用法：sudo bash system/sensord_ch347/ch347_setup.sh
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UDEV_RULE="/etc/udev/rules.d/99-ch347-i2c.rules"
MODULES_CONF="/etc/modules-load.d/ch347.conf"
SUDOERS_FILE="/etc/sudoers.d/sensord_ch347"

# 颜色输出
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()  { echo -e "${GREEN}[OK]${NC} $*"; }
warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
error() { echo -e "${RED}[ERR]${NC} $*"; }

if [ "$(id -u)" -ne 0 ]; then
  error "请以 root 运行: sudo bash $0"
  exit 1
fi

CURRENT_USER="${SUDO_USER:-$(logname 2>/dev/null || echo ubuntu)}"
info "配置用户: $CURRENT_USER"

# ── 1. 安装 udev 规则 ───────────────────────────────────────────────
echo ">>> 安装 udev 规则..."
cat > "$UDEV_RULE" << 'EOF'
# CH347 USB-to-I2C/SPI/GPIO adapter - allow i2c group access
SUBSYSTEM=="i2c-dev", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="55db", MODE="0660", GROUP="i2c"
SUBSYSTEM=="i2c-dev", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="55da", MODE="0660", GROUP="i2c"
SUBSYSTEM=="i2c-dev", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="55d9", MODE="0660", GROUP="i2c"
# Also bind ch347 driver when device is plugged in
ACTION=="add", SUBSYSTEM=="usb", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="55db", RUN+="/usr/local/bin/ch347-bind.sh"
ACTION=="add", SUBSYSTEM=="usb", ATTRS{idVendor}=="1a86", ATTRS{idProduct}=="55da", RUN+="/usr/local/bin/ch347-bind.sh"
EOF
chmod 644 "$UDEV_RULE"
info "udev 规则已写入: $UDEV_RULE"

# ── 2. 创建驱动绑定辅助脚本 ────────────────────────────────────────
cat > /usr/local/bin/ch347-bind.sh << 'BIND_EOF'
#!/bin/bash
# 等待接口注册后绑定 ch347 驱动
sleep 1
for intf in /sys/bus/usb/devices/${DEVPATH##*/}:*/; do
    intf_name=$(basename "$intf")
    driver_link="$intf/driver"
    if [ ! -e "$driver_link" ]; then
        echo "$intf_name" > /sys/bus/usb/drivers/ch347/bind 2>/dev/null || true
    fi
done
# 等待 i2c 设备注册后修复权限
sleep 1
for i2c_dev in /dev/i2c-*; do
    name_file="/sys/class/i2c-adapter/$(basename $i2c_dev)/name"
    if [ -f "$name_file" ] && grep -qi "ch347" "$name_file" 2>/dev/null; then
        chmod 660 "$i2c_dev" 2>/dev/null || true
        chown root:i2c "$i2c_dev" 2>/dev/null || true
    fi
done
BIND_EOF
chmod +x /usr/local/bin/ch347-bind.sh
info "驱动绑定辅助脚本: /usr/local/bin/ch347-bind.sh"

# ── 3. 将用户加入 i2c 组 ───────────────────────────────────────────
echo ">>> 将 $CURRENT_USER 加入 i2c 组..."
if ! getent group i2c > /dev/null 2>&1; then
  groupadd i2c
  info "创建 i2c 组"
fi
if id -nG "$CURRENT_USER" | grep -qw i2c; then
  info "$CURRENT_USER 已在 i2c 组"
else
  usermod -aG i2c "$CURRENT_USER"
  info "$CURRENT_USER 已加入 i2c 组（需重新登录生效）"
fi

# ── 4. 配置内核模块开机自动加载 ───────────────────────────────────
echo ">>> 配置模块自动加载..."
cat > "$MODULES_CONF" << 'EOF'
# CH347 USB multi-function adapter modules
mfd_ch347
i2c_ch347
gpio_ch347
spi_ch347
EOF
info "模块自动加载已配置: $MODULES_CONF"

# ── 5. 配置 sudo 免密权限（sensord_ch347 使用）────────────────────
echo ">>> 配置 sudo 免密权限..."
cat > "$SUDOERS_FILE" << EOF
# Allow sensord_ch347 to bind CH347 driver and fix i2c permissions without password
$CURRENT_USER ALL=(root) NOPASSWD: /usr/bin/tee /sys/bus/usb/drivers/ch347/bind
$CURRENT_USER ALL=(root) NOPASSWD: /bin/chmod 666 /dev/i2c-*
$CURRENT_USER ALL=(root) NOPASSWD: /usr/bin/tee /etc/udev/rules.d/99-ch347-i2c.rules
$CURRENT_USER ALL=(root) NOPASSWD: /sbin/udevadm control --reload-rules
$CURRENT_USER ALL=(root) NOPASSWD: /sbin/udevadm trigger *
$CURRENT_USER ALL=(root) NOPASSWD: /sbin/udevadm settle
$CURRENT_USER ALL=(root) NOPASSWD: /sbin/modprobe mfd_ch347
$CURRENT_USER ALL=(root) NOPASSWD: /sbin/modprobe i2c_ch347
$CURRENT_USER ALL=(root) NOPASSWD: /sbin/modprobe gpio_ch347
$CURRENT_USER ALL=(root) NOPASSWD: /sbin/modprobe spi_ch347
EOF
chmod 440 "$SUDOERS_FILE"
# 验证 sudoers 语法
if visudo -c -f "$SUDOERS_FILE" 2>/dev/null; then
  info "sudo 免密规则已安装: $SUDOERS_FILE"
else
  warn "sudoers 语法验证失败，已删除"
  rm -f "$SUDOERS_FILE"
fi

# ── 6. 立即重载 udev 并应用 ────────────────────────────────────────
echo ">>> 重载 udev 规则..."
udevadm control --reload-rules
udevadm trigger --subsystem-match=usb --action=add
udevadm settle
info "udev 规则已重载"

# ── 7. 立即修复当前 CH347 I2C 设备权限 ────────────────────────────
echo ">>> 修复当前 I2C 设备权限..."
FIXED=0
for name_file in /sys/class/i2c-adapter/*/name; do
  if grep -qi "ch347" "$name_file" 2>/dev/null; then
    bus_dir=$(dirname "$name_file")
    bus_name=$(basename "$bus_dir")
    dev="/dev/${bus_name}"
    if [ -e "$dev" ]; then
      chmod 660 "$dev"
      chown root:i2c "$dev"
      info "已修复权限: $dev"
      FIXED=1
    fi
  fi
done
if [ "$FIXED" -eq 0 ]; then
  warn "当前无 CH347 I2C 设备（插入 CH347 后将自动配置）"
fi

# ── 完成 ──────────────────────────────────────────────────────────
echo ""
echo "======================================================"
info "CH347 环境配置完成！"
echo "======================================================"
echo "  下次插入 CH347 时将自动："
echo "    - 绑定驱动（ch347-bind.sh via udev）"
echo "    - 设置 /dev/i2c-N 权限为 660（i2c 组可读写）"
echo ""
echo "  sensord_ch347 将自动完成以下操作（无需手动）："
echo "    - 加载内核模块"
echo "    - 绑定 USB 接口到驱动"
echo "    - 检测 I2C 总线号"
echo "    - 修复设备权限"
echo ""
if id -nG "$CURRENT_USER" | grep -qw i2c; then
  echo "  用户已在 i2c 组，权限立即生效"
else
  echo "  ⚠ 请重新登录以使 i2c 组权限生效"
fi
