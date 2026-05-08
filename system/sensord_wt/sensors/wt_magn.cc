#include "wt_magn.h"
#include "common/swaglog.h"
#include "common/timing.h"
#include "constants.h"
#include "REG.h"
#include "wt_data_manager.h"
#include "wit_c_sdk.h"

WT_Magn::WT_Magn(const std::string& device, int baud) {
  LOGD("Creating WT magnetometer sensor for PC environment");
  // 确保数据管理器已初始化
  WTDataManager::getInstance(device, baud);
}

void WT_Magn::update_magn_data() {
  // 从 WT SDK 寄存器读取磁力计数据
  // 磁力计数据单位通常为 μT (微特斯拉)
  // 根据 WT 设备手册，磁力计寄存器值需要相应转换
  last_magn_x = (double)sReg[HX];  // 可能需要根据具体设备调整比例
  last_magn_y = (double)sReg[HY];
  last_magn_z = (double)sReg[HZ];
  last_update_ts = nanos_since_boot();

  // 添加详细的数据日志
  LOGD("WT Magn: raw[%d,%d,%d] -> scaled[%.6f,%.6f,%.6f] μT (ts=%lu)",
       sReg[HX], sReg[HY], sReg[HZ],
       last_magn_x, last_magn_y, last_magn_z, last_update_ts);
}

bool WT_Magn::get_event(MessageBuilder &msg, uint64_t ts) {
  if (!enabled) {
    return false;
  }

  WTDataManager* data_manager = WTDataManager::getInstance();
  if (!data_manager->getLatestData()) {
    return false;  // 还未收到过数据
  }

  // 更新磁力计数据
  update_magn_data();

  // 构建 magnetometer 消息
  auto event = msg.initEvent();
  event.setLogMonoTime(ts == 0 ? nanos_since_boot() : ts);

  auto magn_event = event.initMagnetometer();
  magn_event.setSource(cereal::SensorEventData::SensorSource::WT_SDK);
  magn_event.setVersion(1);
  magn_event.setSensor(SENSOR_MAGNETOMETER_UNCALIBRATED);
  magn_event.setType(SENSOR_TYPE_MAGNETIC_FIELD_UNCALIBRATED);
  magn_event.setTimestamp(last_update_ts);

  auto magn = magn_event.initMagneticUncalibrated();
  magn.setV({{(float)last_magn_x, (float)last_magn_y, (float)last_magn_z}});
  magn.setStatus(true);

  return true;
}

int WT_Magn::init() {
  enabled = true;
  return 0;
}

int WT_Magn::shutdown() {
  enabled = false;
  return 0;
}

bool WT_Magn::is_data_valid(uint64_t current_ts) {
  return enabled;
}