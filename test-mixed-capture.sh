#!/bin/bash
# test-mixed-capture.sh: Capture mixed-value alternating bits (#aaaaaa) to test 0-bits at word boundaries
set -euo pipefail

COD=hdaudioC0D1
OUT_SR="/home/christensen/dev/ae5-linux/linux_mixed_capture.sr"
SYSFS_DIR="/sys/bus/hdaudio/devices/$COD"

if [ ! -f "$SYSFS_DIR/ae5_strip_leds" ]; then
    echo "ERROR: Sysfs node not found in $SYSFS_DIR. Run test-sysfs-leds.sh first."
    exit 1
fi

echo "=== [1] Starting 5-second 24 MS/s capture on D0 (Pin 3 Data) & D1 (Pin 2 Clock)... ==="
rm -f "$OUT_SR"
sigrok-cli -d fx2lafw --config samplerate=24M --time 5s -C D0,D1 -o "$OUT_SR" &
SIGROK_PID=$!

sleep 1.0

# #aaaaaa = R=0xaa (10101010), G=0xaa (10101010), B=0xaa (10101010)
# Word 0 boundary: G2 = 0
# Word 1 boundary: R4 = 0
# Word 2 boundary: B6 = 0
# Word 3 boundary: B0 = 0
# All word boundaries contain genuine 0 bits!
echo "=== [2] Sending Mixed-Value Color #aaaaaa (0b10101010 across all channels)... ==="
echo "#aaaaaa" > "$SYSFS_DIR/ae5_strip_leds"

echo "Waiting for logic analyzer capture to complete..."
wait "$SIGROK_PID"

echo "[+] Capture complete: $OUT_SR ($(ls -lh "$OUT_SR" | awk '{print $5}'))"
chmod 666 "$OUT_SR" 2>/dev/null || true
echo ""

echo "=== [3] Verifying Hardware-Spec WS2812 Timing & Decode ==="
python3 /home/christensen/dev/ae5-linux/verify_ws2812_capture.py "$OUT_SR"
