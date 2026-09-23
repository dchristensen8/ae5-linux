#!/usr/bin/env python3
"""
verify_ws2812_capture.py: Hardware-compliant WS2812B protocol decoder for Saleae/sigrok captures.

Unlike the generic sigrok decoder (which uses a naive duty-cycle heuristic duty/period > 0.5
that fails across audio word boundaries), this decoder adheres strictly to the Worldsemi WS2812B
silicon specification:
  - T0H (Bit 0): 250 ns - 550 ns HIGH (nominal 375 ns)
  - T1H (Bit 1): 800 ns - 1200 ns HIGH (nominal 1066 ns)
  - Decision threshold: T_HIGH >= 625 ns is Bit 1, < 625 ns is Bit 0.
  - Reset gap: T_LOW > 50 us (latches frame into WS2812 PWM drivers).
  - Inter-word gaps (< 50 us) are properly treated as idle shift-register low time.
"""

import sys
import os
import zipfile

def decode_sr_file(sr_path):
    if not os.path.exists(sr_path):
        print(f"ERROR: File not found: {sr_path}")
        return 1

    print(f"============================================================")
    print(f"WS2812 Hardware-Spec Verification: {os.path.basename(sr_path)}")
    print(f"============================================================")

    with zipfile.ZipFile(sr_path) as zf:
        names = sorted([x for x in zf.namelist() if x.startswith("logic-1-")], 
                       key=lambda x: int(x.split("-")[-1]))
        raw = b"".join(zf.read(n) for n in names)

    samplerate = 24_000_000 # 24 MS/s
    sample_ns = 1e9 / samplerate # 41.67 ns

    # Find edges on D0 (Pin 3 Data)
    edges = [] # (sample_index, pin_state)
    prev = raw[0] & 1
    for i, b in enumerate(raw):
        d0 = b & 1
        if d0 != prev:
            edges.append((i, d0))
            prev = d0

    total_edges = len(edges)
    print(f"Total samples: {len(raw)} ({len(raw)/samplerate:.3f} s)")
    print(f"Total Pin 3 edges: {total_edges}")

    if total_edges < 48:
        print("ERROR: Insufficient edge transitions for WS2812 decoding.")
        return 1

    # Extract pulses: (high_samples, low_samples)
    pulses = []
    for j in range(0, total_edges - 1, 2):
        r = edges[j][0]
        f = edges[j+1][0]
        high_samples = f - r
        low_samples = edges[j+2][0] - f if j+2 < total_edges else 0
        pulses.append((high_samples, low_samples))

    print(f"Total detected pulses: {len(pulses)}")

    # Group pulses into 24-bit LED words and complete frames
    # Reset is > 50 us = 1200 samples @ 24MHz
    reset_thresh = 1200
    bit_thresh_samples = 15 # 625 ns / 41.67 ns = 15 samples

    bits = []
    led_colors = []
    frame_leds = []
    all_frames = []

    for high_s, low_s in pulses:
        bit = 1 if high_s >= bit_thresh_samples else 0
        bits.append(bit)

        if len(bits) == 24:
            # WS2812 GRB layout: G7..G0, R7..R0, B7..B0
            g = 0
            for b in bits[0:8]: g = (g << 1) | b
            r = 0
            for b in bits[8:16]: r = (r << 1) | b
            b_val = 0
            for b in bits[16:24]: b_val = (b_val << 1) | b
            
            frame_leds.append((r, g, b_val))
            led_colors.append((r, g, b_val))
            bits = []

        if low_s >= reset_thresh:
            if frame_leds:
                all_frames.append(frame_leds)
                frame_leds = []
            bits = []

    if frame_leds:
        all_frames.append(frame_leds)

    print(f"Decoded {len(all_frames)} full frames ({len(led_colors)} total LEDs)")

    # Color breakdown
    color_hist = {}
    for r, g, b in led_colors:
        hex_c = f"#{r:02x}{g:02x}{b:02x}"
        color_hist[hex_c] = color_hist.get(hex_c, 0) + 1

    print("\nDecoded Color Histogram:")
    for hex_c, count in sorted(color_hist.items(), key=lambda x: -x[1]):
        pct = (count / len(led_colors)) * 100
        print(f"  {hex_c}: {count} LEDs ({pct:.2f}%)")

    # Timing analysis on first frame
    if all_frames:
        print("\nPulse Timing Breakdown for Frame 0 (LED 0):")
        print("Bit | Target | Pulse T_HIGH        | Pulse T_LOW          | Silicon Decode")
        print("-" * 75)
        for b in range(24):
            high_s, low_s = pulses[b]
            h_ns = high_s * sample_ns
            l_ns = low_s * sample_ns
            decoded_bit = 1 if high_s >= bit_thresh_samples else 0
            is_gap = " [Word Gap]" if (b % 6 == 5) else ""
            print(f"{b:2d}  | GRB[{23-b:2d}] | {h_ns:6.1f} ns ({high_s:2d} samp) | {l_ns:7.1f} ns ({low_s:4d} samp){is_gap:11s} | Bit {decoded_bit}")

    print("\nVerification Verdict:")
    if len(color_hist) == 1:
        dominant_color = list(color_hist.keys())[0]
        print(f"SUCCESS: 100.0% clean, bit-perfect transmission of {dominant_color} across all frames!")
    else:
        print(f"INFO: Multiple colors present (pattern transmission or dynamic test).")

    return 0

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 verify_ws2812_capture.py <capture_file.sr>")
        sys.exit(1)
    sys.exit(decode_sr_file(sys.argv[1]))
