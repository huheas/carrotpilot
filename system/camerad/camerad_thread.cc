#ifndef QCOM2

#include "system/camerad/cameras/camera_common.h"
#include "system/camerad/cameras/mipi/camera_mipi.h"
#include "system/camerad/cameras/usb/camera_usb.h"
#include "common/timing.h"
#include "common/util.h"
#include "cereal/messaging/messaging.h"

#include <cassert>
#include <iostream>
#include <cstring>
#include <errno.h>
#include <signal.h>
#include <atomic>
#include <vector>
#include <thread>
#include <memory>

// 全局退出标志
std::atomic<bool> g_should_exit(false);

// 摄像头配置结构体
struct CameraConfig {
  std::string msg_name;
  VisionStreamType stream_type;
  std::string cam_id;
  std::string device_path;
  int width;
  int height;
  int framerate;
  int actual_width;
  int actual_height;
  bool use_webcam;
  std::unique_ptr<CameraMipi> mipi_camera;
  std::unique_ptr<CameraUSB> usb_camera;
};

// 信号处理函数
void signal_handler(int sig) {
  if (sig == SIGINT) {
    std::cout << "\nReceived Ctrl+C, shutting down..." << std::endl;
    g_should_exit = true;
  }
}

// 摄像头处理函数
void camera_thread(VisionIpcServer *vipc_server, PubMaster *pm, CameraConfig *config, bool debug_mode) {
  // 初始化CameraBuf
  CameraBuf camera_buf;
  camera_buf.vipc_server = vipc_server;
  camera_buf.stream_type = config->stream_type;
  camera_buf.out_img_width = config->actual_width;
  camera_buf.out_img_height = config->actual_height;
  camera_buf.cur_buf_idx = 0;

  // 使用局部变量跟踪缓冲区计数
  int frame_buf_count = VIPC_BUFFER_COUNT;

  // 主循环
  uint32_t frame_id = 0;
  uint64_t last_frame_time = 0;
  uint64_t frame_interval = 1000000000ULL / config->framerate; // 帧间隔（纳秒）

  // 帧率统计
  static const int FRAME_STATS_WINDOW = 30;
  uint64_t frame_timestamps[FRAME_STATS_WINDOW] = {0};
  int frame_stats_idx = 0;

  while (!g_should_exit) {
    // 计算需要等待的时间以维持帧率
    uint64_t current_time = nanos_since_boot();
    uint64_t time_since_last_frame = current_time - last_frame_time;

    if (time_since_last_frame < frame_interval) {
      // 等待剩余时间（转换为微秒）
      usleep((frame_interval - time_since_last_frame) / 1000);
    }

    // 更新帧数据
    camera_buf.cur_frame_data.frame_id = frame_id++;
    last_frame_time = camera_buf.cur_frame_data.timestamp_sof = nanos_since_boot();

    // 获取当前的VIPC缓冲区
    camera_buf.cur_yuv_buf = camera_buf.vipc_server->get_buffer(camera_buf.stream_type, camera_buf.cur_buf_idx);

    // 读取帧数据
    int ret = 0;
    if (config->use_webcam) {
      ret = config->usb_camera->read_frame(&camera_buf);
    } else {
      ret = config->mipi_camera->read_frame(&camera_buf);
    }
    if (ret < 0) {
      std::cerr << "Failed to read frame for " << config->msg_name << std::endl;
      continue;
    }

    // 发送帧到VIPC
    VisionIpcBufExtra extra = {
      camera_buf.cur_frame_data.frame_id,
      camera_buf.cur_frame_data.timestamp_sof,
      camera_buf.cur_frame_data.timestamp_eof,
    };
    camera_buf.cur_yuv_buf->set_frame_id(camera_buf.cur_frame_data.frame_id);
    camera_buf.vipc_server->send(camera_buf.cur_yuv_buf, &extra);

    // 更新时间戳
    camera_buf.cur_frame_data.timestamp_eof = nanos_since_boot();
    camera_buf.cur_frame_data.processing_time = camera_buf.cur_frame_data.timestamp_eof - camera_buf.cur_frame_data.timestamp_sof;

    // 发送消息
    MessageBuilder msg;
    if (config->stream_type == VISION_STREAM_ROAD) {
      auto framed = msg.initEvent().initRoadCameraState();
      framed.setFrameId(camera_buf.cur_frame_data.frame_id);
      framed.setTimestampSof(camera_buf.cur_frame_data.timestamp_sof);
      framed.setTimestampEof(camera_buf.cur_frame_data.timestamp_eof);
      framed.setProcessingTime(camera_buf.cur_frame_data.processing_time);
    } else if (config->stream_type == VISION_STREAM_DRIVER) {
      auto framed = msg.initEvent().initDriverCameraState();
      framed.setFrameId(camera_buf.cur_frame_data.frame_id);
      framed.setTimestampSof(camera_buf.cur_frame_data.timestamp_sof);
      framed.setTimestampEof(camera_buf.cur_frame_data.timestamp_eof);
      framed.setProcessingTime(camera_buf.cur_frame_data.processing_time);
    } else if (config->stream_type == VISION_STREAM_WIDE_ROAD) {
      auto framed = msg.initEvent().initWideRoadCameraState();
      framed.setFrameId(camera_buf.cur_frame_data.frame_id);
      framed.setTimestampSof(camera_buf.cur_frame_data.timestamp_sof);
      framed.setTimestampEof(camera_buf.cur_frame_data.timestamp_eof);
      framed.setProcessingTime(camera_buf.cur_frame_data.processing_time);
    }

    // 发送消息
    pm->send(config->msg_name.c_str(), msg);

    // 循环缓冲区索引
    camera_buf.cur_buf_idx = (camera_buf.cur_buf_idx + 1) % frame_buf_count;

    // 帧率统计
    frame_timestamps[frame_stats_idx] = nanos_since_boot();
    frame_stats_idx = (frame_stats_idx + 1) % FRAME_STATS_WINDOW;

    // 计算实际帧率
    if (debug_mode && frame_id > FRAME_STATS_WINDOW) {
      uint64_t oldest_time = frame_timestamps[0];
      uint64_t newest_time = frame_timestamps[0];
      for (int i = 0; i < FRAME_STATS_WINDOW; i++) {
        if (frame_timestamps[i] < oldest_time) oldest_time = frame_timestamps[i];
        if (frame_timestamps[i] > newest_time) newest_time = frame_timestamps[i];
      }

      if (newest_time > oldest_time) {
        float actual_fps = (FRAME_STATS_WINDOW * 1000000000.0f) / (newest_time - oldest_time);
        if (frame_id % FRAME_STATS_WINDOW == 0) {
          std::cout << "[DEBUG] " << config->msg_name << " Frame " << frame_id << ": "
                    << "Actual FPS: " << actual_fps << ", "
                    << "Expected FPS: " << config->framerate << ", "
                    << "Processing time: " << camera_buf.cur_frame_data.processing_time << "ms" << std::endl;
        }
      }
    }
  }

  // 清理资源
  if (config->use_webcam) {
    std::cout << "Stopping USB camera for " << config->msg_name << "..." << std::endl;
    config->usb_camera->stop();
    std::cout << "USB camera stopped successfully for " << config->msg_name << std::endl;
  } else {
    std::cout << "Stopping MIPI camera for " << config->msg_name << "..." << std::endl;
    config->mipi_camera->stop();
    std::cout << "MIPI camera stopped successfully for " << config->msg_name << std::endl;
  }
}

void camerad_thread() {
  // 设置信号处理
  signal(SIGINT, signal_handler);

  // 检查debug模式
  const char *debug_env = getenv("CAMERAD_DEBUG");
  bool debug_mode = debug_env && (strcmp(debug_env, "1") == 0 || strcmp(debug_env, "true") == 0);

  if (debug_mode) {
    std::cout << "[DEBUG] Camerad debug mode enabled" << std::endl;
  }

  // 检查是否使用USB摄像头
  const char *use_webcam_env = getenv("USE_WEBCAM");
  bool use_webcam = use_webcam_env && (strcmp(use_webcam_env, "1") == 0 || strcmp(use_webcam_env, "true") == 0);

  std::cout << "[DEBUG] Use USB camera: " << (use_webcam ? "yes" : "no") << std::endl;

  // 帧率设置（所有摄像头共用）
  const char *road_cam_framerate = getenv("ROAD_CAM_FRAMERATE");
  int framerate = road_cam_framerate ? atoi(road_cam_framerate) : 20;

  if (debug_mode) {
    std::cout << "[DEBUG] Framerate: " << framerate << " FPS" << std::endl;
  }

  // 摄像头配置列表
  std::vector<CameraConfig> camera_configs;

  // 1. 添加ROAD_CAM配置
  const char *road_cam_path = getenv("ROAD_CAM_PATH");
  const char *road_cam = getenv("ROAD_CAM");
  const char *road_cam_width = getenv("ROAD_CAM_WIDTH");
  const char *road_cam_height = getenv("ROAD_CAM_HEIGHT");
  const char *road_cam_use_webcam = getenv("ROAD_CAM_USE_WEBCAM");

  if (road_cam_path || road_cam || true) { // 默认可用
    CameraConfig config;
    config.msg_name = "roadCameraState";
    config.stream_type = VISION_STREAM_ROAD;
    config.framerate = framerate;
    // 优先使用摄像头特定配置，未设置时使用全局配置
    if (road_cam_use_webcam) {
      config.use_webcam = (strcmp(road_cam_use_webcam, "1") == 0 || strcmp(road_cam_use_webcam, "true") == 0);
    } else {
      config.use_webcam = use_webcam;
    }

    // 设备路径设置
    if (road_cam_path) {
      config.device_path = road_cam_path;
      if (debug_mode) {
        std::cout << "[DEBUG] Using ROAD_CAM_PATH: " << config.device_path << std::endl;
      }
    } else if (road_cam) {
      config.cam_id = road_cam;
      config.device_path = "/dev/video" + config.cam_id;
      if (debug_mode) {
        std::cout << "[DEBUG] Using ROAD_CAM: " << config.cam_id << " -> " << config.device_path << std::endl;
      }
    } else {
      config.device_path = use_webcam ? "/dev/video45" : "/dev/video0";
      if (debug_mode) {
        std::cout << "[DEBUG] Using default device path for ROAD_CAM: " << config.device_path << std::endl;
      }
    }

    // 分辨率设置
    config.width = road_cam_width ? atoi(road_cam_width) : 1920;
    config.height = road_cam_height ? atoi(road_cam_height) : 1080;
    config.actual_width = config.width;
    config.actual_height = config.height;

    if (debug_mode) {
      std::cout << "[DEBUG] ROAD_CAM Resolution: " << config.width << "x" << config.height << std::endl;
    }

    camera_configs.push_back(std::move(config));
  }

  // 2. 添加DRIVER_CAM配置（如果设置）
  const char *driver_cam = getenv("DRIVER_CAM");
  const char *driver_cam_path = getenv("DRIVER_CAM_PATH");
  const char *driver_cam_width = getenv("DRIVER_CAM_WIDTH");
  const char *driver_cam_height = getenv("DRIVER_CAM_HEIGHT");
  const char *driver_cam_use_webcam = getenv("DRIVER_CAM_USE_WEBCAM");

  if (driver_cam || driver_cam_path) {
    CameraConfig config;
    config.msg_name = "driverCameraState";
    config.stream_type = VISION_STREAM_DRIVER;
    config.framerate = framerate;
    // 优先使用摄像头特定配置，未设置时使用全局配置
    if (driver_cam_use_webcam) {
      config.use_webcam = (strcmp(driver_cam_use_webcam, "1") == 0 || strcmp(driver_cam_use_webcam, "true") == 0);
    } else {
      config.use_webcam = use_webcam;
    }

    // 设备路径设置
    if (driver_cam_path) {
      config.device_path = driver_cam_path;
      if (debug_mode) {
        std::cout << "[DEBUG] Using DRIVER_CAM_PATH: " << config.device_path << std::endl;
      }
    } else if (driver_cam) {
      config.cam_id = driver_cam;
      config.device_path = "/dev/video" + config.cam_id;
      if (debug_mode) {
        std::cout << "[DEBUG] Using DRIVER_CAM: " << config.cam_id << " -> " << config.device_path << std::endl;
      }
    }

    // 分辨率设置
    config.width = driver_cam_width ? atoi(driver_cam_width) : 1920;
    config.height = driver_cam_height ? atoi(driver_cam_height) : 1080;
    config.actual_width = config.width;
    config.actual_height = config.height;

    if (debug_mode) {
      std::cout << "[DEBUG] DRIVER_CAM Resolution: " << config.width << "x" << config.height << std::endl;
    }

    camera_configs.push_back(std::move(config));
  }

  // 3. 添加WIDE_ROAD_CAM配置（如果设置）
  const char *wide_cam = getenv("WIDE_CAM");
  const char *wide_road_cam_path = getenv("WIDE_ROAD_CAM_PATH");
  const char *wide_road_cam_width = getenv("WIDE_ROAD_CAM_WIDTH");
  const char *wide_road_cam_height = getenv("WIDE_ROAD_CAM_HEIGHT");
  const char *wide_road_cam_use_webcam = getenv("WIDE_ROAD_CAM_USE_WEBCAM");

  if (wide_cam || wide_road_cam_path) {
    CameraConfig config;
    config.msg_name = "wideRoadCameraState";
    config.stream_type = VISION_STREAM_WIDE_ROAD;
    config.framerate = framerate;
    // 优先使用摄像头特定配置，未设置时使用全局配置
    if (wide_road_cam_use_webcam) {
      config.use_webcam = (strcmp(wide_road_cam_use_webcam, "1") == 0 || strcmp(wide_road_cam_use_webcam, "true") == 0);
    } else {
      config.use_webcam = use_webcam;
    }

    // 设备路径设置
    if (wide_road_cam_path) {
      config.device_path = wide_road_cam_path;
      if (debug_mode) {
        std::cout << "[DEBUG] Using WIDE_ROAD_CAM_PATH: " << config.device_path << std::endl;
      }
    } else if (wide_cam) {
      config.cam_id = wide_cam;
      config.device_path = "/dev/video" + config.cam_id;
      if (debug_mode) {
        std::cout << "[DEBUG] Using WIDE_CAM: " << config.cam_id << " -> " << config.device_path << std::endl;
      }
    }

    // 分辨率设置
    config.width = wide_road_cam_width ? atoi(wide_road_cam_width) : 1920;
    config.height = wide_road_cam_height ? atoi(wide_road_cam_height) : 1080;
    config.actual_width = config.width;
    config.actual_height = config.height;

    if (debug_mode) {
      std::cout << "[DEBUG] WIDE_ROAD_CAM Resolution: " << config.width << "x" << config.height << std::endl;
    }

    camera_configs.push_back(std::move(config));
  }

  if (camera_configs.empty()) {
    std::cerr << "No cameras configured!" << std::endl;
    return;
  }

  // 初始化VIPC服务器
  VisionIpcServer vipc_server("camerad", nullptr, nullptr);

  // 初始化摄像头和创建缓冲区
  std::vector<std::thread> camera_threads;
  std::vector<std::string> msg_names;

  for (auto &config : camera_configs) {
    msg_names.push_back(config.msg_name);

    // 初始化摄像头
    int ret = 0;
    if (config.use_webcam) {
      config.usb_camera = std::make_unique<CameraUSB>();
      ret = config.usb_camera->init(config.device_path.c_str(), config.width, config.height, config.framerate);
      if (ret < 0) {
        std::cerr << "Failed to initialize USB camera for " << config.msg_name << ": " << strerror(errno) << std::endl;
        std::cerr << "Device path: " << config.device_path << std::endl;
        continue;
      }
      std::cout << "Successfully initialized USB camera: " << config.device_path << " for " << config.msg_name << std::endl;

      // 获取实际分辨率
      config.actual_width = config.usb_camera->get_actual_width();
      config.actual_height = config.usb_camera->get_actual_height();
      std::cout << "[DEBUG] Actual USB camera resolution for " << config.msg_name << ": " << config.actual_width << "x" << config.actual_height << std::endl;

      // 启动摄像头
      ret = config.usb_camera->start();
      if (ret < 0) {
        std::cerr << "Failed to start USB camera for " << config.msg_name << std::endl;
        continue;
      }
    } else {
      config.mipi_camera = std::make_unique<CameraMipi>();
      ret = config.mipi_camera->init(config.device_path.c_str(), config.width, config.height, config.framerate);
      if (ret < 0) {
        std::cerr << "Failed to initialize MIPI camera for " << config.msg_name << ": " << strerror(errno) << std::endl;
        std::cerr << "Device path: " << config.device_path << std::endl;
        continue;
      }
      std::cout << "Successfully initialized MIPI camera: " << config.device_path << " for " << config.msg_name << std::endl;

      // 启动摄像头
      ret = config.mipi_camera->start();
      if (ret < 0) {
        std::cerr << "Failed to start MIPI camera for " << config.msg_name << std::endl;
        continue;
      }
    }

    // 创建VIPC缓冲区
    vipc_server.create_buffers(config.stream_type, VIPC_BUFFER_COUNT, config.actual_width, config.actual_height);
  }

  // 初始化PubMaster
  std::vector<const char *> msg_names_cstr;
  for (const auto &name : msg_names) {
    msg_names_cstr.push_back(name.c_str());
  }
  PubMaster pm(msg_names_cstr);

  // 启动VIPC服务器监听
  vipc_server.start_listener();

  // 启动摄像头线程
  for (auto &config : camera_configs) {
    if (config.mipi_camera || config.usb_camera) {
      camera_threads.emplace_back(camera_thread, &vipc_server, &pm, &config, debug_mode);
    }
  }

  // 等待所有线程结束
  for (auto &thread : camera_threads) {
    thread.join();
  }
}
#endif
