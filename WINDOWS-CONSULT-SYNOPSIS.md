# AE-5 External WS2812 Strip — Linux Handover Synopsis (for Windows-side consult)

Status: current as of 2026-09-09. Companion to `LINUX-TRANSPORT-STATUS.md` (living internal log).

## 1. Objective

Drive the Sound BlasterX AE-5's **external WS2812B LED strip** from Linux. The strip is driven
entirely by the on-card Sound Core3D DSP (no GPIO/interface chip on the strip path). Hardware chain
(header, strip, card circuit) is verified good by the user — all remaining gaps are software.

Card: AE-5 base, PCI `1102:0012`, alsa driver `snd-hda-codec-ca0132`.

## 2. What was inherited from the Windows side

- Windows ground truth: `windriver/decomp/` (12 decompiled FUNs, partial SCPv2 argument library),
  `HANDOFF.md`, `LINUX-DESCRIPTOR-HANDOFF.md` (command-ID table), `AE-5-protocol-capture.md`,
  `ae5-send.log` — a real Windows capture of the card being configured and the strip fed.
- Known byte-exact pixel encoding: 96 kHz DSP path, 6ch, stream 0x18 (source 0x09, dest 0xd0);
  4 words per audio sample; each pixel bit = 8 words (`0xC000`/0`xFC00` = 0/1); frame =
  zero preamble + 8-word-encoded LED data + full-ring zero-fill for the WS2812 reset gap.
- Stream-0x18 exram row (base 0x72f, stride 0x0a → row 0x81f): source 0x09, 6ch, dest 0xd0,
  active, hda_streamid, format.
- Windows DMA model: host ring in RAM (`bufPhys=0x9ce52000`, 0x8000 B), position register
  BAR2+0x6104 (`0xf43fe104`); a descriptor "bakes" ring base+0x8000+arm once via chipio SCP
  command IDs `0x70D/0x70E/0x70C/0x70F/0x710/0x70A` (= in-tree VENDOR verbs).
- **Gap in handoff:** the exact SCP argument values that bake/arm the ring were "statically RE'd,
  never live-captured" — `FUN_0001a454` was never decompiled. `windriver/decomp/` does not contain it.

## 3. What was done on Linux (test builds dma1 → dma11)

1. **dma1–dma4** — infrastructure on the ca0132 driver: ring alloc/fill with the byte-exact encoded
   frames, SysFS trigger (`ae5_strip_test`), host azx PCM open/start/trigger, dmesg tracing.
2. **dma5/dma6** — ring filled + azx trigger; **invalid** (needed DSP DMAC setup). Fixed in dma7.
3. **dma7** — first real drains via `dsp_dma_setup/start` to DSP-DMAC addr 0x190080. Ring
   consumed; still dark.
4. **dma8** — drain + full DSP DMAC teardown; chipio exram stream-0x18 introspect. 
5. **dma9** — "sustained feed" (60 bursts over ~6 s, red→green). Drains ~10 ms/107 polls,
   up to 6 s continuous. **Zero visual → the "keep the pipeline fed continuously" hypothesis is
   falsified.** Sustained feed is NOT sufficient.
6. **dma10** — wrote `hda_streamid` + format into stream-0x18 exram row (sticks across reloads,
   row shows `01 45 08`/`05 45 08`), but 0x18 lanes never go busy, strip dark → lone streamid
   bind is insufficient.
7. **dma11** — added `chipio_set_stream_source_dest(0x18, src, 0xd0)` with live acceptance
   verdict (row + `PARAM_GET` dual readback, ≤3 tries, commit token `0xfa92=0x22`); 2000-poll
   drain budget; then slow-sink loop.

## 4. Decisive experimental findings

- **Router 0x190000 is DSP/8051-managed** — the DMAC cannot paint it; `dsp_chip_to_dsp_addx
  (+0x40)` is an invented hack that does nothing to the route.
- **c0 vs c4 connectors:** alea alloc block `0xfff00` (idx4/tag5) → connectors c0–cb (the
  pre-existing analog-out mux, always wired to dest 0x40 — tapping them is a guaranteed no-op).
  Block `0xfff000` (idx0/tag1) → c4–cf — the block our ring data actually lands on.
  `src = 0xc0 + (ffs(mask) - 9)`. Occupying azx idx 4 (speaker-test) forces our stream to
  idx0/tag1/mask `0xfff000` → source c4.
- **Routing acceptance is instant and verifiable** (try 0): row 0x81f+1 and PARAM_GET both
  return src. `ROUTING ACCEPTED`.
- **The c4 run is the ONLY run where behavior changed (and the only run that matters):**
  - Drain 0 (0x2000-word = 32 KB burst) never completes: with a 200 ms budget it was still
    active after 811 ms; with the slow-sink 4 s budget it was **still active after the full
    ~4 s** (`polls=760`), flagged "genuine stall".
  - The 0x1900b0 keyword flipped `0x0001c800 → 0x00019000` — the audio-path word vs the
    engaged-strip-path word. This only ever happens when routing to c4.
  - Lanes 0x190080–0x1900ac read `0x0001ffcc … 0x0001ffd7` (src cc–d7, dest ff "unrouted",
    state 1) throughout — the DSP holds a pinned-but-unretiring state.
- **c0 runs:** drains always complete at ~107 polls (~10 ms), keyword stays `0x0001c800`,
  nothing changes, strip dark. Confirms c0–cb is not the strip path.
- dma9 (dma8/9) with correct 0x19000 engagement is decisive.

## 5. Current state (exact)

- Source: `kbuild/ca0132.c` — banner `TEST BUILD dma11`; slow-sink loop in `ae5_strip_write_test`
  (~8394+): streamid bind, routing block (`route0x18 … ROUTING ACCEPTED/NOT TAKEN`), 4 bursts
  × up-to-4 s red→green, per-burst lane+keyword sample, abort on "STILL ACTIVE after ~4s".
- Built/staged module: `snd-hda-codec-ca0132-dma11.ko` (loaded).
- Scripts: `/tmp/opencode/reload_dma8.sh` (rebind→rmmod→insmod→rebind; echo text says dma8,
  loads dma11).
- Elevation: passwordless sudo not available (only omarchy helpers); `pkexec` works when the
  user is present to approve the polkit dialog; no polkit auth agent is installed in the
  session by default, but pkexec shows dialogs when the user runs it from their own terminal.
- Ring/encoding: byte-exact verified; azx stream occupies idx0/tag1 when idx4 is held by
  speaker-test.

## 6. Open questions for the Windows side (missing info)

1. **`FUN_0001a454` — the descriptor/ARM bake.** Never decompiled / never live-captured. We need
   the exact SCP argument sequences for command IDs `0x70D/0x70E/0x70C/0x70F/0x710/0x70A` as the
   driver configures and arms the strip (ring base 0x8000 + arm). This is the #1 missing artifact.
2. **Sink semantics:** when our data actually lands at connector c4 the DMA never deasserts
   within 4 s (vs ~10 ms for audio). Does the Windows driver keep such a transfer in flight by
   design (i.e., the strip engine sips the ring over seconds and the position register advances
   slowly)? Or does the driver observe "completion" differently (position-based instead of
   active-flag)? The position register (BAR2+0x6104) is our untested handle.
3. **Is stream 0x18 the right stream?** We assumed it from the 96 kHz/6ch config + source 0x09 /
   dest 0xd0. Confirm, and confirm stream 0x18 is the one the strip descriptor bakes, vs e.g.
   a dedicated effect/loopback stream.
4. **Route to c4 correctness:** Windows never routes strip traffic via the `c4` connector block
   that we use (our c4 = DMA block for host streams). What does the Windows driver tie to the
   strip sink instead? Maybe an entirely different stream index/route is used, and our c4 pin
   is a side effect (the DSP consuming host data for a different purpose, e.g. loopback, that
   also keeps the channel busy).
5. **Keyword semantics:** 0x1900b0 `0x0001c800` (audio idle) vs `0x00019000` (strip engaged).
   What does this word mean structurally? (router graph head / dirty-lane mask / active-stream
   bitmap?) A decode would validate our readback model.
6. **DMA "active" flag semantics under a slow sink** — where does the DSP retire a transfer
   relative to the position register (BAR2+0x6104) advancing to ring end?

## 7. Next steps (Linux side)

- Static RE of `FUN_0001a454` (per user directive: no invented SCP bytes) — recover the exact
  bake/arm sequence.
- Re-test with position-register-based completion (BAR2+0x6104) instead of the DMAC active flag
  — if the ring position advances while the transfer is "active", the engine IS consuming and
  the active flag is meaningless; then multi-second feeds should light the strip.
- If neither: new hypothesis required — the strip path on Linux may need a different stream
  route than stream 0x18 alt source, or a ring-base write we haven't done (see §14 of HANDOFF).