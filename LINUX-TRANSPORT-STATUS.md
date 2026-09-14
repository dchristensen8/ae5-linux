# AE-5 External LED Strip — Linux Transport: Current State & Open Wall

**Goal:** Drive the Sound BlasterX AE-5's external WS2812B LED strip from Linux.
**Card:** Creative Sound BlasterX AE-5 (base), PCI `1102:0012`, Sound Core3D (ca0132) DSP.
**Context:** Long-running reverse-engineering effort. A parallel Windows-side instance
reverse-engineered the Creative Windows drivers (`CtxHda.sys`/`CtxHdb.sys`) with kernel
hooks. This doc is for a fresh engineer to pick up the Linux side.

---

## 1. What is CONFIRMED (reverse-engineered + validated on hardware)

1. **The strip is DSP-driven**, not a host GPIO. There is no GPIO bit that drives it.
2. **Encoding is byte-exact** (validated): each LED pixel -> 30-bit words.
   - 48 kHz path: 4 words/pixel, per-bit `0x800`(0)/`0xE00`(1) -> `0x888...`/`0xEEE...`.
   - 96 kHz path: 8 words/pixel, per-bit `0xC000`/`0xFC00`.
3. **The card consumes encoded frames from a 0x8000-byte (32KB) SYSTEM-RAM ring.**
   - The card's DMA reads the ring and publishes its read-position in a BAR2 MMIO
     register at offset `+0x6104` (on the reference box: BAR2 `0xf43f8000`, phys
     `0xf43fe104`).
   - Windows writes a frame (40-byte preamble + encoded words) at `(pos + 0xA8) % 0x8000`,
     polls `+0x6104` until it advances past the frame, then **zero-fills the ring**
     (the WS2812 reset gap).
4. **The strip stream is "stream 0x18"**: the in-tree Linux driver `ca0132.c`
   (`ae5_post_dsp_stream_setup()`) already configures stream 0x18 = source conn point
   `0x9` -> dest `0xd0`, 6 channels, 96 kHz, stream control on, `CONTROL_PARAM_ASI`.
   The source comment in the kernel literally says ASI "is used to change colors on
   the external LED strip."
5. **The Windows descriptor/ring is set up through the COM/vtable layer**
   (`bufBase`/`ringSize`/`posPtr` object fields; ring base from a buffer query, size
   returned by a vtable method). The address where the card is told the ring base is
   the one thing the Windows capture did NOT definitively pin.

## 2. The transport question that everything hinges on

The senior engineer consulted (via this effort) reframed the mechanism:
**Sound Core3D has no PCI-master/sideband DMA.** Its only host-RAM<->DSP data path is
the **HD-link, driven by the azx HDA controller**. Therefore the "0x8000 system-RAM
ring the card DMAC reads" is almost certainly the **host-side HDA stream ring buffer
(BDLE)**, and the "position register at BAR2+0x6104" is the DSP mirroring its own
consumption counter. Conclusion: **the missing piece is a real azx HDA stream with a
BDLE + started DMA** — not a codec-side ring descriptor.

That is the model being tested: get a genuine azx *playback* stream feeding stream
0x18, and the card reads it.

## 3. What I built / tried on Linux (all failed to make the strip react)

Build environment: fetched the exact running kernel source (Arch `7.1.9.arch1-2`,
based on linux-stable v7.1.9), build the ca0132 codec module out-of-tree, and swap it
in (unbind codec -> rmmod built-in -> insmod modified -> rebind).

1. **Standalone module** (`ae5-strip.ko`): discovers the AE-5 codec
   (`pci_get_device` -> `device_find_child` -> `hdaudioC0D1`), encodes correctly
   (verified word counts). No MMIO risk.
2. **Host-stream feed** via exported `snd_hda_codec_load_dsp_prepare()` (allocates an
   HDA stream + 0x8000 buffer, returns a stream tag) + `snd_hda_codec_load_dsp_trigger()`.
   Routed via `AC_VERB_SET_CHANNEL_STREAMID` on WIDGET_CHIP_CTRL (0x15) and via
   `snd_hda_codec_setup_stream(codec, 0x9, tag, ...)`. **No reaction.**
   *(Senior engineer: this never creates a real BDLE / starts azx DMA, so no data
   crossed the HD-link — i.e. it was never a valid test.)*
3. **Real azx playback PCM** (the senior engineer's P1): added a **"CA0132 Strip"
   playback PCM (device 4)** to `ca0132.c`, real azx DMA via the PCM layer. Tried:
   - converter NID **0x9**: `set_params` fails (0x9 is NOT a valid HDA converter;
     the "0x9" is a DSP *port*, not a NID).
   - converter NID **0x15** (WIDGET_CHIP_CTRL): plays cleanly, no error.
   - **2-channel** and **6-channel**, S32_LE, 96 kHz — both play cleanly.
   - **Still no strip reaction.**

So: a real azx DMA stream now plays through the card without error, but the data does
not reach the strip.

## 4. The current open question (the wall)

When a host HDA stream plays through the "Strip" PCM (converter NID 0x15), the data
enters the DSP — but it does **not** reach stream 0x18's source port `0x9`. The missing
link is: **what routes an incoming HDA host stream to a specific ca0132 DSP stream's
source connection point?**

Candidates (from `ca0132.c`):
- **(a)** The XRAM remap table at `0x1578` maps ChipIO streamIDs -> `0x190000` port
  offsets. Perhaps my stream's tag must be explicitly mapped to source port 0x9.
- **(b)** `chipio_set_stream_source_dest(codec, 0x18, src, 0xd0)` must be re-issued with
  the correct source, or the incoming stream must be routed to source 0x9.
- **(c)** `codec_set_converter_stream_channel` on a specific NID + stream-control param.
- The DSP-firmware-download path works with just
  `codec_set_converter_stream_channel(WIDGET_CHIP_CTRL, stream_id)` — but the firmware
  loader consumes on a special stream, whereas LED stream 0x18 may need the incoming
  data explicitly mapped to source port 0x9.

## 5. Files / artifacts

- `/home/christensen/dev/ae5-linux/` — project root.
  - `ae5-strip.c` — standalone helper module (codec discovery + encoding).
  - `LINUX-IMPLEMENTATION-PLAN.md` — the staged plan (doc -> standalone -> in-tree).
  - `windriver/AE-5-protocol-capture.md` — the resolved transport (Windows captures).
  - `windriver/decomp/` — decompiled CtxHda.sys functions.
  - `led_encoder96.py`, `gen96.py` — 96 kHz encoder + WAV/stream generators.
- `/tmp/opencode/ca0132build/ca0132.c` — the **modified in-tree ca0132.c** with the
  "CA0132 Strip" PCM added (built out-of-tree to `snd-hda-codec-ca0132.ko`).
- `/tmp/opencode/ksrc/` — the full v7.1.9 kernel source (sound/ checked out).
- Windows drive `/run/media/christensen/067039B47039AAF7/Users/b/Desktop/ae5-capture/`
  — the Windows-side deliverables (HANDOFF.md, LINUX-DESCRIPTOR-HANDOFF.md, etc.).

## 6. What the next person should do

The single most useful next step is to **determine how the incoming HDA host stream
connects to ca0132 DSP stream 0x18's source port 0x9** (remap table 0x1578 vs
`chipio_set_stream_source_dest` vs a stream-control/verb). Two parallel routes:

1. **Linux (preferred):** RE the `ca0132.c` stream-remap machinery
   (`chipio_remap_stream`, the `0x1578` table, `CONTROL_PARAM_STREAM_ID`/source/dest),
   and figure out what the "Strip" PCM's `prepare()` must call to route the host stream
   to source port 0x9. Verify the azx stream actually delivers to the DSP.
2. **Windows (ground truth, last resort):** have the `ae5hook5` driver capture the exact
   descriptor/ring write AND the stream routing calls at init and per-frame, to pin
   whether it's an azx BDLE stream (and which tag/NID/port mapping) vs a codec-side
   chipio descriptor.

**Card safety:** the AE-5 hangs/reboots on unknown BAR2 MMIO reads (verified twice).
Prefer codec-verb/ALSA-level work over raw MMIO. The internal (APA102) LEDs already
work via BAR2 GPIO; only the external WS2812 strip is unsolved.
## 2026-09-08 23:50 — DMA CHANNEL TRANSPORT NOW WORKS; STRIP STILL DARK

### What was found
- Root cause of the earlier "hang": the sysfs attr `ae5_strip_test` was created in ca0132_init but NEVER removed on unbind (`device_remove_file` missing). On every reload the fresh module got `-EEXIST`, so the file's store pointer pointed at the FIRST (unloaded) module's function = stale/dangling. The "hang at load_dsp_prepare" was almost certainly writing through that stale store, NOT a real hang in `snd_hdac_dsp_prepare`. Fixed: `device_remove_file` added to `ca0132_codec_remove`.
- After reboot + clean attr: `snd_hdac_dsp_prepare()` (low-level azx stream setup, bypassing the firmware wrapper) works post-init on a free azx stream.
- Missing transport steps found by mirroring dspxfr (firmware-load path) exactly:
   1. `codec_set_converter_format(codec, WIDGET_CHIP_CTRL, snd_hdac_stream_format(6,32,96000))`
   2. `dsp_allocate_ports_format(codec, fmt, &port_map_mask)`  -> yields real AUDCHSEL mask (0xfff00 here)
   3. `codec_set_converter_stream_channel(codec, WIDGET_CHIP_CTRL, stream_tag, 0)`
   4. `dsp_dma_stop/setup_common(port_map_mask)/setup/start` + `snd_hdac_dsp_trigger(hstr, true)` as the source start
- WITHOUT ports+converter+stream-bind (port_map_mask=0): DMA channel armed but starved forever (active=1 after 100 polls).
- WITH them: DMA completes instantly. Full-ring burst test: 3x transfers of 0x2000 words (0x400 red pixels) each completed in ~40-60ms. Driver: `-dma5` (module `snd-hda-codec-ca0132-dma5.ko`).

### The wall
- Even with the full transport moving real data to destination 0x190080 (DBADR=0x40, validated), the external WS2812B strip shows ZERO reaction (user watching).
- Triangulated negatives, ALL to 0x190080, all dead:
   1. raw `chipio_write_multiple` (zero preamble + encoded words)
   2. real azx PCM playback 6ch/96k on NID 0x15
   3. chipio stream-control arm 0x18 before write
   4. DSP DMAC full-ring transfers (now, with correct routing)
- Encode is byte-exact vs Windows (0x800/0xE00 words, 8 words/pixel at 96k).

### Leading hypothesis
The Windows driver does a host-ring handshake that we do NOT replicate:
  destPhys host ring (0x9ce52000, ring 0x8000) -> position poll -> COMMIT KICK -> zero-fill
The DSP firmware's LED consumer likely only drains the ring when the position/commit protocol advances ("frame N ready"). Raw writes/DMA just park data where nothing reads it.
Barrier: BAR2 is only 16K on this Linux box, so the Windows position register (BAR2+0x6104) read HANGS the PCI bus here. Need: (a) confirm 0x190080 is really the LED consumer (vs some other stream/port), (b) what exactly the commit-kick writes, and (c) whether position/advance is reachable via a CHIPIO-addressable window instead of BAR2.

### Modules preserved (~/dev/ae5-linux/)
- snd-hda-codec-ca0132-dma5.ko : current (full routing, full-ring red, 3 bursts, device_remove_file)
- -dma4 : full routing single-pixel
- -dma3 : source-bypass + device_remove_file (no ports)
- -dma, -armed, -visual, -frame, -test, -dryrun : earlier
Build dir: ~/dev/ae5-linux/kbuild/ (persistent)

### Refinement from Windows captures (ae5hook5 + windriver RE) — the per-frame handshake
- ae5hook5 commit record confirms: posPtr/posPhys = **0xF43FE104 (= BAR2+0x6104)**; memcpy dest (=bufPhys 0x9ce52000) is the HOST system-RAM ring that the DSP DMAs. Encoded words in the captured src match our 0x800/0xE00 encoding byte-for-byte.
- The DSP-facing target buffer is obj+0x10 (ring base 0x9ce52000 in system RAM lives there); obj+0x14 = LedB encoded source; the driver copies encoded->ring at (pos+delta)%0x8000.
- Per-frame state machine we do NOT replicate:
  1. frame -> host ring         (we DO: azx BDLE ring + DSP DMAC)
  2. spin-wait position (BAR2+0x6104) advancing   (NOT READABLE on this box: BAR2 16K)
  3. **commit DMA kick [vt+0x48]** per frame      (NEVER IDENTIFIED at register level)
  4. zero-fill ring for WS2812 reset gap
- Commit fn CtxHda 0x31D80/0x161D30; descriptor/target programmed via vtable [vt+0x28]/[vt+0x60] with DSP command IDs 0x70D, 0x70B, 0xF0C, 0x70C, 0xF0B, 0x0D — issueable via ca0132's dspio_send/dspio_write (VENDOR_DSPIO SCP verbs present in-tree).
- ASK ENGINEER: (1) what does [vt+0x48] kick actually WRITE (does it depend on position VALUE or just 'advanced'?); (2) can DMAC-completion surrogate replace the position read?; (3) is 0x190080 really the DSP consumption port or is the DSP-facing buffer elsewhere; (4) can the azx stream's own LPIB/posbuf feed the DSP's position requirement if it consumes continuously?

## 2026-09-09 00:30 — [vt+0x48] RESOLVED VIA PRIMARY DISASSEMBLY (answers Q1)

Ghidra on windriver/CtxHda.sys (base 0x10000; RVA=addr-0x10000; hook base fffff8049b130000 → vt RVA 0x104510 → addr 0x114510):
- [vt+0x48] slot @ 0x114558 = **FUN_00041d30** (the hook's `commit=0x31D30`).
- FUN_00041d30 = `if (obj->buf) FUN_00043860(buf, 0, ringSize)`.
- FUN_00043860 = **optimized memset** (`(c&0xff)*0x0101...` qword fill) == the `fill_ring_tail` RVA 0x3385D from earlier RE (same codegen, tail entry).
- ==> **The commit kick is NOT a register/DSP write. It ZERO-FILLS the entire 0x8000 host ring = the WS2812 reset gap. Takes no position value.**

Full per-frame state machine (FUN_00042650 dispatch):
- obj+0x13 != 0 → ring/DMA mode FUN_00041d80: memcpy frame→ring at (pos+[0xA8])%0x8000, wait `*(obj+0x90)` (BAR2+0x6104) advance, then [vt+0x48] = memset(ring,0,0x8000).
- obj+0x13 == 0 → stream mode FUN_00042674: drive stream objects obj+0x78 (vt +0x50/+0x68) and obj+0x10 (vt +0x28/+0x30/+0x18), wait `**(obj+0x90)` >= frameLen.
- Both modes read the position pointer live; position = consumption watermark ONLY (no register the kick depends on).

Vtable slot map (@ 0x114510): +0x00=0x42360 +0x08=0x418bc +0x10=0x41900 +0x18=0x4196c +0x20=0x419ac +0x28=0x419a0 +0x30=0x41870 +0x38=0x423e8 +0x40=0x425e4 +0x48=0x41d30(kick/memset) +0x50=0x42650(dispatch) +0x58=0x42784 +0x60=0x4282c +0x68=0x42944.

Issue for Linux (per senior-eng process caution, now grounded): one-shot DMAC→0x190080 omitted the ring discipline entirely. Next test (RE-grounded, falsifiable): CONTIGUOUS drain — ring filled with repeated [red frame][reset-gap] pattern, azx stream left triggered ON, DSP DMAC re-armed in a loop (>0.5s), mimicking the ring model. Target module: snd-hda-codec-ca0132-dma6.ko.

## 2026-09-09 session — LIVE CHIPIO INTROSPECTION UNLOCKED; DSP transport proven; strip still dark
### Infrastructure win
The 8051/chipio console was wedged (chipio status 0xF01 = BUSY). Root cause: a stale
root-owned `ca0132-8051-command-line` process held the codec's chipio lock via a stuck verb
ioctl, which also blocked PCI unbind (remove hung). Clearing it (kill + module reload) makes
**all chipio reads work live**: stream table (exram 0x72f), port descriptors (0x190000+),
flags are now readable on-demand. Console protocol stays dead; legs/verbs fully usable.

### Ground truth read from the live card (DSP agrees with our init)
- Stream 0x18 row (exram 0x72f + 0x18*10 = 0x81f): `18 09 06 d0 00 01 00 00 00` = source 0x09, dest 0xd0, channels 0x06, type 0, active 1, hda_streamid 0.
- Stream table @ 0x72f; start/end port table @ 0x1578/0x159d. Stream 0x18 ports 0x20..0x2b = 0x190080..0x1900ac (12 lanes).
- Router words @ 0x190000 are `dest:src:2bit-state` (state 0 idle / 1 active / 3 SRC), e.g. 0x000140c0 = src 0xc0, dest 0x40, state 1. ARM comment at kbuild/ca0132.c:7613.
- Router is **owned by the 8051** — a DSP-side DMAC write (our DBADR=0x40 hack from `dsp_chip_to_dsp_addx`) cannot paint it; only ever reached DSP scratch.
- During real azx+DSP-DMAC drains, router 0x190004..0x190184 flickers to live routing words then reverts, and an index-0x2c region (0x1900b0+) flips its per-lane busy flag 0x0000c800→0x0001c800. Stream-0x18's own lanes (0x190080..) NEVER flip busy in any run.
- HDA StreamID/Fmt fields of the 0x18 row stay 0 through every test — the DSP never binds our azx tag to stream 0x18 by itself.

### Test matrix (all dark, honest)
- dma5/dma6: `dsp_dma_*` to DBADR 0x40 "completed" in 3 polls — azx never triggered, no real data flowed. Invalid.
- dma7: pure azx (trigger ON, no DMAC) — data into DSP audio mix; ports static. Invalid.
- **dma8/dma9: azx TRIGGERED + DSP DMAC re-armed, REAL 32KB transfers (~10ms / ~100 polls each), up to 6s sustained, red→green. ZERO visual.**
- Sustained feed, correct WS2812 frame+reset-gap pattern, byte-exact 96k encoding — all validated; strip never reacts.

### Conclusion / why still dark
Windows ground truth (HANDOFF.md:342-373): frames → host RAM bufPhys (0x9ce52000) via a real
HDA/BDLE stream (zero preamble, no chipio 0x190000 writes), and the card is bound to that ring
through the **dmae/ARM descriptor** written via chipio SCP command IDs 0x70D/0x70B/0xF0C/
0x70C/0xF0B/0x0D (= VENDOR_CHIPIO_8051_ADDRESS_LOW/HIGH, PLL_PMU_WRITE, FLAG_SET, PARAM_SET;
FUN_0001a454 bakes ring base + 0x8000 + arm into a RAM descriptor; CtxHda [vt+0x28]→0x8000;
posPtr BAR2+0x6104). Every Linux build delivers data INTO the DSP (real drains) but never runs
the **SCP descriptor/ARM handoff** that tells the DSP's dmae/stream-0x18 consumer "ring base X,
size 0x8000, go" — the single untested step.

### Next step (dma10)
Program VENDOR_CHIPIO_8051_ADDRESS_LOW/HIGH + PLL_PMU_WRITE + FLAG_SET/PARAM_SET (the
0x70D/0x70B/0xF0C/0x70C/0xF0B/0x0D sequence) mirroring FUN_0001a454's descriptor bake, using the
azx BDLE ring's physical address + 0x8000 + stream-0x18 arm, issued from ae5_strip_* around the
sustained drain.

Modules preserved: -dma9 = sustained azx+DMAC (current), -dma8 = 12-burst azx+DMAC, -dma7 =
pure-azx, -dma6/-dma5 = DMAC-no-trigger, earlier variants.

### UPDATE dma10→dma13 (2026-09-09): engagement found, ring ARM is the gate

- **dma10** bound hda_streamid+fmt into stream-0x18 exram row (row `05 45 08`→`01 45 08`, sticks across
  reloads) — lanes never go busy, strip dark → lone streamid bind insufficient.
- **dma11** added `chipio_set_stream_source_dest(0x18, src, 0xd0)` with dual readback (row 0x81f+1
  AND PARAM_GET, ≤3 tries, commit token 0xfa92=0x22) — accepted try 0 every time.
- **Connector blocks identified**: alloc `0xfff00` (idx4/tag5) → c0–cb = pre-existing analog-out mux
  (dest 0x40, tapping = guaranteed no-op; drains complete ~107 polls, no change). Alloc `0xfff000`
  (idx0/tag1, forced by speaker-test holding idx4) → **c4–cf = our ring's real input**.
  `src = 0xc0 + (ffs(mask) - 9)`.
- **The c4 run is the only behavior-changing run**: keyword 0x1900b0 flips
  `0x0001c800 → 0x00019000` (DSP acknowledges stream-0x18 sourcing c4). Lanes read
  `0x0001ffc0..0x0001ffcb` (src c0–cb, dest ff "unrouted"). DMAC channel **never retires**.

### dma12: XFRCNT-CCNT probe — no-fetch confirmed (2026-09-09)

Probed CCNT/IRQCNT.CICNT during the c4-pinned burst: `ccn=0x1fff cicn=0xffff` — **frozen for the
entire 10 s**, never one word fetched, never one interrupt. `bucket f=no-fetch`.
**Falsifies the "slow sip" theory** (CCNT would have decremented) and the "just wait" theory.
When source=c0 (audio mux), plain drains complete in ~107 polls (~10 ms); when source=c4 is
accepted, the DSP's strip consumer gate **backpressures the DMA** because the ring base/size/arm
was never programmed.

### dma13: captured-ARM drop-in engine (2026-09-09)

`ae5_strip_arm_sequence[]` + `ae5_strip_run_arm()` — empty table (NO invented SCP bytes, per
directive), runs the captured Windows sequence verbatim once captured. Wired after routing
acceptance; logs "arm table empty (0 steps) - awaiting Windows capture" (verified live). c4
behavior reproduces bit-for-bit (engaged, no-fetch, abort -19).

### Conclusion now (fully evidenced)

The single untested step is now precisely scoped: **the ring-base/size + arm program** that
Windows sends once at LED-stream object setup (chipio 0x70x + SCP via COM/vtable; commit fn
0x31D80, RAM-descriptor setup 0x32020, vt+0x28→0x8000; IDs 0x70D/0x70B/0xF0C/0x70C/0xF0B/0x0D).
Static RE was already pushed to its limit (windriver/ANALYSIS.md §16). The exact ARG bytes were
never live-captured → delivered `CAPTURE-REQ.md` to the Windows side (both machines have it); the
Linux injector is ready to accept them. See WINDOWS-CONSULT-SYNOPSIS.md §6 for the full open-question list.

Modules preserved: -dma13 = ARM-injector + empty table (current), -dma12 = CCNT probe, -dma11 =
slow-sink/serial variants, -dma10/-dma9/-dma8, earlier variants.

## UPDATE dma14 + Windows answers on-stream (2026-09-13)

### Windows ANSWERS-2026-09-09 incorporated
- **Q2/Q6:** Windows never gates on a DMA active bit. Per send: write frame to host ring →
  spin-wait **position advance (BAR2+0x6104)** → commit → **zero-fill the whole ring** (reset
  gap). A transfer staying active for seconds = normal engagement. → falsifies our sustained-fill
  audit model; the azx stream position buffer is NOT the gate — the card's own scan pointer is.
- **Q3:** stream 0x18 confirmed as the ASI strip stream.
- **Q1 (naming corrected):** the bake site is **CtxHda RVA `0x1a454`** (NOT CtxHdb — that is the
  GUID-check factory). Statically pinned, never arg-captured; recoverable by static RE of the
  crash dump (base `fffff801846f0000`), pending kd elevation on the Windows box. Exact
  `0x70D.../0x0D` arg bytes are the open deliverable.

### dma14: pure-azx + position-register harness (Windows commit model)
- Replaced the dma12 DMAC drain with a **pure-azx + pos-gated** model: azx bound + routed c4,
  **no dsp_dma_\* at all**, one frame per iteration, wait pos advance (100 ms polls, ~4 s cap),
  then zero-fill the ring. Added `pos_base` (`pci_iomap_range(BAR2, 0x6104, 4)`) + `ae5_strip_pos()`.
- Build: clean (unused-var warnings only). Staged `-dma14` and reloaded.
- **Run result: pos is physically unreachable on this host.** `pos_base` mapping returned NULL:
  this card's own BAR2 is only **16K (`0xf4300000..0xf4303fff`)**, so offset `0x6104` (>`0x4000`)
  does not exist, while the Windows box's BAR window is ≥ `0x6108`. Reads log `0xffffffff`
  (= UINT_MAX placeholder). Everything else in the run matches dma13 bit-for-bit (c4 accepted
  try 0, ROUTING ACCEPTED, keyword `0x00019000` held, arm table empty, no crash, graceful skip).
- **Open reconciliation ask added to CAPTURE-REQ.md:** dump the AE-5's full BAR set (base+size
  per BAR) on the Windows box to pin down whether (a) the same SKU exposes a bigger window there
  (firmware/BIOS diff → pos polling forever unavailable here) or (b) Windows' "BAR2" is a
  different Linux BAR index (→ poll from the right window).

### Current wall (single untested step, unchanged)
Ring-base/size + **ARM bake** bytes from CtxHda RVA `0x1a454` (static RE, kd pending) feeding
`ae5_strip_arm_sequence[]` (dma13 runner) + dma14 harness = full Windows-mirror path. Everything
else on the Linux side is validated and staged.
