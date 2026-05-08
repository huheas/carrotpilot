#pragma once

#include "system/camerad/cameras/camera_common.h"
#include <linux/videodev2.h>

class CameraUSB {
private:
  int fd = -1;
  int width = 0;
  int height = 0;
  int actual_width = 0;
  int actual_height = 0;
  int buf_count = 0;
  bool is_capture = false; // 是否为单平面设备
  std::vector<struct v4l2_buffer> buffers;
  std::vector<std::vector<void*>> mmap_buffers;
  size_t plane_sizes[2];

public:
  CameraUSB() = default;
  ~CameraUSB();

  int init(const char *device_path, int w, int h, int framerate = 20);
  int start();
  int stop();
  int read_frame(CameraBuf *buf);

  int get_width() const { return width; }
  int get_height() const { return height; }
  int get_actual_width() const { return actual_width; }
  int get_actual_height() const { return actual_height; }
  bool get_is_capture() const { return is_capture; }
};
