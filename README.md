# Sound BlasterX AE-5 / AE-5 Plus Linux Driver & Tools

Kernel driver patch and userspace tools for Creative Sound BlasterX AE-5 and AE-5 Plus RGB lighting control on Linux.

Supports both lighting zones:
1. **On-Card LEDs (Zone 0):** 5 cascaded APA102 (DotStar) addressable LEDs bit-banged via PCIe BAR2 GPIO registers.
2. **External ARGB Strip (Zone 1):** 3-pin 5V header driving WS2812B (Neopixel) strips up to 100 LEDs via the CA0113 HDA link sniffer transport.

---

## Hardware Architecture & Transport Discovery

The Sound BlasterX AE-5 uses a dual-chip architecture:
- **CA0113:** PCIe-to-HD-Audio bus bridge.
- **CA0132:** Sound Core3D audio DSP.

### Internal APA102 LEDs
The five on-board LEDs are wired to a dedicated GPIO register in PCIe BAR2 at offset `0x320`. They are driven by standard SPI bit-banging (`LED_BIT_HIGH=0x102`, `LED_BIT_LOW=0x02`, `LED_CLOCK_HIGH=0x103`, `LED_CLOCK_LOW=0x03`).

### External WS2812B Strip
The external addressable header does **not** use the CA0132 DSP or MMIO GPIO. Instead, the CA0113 bridge contains an autonomous hardware HDA link sniffer and serializer:
- The host configures dynamic stream tag routing in CA0113 register `BAR2 + 0x104` (Byte 0 = Data Pin 3, Byte 1 = Clock Pin 2).
- Output serializers and drive buffers are enabled across `BAR2 0x100..0x514`.
- When an HDA DMA audio stream with the matching stream tag is sent across the link, the CA0113 hardware snoops the frame payload, extracts the 24-bit GRB color data, and serializes it as 800 kHz single-wire NRZ pulses output to the 3-pin header.

Waveform timing and signal integrity have been validated using a 24 MS/s Saleae logic analyzer, confirming 100.00% WS2812B protocol compliance.

---

## Kernel Module (`snd-hda-codec-ca0132`)

The patched `snd-hda-codec-ca0132` module exposes external strip controls via standard ALSA card controls:

* `AE-5 LED Strip`: 300-byte volatile `BYTES` control holding up to 100 RGB triplets (Red, Green, Blue bytes per LED).
* `AE-5 LED Strip Count`: Volatile `INTEGER` control (range 1–100) setting the number of active LEDs on the strip.

Because these controls use `IFACE_CARD` and `SNDRV_CTL_ELEM_ACCESS_VOLATILE`, changes do not wake up audio daemons (PipeWire / PulseAudio) or trigger `alsactl store/restore`.

### Building and Loading

```bash
cd kbuild
make
sudo ../reload-ae5.sh
```

---

## OpenRGB Integration

OpenRGB native Linux support communicates directly with this driver interface:
- **Zone 0 (Internal):** MMIO mapping of PCIe BAR2 (`/dev/mem` or `resource2`).
- **Zone 1 (External Strip):** Native ALSA control ioctls on `/dev/snd/controlC*` targeting `"AE-5 LED Strip"` and `"AE-5 LED Strip Count"` (with legacy sysfs fallback).

### udev Rules (`/etc/udev/rules.d/99-creative-ae5.rules`)

```udev
# Creative Sound BlasterX AE-5 BAR2 MMIO access (for Zone 0 on-card LEDs)
SUBSYSTEM=="pci", ATTRS{vendor}=="0x1102", ATTRS{device}=="0x0012", RUN+="/bin/chmod 0666 /sys$env{DEVPATH}/resource2"
```

Reload rules with:
```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
```

---

## Standalone Tools

- `ae5-led.py`: Standalone Python CLI to control strip colors and run test animations.
- `verify_ws2812_capture.py`: Logic analyzer trace decoder and timing validator.
