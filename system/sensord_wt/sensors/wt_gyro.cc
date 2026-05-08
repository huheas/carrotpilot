#include "wt_gyro.h"
#include "common/swaglog.h"
#include "common/timing.h"
#include "REG.h"
#include "wit_c_sdk.h"
#include <cmath>
#include "constants.h"
#include "wt_data_manager.h"
WT_Gyro::WT_Gyro(const std::string& device, int baud) {
  LOGD("Creating WT gyroscope sensor for PC environment");
  // 确保数据管理器已初始化
  WTDataManager::getInstance(device, baud);
}

void WT_Gyro::update_gyro_data() {
  // 从 WT SDK 寄存器读取陀螺仪数据
  // 陀螺仪数据范围通常是 ±2000°/s，寄存器值范围是 ±32768
  // 转换为 rad/s
  const double DEG_TO_RAD = M_PI / 180.0;
  last_gyro_x = (double)sReg[GX] / 32768.0 * 2000.0 * DEG_TO_RAD;
  last_gyro_y = (double)sReg[GY] / 32768.0 * 2000.0 * DEG_TO_RAD;
  last_gyro_z = (double)sReg[GZ] / 32768.0 * 2000.0 * DEG_TO_RAD;
  last_update_ts = nanos_since_boot();

  // 添加详细的数据日志
  LOGD("WT Gyro: raw[%d,%d,%d] -> scaled[%.6f,%.6f,%.6f] rad/s (ts=%lu)",
       sReg[GX], sReg[GY], sReg[GZ],
       last_gyro_x, last_gyro_y, last_gyro_z, last_update_ts);
}

bool WT_Gyro::get_event(MessageBuilder &msg, uint64_t ts) {
  if (!enabled) {
    return false;
  }

  WTDataManager* data_manager = WTDataManager::getInstance();
  if (!data_manager->getLatestData()) {
    return false;  // 还未收到过数据
  }

  // 更新陀螺仪数据（sReg 由后台线程的 WT SDK 填充，无锁读取）
  update_gyro_data();

  LOGD("WT_Gyro: Building gyroscope message, enabled=%s", enabled ? "true" : "false");

  auto event = msg.initEvent().initGyroscope();
  event.setSource(cereal::SensorEventData::SensorSource::WT_SDK);
  event.setVersion(1);
  event.setSensor(SENSOR_GYRO_UNCALIBRATED);
  event.setType(SENSOR_TYPE_GYROSCOPE_UNCALIBRATED);
  event.setTimestamp(ts == 0 ? nanos_since_boot() : ts);

  auto gyro = event.initGyroUncalibrated();
  //
  // WT 传感器物理轴方向（与加速度计相同，实测验证）:
  //   WT_X 正 = 物理左方向
  //   WT_Y 正 = 物理前进方向
  //   WT_Z 正 = 物理向上方向
  //
  // openpilot 陀螺仪期望（locationd）:
  //   meas_gyro[0] = roll  = 绕前进轴(X)旋转，右侧向下为正
  //   meas_gyro[1] = pitch = 绕右侧轴(Y)旋转，机头向上为正
  //   meas_gyro[2] = yaw   = 绕向上轴(Z)旋转，向左转为正
  //
  // 结合加速度计物理轴推导：
  // 实车验证：WT_Y正方向 = 车辆后退，所以绕"前进轴"旋转 = 绕(-WT_Y)旋转
  //   roll  = 绕(-WT_Y)轴旋转 → -WT_GY方向
  //   pitch = 绕(-WT_X)轴旋转 → -WT_GX方向
  //   yaw   = 绕WT_Z轴旋转   → WT_GZ方向
  //
  // locationd 变换: meas = [-v[2], -v[1], -v[0]]
  //   meas[0] = roll  = -WT_GY → -v[2]=-WT_GY → v[2]=+gy
  //   meas[1] = pitch = -WT_GX → -v[1]=-WT_GX → v[1]=+gx
  //   meas[2] = yaw   = +WT_GZ → -v[0]=WT_GZ  → v[0]=-gz
  gyro.setV({{(float)(-last_gyro_z), (float)(last_gyro_x), (float)(last_gyro_y)}});
  gyro.setStatus(true);

  LOGD("WT_Gyro: Message built successfully");
  return true;
}