#pragma once

#include "cereal/messaging/messaging.h"
#include <string>
#include <cstdint>

class UniversalYawSensor {
public:
  UniversalYawSensor();
  ~UniversalYawSensor();

  int init();
  bool get_event(MessageBuilder &msg, uint64_t ts = 0);
  int shutdown();

private:
  SubMaster sm;

  struct YawRateData {
    double yaw_rate = 0.0;
    double pitch_rate = 0.0;
    double roll_rate = 0.0;
    uint64_t timestamp = 0;
    bool valid = false;
  } current_data;

  // 用于从加速度变化率估算 pitch/roll rate 的历史数据
  double prev_aEgo = 0.0;
  double prev_aEgoY = 0.0;
  uint64_t prev_ts = 0;
  double filtered_pitch_rate = 0.0;
  double filtered_roll_rate = 0.0;
  bool has_prev = false;

  bool is_vehicle_supported();
  bool update_from_carstate();
};

class UniversalAccelSensor {
public:
  UniversalAccelSensor();
  ~UniversalAccelSensor();

  int init();
  bool get_event(MessageBuilder &msg, uint64_t ts = 0);
  int shutdown();

private:
  SubMaster sm;

  struct AccelData {
    double longitudinal_accel = 0.0;
    double lateral_accel = 0.0;
    uint64_t timestamp = 0;
    bool valid = false;
  } current_data;

  bool is_vehicle_supported();
  bool update_from_carstate();
};