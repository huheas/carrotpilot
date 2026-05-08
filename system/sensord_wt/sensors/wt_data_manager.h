#pragma once

#include <string>
#include <mutex>
#include <memory>
#include <cstdint>
#include <atomic>
#include <thread>

class WTDataManager {
private:
  static std::unique_ptr<WTDataManager> instance;
  static std::mutex instance_mutex;

  std::string device_path;
  int serial_fd;
  std::mutex data_mutex;  // 保护缓存数据
  std::atomic<uint64_t> last_update_time;
  std::atomic<bool> data_valid;
  std::atomic<bool> reader_running;
  std::thread reader_thread;

  WTDataManager(const std::string& device, int baud);
  void reader_loop();

public:
  static WTDataManager* getInstance(const std::string& device, int baud);
  static WTDataManager* getInstance();

  /** 获取最新缓存数据，不阻塞。返回 false 表示从未收到过数据 */
  bool getLatestData() const;
  bool isDataValid() const;
  uint64_t getLastUpdateTime() const;

  ~WTDataManager();

  // 禁止拷贝和赋值
  WTDataManager(const WTDataManager&) = delete;
  WTDataManager& operator=(const WTDataManager&) = delete;
};