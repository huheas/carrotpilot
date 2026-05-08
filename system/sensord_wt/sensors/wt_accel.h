#pragma once

#include "cereal/messaging/messaging.h"
#include <string>
#include <cstdint>

class WT_Accel {
private:
  bool enabled = true;  // 默认启用
  double last_accel_x = 0.0;
  double last_accel_y = 0.0;
  double last_accel_z = 0.0;
  uint64_t last_update_ts = 0;

public:
  WT_Accel(const std::string& device = "/dev/ttyUSB0",
           int baud = 115200);

  // 移除 virtual 和 override，因为不再继承基类
  bool get_event(MessageBuilder &msg, uint64_t ts = 0);

  // 添加传感器管理方法
  int init() { enabled = true; return 0; }
  int shutdown() { enabled = false; return 0; }
  bool is_data_valid(uint64_t current_ts) { return enabled; }

  // 获取最近一次的原始值（供 verbose 打印使用）
  void get_last_values(double &ax, double &ay, double &az) const {
    ax = last_accel_x; ay = last_accel_y; az = last_accel_z;
  }

protected:
  void update_accel_data();
};