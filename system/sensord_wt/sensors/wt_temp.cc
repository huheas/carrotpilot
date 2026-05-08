#include "wt_temp.h"
#include "common/swaglog.h"
#include "common/timing.h"
#include "constants.h"
#include "REG.h"
#include "wt_data_manager.h"
#include "wit_c_sdk.h"

WT_Temp::WT_Temp(const std::string& device, int baud) {
  LOGD("Creating WT temperature sensor for PC environment");
  // 确保数据管理器已初始化
  WTDataManager::getInstance(device, baud);
}

void WT_Temp::update_temp_data() {
  // 从 WT SDK 寄存器读取温度数据
  // 温度数据通常需要除以100得到摄氏度
  last_temperature = (double)sReg[TEMP] / 100.0;
  last_update_ts = nanos_since_boot();

  // 添加详细的数据日志
  LOGD("WT Temp: raw[%d] -> scaled[%.2f] °C (ts=%lu)",
       sReg[TEMP], last_temperature, last_update_ts);
}

bool WT_Temp::get_event(MessageBuilder &msg, uint64_t ts) {
  if (!enabled) {
    return false;
  }

  WTDataManager* data_manager = WTDataManager::getInstance();
  if (!data_manager->getLatestData()) {
    return false;  // 还未收到过数据
  }

  // 更新温度数据
  update_temp_data();

  // 构建 temperature 消息
  auto event = msg.initEvent();
  event.setLogMonoTime(ts == 0 ? nanos_since_boot() : ts);

  auto temp_event = event.initTemperatureSensor();
  temp_event.setSource(cereal::SensorEventData::SensorSource::WT_SDK);
  temp_event.setVersion(1);
  temp_event.setType(SENSOR_TYPE_AMBIENT_TEMPERATURE);
  temp_event.setTimestamp(last_update_ts);
  temp_event.setTemperature(last_temperature);

  return true;
}

int WT_Temp::init() {
  enabled = true;
  return 0;
}

int WT_Temp::shutdown() {
  enabled = false;
  return 0;
}

bool WT_Temp::is_data_valid(uint64_t current_ts) {
  return enabled;
}