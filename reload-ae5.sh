#!/bin/bash
# Reload the AE-5 prod ca0132 module (with external-strip sysfs support).
set -u
COD=hdaudioC0D1; DRV=snd_hda_codec_ca0132
KO=/home/christensen/dev/ae5-linux/kbuild/snd-hda-codec-ca0132.ko
pkill -STOP wireplumber 2>/dev/null || true
echo "$COD" > /sys/bus/hdaudio/drivers/$DRV/unbind 2>/dev/null || true
sleep 1
rmmod $DRV 2>/dev/null || true
sleep 1
grep -q "^$DRV " /proc/modules && echo "WARN: still resident" || echo "OK: unloaded"
insmod "$KO" && echo "OK: prod module loaded"
echo "$COD" > /sys/bus/hdaudio/drivers/$DRV/bind 2>/dev/null || true
sleep 2
pkill -CONT wireplumber 2>/dev/null || true
echo "=== verify strip ALSA controls ==="
amixer -c Creative controls | grep -i "AE-5 LED Strip" || true
amixer -c Creative cget iface=CARD,name='AE-5 LED Strip Count' 2>/dev/null || true
echo "=== updating openrgb binary ==="
systemctl stop openrgb-server.service 2>/dev/null || true
install -m 755 /home/christensen/openrgb-src/build/openrgb /opt/openrgb-ae5/openrgb && echo "OK: openrgb binary installed"
systemctl start openrgb-server.service 2>/dev/null || true