#include "wt_accel.h"
#include "common/swaglog.h"
#include "common/timing.h"
#include "REG.h"
#include "wt_data_manager.h"
#include "wit_c_sdk.h"
#include "constants.h"

WT_Accel::WT_Accel(const std::string& device, int baud) {  LOGD("Creating WT accelerometer sensor for PC environment");
  // 确保数据管理器已初始化
  WTDataManager::getInstance(device, baud);
}

void WT_Accel::update_accel_data() {
  // 从 WT SDK 寄存器读取加速度数据
  // 加速度数据范围通常是 ±16g，寄存器值范围是 ±32768
  // 转换为 m/s²
  last_accel_x = (double)sReg[AX] / 32768.0 * 16.0 * 9.8;
  last_accel_y = (double)sReg[AY] / 32768.0 * 16.0 * 9.8;
  last_accel_z = (double)sReg[AZ] / 32768.0 * 16.0 * 9.8;
  last_update_ts = nanos_since_boot();

  // 添加详细的数据日志
  LOGD("WT Accel: raw[%d,%d,%d] -> scaled[%.6f,%.6f,%.6f] m/s² (ts=%lu)",
       sReg[AX], sReg[AY], sReg[AZ],
       last_accel_x, last_accel_y, last_accel_z, last_update_ts);
}

bool WT_Accel::get_event(MessageBuilder &msg, uint64_t ts) {
  if (!enabled) {
    return false;
  }

  WTDataManager* data_manager = WTDataManager::getInstance();
  if (!data_manager->getLatestData()) {
    return false;  // 还未收到过数据
  }

  // 更新加速度数据（sReg 由后台线程的 WT SDK 填充，无锁读取）
  update_accel_data();

  // 构建 accelerometer 消息
  auto event = msg.initEvent();
  event.setLogMonoTime(ts == 0 ? nanos_since_boot() : ts);

  auto accel = event.initAccelerometer();
  accel.setVersion(1);
  accel.setSensor(1);
  accel.setType(1);
  accel.setTimestamp(last_update_ts);
  accel.setSource(cereal::SensorEventData::SensorSource::WT_SDK);

  // 设置加速度数据
  auto acceleration = accel.initAcceleration();
  auto v = acceleration.initV(3);
  //
  // WT 传感器物理轴方向（实测验证）:
  //   WT_X 正 = 物理左方向
  //   WT_Y 正 = 物理前进方向
  //   WT_Z 正 = 物理向上方向（静止时 WT_Z ≈ +9.87）
  //
  // openpilot 设备坐标系（locationd 期望）:
  //   meas[0] = X 前进（前进为正）
  //   meas[1] = Y 右侧（右为正）
  //   meas[2] = Z 向上（静止时重力 ≈ -9.81）
  //
  // 实车验证结论（场景2/3坡道测试）:
  //   WT_Y 正方向 = 车辆【后退】方向（传感器反装）
  //   因此 X前进 = -WT_Y，需要 v[2] = +WT_Y
  //
  // locationd 变换: meas = [-v[2], -v[1], -v[0]]
  //   meas[0] = -v[2] = X前进 = -WT_Y  → v[2] = +WT_Y
  //   meas[1] = -v[1] = Y右侧 = -WT_X  → v[1] = +WT_X
  //   meas[2] = -v[0] = Z上   = -WT_Z  → v[0] = +WT_Z
  //
  // 验证（静止，车头朝上坡道）:
  //   meas[0] = -(+WT_Y) = -0.40 < 0  ✓（上坡重力向后，X前进<0）
  //   meas[1] = -(+WT_X) = +0.62 ≈ 0  ✓
  //   meas[2] = -(+WT_Z) = -9.87 ≈ -9.81  ✓
  v.set(0, last_accel_z);       // +WT_Z → meas[2] = -WT_Z ≈ -9.81 ✓
  v.set(1, last_accel_x);       // +WT_X → meas[1] = -WT_X = Y右  ✓
  v.set(2, last_accel_y);       // +WT_Y → meas[0] = -WT_Y = X前进 ✓（WT_Y正=后退）
  acceleration.setStatus(0);

  return true;
}