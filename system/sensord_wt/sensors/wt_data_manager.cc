#include "wt_data_manager.h"
#include "common/swaglog.h"
#include "common/timing.h"
#include "serial.h"
#include "wit_c_sdk.h"
#include <unistd.h>

std::unique_ptr<WTDataManager> WTDataManager::instance = nullptr;
std::mutex WTDataManager::instance_mutex;

// ─── 串口读取后台线程：持续读串口并送入 WT SDK ─────────
// 此线程独立运行，不需要被其他线程阻塞，保证数据流不断。
void WTDataManager::reader_loop() {
  LOGD("[WTDataManager] Reader thread started");
  unsigned char buffer[256];

  while (reader_running.load()) {
    if (serial_fd < 0) {
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
      continue;
    }

    int len = serial_read_data(serial_fd, buffer, sizeof(buffer));
    if (len > 0) {
      // 将接收到的数据传递给 WT SDK 处理
      for (int i = 0; i < len; i++) {
        WitSerialDataIn(buffer[i]);
      }

      // 更新缓存标记
      last_update_time.store(nanos_since_boot());
      data_valid.store(true);
    } else {
      // 串口没有数据时短暂等待，避免空转
      std::this_thread::sleep_for(std::chrono::microseconds(500));
    }
  }
  LOGD("[WTDataManager] Reader thread stopped");
}

WTDataManager::WTDataManager(const std::string& device, int baud)
    : device_path(device), serial_fd(-1),
      last_update_time(0), data_valid(false), reader_running(false) {

  serial_fd = serial_open(device.c_str(), baud);
  if (serial_fd < 0) {
    LOGE("Failed to open WT serial device: %s", device.c_str());
    return;
  }

  LOGD("WT serial opened on %s @ %d baud, starting SDK + reader thread", device.c_str(), baud);

  // 初始化 WT SDK
  // JY901B 串口协议格式为 0x55 + 类型 + 数据，与 JY61 相同
  WitInit(WIT_PROTOCOL_JY61, 0x50);
  WitDelayMsRegister([](uint16_t ms) { usleep(ms * 1000); });
  WitRegisterCallBack([](uint32_t reg, uint32_t reg_num) {
    // SDK 解析到传感器数据后会触发此回调
  });

  // 启动后台读取线程
  reader_running.store(true);
  reader_thread = std::thread(&WTDataManager::reader_loop, this);
}

WTDataManager* WTDataManager::getInstance(const std::string& device, int baud) {
  std::lock_guard<std::mutex> lock(instance_mutex);
  if (!instance) {
    instance = std::unique_ptr<WTDataManager>(new WTDataManager(device, baud));
  }
  return instance.get();
}

WTDataManager* WTDataManager::getInstance() {
  std::lock_guard<std::mutex> lock(instance_mutex);
  return instance.get();
}

bool WTDataManager::getLatestData() const {
  // 直接读取最新数据，不阻塞。
  // 只检查是否收到过数据，不读串口。
  return data_valid.load() && (serial_fd >= 0);
}

bool WTDataManager::isDataValid() const {
  return data_valid.load() && (serial_fd >= 0);
}

uint64_t WTDataManager::getLastUpdateTime() const {
  return last_update_time;
}

WTDataManager::~WTDataManager() {
  // 停止后台读取线程
  if (reader_running.load()) {
    reader_running.store(false);
    if (reader_thread.joinable()) {
      reader_thread.join();
    }
  }
  if (serial_fd >= 0) {
    close(serial_fd);
    serial_fd = -1;
  }
}