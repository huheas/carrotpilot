#!/bin/bash
sudo chmod -R 777 /dev/bus/usb/* /dev/ttyUSB*
export BYD_RADAR=1
export GPU=1
export FINGERPRINT="BYD_HAN_EV_20"
OP_DIR=$(dirname "$(readlink -f "$0")")
export PARAMS_ROOT="$OP_DIR/params"
export LOG_ROOT="$OP_DIR/.comma"
export API_HOST=https://api.konik.ai
export ATHENA_HOST=wss://athena.konik.ai
export MAPS_HOST=https://api.konik.ai/maps
export USE_CH347_IMU=1
cd "$OP_DIR" &&
source .venv/bin/activate &&
USE_WEBCAM=1 ROAD_CAM=0 system/manager/manager.py
