#!/usr/bin/env python3
import os
import shutil
import threading
import time
from openpilot.system.hardware.hw import Paths
from openpilot.common.swaglog import cloudlog
from openpilot.system.loggerd.config import get_available_bytes, get_available_percent
from openpilot.system.loggerd.uploader import listdir_by_creation
from openpilot.system.loggerd.xattr_cache import getxattr

MIN_BYTES = 10 * 1024 * 1024 * 1024  # 10GB
MIN_PERCENT = 20  # 20%

DELETE_LAST = ['boot', 'crash']

PRESERVE_ATTR_NAME = 'user.preserve'
PRESERVE_ATTR_VALUE = b'1'
PRESERVE_COUNT = 5

MAX_DELETIONS_PER_CYCLE = 3  # 每次检查最多删除3个目录
MIN_LOG_AGE_DAYS = 1  # 至少保留1天内的日志
CRITICAL_SPACE_BYTES = 2 * 1024 * 1024 * 1024  # 2GB紧急阈值


def has_preserve_xattr(d: str) -> bool:
  return getxattr(os.path.join(Paths.log_root(), d), PRESERVE_ATTR_NAME) == PRESERVE_ATTR_VALUE


def get_preserved_segments(dirs_by_creation: list[str]) -> set[str]:
  # skip deleting most recent N preserved segments (and their prior segment)
  preserved = set()
  for n, d in enumerate(filter(has_preserve_xattr, reversed(dirs_by_creation))):
    if n == PRESERVE_COUNT:
      break
    date_str, _, seg_str = d.rpartition("--")

    # ignore non-segment directories
    if not date_str:
      continue
    try:
      seg_num = int(seg_str)
    except ValueError:
      continue

    # preserve segment and two prior
    for _seg_num in range(max(0, seg_num - 2), seg_num + 1):
      preserved.add(f"{date_str}--{_seg_num}")

  return preserved


def is_old_enough_to_delete(log_dir: str, min_age_days: int = MIN_LOG_AGE_DAYS) -> bool:
  """
  检查日志目录是否足够旧可以删除
  格式: route_id--timestamp--segment_number
  """
  try:
    parts = log_dir.split("--")
    if len(parts) >= 2:
      try:
        # 时间戳是16进制
        timestamp = int(parts[1], 16)  # 从16进制转换为10进制
        age_seconds = time.time() - timestamp
        age_days = age_seconds / 86400

        # 如果时间戳是未来的（可能是错误），则保留
        if age_seconds < 0:
          cloudlog.warning(f"Future timestamp in log directory {log_dir}: {timestamp}")
          return False

        return age_days >= min_age_days
      except ValueError:
        # 如果不能解析时间戳，检查是否为特殊目录
        if log_dir in DELETE_LAST:
          return True  # boot/crash目录没有时间戳
        return False  # 不能解析时间的日志目录保留
    return True  # 非标准格式目录，按旧逻辑处理
  except Exception:
    cloudlog.exception(f"Error checking age of {log_dir}")
    return False  # 出错时保留


def deleter_thread(exit_event: threading.Event):
  deletion_count = 0
  last_deletion_time = 0

  while not exit_event.is_set():
    available_bytes = get_available_bytes(default=MIN_BYTES + 1)
    available_percent = get_available_percent(default=MIN_PERCENT + 1)

    out_of_bytes = available_bytes < MIN_BYTES
    out_of_percent = available_percent < MIN_PERCENT
    critical_space = available_bytes < CRITICAL_SPACE_BYTES

    if out_of_percent or out_of_bytes:
      cloudlog.info(f"Low disk space: {available_bytes / (1024**3):.1f}GB ({available_percent:.1f}%) available")

      dirs = listdir_by_creation(Paths.log_root())
      preserved_dirs = get_preserved_segments(dirs)

      # 紧急情况下放宽时间限制
      min_age_days = 0 if critical_space else MIN_LOG_AGE_DAYS

      # 准备要删除的候选目录
      candidates = []
      for d in dirs:
        if d in preserved_dirs:
          continue

        # 检查是否足够旧
        if not is_old_enough_to_delete(d, min_age_days):
          continue

        candidates.append(d)

      # 排序：使用改进的排序键
      candidates.sort(key=lambda d: get_directory_sort_key(d))

      deleted_in_cycle = 0
      for delete_dir in candidates:
        if deleted_in_cycle >= MAX_DELETIONS_PER_CYCLE:
          break

        delete_path = os.path.join(Paths.log_root(), delete_dir)

        # 检查锁文件
        try:
          if any(name.endswith(".lock") for name in os.listdir(delete_path)):
            continue
        except OSError:
          cloudlog.warning(f"Cannot list files in {delete_path}, skipping")
          continue

        try:
          cloudlog.info(f"deleting {delete_path} (space: {available_bytes / (1024**3):.1f}GB, {available_percent:.1f}%)")
          shutil.rmtree(delete_path)
          deleted_in_cycle += 1
          deletion_count += 1
          last_deletion_time = time.time()

          # 删除后检查是否满足条件
          available_bytes = get_available_bytes(default=MIN_BYTES + 1)
          available_percent = get_available_percent(default=MIN_PERCENT + 1)
          if available_bytes >= MIN_BYTES and available_percent >= MIN_PERCENT:
            cloudlog.info(f"Disk space restored: {available_bytes / (1024**3):.1f}GB ({available_percent:.1f}%)")
            break

        except OSError:
          cloudlog.exception(f"issue deleting {delete_path}")

      # 根据紧急程度调整等待时间
      if critical_space:
        exit_event.wait(1)  # 紧急情况快速检查
      elif out_of_percent or out_of_bytes:
        exit_event.wait(5)  # 空间不足，稍快检查
      else:
        exit_event.wait(30)  # 空间充足，正常检查
    else:
      # 空间充足时重置删除计数器
      if deletion_count > 0:
        cloudlog.info(f"Deletion cycle completed: deleted {deletion_count} directories")
        deletion_count = 0
      exit_event.wait(30)


def get_timestamp_from_dir(log_dir: str) -> int:
  """
  从目录名中提取时间戳
  格式: route_id--timestamp--segment_number
  """
  try:
    parts = log_dir.split("--")
    if len(parts) >= 2:
      timestamp = int(parts[1], 16)  # 16进制时间戳
      # 验证时间戳合理性（2000-01-01到未来5年）
      min_timestamp = 946684800  # 2000-01-01
      max_timestamp = int(time.time()) + 5 * 365 * 86400  # 现在+5年
      if min_timestamp <= timestamp <= max_timestamp:
        return timestamp
  except (ValueError, IndexError):
    pass
  return 0  # 无法解析时间戳


def get_directory_sort_key(log_dir: str) -> tuple:
  """
  获取目录排序键，用于确定删除优先级
  删除优先级：1. boot/crash目录最后删除 2. 时间戳最旧的先删除 3. segment号最小的先删除

  返回: (is_delete_last, timestamp, segment_num)
  """
  is_delete_last = log_dir in DELETE_LAST

  timestamp = get_timestamp_from_dir(log_dir)
  # 如果无法获取时间戳，使用一个很大的值让它排在后面
  if timestamp == 0:
    timestamp = float('inf')

  # 解析segment number
  segment_num = 0
  try:
    parts = log_dir.split("--")
    if len(parts) >= 3:
      segment_num = int(parts[2])
  except (ValueError, IndexError):
    pass

  # 排序规则:
  # 1. is_delete_last: False < True (boot/crash最后删除)
  # 2. timestamp: 小的先删除
  # 3. segment_num: 小的先删除
  return (is_delete_last, timestamp, segment_num)


def main():
  deleter_thread(threading.Event())


if __name__ == "__main__":
  main()
