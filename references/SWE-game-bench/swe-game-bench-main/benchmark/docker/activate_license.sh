#!/bin/bash
# Activate the mounted Unity license in this container (idempotent; Unity
# skips activation when the license is already valid).

LICENSE_FILE="/usr/share/unity3d/Unity/Unity_lic.ulf"

echo "Using license at: $LICENSE_FILE"

xvfb-run --auto-servernum --server-args="-screen 0 640x480x24" \
  unity-editor -batchmode -nographics -quit \
  -manualLicenseFile "$LICENSE_FILE" \
  -logFile /dev/stdout
