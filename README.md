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

The patched `snd-hda-codec-ca0132` module adds sysfs attributes under the codec device:

* `/sys/bus/hdaudio/devices/hdaudioC*D*/ae5_strip_leds`: Write comma-separated `#RRGGBB` hex color values.
* `/sys/bus/hdaudio/devices/hdaudioC*D*/ae5_strip_num_leds`: Read/write configured LED count.
* `/sys/bus/hdaudio/devices/hdaudioC*D*/ae5_strip_test`: Trigger hardware diagnostic pattern.

### Building and Loading

```bash
cd kbuild
make
sudo rmmod snd_hda_codec_ca0132
sudo insmod snd-hda-codec-ca0132.ko
```

---

## OpenRGB Integration

OpenRGB native Linux support communicates directly with this driver interface:
- **Zone 0:** MMIO mapping of PCIe BAR2 (`resource2`).
- **Zone 1:** Persistent sysfs writes to `ae5_strip_leds`.

### udev Rules (`/etc/udev/rules.d/99-creative-ae5.rules`)

```udev
# Creative Sound BlasterX AE-5 BAR2 MMIO access
SUBSYSTEM=="pci", ATTRS{vendor}=="0x1102", ATTRS{device}=="0x0012", RUN+="/bin/chmod 0666 /sys$env{DEVPATH}/resource2"

# Creative Sound BlasterX AE-5 external strip sysfs access
SUBSYSTEM=="hdaudio", ATTR{ae5_strip_leds}!="", RUN+="/bin/chmod 0666 /sys$env{DEVPATH}/ae5_strip_leds /sys$env{DEVPATH}/ae5_strip_num_leds"
```

Reload rules with:
```bash
sudo udevadm control --reload-rules && sudo udevadm trigger
```

---

## Standalone Tools

- `ae5-led.py`: Standalone Python CLI to control strip colors and run test animations.
- `verify_ws2812_capture.py`: Logic analyzer trace decoder and timing validator.
