# Sound BlasterX AE-5 / AE-5 Plus Linux Driver & OpenRGB Guide

Complete Linux kernel driver patch, setup guide, and OpenRGB support for the **Creative Sound BlasterX AE-5** and **AE-5 Plus** (`1102:0012`).

Supports both hardware lighting zones:
1. **Zone 0 (On-Card LEDs):** 5 cascaded APA102 (DotStar) addressable LEDs bit-banged via PCIe BAR2 MMIO registers.
2. **Zone 1 (External ARGB Strip):** 3-pin 5V header driving WS2812B (NeoPixel) strips up to 100 LEDs via autonomous CA0113 HDA link sniffer DMA serialization.

---

## Quick Start / Step-by-Step Installation

Follow these steps to get the driver and OpenRGB running on your machine.

### Step 1: Install Build Prerequisites

#### Arch Linux / Manjaro / Omarchy:
```bash
sudo pacman -S base-devel linux-headers git qt5-base libusb hidapi mbedtls
```

#### Ubuntu / Debian / Pop!_OS:
```bash
sudo apt update
sudo apt install build-essential linux-headers-$(uname -r) git \
    qtbase5-dev qtchooser qt5-qmake qtbase5-dev-tools \
    libusb-1.0-0-dev libhidapi-dev libmbedtls-dev
```

#### Fedora:
```bash
sudo dnf install @development-tools kernel-devel git \
    qt5-qtbase-devel libusb1-devel hidapi-devel mbedtls-devel
```

---

### Step 2: Install udev Rules for OpenRGB Access

Zone 0 (on-card LEDs) requires access to the card's PCIe BAR2 resource file. Create a udev rule so OpenRGB does not need to run as root:

```bash
sudo tee /etc/udev/rules.d/99-creative-ae5.rules << 'EOF'
# Creative Sound BlasterX AE-5 BAR2 MMIO access (for Zone 0 on-card LEDs)
SUBSYSTEM=="pci", ATTRS{vendor}=="0x1102", ATTRS{device}=="0x0012", RUN+="/bin/chmod 0666 /sys$env{DEVPATH}/resource2"
EOF

sudo udevadm control --reload-rules && sudo udevadm trigger
```

> **Note on Zone 1 (External Strip):** Zone 1 uses standard ALSA card controls (`/dev/snd/controlC*`), which are already accessible to logged-in desktop users by default via systemd ACLs.

---

### Step 3: Build & Load the Patched Kernel Driver

Clone this repository and compile the out-of-tree kernel module:

```bash
git clone https://github.com/dchristensen8/ae5-linux.git
cd ae5-linux/kbuild
make
```

Reload the driver using the included reload script:
```bash
sudo ../reload-ae5.sh
```

#### Verify the ALSA Controls
Check that ALSA has exposed the strip controls on the Creative card:
```bash
amixer -c Creative controls | grep -i "AE-5 LED Strip"
```

You should see:
```text
numid=...,iface=CARD,name='AE-5 LED Strip'
numid=...,iface=CARD,name='AE-5 LED Strip Count'
```

#### Test Strip Illumination (Optional CLI Check)
You can directly illuminate the external strip from the command line without OpenRGB:
```bash
# Set external strip to 10 LEDs
amixer -c Creative cset iface=CARD,name='AE-5 LED Strip Count' 10

# Set first 3 LEDs to Red, Green, Blue (values are RGB triplets)
amixer -c Creative cset iface=CARD,name='AE-5 LED Strip' 255,0,0,0,255,0,0,0,255
```

---

### Step 4: Build & Install OpenRGB with AE-5 Support

Clone the OpenRGB branch containing native AE-5 Linux support:

```bash
git clone -b creative-ae5-linux-support https://gitlab.com/fairlite/OpenRGB.git
cd OpenRGB
qmake OpenRGB.pro
make -j$(nproc)
sudo make install
```

*(Alternatively, copy the compiled executable directly: `sudo install -m 755 openrgb /usr/local/bin/openrgb`)*

---

### Step 5: Launch OpenRGB & Configure LEDs

1. **Detect Devices via CLI:**
   ```bash
   openrgb --list-devices
   ```
   You should see:
   ```text
   0: Creative SoundBlaster AE-5 (or AE-5 Plus)
     Type:           Speaker
     Description:    Creative SoundBlaster AE-5 Device
     Location:       PCI: 0000:xx:00.0
     Modes:          [Direct]
     Zones:          'Internal' (5 LEDs), 'Addressable RGB Header' (10 LEDs)
   ```

2. **Launch the OpenRGB GUI:**
   ```bash
   openrgb
   ```

3. **Configure Strip Length (Zone 1):**
   - Click on the **Information** tab or select **Addressable RGB Header**.
   - Click **Resize** to set the exact number of LEDs on your connected strip (supports 1 to 100 LEDs).
   - Click **Save Size**. The driver and hardware strip synchronize immediately.

4. **Animations & Effects:**
   - Use the **Effects** tab (OpenRGB Effects Plugin) to run effects like Rainbow Wave, Audio Visualizer, Breathing, or Gradient Morphs at 60 FPS.
   - The asynchronous background writer in the driver guarantees that continuous WS2812B frame transfers never stall OpenRGB or cause audio dropouts.

---

## Making the Driver Persistent Across Reboots

When your machine reboots, the kernel will load the in-tree stock `snd-hda-codec-ca0132` module unless replaced or updated.

### Option A: Install Module into Kernel Directory (Recommended)
Replace the active kernel's default ca0132 module with the patched build:

```bash
# Backup stock module
sudo cp /lib/modules/$(uname -r)/kernel/sound/pci/hda/snd-hda-codec-ca0132.ko.zst \
        /lib/modules/$(uname -r)/kernel/sound/pci/hda/snd-hda-codec-ca0132.ko.zst.bak 2>/dev/null || true

# Compress and install patched module (zstd for modern kernels)
zstd -f kbuild/snd-hda-codec-ca0132.ko -o /tmp/snd-hda-codec-ca0132.ko.zst
sudo cp /tmp/snd-hda-codec-ca0132.ko.zst /lib/modules/$(uname -r)/kernel/sound/pci/hda/
sudo depmod -a
```

*(Note: On systems not using zstd module compression, simply copy `snd-hda-codec-ca0132.ko` directly).*

### Option B: Quick Reload Script
Alternatively, keep `reload-ae5.sh` handy and run `sudo ./reload-ae5.sh` whenever you need to reload the driver after boot.

---

## Hardware Architecture & Technical Details

For developers, kernel hackers, or curious engineers, here is how the Sound BlasterX AE-5 RGB architecture operates:

The Sound BlasterX AE-5 uses a dual-chip architecture:
- **CA0113:** PCIe-to-HD-Audio bus bridge.
- **CA0132:** Sound Core3D audio DSP.

### Internal APA102 LEDs (Zone 0)
The five on-board LEDs are wired to a dedicated GPIO register in PCIe BAR2 at offset `0x320`. They are driven by standard SPI bit-banging (`LED_BIT_HIGH=0x102`, `LED_BIT_LOW=0x02`, `LED_CLOCK_HIGH=0x103`, `LED_CLOCK_LOW=0x03`).

### External WS2812B Strip (Zone 1)
The external addressable header does **not** use the CA0132 DSP or MMIO GPIO. Instead, the CA0113 bridge contains an autonomous hardware HDA link sniffer and serializer:
- The host configures dynamic stream tag routing in CA0113 register `BAR2 + 0x104` (Byte 0 = Data Pin 3, Byte 1 = Clock Pin 2).
- Output serializers and drive buffers are enabled across `BAR2 0x100..0x514`.
- When an HDA DMA audio stream with the matching stream tag is sent across the link, the CA0113 hardware snoops the frame payload, extracts the 24-bit GRB color data, and serializes it as 800 kHz single-wire NRZ pulses output to the 3-pin header.

Waveform timing and signal integrity have been validated using a 24 MS/s Saleae logic analyzer, confirming 100.00% WS2812B protocol compliance.

### ALSA Control Element Interface
Following ALSA upstream maintainer review, the external strip is exposed via two card controls:
- `"AE-5 LED Strip"`: 300-byte volatile `BYTES` control holding up to 100 RGB triplets.
- `"AE-5 LED Strip Count"`: Volatile `INTEGER` control (range 1–100).
- Configured with `IFACE_CARD` and `SNDRV_CTL_ELEM_ACCESS_VOLATILE` so frequent 60 Hz frame updates never wake up audio daemons (PipeWire / PulseAudio) or pollute `alsactl store/restore`.

---

## Standalone Diagnostics & Scripts

- `reload-ae5.sh`: Safe reload script that pauses audio daemons, swaps modules, and verifies controls.
- `ae5-led.py`: Standalone Python CLI to control strip colors and run test animations without OpenRGB.
- `verify_ws2812_capture.py`: Logic analyzer trace decoder and timing validator.
- `submission/`: Contains the upstream Linux kernel patch (`v2-0001-ALSA-hda-ca0132-Add-Sound-BlasterX-AE-5-external-.patch`) submitted to the ALSA sound subsystem.
