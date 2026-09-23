#!/bin/bash
# test-sysfs-multi.sh: Test color patterns and dynamic control on AE-5 external RGB strip
set -euo pipefail

COD=hdaudioC0D1
SYSFS_DIR="/sys/bus/hdaudio/devices/$COD"

if [ ! -f "$SYSFS_DIR/ae5_strip_leds" ]; then
    echo "ERROR: $SYSFS_DIR/ae5_strip_leds not found. Run sudo ./test-sysfs-leds.sh first."
    exit 1
fi

echo "=== Sound BlasterX AE-5 RGB Strip Dynamic Control Test ==="
echo "Active LED count: $(cat "$SYSFS_DIR/ae5_strip_num_leds")"
echo ""

echo "[1] Testing Solid Green (#00ff00)..."
echo "#00ff00" > "$SYSFS_DIR/ae5_strip_leds"
sleep 1

echo "[2] Testing Solid Red (#ff0000)..."
echo "#ff0000" > "$SYSFS_DIR/ae5_strip_leds"
sleep 1

echo "[3] Testing Solid Blue (#0000ff)..."
echo "#0000ff" > "$SYSFS_DIR/ae5_strip_leds"
sleep 1

echo "[4] Testing 10-LED Multi-Color Pattern..."
# Red, Green, Blue, Yellow, Cyan, Magenta, White, Orange, Purple, Pink
PATTERN="#ff0000,#00ff00,#0000ff,#ffff00,#00ffff,#ff00ff,#ffffff,#ff8800,#8800ff,#ff0088"
echo "$PATTERN" > "$SYSFS_DIR/ae5_strip_leds"
echo "Readback leds: $(cat "$SYSFS_DIR/ae5_strip_leds")"
sleep 1

echo "[5] Testing Turn Off (#000000)..."
echo "#000000" > "$SYSFS_DIR/ae5_strip_leds"
echo "Readback leds: $(cat "$SYSFS_DIR/ae5_strip_leds")"

echo ""
echo "=== Done! All dynamic color changes completed successfully. ==="
