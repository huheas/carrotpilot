#!/bin/bash
# 完整修复 ch34x_mphsi_master 驱动

DRIVER_DIR="/data/soft/ch34x_mphsi_master_linux/driver"

echo "=== 修复 ch34x_mphsi_master 驱动兼容性 ==="
echo ""

# 备份原文件
cp ${DRIVER_DIR}/ch34x_mphsi.h ${DRIVER_DIR}/ch34x_mphsi.h.bak
cp ${DRIVER_DIR}/ch34x_mphsi_master_spi.c ${DRIVER_DIR}/ch34x_mphsi_master_spi.c.bak2

echo "1. 修复头文件 ch34x_mphsi.h..."
# 在头文件开头添加兼容性定义
sed -i '1i\
/* Kernel 6.x compatibility: spi_master renamed to spi_controller */\
#if LINUX_VERSION_CODE >= KERNEL_VERSION(6,0,0)\
#define spi_master spi_controller\
#define spi_alloc_master spi_alloc_controller\
#define spi_master_get_devdata spi_controller_get_devdata\
#define spi_register_master spi_register_controller\
#define spi_unregister_master spi_unregister_controller\
#define spi_master_put spi_controller_put\
#define SPI_MASTER_MUST_RX SPI_CONTROLLER_MUST_RX\
#define SPI_MASTER_MUST_TX SPI_CONTROLLER_MUST_TX\
#endif\
' ${DRIVER_DIR}/ch34x_mphsi.h

# 还需要包含 linux/version.h
sed -i '1i\
#include <linux/version.h>' ${DRIVER_DIR}/ch34x_mphsi.h

echo "2. 修复 chip_select 数组访问..."
# 修复所有 chip_select 的使用
sed -i 's/spi->chip_select == 0/spi->chip_select\[0\] == 0/g' ${DRIVER_DIR}/ch34x_mphsi_master_spi.c
sed -i 's/spi->chip_select == 1/spi->chip_select\[0\] == 1/g' ${DRIVER_DIR}/ch34x_mphsi_master_spi.c
sed -i 's/(spi->chip_select >/(spi->chip_select\[0\] >/g' ${DRIVER_DIR}/ch34x_mphsi_master_spi.c
sed -i 's/(1 << spi->chip_select)/(1 << spi->chip_select\[0\])/g' ${DRIVER_DIR}/ch34x_mphsi_master_spi.c

echo "3. 重新编译..."
cd ${DRIVER_DIR}
make clean
make 2>&1 | tail -50

if [ ${PIPESTATUS[1]} -eq 0 ]; then
    echo ""
    echo "✓ 编译成功！"
    echo ""
    echo "4. 安装驱动..."
    sudo make install

    echo ""
    echo "5. 加载驱动..."
    sudo rmmod ch34x_pis 2>/dev/null || echo "  (ch34x_pis 未加载)"
    sudo rmmod ch34x_mphsi_master 2>/dev/null || echo "  (ch34x_mphsi_master 未加载)"
    sudo insmod ch34x_mphsi_master.ko

    if [ $? -eq 0 ]; then
        echo "✓ 驱动加载成功！"
        echo ""
        echo "6. 检查设备..."
        sleep 2
        echo ""
        echo "I2C 总线:"
        ls /dev/i2c-* 2>/dev/null || echo "  (无)"
        echo ""
        echo "Master 设备:"
        ls /sys/class/master/ 2>/dev/null || echo "  (无)"
    else
        echo "✗ 驱动加载失败"
        dmesg | tail -20
    fi
else
    echo ""
    echo "✗ 编译失败"
    echo ""
    echo "查看完整错误信息："
    make 2>&1 | grep "error:"
fi
