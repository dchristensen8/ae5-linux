#!/usr/bin/env python3
"""
rainbow-wave.py: Smooth, vibrant Rainbow Wave animation for Sound BlasterX AE-5 RGB LED strip.

Features:
  - 30-40 FPS silky-smooth animation.
  - Perceptual gamma correction (gamma=2.2) for rich, saturated colors.
  - Live ANSI Truecolor terminal preview of the strip in real time.
  - Configurable speed, brightness, wavelength/spread, and direction.
  - Graceful exit on Ctrl+C.
"""

import os
import sys
import time
import glob
import math
import argparse

# Gamma correction lookup table (gamma = 2.2)
GAMMA_TABLE = [int(((i / 255.0) ** 2.2) * 255.0 + 0.5) for i in range(256)]

def find_ae5_sysfs():
    nodes = glob.glob("/sys/bus/hdaudio/devices/*/ae5_strip_leds")
    if not nodes:
        return None, None
    leds_path = nodes[0]
    num_path = os.path.join(os.path.dirname(leds_path), "ae5_strip_num_leds")
    return leds_path, num_path

def get_num_leds(num_path):
    try:
        with open(num_path, "r") as f:
            return int(f.read().strip())
    except Exception:
        return 10

def hsv_to_rgb(h, s=1.0, v=1.0, gamma=True):
    """Convert HSV (0..1) to RGB (0..255) with optional gamma correction."""
    h = h % 1.0
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
    
    r_byte = int(r * 255)
    g_byte = int(g * 255)
    b_byte = int(b * 255)

    if gamma:
        r_byte = GAMMA_TABLE[max(0, min(255, r_byte))]
        g_byte = GAMMA_TABLE[max(0, min(255, g_byte))]
        b_byte = GAMMA_TABLE[max(0, min(255, b_byte))]

    return r_byte, g_byte, b_byte

def main():
    parser = argparse.ArgumentParser(description="Sound BlasterX AE-5 Rainbow Wave Animation")
    parser.add_argument("-n", "--num", type=int, default=None, help="Number of LEDs on strip (default: autodetect)")
    parser.add_argument("-s", "--speed", type=float, default=1.0, help="Wave speed multiplier (default: 1.0)")
    parser.add_argument("-b", "--brightness", type=float, default=1.0, help="Brightness (0.1 to 1.0, default: 1.0)")
    parser.add_argument("-c", "--cycles", type=float, default=1.0, help="Number of full rainbow cycles along the strip (default: 1.0)")
    parser.add_argument("-r", "--reverse", action="store_true", help="Reverse wave direction")
    parser.add_argument("--no-gamma", action="store_true", help="Disable perceptual gamma correction")
    parser.add_argument("--off-on-exit", action="store_true", default=True, help="Turn off LEDs when stopping (default: True)")

    args = parser.parse_args()

    leds_path, num_path = find_ae5_sysfs()
    if not leds_path:
        print("ERROR: Sound BlasterX AE-5 controller not found in /sys/bus/hdaudio/devices/.")
        sys.exit(1)

    num_leds = args.num if args.num else get_num_leds(num_path)
    brightness = max(0.05, min(1.0, args.brightness))
    gamma = not args.no_gamma
    direction = -1.0 if args.reverse else 1.0

    print("=======================================================")
    print(" 🌈 Sound BlasterX AE-5 Smooth Rainbow Wave Controller")
    print(f" Strip: {num_leds} LEDs | Speed: {args.speed}x | Brightness: {int(brightness*100)}%")
    print(" Press Ctrl+C at any time to stop.")
    print("=======================================================\n")

    # Keep sysfs node open and use seek(0) for ultra-low latency updates
    try:
        f = open(leds_path, "w")
    except PermissionError:
        print(f"ERROR: Permission denied writing to {leds_path}.")
        print("Run with sudo or apply the udev rule from: ./ae5-led.py udev")
        sys.exit(1)

    offset = 0.0
    # Step size per frame
    step = 0.015 * args.speed * direction
    frame_count = 0
    t_start = time.time()

    try:
        while True:
            t_frame_start = time.time()
            hex_colors = []
            ansi_preview = []

            for i in range(num_leds):
                # Calculate hue position along the strip
                hue = (offset + (i / num_leds) * args.cycles) % 1.0
                r, g, b = hsv_to_rgb(hue, s=1.0, v=brightness, gamma=gamma)
                hex_colors.append(f"#{r:02x}{g:02x}{b:02x}")
                # Truecolor terminal block for visual preview
                ansi_preview.append(f"\033[48;2;{r};{g};{b}m  \033[0m")

            payload = ",".join(hex_colors) + "\n"
            f.seek(0)
            f.write(payload)
            f.flush()

            offset = (offset + step) % 1.0
            frame_count += 1

            # Print animated terminal preview on one line
            sys.stdout.write(f"\r  Strip: [{' '.join(ansi_preview)}] ({frame_count / max(0.1, time.time() - t_start):4.1f} FPS)")
            sys.stdout.flush()

            # Target ~35 FPS (sleep remaining delta if needed)
            elapsed = time.time() - t_frame_start
            sleep_time = max(0.001, 0.028 - elapsed)
            time.sleep(sleep_time)

    except KeyboardInterrupt:
        print("\n\nStopping animation...")
    finally:
        if args.off_on_exit:
            f.seek(0)
            f.write("#000000\n")
            f.flush()
            print("LED strip turned off.")
        f.close()

if __name__ == "__main__":
    main()
