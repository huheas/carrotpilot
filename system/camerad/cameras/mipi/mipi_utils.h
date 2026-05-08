#pragma once

#include <linux/videodev2.h>
#include <cstddef>
#include <cstdint>
#include <sys/ioctl.h>

// MIPI摄像头相关工具函数
int mipi_open_camera(const char *device_path);
int mipi_close_camera(int fd);
int mipi_check_capability(int fd);
int mipi_set_format(int fd, int width, int height);
int mipi_request_buffers(int fd, int count);
int mipi_query_buffer(int fd, int index, struct v4l2_buffer *buf);
void *mipi_mmap_buffer(int fd, struct v4l2_buffer *buf, int plane_idx);
int mipi_munmap_buffer(void *addr, size_t length);
int mipi_queue_buffer(int fd, struct v4l2_buffer *buf);
int mipi_dequeue_buffer(int fd, struct v4l2_buffer *buf);
int mipi_start_stream(int fd);
int mipi_stop_stream(int fd);

// NV12数据处理函数
int mipi_copy_nv12_frame(void *y_plane, void *uv_plane, size_t y_size, size_t uv_size, uint8_t *dest);
int mipi_get_nv12_size(int width, int height);
