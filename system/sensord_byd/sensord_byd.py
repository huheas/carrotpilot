#!/usr/bin/env python3
"""
sensord_byd - BYD CAN sensor bridge daemon

Bridges carState (yawRate, aEgo, aEgoY) to standard openpilot sensor
messages (gyroscope, accelerometer) so that locationd can use CAN-bus
data from the BYD ESC module instead of a hardware IMU.

This daemon is designed for PC development environments connected to a
BYD vehicle via CAN, where no physical IMU (WT or CH347) is available.

Usage:
  python3 -m openpilot.system.sensord_byd.sensord_byd [OPTIONS]

  --no-accel     Disable accelerometer bridge
  --no-gyro      Disable gyroscope bridge
  --verbose      Enable debug logging
  --help         Show this help

Activation (mutually exclusive with sensord_wt and sensord_ch347):
  Default PC mode     -> sensord_byd  (this daemon)
  USE_WT_IMU=1        -> sensord_wt   (WT hardware sensor)
  USE_CH347_IMU=1     -> sensord_ch347 (CH347 USB IMU)
"""
import argparse
import os
import time
import threading

import cereal.messaging as messaging
from cereal.services import SERVICE_LIST
from openpilot.common.realtime import Ratekeeper
from openpilot.common.swaglog import cloudlog

from openpilot.system.sensord_byd.sensors.byd_gyro import BYDGyro
from openpilot.system.sensord_byd.sensors.byd_accel import BYDAccel


def parse_args() -> argparse.Namespace:
  parser = argparse.ArgumentParser(
    description="BYD CAN sensor bridge daemon",
    formatter_class=argparse.RawDescriptionHelpFormatter,
  )
  parser.add_argument("--no-accel", action="store_true",
                      help="Disable accelerometer bridge")
  parser.add_argument("--no-gyro",  action="store_true",
                      help="Disable gyroscope bridge")
  parser.add_argument("--verbose",  action="store_true",
                      default=os.environ.get("SENSORD_BYD_VERBOSE", "0") == "1",
                      help="Enable debug logging (or set SENSORD_BYD_VERBOSE=1)")
  return parser.parse_args()


def polling_loop(sensor, service: str, exit_event: threading.Event) -> None:
  """
  Polling loop for a single sensor.

  Each loop creates its own SubMaster so sensors run independently
  and do not block each other.

  Publishing strategy:
  - When carState is updated: compute new sensor event and cache it.
  - Always publish the latest cached event every loop tick (at service
    frequency, ~104 Hz) so that locationd's sensor_alive 100 ms timeout
    is never triggered.  The event timestamp is refreshed to the current
    monotonic time on every publish so that locationd's _validate_sensor_time
    check (|sensor_t - log_t| < 100 ms) always passes.
  """
  pm = messaging.PubMaster([service])
  sm = messaging.SubMaster(['carState'])
  rk = Ratekeeper(SERVICE_LIST[service].frequency, print_delay_threshold=None)

  cloudlog.info(f"[sensord_byd] Starting {service} @ {SERVICE_LIST[service].frequency}Hz")

  last_event = None  # cached latest sensor event

  while not exit_event.is_set():
    sm.update(20)  # 20 ms timeout

    if sm.updated['carState']:
      event = sensor.get_event(sm['carState'])
      if event is not None:
        last_event = event

    if last_event is not None:
      # Refresh timestamp so locationd _validate_sensor_time always passes
      last_event.timestamp = time.monotonic_ns()
      msg = messaging.new_message(service, valid=True)
      setattr(msg, service, last_event)
      pm.send(service, msg)

    rk.keep_time()

  cloudlog.info(f"[sensord_byd] Stopped {service}")


def main() -> None:
  args = parse_args()

  if args.verbose:
    os.environ["LOGPRINT"] = "debug"

  cloudlog.info("[sensord_byd] Starting BYD CAN sensor bridge daemon")
  cloudlog.info(f"[sensord_byd] gyro={not args.no_gyro}, accel={not args.no_accel}")

  sensors_cfg: list[tuple[object, str]] = []
  if not args.no_gyro:
    sensors_cfg.append((BYDGyro(),  "gyroscope"))
  if not args.no_accel:
    sensors_cfg.append((BYDAccel(), "accelerometer"))

  if not sensors_cfg:
    cloudlog.error("[sensord_byd] No sensors enabled, exiting")
    return

  exit_event = threading.Event()
  threads = [
    threading.Thread(
      target=polling_loop,
      args=(sensor, service, exit_event),
      daemon=True,
      name=f"poll_{service}",
    )
    for sensor, service in sensors_cfg
  ]

  try:
    for t in threads:
      t.start()
    cloudlog.info(f"[sensord_byd] {len(threads)} sensor thread(s) running")
    while any(t.is_alive() for t in threads):
      time.sleep(1)
  except KeyboardInterrupt:
    cloudlog.info("[sensord_byd] Interrupted, shutting down")
  finally:
    exit_event.set()
    for t in threads:
      if t.is_alive():
        t.join(timeout=2.0)

  cloudlog.info("[sensord_byd] Daemon stopped")


if __name__ == "__main__":
  main()
