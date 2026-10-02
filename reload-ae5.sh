#!/bin/bash
# Reload the AE-5 ca0132 module (with external-strip ALSA controls).
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
COD=hdaudioC0D1; DRV=snd_hda_codec_ca0132
KO="${1:-$SCRIPT_DIR/kbuild/snd-hda-codec-ca0132.ko}"

if [ ! -f "$KO" ]; then
    echo "Error: Kernel module not found at $KO"
    echo "Run 'make' in $SCRIPT_DIR/kbuild first."
    exit 1
fi

pkill -STOP wireplumber 2>/dev/null || true
echo "$COD" > /sys/bus/hdaudio/drivers/$DRV/unbind 2>/dev/null || true
sleep 1
rmmod $DRV 2>/dev/null || true
sleep 1
grep -q "^$DRV " /proc/modules && echo "WARN: still resident" || echo "OK: unloaded"
insmod "$KO" && echo "OK: ca0132 module loaded"
echo "$COD" > /sys/bus/hdaudio/drivers/$DRV/bind 2>/dev/null || true
sleep 2
pkill -CONT wireplumber 2>/dev/null || true
echo "=== verify ALSA controls ==="
amixer -c Creative controls | grep -E -i "AE-5 (LED Strip|On-Card LEDs)" || true
amixer -c Creative cget iface=CARD,name='AE-5 LED Strip Count' 2>/dev/null || true

# Optional: restart openrgb-server if present
if systemctl is-active --quiet openrgb-server.service 2>/dev/null; then
    echo "=== restarting openrgb-server ==="
    systemctl restart openrgb-server.service 2>/dev/null || true
fi