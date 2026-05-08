#include "system/camerad/cameras/mipi/mipi_utils.h"

#include <fcntl.h>
#include <unistd.h>
#include <sys/mman.h>
#include <cstring>
#include <iostream>
#include <errno.h>

int mipi_open_camera(const char *device_path) {
  int fd = open(device_path, O_RDWR | O_NONBLOCK);
  return fd;
}

int mipi_check_capability(int fd) {
  struct v4l2_capability cap = {};
  int ret = ioctl(fd, VIDIOC_QUERYCAP, &cap);
  if (ret < 0) {
    std::cerr << "VIDIOC_QUERYCAP failed: " << strerror(errno) << std::endl;
    return ret;
  }

  // 打印设备信息
  std::cout << "Device: " << cap.driver << " " << cap.card << " " << cap.bus_info << std::endl;

  // 检查是否支持视频捕获
  if (!(cap.capabilities & V4L2_CAP_VIDEO_CAPTURE_MPLANE)) {
    std::cerr << "Device does not support V4L2_CAP_VIDEO_CAPTURE_MPLANE" << std::endl;
    return -1;
  }

  return 0;
}

int mipi_close_camera(int fd) {
  if (fd >= 0) {
    return close(fd);
  }
  return 0;
}

int mipi_set_format(int fd, int width, int height) {
  // 使用多平面模式
  struct v4l2_format fmt = {};
  fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
  fmt.fmt.pix_mp.width = width;
  fmt.fmt.pix_mp.height = height;
  fmt.fmt.pix_mp.pixelformat = V4L2_PIX_FMT_NV12;
  fmt.fmt.pix_mp.num_planes = 2;
  fmt.fmt.pix_mp.plane_fmt[0].sizeimage = width * height;
  fmt.fmt.pix_mp.plane_fmt[0].bytesperline = width;
  fmt.fmt.pix_mp.plane_fmt[1].sizeimage = (width * height) / 2;
  fmt.fmt.pix_mp.plane_fmt[1].bytesperline = width;

  std::cout << "Setting format: " << width << "x" << height << " NV12" << std::endl;
  int ret = ioctl(fd, VIDIOC_S_FMT, &fmt);
  if (ret < 0) {
    std::cerr << "VIDIOC_S_FMT failed: " << strerror(errno) << std::endl;
    return ret;
  }

  std::cout << "Format set successfully" << std::endl;
  return ret;
}

int mipi_request_buffers(int fd, int count) {
  struct v4l2_requestbuffers req = {};
  req.count = count;
  req.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
  req.memory = V4L2_MEMORY_MMAP;

  int ret = ioctl(fd, VIDIOC_REQBUFS, &req);
  if (ret < 0) {
    std::cerr << "VIDIOC_REQBUFS failed: " << strerror(errno) << std::endl;
  } else {
    std::cout << "Buffers requested successfully, count: " << req.count << std::endl;
  }

  return ret;
}

int mipi_query_buffer(int fd, int index, struct v4l2_buffer *buf) {
  memset(buf, 0, sizeof(struct v4l2_buffer));
  buf->index = index;
  buf->type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
  buf->memory = V4L2_MEMORY_MMAP;
  buf->length = 2; // 对于NV12格式，我们需要2个平面
  // 在多平面模式下，需要初始化m.planes数组
  buf->m.planes = new v4l2_plane[2];
  memset(buf->m.planes, 0, sizeof(v4l2_plane) * 2);

  int ret = ioctl(fd, VIDIOC_QUERYBUF, buf);
  if (ret < 0) {
    std::cerr << "VIDIOC_QUERYBUF failed: " << strerror(errno) << std::endl;
  }

  // 释放planes数组
  delete[] buf->m.planes;
  buf->m.planes = nullptr;

  return ret;
}

void *mipi_mmap_buffer(int fd, struct v4l2_buffer *buf, int plane_idx) {
  // 多平面模式，映射指定平面
  if (plane_idx >= 0 && plane_idx < buf->length) {
    return mmap(nullptr, buf->m.planes[plane_idx].length, PROT_READ | PROT_WRITE, MAP_SHARED, fd, buf->m.planes[plane_idx].m.mem_offset);
  }
  return nullptr;
}

int mipi_munmap_buffer(void *addr, size_t length) {
  if (addr) {
    return munmap(addr, length);
  }
  return 0;
}

int mipi_queue_buffer(int fd, struct v4l2_buffer *buf) {
  std::cout << "Queueing buffer index: " << buf->index << std::endl;
  buf->type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
  int ret = ioctl(fd, VIDIOC_QBUF, buf);
  if (ret < 0) {
    std::cerr << "VIDIOC_QBUF failed: " << strerror(errno) << std::endl;
  } else {
    std::cout << "Buffer queued successfully, index: " << buf->index << std::endl;
  }

  return ret;
}

int mipi_dequeue_buffer(int fd, struct v4l2_buffer *buf) {
  buf->type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
  buf->memory = V4L2_MEMORY_MMAP;
  int ret = ioctl(fd, VIDIOC_DQBUF, buf);
  if (ret < 0) {
    std::cerr << "VIDIOC_DQBUF failed: " << strerror(errno) << std::endl;
  } else {
    std::cout << "Buffer dequeued successfully, index: " << buf->index << std::endl;
  }
  return ret;
}

int mipi_start_stream(int fd) {
  enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
  return ioctl(fd, VIDIOC_STREAMON, &type);
}

int mipi_stop_stream(int fd) {
  enum v4l2_buf_type type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
  return ioctl(fd, VIDIOC_STREAMOFF, &type);
}

int mipi_copy_nv12_frame(void *y_plane, void *uv_plane, size_t y_size, size_t uv_size, uint8_t *dest) {
  // Copy Y plane
  memcpy(dest, y_plane, y_size);
  // Copy UV plane
  memcpy(dest + y_size, uv_plane, uv_size);
  return 0;
}

int mipi_get_nv12_size(int width, int height) {
  return width * height * 3 / 2;
}
