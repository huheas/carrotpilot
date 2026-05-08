#pragma once

#include "cereal/messaging/messaging.h"
#include "common/swaglog.h"
#include <cstdint>

/**
 * CAN传感器基类
 * 提供标准的传感器接口，用于从CAN总线接收数据并转换为传感器数据
 */
class CANSensor {
public:
  CANSensor(const std::string& can_device, uint32_t can_id, const std::string& name);
  virtual ~CANSensor() = default;

  // 传感器基本操作
  virtual int init() = 0;
  virtual bool get_event(MessageBuilder &msg, uint64_t ts = 0) = 0;
  virtual bool has_interrupt_enabled() = 0;
  virtual int shutdown() = 0;

  // 数据有效性检查
  virtual bool is_data_valid(uint64_t ts) {
    return (ts - last_read_time) < max_read_time_diff;
  }

  // 获取传感器信息
  std::string get_name() const { return sensor_name; }
  uint32_t get_can_id() const { return can_msg_id; }
  std::string get_can_device() const { return can_device_name; }

protected:
  std::string can_device_name;  // CAN设备名称 (e.g., "can0")
  uint32_t can_msg_id;          // CAN消息ID
  std::string sensor_name;      // 传感器名称

  // 数据时效性控制
  uint64_t last_read_time = 0;
  uint64_t max_read_time_diff = 100000000ULL; // 100ms 超时

  // CAN原始数据解析
  virtual bool parse_can_data(const uint8_t* data, size_t len) = 0;

  // 工具函数
  uint16_t extract_signal_16(const uint8_t* data, int start_bit, int length, bool is_signed = false);
  uint32_t extract_signal_32(const uint8_t* data, int start_bit, int length, bool is_signed = false);
  double apply_scaling(uint32_t raw_value, double scale, double offset);
};