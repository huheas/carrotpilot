#include "system/sensord_can/sensors/can_sensor.h"
#include "common/timing.h"
#include <cstring>

CANSensor::CANSensor(const std::string& can_device, uint32_t can_id, const std::string& name)
    : can_device_name(can_device), can_msg_id(can_id), sensor_name(name) {
  LOGD("Creating CAN sensor '%s' for device %s, CAN ID: 0x%03X",
       name.c_str(), can_device.c_str(), can_id);
}

uint16_t CANSensor::extract_signal_16(const uint8_t* data, int start_bit, int length, bool is_signed) {

  uint16_t raw_value = 0;

  // 处理跨字节的信号
  for (int i = 0; i < length; i++) {
    int current_byte = (start_bit + i) / 8;
    int current_bit = (start_bit + i) % 8;

    if (current_byte < 8) { // 确保不越界
      if (data[current_byte] & (1 << (7 - current_bit))) {
        raw_value |= (1 << (length - 1 - i));
      }
    }
  }

  // 处理有符号数
  if (is_signed && (raw_value & (1 << (length - 1)))) {
    raw_value |= (0xFFFF << length); // 符号扩展
  }

  return raw_value;
}

uint32_t CANSensor::extract_signal_32(const uint8_t* data, int start_bit, int length, bool is_signed) {

  uint32_t raw_value = 0;

  // 处理跨字节的信号
  for (int i = 0; i < length; i++) {
    int current_byte = (start_bit + i) / 8;
    int current_bit = (start_bit + i) % 8;

    if (current_byte < 8) { // 确保不越界
      if (data[current_byte] & (1 << (7 - current_bit))) {
        raw_value |= (1 << (length - 1 - i));
      }
    }
  }

  // 处理有符号数
  if (is_signed && (raw_value & (1 << (length - 1)))) {
    raw_value |= (0xFFFFFFFF << length); // 符号扩展
  }

  return raw_value;
}

double CANSensor::apply_scaling(uint32_t raw_value, double scale, double offset) {
  return (raw_value * scale) + offset;
}