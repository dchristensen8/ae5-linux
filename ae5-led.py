#!/usr/bin/env python3
"""
ae5-led.py: Rich Userspace CLI and Animation Controller for Sound BlasterX AE-5 External RGB Strip.

Features:
  - Auto-locates the AE-5 sysfs controller node.
  - Set solid colors by name, hex (#RRGGBB), or RGB (R,G,B).
  - Set per-LED gradients and individual colors.
  - Live animations: Rainbow wave, Breathing pulse, Comet chase, CPU meter.
  - Udev rule generation for passwordless userspace control.
"""

import os
import sys
import time
import glob
import math
import argparse

COLOR_MAP = {
    "red": "#ff0000",
    "green": "#00ff00",
    "blue": "#0000ff",
    "yellow": "#ffff00",
    "cyan": "#00ffff",
    "magenta": "#ff00ff",
    "white": "#ffffff",
    "warmwhite": "#ffb469",
    "orange": "#ff6600",
    "purple": "#8800ff",
    "pink": "#ff0088",
    "gold": "#ffaa00",
    "off": "#000000",
    "black": "#000000",
}

def find_ae5_sysfs():
    nodes = glob.glob("/sys/bus/hdaudio/devices/*/ae5_strip_leds")
    if not nodes:
        return None, None
    leds_path = nodes[0]
    dev_dir = os.path.dirname(leds_path)
    num_path = os.path.join(dev_dir, "ae5_strip_num_leds")
    return leds_path, num_path

def get_num_leds(num_path):
    try:
        with open(num_path, "r") as f:
            return int(f.read().strip())
    except Exception:
        return 10

def set_num_leds(num_path, n):
    try:
        with open(num_path, "w") as f:
            f.write(f"{n}\n")
    except PermissionError:
        print(f"Permission denied writing to {num_path}. Run with sudo or install udev rule.")
        sys.exit(1)

def write_leds(leds_path, color_string):
    try:
        with open(leds_path, "w") as f:
            f.write(color_string + "\n")
    except PermissionError:
        print(f"Permission denied writing to {leds_path}. Run with sudo or install udev rule.")
        sys.exit(1)

def read_leds(leds_path):
    try:
        with open(leds_path, "r") as f:
            return f.read().strip()
    except Exception as e:
        return f"Error: {e}"

def parse_color(color_arg):
    c = color_arg.lower().strip()
    if c in COLOR_MAP:
        return COLOR_MAP[c]
    if c.startswith("#"):
        return c
    if len(c) == 6 and all(ch in "0123456789abcdef" for ch in c):
        return "#" + c
    if "," in c:
        parts = [int(p.strip()) for p in c.split(",")]
        if len(parts) == 3:
            return f"#{parts[0]:02x}{parts[1]:02x}{parts[2]:02x}"
    raise ValueError(f"Unknown color format: {color_arg}")

def hsv_to_rgb(h, s, v):
    """h: 0.0-1.0, s: 0.0-1.0, v: 0.0-1.0 -> hex #RRGGBB"""
    if s == 0.0:
        r = g = b = int(v * 255)
    else:
        i = int(h * 6.0)
        f = (h * 6.0) - i
        p = v * (1.0 - s)
        q = v * (1.0 - s * f)
        t = v * (1.0 - s * (1.0 - f))
        i %= 6
        if i == 0: r, g, b = v, t, p
        elif i == 1: r, g, b = q, v, p
        elif i == 2: r, g, b = p, v, t
        elif i == 3: r, g, b = p, q, v
        elif i == 4: r, g, b = t, p, v
        else: r, g, b = v, p, q
        r, g, b = int(r * 255), int(g * 255), int(b * 255)
    return f"#{r:02x}{g:02x}{b:02x}"

def animate_rainbow(leds_path, num_leds, speed=0.03):
    print("Running Rainbow Wave animation... (Ctrl+C to stop)")
    offset = 0.0
    try:
        while True:
            frame = []
            for i in range(num_leds):
                hue = (offset + (i / num_leds)) % 1.0
                frame.append(hsv_to_rgb(hue, 1.0, 1.0))
            write_leds(leds_path, ",".join(frame))
            offset = (offset + 0.02) % 1.0
            time.sleep(speed)
    except KeyboardInterrupt:
        print("\nStopped.")

def animate_breathe(leds_path, num_leds, color_hex, speed=0.04):
    print(f"Running Breathing pulse animation with {color_hex}... (Ctrl+C to stop)")
    r_target = int(color_hex[1:3], 16)
    g_target = int(color_hex[3:5], 16)
    b_target = int(color_hex[5:7], 16)
    theta = 0.0
    try:
        while True:
            scale = (math.sin(theta) + 1.0) / 2.0 # 0.0 to 1.0
            r = int(r_target * (0.05 + 0.95 * (scale ** 2)))
            g = int(g_target * (0.05 + 0.95 * (scale ** 2)))
            b = int(b_target * (0.05 + 0.95 * (scale ** 2)))
            hex_str = f"#{r:02x}{g:02x}{b:02x}"
            write_leds(leds_path, hex_str)
            theta += 0.08
            time.sleep(speed)
    except KeyboardInterrupt:
        print("\nStopped.")

def animate_chase(leds_path, num_leds, color_hex, speed=0.06):
    print(f"Running Comet Chase animation with {color_hex}... (Ctrl+C to stop)")
    r_target = int(color_hex[1:3], 16)
    g_target = int(color_hex[3:5], 16)
    b_target = int(color_hex[5:7], 16)
    pos = 0
    try:
        while True:
            frame = []
            for i in range(num_leds):
                dist = (i - pos) % num_leds
                decay = max(0.0, 1.0 - (dist / 4.0))
                r = int(r_target * decay)
                g = int(g_target * decay)
                b = int(b_target * decay)
                frame.append(f"#{r:02x}{g:02x}{b:02x}")
            write_leds(leds_path, ",".join(frame))
            pos = (pos + 1) % num_leds
            time.sleep(speed)
    except KeyboardInterrupt:
        print("\nStopped.")

def animate_cpu(leds_path, num_leds):
    print("Running CPU Load Meter animation... (Ctrl+C to stop)")
    def get_cpu():
        with open("/proc/stat", "r") as f:
            fields = [float(column) for column in f.readline().strip().split()[1:]]
        idle, total = fields[3], sum(fields)
        return idle, total

    prev_idle, prev_total = get_cpu()
    time.sleep(0.2)
    try:
        while True:
            idle, total = get_cpu()
            d_idle = idle - prev_idle
            d_total = total - prev_total
            usage = 1.0 - (d_idle / d_total) if d_total > 0 else 0.0
            prev_idle, prev_total = idle, total

            active_leds = max(1, int(round(usage * num_leds)))
            frame = []
            for i in range(num_leds):
                if i < active_leds:
                    pct = i / max(1, num_leds - 1)
                    r = int(min(255, pct * 2.0 * 255))
                    g = int(min(255, (1.0 - pct) * 2.0 * 255))
                    frame.append(f"#{r:02x}{g:02x}00")
                else:
                    frame.append("#000000")
            write_leds(leds_path, ",".join(frame))
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("\nStopped.")

def show_udev_instructions():
    print("""
=== Setting Up Passwordless Userspace Access (Udev Rule) ===

To control the AE-5 LED strip from userspace without typing 'sudo':

1. Create a udev rule file:
   echo 'SUBSYSTEM=="hdaudio", ATTR{ae5_strip_leds}=="*", MODE="0666"' | sudo tee /etc/udev/rules.d/99-ae5-leds.rules
   echo 'SUBSYSTEM=="hdaudio", ATTR{ae5_strip_num_leds}=="*", MODE="0666"' | sudo tee -a /etc/udev/rules.d/99-ae5-leds.rules

2. Trigger udev to apply changes immediately:
   sudo udevadm control --reload-rules && sudo udevadm trigger

3. Change permissions on the current device (until next boot):
   sudo chmod 666 /sys/bus/hdaudio/devices/*/ae5_strip_*

Once configured, any user script, desktop widget, or game profile can drive the LEDs directly!
""")

def main():
    leds_path, num_path = find_ae5_sysfs()
    if not leds_path and len(sys.argv) > 1 and sys.argv[1] == "udev":
        show_udev_instructions()
        return

    if not leds_path:
        print("ERROR: Could not locate Sound BlasterX AE-5 LED controller in /sys/bus/hdaudio/devices/.")
        print("Please verify the ca0132 driver is loaded.")
        sys.exit(1)

    num_leds = get_num_leds(num_path)

    parser = argparse.ArgumentParser(description="Sound BlasterX AE-5 External RGB Strip Controller")
    sub = parser.add_subparsers(dest="command", help="Command to run")

    # set
    p_set = sub.add_parser("set", help="Set all LEDs to a solid color")
    p_set.add_argument("color", help="Color name (red, green, blue, etc.), hex (#ff0088), or r,g,b")

    # set-multi
    p_multi = sub.add_parser("set-multi", help="Set individual LED colors (comma-separated)")
    p_multi.add_argument("colors", help="List of colors, e.g. '#ff0000,#00ff00,#0000ff'")

    # off
    sub.add_parser("off", help="Turn off the LED strip")

    # status
    sub.add_parser("status", help="Show current strip configuration and colors")

    # count
    p_count = sub.add_parser("count", help="Set the active LED count")
    p_count.add_argument("num", type=int, help="Number of LEDs on strip (e.g. 10, 30, 60)")

    # animations
    sub.add_parser("rainbow", help="Run rainbow wave animation")
    
    p_breathe = sub.add_parser("breathe", help="Run breathing pulse animation")
    p_breathe.add_argument("color", nargs="?", default="cyan", help="Color to breathe (default: cyan)")

    p_chase = sub.add_parser("chase", help="Run comet chase animation")
    p_chase.add_argument("color", nargs="?", default="purple", help="Color of comet (default: purple)")

    sub.add_parser("cpu", help="Run real-time CPU usage meter animation")

    sub.add_parser("udev", help="Show instructions for passwordless userspace control")

    args = parser.parse_args()

    if not args.command or args.command == "status":
        print(f"AE-5 Controller: {os.path.dirname(leds_path)}")
        print(f"Active LEDs:    {num_leds}")
        print(f"Current State:  {read_leds(leds_path)}")
        return

    if args.command == "set":
        hex_c = parse_color(args.color)
        write_leds(leds_path, hex_c)
        print(f"Set {num_leds} LEDs to {hex_c}")

    elif args.command == "set-multi":
        raw_list = args.colors.split(",")
        parsed = [parse_color(c) for c in raw_list]
        payload = ",".join(parsed)
        write_leds(leds_path, payload)
        print(f"Set {len(parsed)} individual LEDs: {payload}")

    elif args.command == "off":
        write_leds(leds_path, "#000000")
        print("Turned strip OFF.")

    elif args.command == "count":
        set_num_leds(num_path, args.num)
        print(f"Updated active LED count to {args.num}")

    elif args.command == "rainbow":
        animate_rainbow(leds_path, num_leds)

    elif args.command == "breathe":
        hex_c = parse_color(args.color)
        animate_breathe(leds_path, num_leds, hex_c)

    elif args.command == "chase":
        hex_c = parse_color(args.color)
        animate_chase(leds_path, num_leds, hex_c)

    elif args.command == "cpu":
        animate_cpu(leds_path, num_leds)

    elif args.command == "udev":
        show_udev_instructions()

if __name__ == "__main__":
    main()
