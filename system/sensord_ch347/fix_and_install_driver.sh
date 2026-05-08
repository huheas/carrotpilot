#!/bin/bash
# 修复 ch34x_mphsi_master 驱动以兼容 kernel 6.11

DRIVER_DIR="/data/soft/ch34x_mphsi_master_linux/driver"

echo "修复 ch34x_mphsi_master 驱动兼容性..."

# 备份原文件
cp ${DRIVER_DIR}/ch34x_mphsi_master_spi.c ${DRIVER_DIR}/ch34x_mphsi_master_spi.c.bak

# 修复 spi_master -> spi_controller
sed -i 's/spi_master_get_devdata/spi_controller_get_devdata/g' ${DRIVER_DIR}/ch34x_mphsi_master_spi.c
sed -i 's/spi_register_master/spi_register_controller/g' ${DRIVER_DIR}/ch34x_mphsi_master_spi.c
sed -i 's/spi_unregister_master/spi_unregister_controller/g' ${DRIVER_DIR}/ch34x_mphsi_master_spi.c
sed -i 's/spi_master_put/spi_controller_put/g' ${DRIVER_DIR}/ch34x_mphsi_master_spi.c
sed -i 's/SPI_MASTER_MUST_RX/SPI_CONTROLLER_MUST_RX/g' ${DRIVER_DIR}/ch34x_mphsi_master_spi.c
sed -i 's/SPI_MASTER_MUST_TX/SPI_CONTROLLER_MUST_TX/g' ${DRIVER_DIR}/ch34x_mphsi_master_spi.c

# 修复 spi->master -> spi->controller
sed -i 's/spi->master/spi->controller/g' ${DRIVER_DIR}/ch34x_mphsi_master_spi.c

# 修复 spi_alloc_master -> spi_alloc_controller
sed -i 's/spi_alloc_master/spi_alloc_controller/g' ${DRIVER_DIR}/ch34x_mphsi_master_spi.c

# 修复 struct spi_master -> struct spi_controller
sed -i 's/struct spi_master/struct spi_controller/g' ${DRIVER_DIR}/ch34x_mphsi_master_spi.c

# 修复 chip_select 数组访问（kernel 6.x 改为数组）
sed -i 's/spi->chip_select == 0/spi->chip_select[0] == 0/g' ${DRIVER_DIR}/ch34x_mphsi_master_spi.c
sed -i 's/spi->chip_select == 1/spi->chip_select[0] == 1/g' ${DRIVER_DIR}/ch34x_mphsi_master_spi.c
sed -i 's/spi->chip_select > /spi->chip_select[0] > /g' ${DRIVER_DIR}/ch34x_mphsi_master_spi.c

echo "修复完成！"
echo "正在重新编译..."

cd ${DRIVER_DIR}
make clean
make

if [ $? -eq 0 ]; then
    echo ""
    echo "✓ 编译成功！"
    echo ""
    echo "正在安装驱动..."
    sudo make install
    echo ""
    echo "正在加载驱动..."
    sudo rmmod ch34x_pis 2>/dev/null || true
    sudo rmmod ch34x_mphsi_master 2>/dev/null || true
    sudo insmod ch34x_mphsi_master.ko

    if [ $? -eq 0 ]; then
        echo "✓ 驱动加载成功！"
        echo ""
        echo "检查 I2C 总线..."
        sleep 2
        ls -la /dev/i2c-* 2>/dev/null | tail -5
        echo ""
        echo "检查 /sys/class/master/..."
        ls -la /sys/class/master/ 2>/dev/null || echo "（无 master 目录）"
    else
        echo "✗ 驱动加载失败"
    fi
else
    echo "✗ 编译失败"
fi
