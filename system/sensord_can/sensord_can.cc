#include <sys/resource.h>
#include <chrono>
#include <thread>
#include <vector>
#include <map>
#include <poll.h>
#include <getopt.h>
#include <fstream>
#include <iomanip>

#include "cereal/services.h"
#include "cereal/messaging/messaging.h"
#include "common/ratekeeper.h"
#include "common/swaglog.h"
#include "common/timing.h"
#include "common/util.h"
#include "system/sensord_can/sensors/universal_can_sensor.h"

ExitHandler do_exit;

// PC环境通用CAN传感器配置参数结构
struct SensordCANConfig {
  bool enable_yaw = true;
  bool enable_accel = true;
  bool verbose = false;
  bool enable_file_logging = true;  // 默认启用
  std::string log_file_path = "/data/debug/sensord_can_data.csv";
};

void print_usage(const char* prog_name) {
  printf("Usage: %s [OPTIONS]\n", prog_name);
  printf("Universal CAN Sensor Daemon (from carState)\n");
  printf("Options:\n");
  printf("  -y, --no-yaw          Disable yaw rate sensor\n");
  printf("  -a, --no-accel        Disable acceleration sensor\n");
  printf("  -v, --verbose         Verbose output\n");
  printf("  -h, --help            Show this help\n");
  printf("\nExample:\n");
  printf("  %s --no-yaw\n", prog_name);
}

SensordCANConfig parse_args(int argc, char* argv[]) {
  SensordCANConfig config;

  static struct option long_options[] = {
    {"no-yaw",        no_argument,       0, 'y'},
    {"no-accel",      no_argument,       0, 'a'},
    {"verbose",       no_argument,       0, 'v'},
    {"help",          no_argument,       0, 'h'},
    {0, 0, 0, 0}
  };

  int c;
  while ((c = getopt_long(argc, argv, "yavh", long_options, nullptr)) != -1) {
    switch (c) {
      case 'y':
        config.enable_yaw = false;
        break;
      case 'a':
        config.enable_accel = false;
        break;
      case 'v':
        config.verbose = true;
        break;
      case 'h':
        print_usage(argv[0]);
        exit(0);
      default:
        print_usage(argv[0]);
        exit(1);
    }
  }

  return config;
}

template<typename T>
void polling_loop(T *sensor, const std::string& msg_name) {
  PubMaster pm({msg_name.c_str()});
  RateKeeper rk("sensord_can", 100);

  LOGD("Starting polling loop for %s", msg_name.c_str());

  while (!do_exit) {
    MessageBuilder msg;
    if (sensor->get_event(msg)) {
      pm.send(msg_name.c_str(), msg);
    }
    rk.keepTime();
  }

  LOGD("Stopped polling loop for %s", msg_name.c_str());
}

int sensor_loop(const SensordCANConfig& config) {
  LOGD("Initializing Universal CAN sensors (from carState):");
  LOGD("  YAW_RATE enabled: %s", config.enable_yaw ? "yes" : "no");
  LOGD("  ACCEL enabled: %s", config.enable_accel ? "yes" : "no");

  // 传感器初始化
  std::vector<std::pair<UniversalYawSensor*, std::string>> yaw_sensors;
  std::vector<std::pair<UniversalAccelSensor*, std::string>> accel_sensors;
  std::vector<std::thread> threads;

  // 根据配置初始化偏航率传感器
  if (config.enable_yaw) {
    auto yaw_sensor = new UniversalYawSensor();
    if (yaw_sensor->init() >= 0) {
      yaw_sensors.emplace_back(yaw_sensor, "gyroscope");
      threads.emplace_back(polling_loop<UniversalYawSensor>, yaw_sensor, std::string("gyroscope"));
      LOGD("Successfully initialized yaw sensor");
    } else {
      LOGE("Failed to initialize yaw sensor");
      delete yaw_sensor;
    }
  }

  // 根据配置初始化加速度传感器
  if (config.enable_accel) {
    auto accel_sensor = new UniversalAccelSensor();
    if (accel_sensor->init() >= 0) {
      accel_sensors.emplace_back(accel_sensor, "accelerometer");
      threads.emplace_back(polling_loop<UniversalAccelSensor>, accel_sensor, std::string("accelerometer"));
      LOGD("Successfully initialized acceleration sensor");
    } else {
      LOGE("Failed to initialize acceleration sensor");
      delete accel_sensor;
    }
  }

  // 检查是否有传感器被初始化
  if (threads.empty()) {
    LOGE("No sensors enabled or initialized successfully");
    return -1;
  }

  LOGD("Successfully initialized %zu sensors", threads.size());

  // 提高进程优先级
  setpriority(PRIO_PROCESS, 0, -18);

  LOGD("Universal CAN sensor daemon (from carState) is running... Press Ctrl+C to stop");

  // 等待所有线程结束
  for (auto &t : threads) {
    t.join();
  }

  // 清理资源
  for (auto &[sensor, msg_name] : yaw_sensors) {
    sensor->shutdown();
    delete sensor;
  }
  for (auto &[sensor, msg_name] : accel_sensors) {
    sensor->shutdown();
    delete sensor;
  }

  LOGD("Universal CAN sensor daemon stopped");
  return 0;
}

int main(int argc, char *argv[]) {
  // 解析命令行参数
  SensordCANConfig config = parse_args(argc, argv);

  // 设置日志级别
  if (config.verbose) {
    setenv("LOGPRINT", "debug", 1);
  }

  // 显示启动信息
  LOGD("Starting Universal CAN Sensor Daemon (from carState)");
  LOGD("Version: 2.0.0");

  // 运行传感器循环
  int result = sensor_loop(config);

  if (result == 0) {
    LOGD("Universal CAN sensor daemon exited successfully");
  } else {
    LOGE("Universal CAN sensor daemon exited with error: %d", result);
  }

  return result;
}