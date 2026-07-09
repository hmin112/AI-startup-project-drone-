#!/bin/bash
set -e

source /opt/ros/humble/setup.bash
source /bridge_drone_ws/install/setup.bash

exec "$@"
