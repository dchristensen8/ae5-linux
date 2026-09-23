#!/bin/bash
# test-sysfs-leds.sh: Reload production driver, test sysfs ae5_strip_leds and capture on analyzer
set -euo pipefail

COD=hdaudioC0D1
DRV=snd_hda_codec_ca0132
KO=/home/christensen/dev/ae5-linux/snd-hda-codec-ca0132-prod.ko
OUT_SR="/home/christensen/dev/ae5-linux/linux_sysfs_capture.sr"
SYSFS_DIR="/sys/bus/hdaudio/devices/$COD"

echo "=== [1] Freeze Audio & Load Production Kernel Module ==="
pkill -STOP wireplumber 2>/dev/null || true
echo "$COD" > /sys/bus/hdaudio/drivers/$DRV/unbind 2>/dev/null || true
sleep 1
rmmod $DRV 2>/dev/null || true
sleep 1
grep -q "^$DRV " /proc/modules && echo "WARN: still resident" || echo "OK: unloaded"
insmod "$KO" && echo "OK: production module loaded"
echo "$COD" > /sys/bus/hdaudio/drivers/$DRV/bind 2>/dev/null || true
sleep 2
pkill -CONT wireplumber 2>/dev/null || true

echo "=== [2] Check Sysfs Attributes ==="
if [ -f "$SYSFS_DIR/ae5_strip_leds" ] && [ -f "$SYSFS_DIR/ae5_strip_num_leds" ]; then
    echo "SUCCESS: $SYSFS_DIR/ae5_strip_leds exists!"
    echo "SUCCESS: $SYSFS_DIR/ae5_strip_num_leds exists!"
    echo "Initial num_leds: $(cat "$SYSFS_DIR/ae5_strip_num_leds")"
    echo "Initial leds:     $(cat "$SYSFS_DIR/ae5_strip_leds")"
else
    echo "ERROR: Sysfs attributes not found in $SYSFS_DIR!"
    exit 1
fi

echo "=== [3] Starting 5-second 24 MS/s capture on D0 (Pin 3 Data) & D1 (Pin 2 Clock)... ==="
rm -f "$OUT_SR"
sigrok-cli -d fx2lafw --config samplerate=24M --time 5s -C D0,D1 -o "$OUT_SR" &
SIGROK_PID=$!

sleep 1.0

echo "=== [4] Setting Blue color (#0000ff) via sysfs ae5_strip_leds... ==="
echo "#0000ff" > "$SYSFS_DIR/ae5_strip_leds"

echo "Waiting for logic analyzer capture to complete..."
wait "$SIGROK_PID"

echo "[+] Capture complete: $OUT_SR ($(ls -lh "$OUT_SR" | awk '{print $5}'))"
chmod 666 "$OUT_SR" 2>/dev/null || true
echo ""

echo "=== [5] Checking Sysfs Readback ==="
echo "Current leds: $(cat "$SYSFS_DIR/ae5_strip_leds")"
echo ""

echo "=== [6] Signal Edge Transition Analysis ==="
unzip -p "$OUT_SR" 'logic-1-*' | /tmp/analyze_sr
echo ""

echo "=== [7] WS2812 Protocol Decode on D0 (Pin 3 Data) ==="
sigrok-cli -i "$OUT_SR" -P rgb_led_ws281x:din=D0 | grep -E "#[0-9a-fA-F]{6}" | head -n 10 || true
echo ""
echo "First 20 protocol decoder packets:"
sigrok-cli -i "$OUT_SR" -P rgb_led_ws281x:din=D0 | head -n 20 || true

echo ""
echo "=== [8] Kernel Log (AE5 strip:) ==="
journalctl -b --no-pager 2>/dev/null | grep -E "AE5 strip:" | tail -n 15 || dmesg | grep -i "AE5 strip:" | tail -n 15 || true

