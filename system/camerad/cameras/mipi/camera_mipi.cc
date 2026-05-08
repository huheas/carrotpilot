#include "system/camerad/cameras/mipi/camera_mipi.h"
#include "system/camerad/cameras/mipi/mipi_utils.h"

#include <cstring>
#include <unistd.h>
#include <vector>
#include <iostream>
#include <sys/mman.h>

CameraMipi::~CameraMipi() {
  stop();

  // 释放内存映射
  for (int i = 0; i < mmap_buffers.size(); i++) {
    for (int j = 0; j < mmap_buffers[i].size(); j++) {
      if (mmap_buffers[i][j]) {
        if (is_capture) {
          // 对于单平面设备，使用munmap
          munmap(mmap_buffers[i][j], plane_sizes[0] + plane_sizes[1]);
        } else {
          // 对于多平面设备，使用free
          free(mmap_buffers[i][j]);
        }
        mmap_buffers[i][j] = nullptr;
      }
    }
  }

  // 释放planes数组
  for (int i = 0; i < plane_arrays.size(); i++) {
    if (plane_arrays[i]) {
      delete[] plane_arrays[i];
      plane_arrays[i] = nullptr;
    }
  }

  // 关闭摄像头设备
  if (fd >= 0) {
    close(fd);
    fd = -1;
  }
}

int CameraMipi::init(const char *device_path, int w, int h, int framerate) {
  // 打开摄像头设备
  // 默认使用MIPI摄像头22，如果没有指定设备路径
  const char *cam_path = device_path ? device_path : "/dev/video22";
  fd = mipi_open_camera(cam_path);
  if (fd < 0) {
    return fd;
  }

  // 检查设备能力
  struct v4l2_capability cap;
  int ret = ioctl(fd, VIDIOC_QUERYCAP, &cap);
  if (ret < 0) {
    std::cerr << "VIDIOC_QUERYCAP failed: " << strerror(errno) << std::endl;
    return ret;
  }

  // 打印设备信息
  std::cout << "Device: " << cap.driver << " " << cap.card << " " << cap.bus_info << std::endl;

  // 检查是否支持视频捕获
  is_capture = cap.capabilities & V4L2_CAP_VIDEO_CAPTURE;
  bool is_mplane_capture = cap.capabilities & V4L2_CAP_VIDEO_CAPTURE_MPLANE;

  std::cout << "Device capture types: capture=" << is_capture << ", mplane_capture=" << is_mplane_capture << std::endl;

  if (!is_capture && !is_mplane_capture) {
    std::cerr << "Device does not support video capture" << std::endl;
    return -1;
  }

  // 检查是否支持流I/O
  if (!(cap.capabilities & V4L2_CAP_STREAMING)) {
    std::cerr << "Device does not support streaming I/O" << std::endl;
    return -1;
  }

  // 设置分辨率和格式
  width = w;
  height = h;

  // 设置格式
  struct v4l2_format fmt;
  memset(&fmt, 0, sizeof(fmt));

  if (is_capture) {
    fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    fmt.fmt.pix.width = width;
    fmt.fmt.pix.height = height;
    fmt.fmt.pix.pixelformat = V4L2_PIX_FMT_NV12;
    fmt.fmt.pix.field = V4L2_FIELD_NONE;
    std::cout << "Setting format for capture device: " << width << "x" << height << ", NV12" << std::endl;
  } else {
    fmt.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
    fmt.fmt.pix_mp.width = width;
    fmt.fmt.pix_mp.height = height;
    fmt.fmt.pix_mp.pixelformat = V4L2_PIX_FMT_NV12;
    fmt.fmt.pix_mp.field = V4L2_FIELD_NONE;
    std::cout << "Setting format for mplane capture device: " << width << "x" << height << ", NV12" << std::endl;
  }

  if (ioctl(fd, VIDIOC_S_FMT, &fmt) < 0) {
    std::cerr << "VIDIOC_S_FMT failed: " << strerror(errno) << std::endl;
    return -1;
  }

  std::cout << "Format set successfully" << std::endl;

  // 设置帧率
  struct v4l2_streamparm parm;
  memset(&parm, 0, sizeof(struct v4l2_streamparm));
  parm.type = is_capture ? V4L2_BUF_TYPE_VIDEO_CAPTURE : V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
  parm.parm.capture.timeperframe.numerator = 1;
  parm.parm.capture.timeperframe.denominator = framerate;
  
  if (ioctl(fd, VIDIOC_S_PARM, &parm) < 0) {
    std::cerr << "VIDIOC_S_PARM failed (framerate): " << strerror(errno) << std::endl;
    std::cerr << "Using default framerate" << std::endl;
  } else {
    std::cout << "Framerate set to: " << framerate << " FPS" << std::endl;
  }

  // 申请缓冲区
  buf_count = VIPC_BUFFER_COUNT;
  struct v4l2_requestbuffers req;
  memset(&req, 0, sizeof(req));
  req.count = 4;
  req.type = is_capture ? V4L2_BUF_TYPE_VIDEO_CAPTURE : V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
  req.memory = is_capture ? V4L2_MEMORY_MMAP : V4L2_MEMORY_USERPTR;

  std::cout << "Requesting " << req.count << " buffers with memory type: " << (is_capture ? "MMAP" : "USERPTR") << std::endl;

  if (ioctl(fd, VIDIOC_REQBUFS, &req) < 0) {
    std::cerr << "VIDIOC_REQBUFS failed: " << strerror(errno) << std::endl;
    return -1;
  }

  buf_count = req.count;
  std::cout << "Buffers requested successfully, count: " << buf_count << std::endl;

  // 映射缓冲区
  plane_sizes[0] = width * height;
  plane_sizes[1] = (width * height) / 2;

  // 调整缓冲区大小
  buffers.resize(buf_count);
  mmap_buffers.resize(buf_count);
  plane_arrays.resize(buf_count); // 用于存储每个缓冲区的planes数组

  for (int i = 0; i < buf_count; i++) {
    if (is_capture) {
      // 对于单平面设备
      struct v4l2_buffer buffer;
      memset(&buffer, 0, sizeof(buffer));
      buffer.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
      buffer.memory = V4L2_MEMORY_MMAP;
      buffer.index = i;

      if (ioctl(fd, VIDIOC_QUERYBUF, &buffer) < 0) {
        std::cerr << "VIDIOC_QUERYBUF failed: " << strerror(errno) << std::endl;
        return -1;
      }

      // 映射单平面缓冲区
      mmap_buffers[i].resize(1);
      void *addr = mmap(nullptr, buffer.length, PROT_READ | PROT_WRITE, MAP_SHARED, fd, buffer.m.offset);
      if (!addr) {
        std::cerr << "mmap failed: " << strerror(errno) << std::endl;
        return -1;
      }
      mmap_buffers[i][0] = addr;

      // 保存缓冲区信息
      buffers[i] = buffer;

      // 将缓冲区加入队列
      ret = ioctl(fd, VIDIOC_QBUF, &buffer);
      if (ret < 0) {
        std::cerr << "VIDIOC_QBUF failed: " << strerror(errno) << std::endl;
        return ret;
      }
    } else {
      // 对于多平面设备
      // 为每个缓冲区分配内存
      size_t buffer_size = width * height * 3 / 2; // NV12 格式的大小
      void *buffer = malloc(buffer_size);
      if (!buffer) {
        std::cerr << "Failed to allocate buffer" << std::endl;
        return -1;
      }

      // 映射多平面缓冲区
      mmap_buffers[i].resize(1);
      mmap_buffers[i][0] = buffer;

      // 将缓冲区加入队列
      struct v4l2_buffer v4l2_buf;
      struct v4l2_plane planes[1];
      memset(&v4l2_buf, 0, sizeof(v4l2_buf));
      memset(planes, 0, sizeof(planes));
      v4l2_buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
      v4l2_buf.memory = V4L2_MEMORY_USERPTR;
      v4l2_buf.index = i;
      v4l2_buf.m.planes = planes;
      v4l2_buf.length = 1;
      planes[0].m.userptr = reinterpret_cast<uintptr_t>(buffer);
      planes[0].length = buffer_size;

      ret = ioctl(fd, VIDIOC_QBUF, &v4l2_buf);
      if (ret < 0) {
        std::cerr << "VIDIOC_QBUF failed: " << strerror(errno) << std::endl;
        free(buffer);
        return -1;
      }

      // 保存缓冲区信息
      buffers[i] = v4l2_buf;
    }
  }

  // 启动流
  enum v4l2_buf_type buf_type = is_capture ? V4L2_BUF_TYPE_VIDEO_CAPTURE : V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
  std::cout << "Starting stream with type: " << (is_capture ? "VIDEO_CAPTURE" : "VIDEO_CAPTURE_MPLANE") << std::endl;

  if (ioctl(fd, VIDIOC_STREAMON, &buf_type) < 0) {
    std::cerr << "VIDIOC_STREAMON failed: " << strerror(errno) << std::endl;
    return -1;
  }

  std::cout << "Stream started successfully" << std::endl;

  std::cout << "MIPI camera initialized successfully" << std::endl;

  return 0;
}

int CameraMipi::start() {
  // 流已经在init()方法中启动，这里可以简化
  if (fd < 0) {
    return -1;
  }
  std::cout << "MIPI camera stream started" << std::endl;
  return 0;
}

int CameraMipi::stop() {
  if (fd < 0) {
    return 0;
  }

  // 停止流
  enum v4l2_buf_type buf_type = is_capture ? V4L2_BUF_TYPE_VIDEO_CAPTURE : V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
  int ret = ioctl(fd, VIDIOC_STREAMOFF, &buf_type);
  if (ret < 0) {
    std::cerr << "VIDIOC_STREAMOFF failed: " << strerror(errno) << std::endl;
  } else {
    std::cout << "MIPI camera stream stopped successfully" << std::endl;
  }
  return ret;
}

int CameraMipi::read_frame(CameraBuf *buf) {
  if (fd < 0 || !buf) {
    return -1;
  }

  // 等待帧数据
  fd_set fds;
  FD_ZERO(&fds);
  FD_SET(fd, &fds);

  struct timeval tv;
  tv.tv_sec = 2;
  tv.tv_usec = 0;

  int ret = select(fd + 1, &fds, nullptr, nullptr, &tv);
  if (ret < 0) {
    return ret;
  }

  if (ret == 0) {
    return -1; // 超时
  }

  // 出队缓冲区
  struct v4l2_buffer buf_info;
  memset(&buf_info, 0, sizeof(struct v4l2_buffer));

  if (is_capture) {
    // 对于单平面设备
    buf_info.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
    buf_info.memory = V4L2_MEMORY_MMAP;

    ret = ioctl(fd, VIDIOC_DQBUF, &buf_info);
    if (ret < 0) {
      std::cerr << "VIDIOC_DQBUF failed: " << strerror(errno) << std::endl;
      return ret;
    }

    // 复制NV12数据到CameraBuf
    int index = buf_info.index;
    if (index >= 0 && index < mmap_buffers.size()) {
      std::vector<void*> &mmap_planes = mmap_buffers[index];
      if (!mmap_planes.empty() && buf->cur_yuv_buf) {
        // 在单平面模式下，NV12数据是连续存储的
        // Y平面在前，UV平面在后
        void *buffer = mmap_planes[0];
        if (buffer) {
          size_t nv12_size = width * height * 3 / 2;
          memcpy(reinterpret_cast<uint8_t*>(buf->cur_yuv_buf->addr), buffer, nv12_size);
        }
      }
    }

    // 将缓冲区重新入队
    ret = ioctl(fd, VIDIOC_QBUF, &buf_info);
    if (ret < 0) {
      std::cerr << "VIDIOC_QBUF failed: " << strerror(errno) << std::endl;
      return ret;
    }
  } else {
    // 对于多平面设备
    struct v4l2_plane planes[1];
    memset(planes, 0, sizeof(planes));
    buf_info.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
    buf_info.memory = V4L2_MEMORY_USERPTR;
    buf_info.m.planes = planes;
    buf_info.length = 1;

    ret = ioctl(fd, VIDIOC_DQBUF, &buf_info);
    if (ret < 0) {
      std::cerr << "VIDIOC_DQBUF failed: " << strerror(errno) << std::endl;
      return ret;
    }

    // 复制NV12数据到CameraBuf
    int index = buf_info.index;
    if (index >= 0 && index < mmap_buffers.size()) {
      std::vector<void*> &mmap_planes = mmap_buffers[index];
      if (!mmap_planes.empty() && buf->cur_yuv_buf) {
        // 在多平面模式下，NV12数据是连续存储在用户指针中的
        void *buffer = mmap_planes[0];
        if (buffer) {
          size_t nv12_size = width * height * 3 / 2;
          memcpy(reinterpret_cast<uint8_t*>(buf->cur_yuv_buf->addr), buffer, nv12_size);
        }
      }
    }

    // 将缓冲区重新入队
    struct v4l2_buffer queue_buf;
    struct v4l2_plane queue_planes[1];
    memset(&queue_buf, 0, sizeof(queue_buf));
    memset(queue_planes, 0, sizeof(queue_planes));
    queue_buf.type = V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE;
    queue_buf.memory = V4L2_MEMORY_USERPTR;
    queue_buf.index = buf_info.index;
    queue_buf.m.planes = queue_planes;
    queue_buf.length = 1;
    queue_planes[0].m.userptr = reinterpret_cast<uintptr_t>(mmap_buffers[buf_info.index][0]);
    queue_planes[0].length = width * height * 3 / 2;

    ret = ioctl(fd, VIDIOC_QBUF, &queue_buf);
    if (ret < 0) {
      std::cerr << "VIDIOC_QBUF failed: " << strerror(errno) << std::endl;
      return ret;
    }
  }

  return 0;
}
