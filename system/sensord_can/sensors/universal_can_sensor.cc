#include "system/sensord_can/sensors/universal_can_sensor.h"
#include "cereal/gen/cpp/log.capnp.h"
#include "common/timing.h"
#include <algorithm>
#include <cmath>
#include "common/swaglog.h"
#include "system/sensord/sensors/constants.h"
#include "common/util.h"

// =============================================================================
// 通用偏航率传感器实现
// =============================================================================

UniversalYawSensor::UniversalYawSensor()
    : sm({"carState"}) {
}

UniversalYawSensor::~UniversalYawSensor() {
  shutdown();
}

bool UniversalYawSensor::is_vehicle_supported() {
  return true;
}

bool UniversalYawSensor::update_from_carstate() {
  sm.update(0);

  if (!sm.updated("carState")) {
    return false;
  }

  auto car_state = sm["carState"].getCarState();

  current_data.yaw_rate = car_state.getYawRate();
  current_data.timestamp = nanos_since_boot();

  // 检查偏航率数据是否合理（不是NaN或无穷大）
  if (std::isnan(current_data.yaw_rate) || std::isinf(current_data.yaw_rate)) {
    current_data.valid = false;
    return false;
  }

  // --- 从加速度变化率估算 pitch/roll rate（补全3轴陀螺仪数据） ---
  // carState 提供纵向加速度(aEgo)和横向加速度(aEgoY)，来自CAN总线ESC模块。
  // 利用加速度的时间变化率(jerk)和车辆悬挂动力学关系估算车体俯仰/横滚角速度。
  // 比例系数 K 表示"单位jerk引起的角速度"，取决于悬挂刚度和重心高度。
  double aEgo = car_state.getAEgo();
  double aEgoY = car_state.getAEgoY();

  if (std::isnan(aEgo) || std::isinf(aEgo)) aEgo = 0.0;
  if (std::isnan(aEgoY) || std::isinf(aEgoY)) aEgoY = 0.0;

  if (has_prev && prev_ts > 0) {
    double dt = (current_data.timestamp - prev_ts) * 1e-9;
    if (dt > 0.001 && dt < 0.1) {
      // 典型乘用车悬挂动力学比例系数:
      //   制动jerk 10 m/s³ → 约产生 0.02 rad/s 俯仰角速度 → K ≈ 0.002
      //   转向jerk 10 m/s³ → 约产生 0.015 rad/s 横滚角速度 → K ≈ 0.0015
      constexpr double K_PITCH = 0.002;
      constexpr double K_ROLL = 0.0015;

      double long_jerk = (aEgo - prev_aEgo) / dt;
      double lat_jerk = (aEgoY - prev_aEgoY) / dt;

      // jerk → 角速度: 减速(负jerk)→车头下俯(负pitch_rate)
      double raw_pitch_rate = -K_PITCH * long_jerk;
      // 左转(正lat_accel增大)→车体右倾(正roll_rate)
      double raw_roll_rate = K_ROLL * lat_jerk;

      // 一阶低通滤波（alpha=0.15, 截止频率≈2.4Hz @100Hz采样）
      constexpr double ALPHA = 0.15;
      filtered_pitch_rate = ALPHA * raw_pitch_rate + (1.0 - ALPHA) * filtered_pitch_rate;
      filtered_roll_rate = ALPHA * raw_roll_rate + (1.0 - ALPHA) * filtered_roll_rate;

      // 限幅: 乘用车 pitch/roll rate 正常范围 ±0.1 rad/s
      constexpr double MAX_RATE = 0.1;
      current_data.pitch_rate = std::clamp(filtered_pitch_rate, -MAX_RATE, MAX_RATE);
      current_data.roll_rate = std::clamp(filtered_roll_rate, -MAX_RATE, MAX_RATE);
    }
  }

  prev_aEgo = aEgo;
  prev_aEgoY = aEgoY;
  prev_ts = current_data.timestamp;
  has_prev = true;

  current_data.valid = true;
  return true;
}

int UniversalYawSensor::init() {
  LOGD("Initializing Universal Yaw Rate sensor (from carState)");

  // 等待carState数据可用，最多重试10次
  int retry_count = 0;
  while (retry_count < 10) {
    sm.update(100);
    if (sm.updated("carState")) {
      auto car_state = sm["carState"].getCarState();
      // 检查是否有有效的偏航率数据
      if (std::abs(car_state.getYawRate()) > 0.001 || retry_count > 5) {
        LOGD("Universal Yaw Rate sensor initialized successfully");
        return 0;
      }
    }
    retry_count++;
    util::sleep_for(200);
  }

  // 即使没有检测到数据，也允许初始化，在运行时检查数据有效性
  LOGW("No yaw rate data detected, but allowing initialization");
  return 0;
}

bool UniversalYawSensor::get_event(MessageBuilder &msg, uint64_t ts) {
  if (!update_from_carstate()) {
    return false;
  }

  if (!current_data.valid) {
    return false;
  }

  // 构建传感器消息
  auto event = msg.initEvent().initGyroscope();
  event.setSource(cereal::SensorEventData::SensorSource::ANDROID);
  event.setVersion(1);
  event.setSensor(SENSOR_GYRO_UNCALIBRATED);
  event.setType(SENSOR_TYPE_GYROSCOPE_UNCALIBRATED);
  event.setTimestamp(ts == 0 ? nanos_monotonic() : ts);

  auto gyro = event.initGyroUncalibrated();
  gyro.setV({{(float)(current_data.yaw_rate),
              (float)(current_data.pitch_rate),
              (float)(current_data.roll_rate)}});
  gyro.setStatus(true);

  return true;
}

int UniversalYawSensor::shutdown() {
  LOGD("Shutting down Universal Yaw Rate sensor");
  current_data.valid = false;
  return 0;
}

// =============================================================================
// 通用加速度传感器实现
// =============================================================================

UniversalAccelSensor::UniversalAccelSensor()
    : sm({"carState"}) {
}

UniversalAccelSensor::~UniversalAccelSensor() {
  shutdown();
}

bool UniversalAccelSensor::is_vehicle_supported() {
  return true;
}

bool UniversalAccelSensor::update_from_carstate() {
  sm.update(0);

  if (!sm.updated("carState")) {
    return false;
  }

  auto car_state = sm["carState"].getCarState();

  current_data.longitudinal_accel = car_state.getAEgo();    // X轴
  current_data.lateral_accel = car_state.getAEgoY();        // Y轴
  current_data.timestamp = nanos_since_boot();
  current_data.valid = true;

  // 检查数据是否合理（不是NaN或无穷大）
  if (std::isnan(current_data.longitudinal_accel) || std::isinf(current_data.longitudinal_accel) ||
      std::isnan(current_data.lateral_accel) || std::isinf(current_data.lateral_accel)) {
    current_data.valid = false;
    return false;
  }

  return true;
}

int UniversalAccelSensor::init() {
  LOGD("Initializing Universal Acceleration sensor (from carState) with 3-axis support");

  int retry_count = 0;
  while (retry_count < 10) {
    sm.update(100);
    if (sm.updated("carState")) {
      auto car_state = sm["carState"].getCarState();
      // 检查纵向或横向加速度是否有有效数据
      if (std::abs(car_state.getAEgo()) > 0.001 ||
          std::abs(car_state.getAEgoY()) > 0.001 ||
          retry_count > 5) {
        LOGD("Universal Acceleration sensor (3-axis) initialized successfully");
        return 0;
      }
    }
    retry_count++;
    util::sleep_for(200);
  }

  LOGW("No acceleration data detected, but allowing initialization");
  return 0;
}

bool UniversalAccelSensor::get_event(MessageBuilder &msg, uint64_t ts) {
  if (!update_from_carstate()) {
    return false;
  }

  if (!current_data.valid) {
    return false;
  }

  auto event = msg.initEvent().initAccelerometer();
  event.setSource(cereal::SensorEventData::SensorSource::ANDROID);
  event.setVersion(1);
  event.setSensor(SENSOR_ACCELEROMETER);
  event.setType(SENSOR_TYPE_ACCELEROMETER);
  event.setTimestamp(ts == 0 ? nanos_monotonic() : ts);

  auto accel = event.initAcceleration();
  // locationd transforms: meas = [-v[2], -v[1], -v[0]]
  // v[0] → meas[2] (Z-vertical) = -v[0] → gravity should be positive 9.81
  // v[1] → meas[1] (Y-lateral) = -v[1] → v[1] = -lateral_accel
  // v[2] → meas[0] (X-longitudinal) = -v[2] → v[2] = -longitudinal_accel
  accel.setV({{9.81f, (float)(-current_data.lateral_accel), (float)(-current_data.longitudinal_accel)}});
  accel.setStatus(true);

  return true;
}

int UniversalAccelSensor::shutdown() {
  LOGD("Shutting down Universal Acceleration sensor");
  current_data.valid = false;
  return 0;
}
