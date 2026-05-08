#include <iostream>
#include <iomanip>
#include <csignal>
#include <cmath>
#include <thread>
#include <chrono>
#include <unistd.h>
#include <mutex>
#include "system/sensord_wt/sensors/wit_c_sdk.h"
#include "system/sensord_wt/sensors/serial.h"
#include "common/timing.h"

bool g_running = true;
std::mutex g_data_mutex;
int g_serial_fd = -1;

void signal_handler(int sig) {
  g_running = false;
}

void serial_write_callback(uint8_t* data, uint32_t len) {
  if (g_serial_fd >= 0) {
    serial_write_data(g_serial_fd, data, len);
  }
}

void reg_update_callback(uint32_t reg, uint32_t reg_num) {
}

void delay_ms_callback(uint16_t ms) {
  usleep(ms * 1000);
}

void print_separator() {
  std::cout << std::string(70, '-') << "\n";
}

int main(int argc, char* argv[]) {
  std::signal(SIGINT, signal_handler);

  std::string device = "/dev/ttyUSB0";
  int baud = 115200;

  if (argc > 1) device = argv[1];
  if (argc > 2) baud = std::stoi(argv[2]);

  std::cout << "\n";
  print_separator();
  std::cout << "WT加速度计轴映射验证工具\n";
  std::cout << "设备: " << device << " 波特率: " << baud << "\n";
  print_separator();

  g_serial_fd = serial_open(device.c_str(), baud);
  if (g_serial_fd < 0) {
    std::cerr << "无法打开串口设备: " << device << "\n";
    return 1;
  }

  WitInit(WIT_PROTOCOL_JY61, 0x50);
  WitSerialWriteRegister(serial_write_callback);
  WitRegisterCallBack(reg_update_callback);
  WitDelayMsRegister(delay_ms_callback);

  std::cout << "\n正在连接WT传感器...\n";

  std::this_thread::sleep_for(std::chrono::milliseconds(500));

  unsigned char buffer[256];
  for (int i = 0; i < 10; ++i) {
    int len = serial_read_data(g_serial_fd, buffer, sizeof(buffer));
    if (len > 0) {
      for (int j = 0; j < len; j++) {
        WitSerialDataIn(buffer[j]);
      }
    }
    std::this_thread::sleep_for(std::chrono::milliseconds(100));
  }

  std::cout << "\n采集加速度计数据中...\n";
  std::cout << "注意: 车辆应保持静止状态进行测试\n";
  std::cout << "预期结果: 重力应该只出现在一个轴上 (~9.8 m/s²)\n\n";

  print_separator();

  double sum_raw[3] = {0, 0, 0};
  double sum_mapped[3] = {0, 0, 0};
  int sample_count = 0;
  const int required_samples = 100;

  while (g_running && sample_count < required_samples) {
    int len = serial_read_data(g_serial_fd, buffer, sizeof(buffer));
    if (len > 0) {
      for (int j = 0; j < len; j++) {
        WitSerialDataIn(buffer[j]);
      }
    }

    {
      std::lock_guard<std::mutex> lock(g_data_mutex);

      int16_t raw_ax = sReg[AX];
      int16_t raw_ay = sReg[AY];
      int16_t raw_az = sReg[AZ];

      if (raw_ax != 0 || raw_ay != 0 || raw_az != 0) {
        double ax = (double)raw_ax / 32768.0 * 16.0 * 9.8;
        double ay = (double)raw_ay / 32768.0 * 16.0 * 9.8;
        double az = (double)raw_az / 32768.0 * 16.0 * 9.8;

        double v0 = az;
        double v1 = ax;
        double v2 = ay;

        double meas0 = -v2;
        double meas1 = -v1;
        double meas2 = -v0;

        sum_raw[0] += ax;
        sum_raw[1] += ay;
        sum_raw[2] += az;
        sum_mapped[0] += meas0;
        sum_mapped[1] += meas1;
        sum_mapped[2] += meas2;
        sample_count++;

        if (sample_count <= 5) {
          std::cout << "样本 " << sample_count << ": "
                    << "RAW[ax=" << std::fixed << std::setprecision(3) << ax
                    << ", ay=" << ay << ", az=" << az << "] -> "
                    << "meas[0]=" << meas0 << ", meas[1]=" << meas1
                    << ", meas[2]=" << meas2 << "\n";
        }
      }
    }

    std::this_thread::sleep_for(std::chrono::milliseconds(20));
  }

  serial_close(g_serial_fd);

  if (sample_count == 0) {
    std::cerr << "\n没有采集到数据，请检查传感器连接\n";
    return 1;
  }

  double mean_raw[3] = {sum_raw[0] / sample_count, sum_raw[1] / sample_count, sum_raw[2] / sample_count};
  double mean_meas[3] = {sum_mapped[0] / sample_count, sum_mapped[1] / sample_count, sum_mapped[2] / sample_count};

  print_separator();
  std::cout << "\n采集完成: " << sample_count << " 个样本\n\n";

  std::cout << "【原始数据 - wt_accel.cc中的v[]数组】\n";
  std::cout << "  v[0] (WT Y轴): " << std::fixed << std::setprecision(4) << mean_raw[0] << " m/s²\n";
  std::cout << "  v[1] (WT X轴): " << mean_raw[1] << " m/s²\n";
  std::cout << "  v[2] (WT Z轴): " << mean_raw[2] << " m/s²\n";

  std::cout << "\n【locationd转换后 - meas数组】\n";
  std::cout << "  meas[0] (纵向X): " << mean_meas[0] << " m/s²\n";
  std::cout << "  meas[1] (横向Y): " << mean_meas[1] << " m/s²\n";
  std::cout << "  meas[2] (垂直Z): " << mean_meas[2] << " m/s²\n";

  print_separator();
  std::cout << "\n【验证结果】\n";

  double gravity = 9.81;
  double tolerance = 1.0;

  bool meas_z_correct = std::abs(std::abs(mean_meas[2]) - gravity) < tolerance;
  bool meas_x_correct = std::abs(mean_meas[0]) < 1.0;
  bool meas_y_correct = std::abs(mean_meas[1]) < 1.0;

  std::cout << "预期: 重力应该在 Z轴 (~" << (mean_meas[2] < 0 ? "-" : "+") << gravity << " m/s²)\n";
  std::cout << "     X和Y轴应该接近 0\n\n";

  if (meas_z_correct && meas_x_correct && meas_y_correct) {
    std::cout << "✅ 映射正确!\n";
    std::cout << "   - Z轴(重力): " << mean_meas[2] << " m/s² (预期 ~-" << gravity << " 或 ~+" << gravity << ")\n";
    std::cout << "   - X轴(纵向): " << mean_meas[0] << " m/s² (预期 ~0)\n";
    std::cout << "   - Y轴(横向): " << mean_meas[1] << " m/s² (预期 ~0)\n";
  } else {
    std::cout << "❌ 映射可能有问题:\n";
    if (!meas_z_correct)
      std::cout << "   - Z轴(重力): " << mean_meas[2] << " m/s² (预期 ~-" << gravity << " 或 ~+" << gravity << ")\n";
    if (!meas_x_correct)
      std::cout << "   - X轴(纵向): " << mean_meas[0] << " m/s² (预期 ~0)\n";
    if (!meas_y_correct)
      std::cout << "   - Y轴(横向): " << mean_meas[1] << " m/s² (预期 ~0)\n";
  }

  print_separator();

  return (meas_z_correct && meas_x_correct && meas_y_correct) ? 0 : 1;
}
