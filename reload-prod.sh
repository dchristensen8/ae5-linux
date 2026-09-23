#!/bin/bash
# reload-prod.sh: Reload the production snd-hda-codec-ca0132 driver module
set -euo pipefail

COD=hdaudioC0D1
DRV=snd_hda_codec_ca0132
KO=/home/christensen/dev/ae5-linux/snd-hda-codec-ca0132-prod.ko

echo "=== Reloading Production AE-5 Driver ==="
pkill -STOP wireplumber 2>/dev/null || true
echo "$COD" > /sys/bus/hdaudio/drivers/$DRV/unbind 2>/dev/null || true
sleep 1
rmmod $DRV 2>/dev/null || true
sleep 1
grep -q "^$DRV " /proc/modules && echo "WARN: module still resident" || echo "OK: unloaded old module"
insmod "$KO" && echo "OK: loaded new production module"
echo "$COD" > /sys/bus/hdaudio/drivers/$DRV/bind 2>/dev/null || true
sleep 2
pkill -CONT wireplumber 2>/dev/null || true

# Apply world-writable permissions to sysfs files
chmod 666 /sys/bus/hdaudio/devices/$COD/ae5_strip_* 2>/dev/null || true

echo "=== Driver reloaded successfully! Current status: ==="
echo "Active LEDs: $(cat /sys/bus/hdaudio/devices/$COD/ae5_strip_num_leds)"
echo "Current Colors: $(cat /sys/bus/hdaudio/devices/$COD/ae5_strip_leds)"
