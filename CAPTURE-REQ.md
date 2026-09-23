# CAPTURE-REQ: the one datum needed from the Windows side (2026-09-09)

Everything else is proven or implementable on Linux. This single capture unblocks the strip.

## Why (5-line summary)

1. Windows drives the AE-5 strip via a **fixed 32 KB host-RAM ring**; the card bus-masters it
   continuously and publishes read position at **BAR2+0x6104** (`0xF43FE104`). Frame layout and
   encoding are byte-exact known.
2. Linux replicated feed + routing: stream 0x18 source routed to connector c4 → the DSP
   **accepts** (keyword `0x1900b0` flips `0x0001c800 → 0x00019000`).
3. But the DSP DMAC **never fetches a word** (XFRCNT.CCNT frozen at `0x1fff` for 10 s) — the
   strip DMA engine was never told our ring base/size → nothing consumes → backpressure stall.
4. The ring base/size/arm is programmed **once at object setup** via chipio verbs `0x70D/0x70B/
   0xF0C/0x70C/0xF0B/0x0D` + SCP, going through the COM/vtable layer (capture-notes §
   "Static RE of the commit path").
5. Those exact **argument bytes** were "statically RE'd, never live-captured". We will not
   invent them. We need the live capture.

## What to capture (Windows side, hooks already exist)

On a fresh boot, at the moment the strip is first enabled (settings open / first pattern send),
hook the driver's send path and log, **in order**, every request from LED-stream create through
the first frame commit:

| # | What | Why |
|---|------|-----|
| A | Every **chipio/SCP request**: command ID (verb like `0x70D`, SCP req like `0x0D`) **+ full data argument words** | The ring-base write and the arm live here. IDs only aren't enough — the ARG bytes ARE the missing artifact. |
| B | The **RAM descriptor struct** programmed by the `0x32020` helper (`and/or [r9+8], [r9+0xC]`, masks `0x1C71C700/0xFFFFC0FF/0xFC000/0x3F00000/0x3FFFFFF`): log `r9` and the written control words | Is the host ring base described in host-RAM and pointed to, or sent inline as SCP args? |
| C | The returned value of the **`[vt+0x28]` ring-size method** (reported `0x8000`) and of `[vt+0x60]/[vt+0x28]` command-id calls | Confirm the size source; identify which calls the Linux driver must mirror. |
| D | The **ring base (bufPhys) and BAR2 position offset** for that run | To pin the descriptor fields to concrete values. |

### Minimal form (if the full window is heavy)

At minimum: the **first ~16 requests** (IDs + args) issued between the factory create
(`factory->vtable[0]` with `&DAT_001111c0`) and the first commit (`0x31DF6` memcpy) — that set
contains the ring-base program + arm.

## Output format

Plain text table per request, mirroring the capture tool's existing log style:

```
SEQ KIND ID     ARG_WORDS
000 verb 0x70d  00 01 02 ...   (hex bytes, little-endian order as sent)
001 scp  0x0d   04 00 00 00 44 11 11 00 ...
...
```

Plus, if reachable, a one-time dump of the descriptor RAM words written at setup (B).

## EXTRA (2026-09-13): BAR-window reconciliation required

On this Linux host the AE-5's own PCI windows are: **BAR0 = 0xf4304000 (16K), BAR2 =
0xf4300000 (16K)** — i.e. the card's BAR2 is only 0x4000 bytes, and the position
register at BAR2+0x6104 does NOT fit (0x6104 > 0x4000). The Windows box's position
reg `0xF43FE104` implies a BAR ≥ 0x6108.

Please capture during the kd session: the **BAR count, each BAR base+size** as the
AE-5 exposes them on the Windows box (the `!pci`/`!devobj` BAR dump), specifically
which BAR and offset actually hosts `0xF43FE104`. Two possibilities to disambiguate:

- (a) the same card exposes a larger window on the Windows box (BIOS/firmware/SKU
      difference) — then Linux BAR2 at 16K may never map 0x6104 and position
      polling is unavailable here;
- (b) Windows' "BAR2" corresponds to a different Linux BAR index (Linux resource{}).
      Then we can poll from the right window.

Either way, one line of `.stm`/text output resolves it: `BARx base size`.

## Linux-side drop-in

The Linux driver (`kbuild/ca0132.c`, dma13) has `ae5_strip_arm_sequence[]` ready — the captured
`SEQ/KIND/ID/ARG` rows translate 1:1 into `{AE5_OP_VERB_WRITE|AE5_OP_SCP_SET, ...}` entries; the
runner executes and logs each step. No Linux-side code changes needed after the bytes arrive.
dma14 already runs the pure-azx pos-gated one-frame write/zero-fill harness (Windows commit
model) and logs "pos@start" + per-burst pos samples — it is the exact harness the bake bytes
plug into.
## EXTRA (2026-09-14): bake verification is now fully local — the address operands are gold

We built and validated a complete 8051-EXRAM readback spy (`chipio_8051_read_exram`, in-tree).
Full pre-bake baseline of the data plane captured (see LINUX-TRANSPORT-STATUS.md dma15/dma16).
**When you capture the bake, the ADDRESS operand bytes inside the 0x70X record rows are what we
write to** — the sequence translates 1:1 from the table. After we run it we re-sweep and diff;
the descriptor structure (ring phys base + size 0x8000) will appear as a new cluster. If the
capture table lists a data-row but not the INTERPRETED address, we only need the raw rows.

## DELTA 2026-09-14 (after CAPTURE-REQ-ANSWER): two byte-level asks remain

Follow-up on your ANSWER (host-RAM descriptor at ring base; no chipio bake). We
accept the model. Two asks still gate a hardware run:

**ASK-A (the descriptor bytes):** during a live send under ae5hook, dump the ring
at `bufPhys` for offsets `0x000..0x03F` (16 dwords, dword view) AND `0x040..0x0A7`
— i.e. the host-RAM descriptor zone built by 0x32020, as actually written
(pre/post memcpy either way). These 168 bytes are byte-exact gold; we will embed
them verbatim at ring base on Linux.

**ASK-B (ring-base plumbing):** state how the DSP DMAC is told the ring base —
the azx BDLE (via commit [vt+0x48]=0x31D30) or a chipio-programmed address — *if
there is truly no chipio bake*. If it is the BDLE, our `snd_hdac_dsp` stream
already covers it and only ASK-A remains; if a chipio order exists, its address
operands (the 0x70X rows) are needed too.

**ASK-C (sanity):** the 0x32020 result goes INTO ring[0x00..] — confirmed by the
memcpy hook writing at (pos+0xA8) which skips 0x00..0xA7 entirely. Just confirm
"descriptor lives at ring+0; frames never overlap 0x00..0xA7".

## ASK-D (2026-09-14): live capture of the BIND/ARM verb sequence (senior-engineer review)

### Context: why this ask now

A fresh-eyes senior review killed our one positive hardware signal. We had been reading
BAR0+0x2104 as "the strip DMAC position" and treating its advancement under
`snd_hdac_dsp_trigger(true)` as proof the strip engine consumed our ring. A **decoy-stream
test** (dma27: bare azx stream, zero strip plumbing, 2s trigger) advanced that register
identically (`0x0 -> 0x7ec0`) — so it is a generic azx **LPIB-style position counter** (wraps
at buffer length whenever any DMA runs on the tag), NOT the strip DMAC. That "ADV" evidence is
retired. The strip has never produced a photon in 27 builds, and we now have **no positive
signal** that the ring reaches stream 0x18's DMAC at all.

The most likely root cause is now **binding wrong** (our ring never actually feeds stream
0x18), not encoding/layout/rate (those are byte-exact against your captures and are copied,
not synthesized). Our one inferred binding step — patching stream 0x18's 8051-EXRAM row at
`0x81f` (byte7 = hda_streamid, bytes8/9 = format) — was built from static RE and is
**unverified**; it may be the wrong row, wrong field width, or missing a gating bit.

### The ask

On the Windows box, under the existing ae5hook (or a new hook at the same sites), capture the
**complete ordered verb/IO sequence Windows issues from the moment stream 0x18 is (re)bound to
a host stream tag through the FIRST successful frame commit**, i.e. the window between
`chipio_set_stream_source_dest(0x18, src, 0xd0)`-equivalent calls and the first
`0x31DF6` memcpy. We need the row/address-level detail, not just command IDs:

| # | What to log | Why |
|---|-------------|-----|
| A | Every **8051-EXRAM read/write** (`0x70D` addr-low / `0x70B` data / `0xF0B` read-back) with **full address + data bytes**, in order, for the first ~64 ops after stream-0x18 bind | This reveals the REAL stream-0x18 control row(s): base address, which bytes carry hda_streamid + format, and any gating bytes. Our `0x81f` assumption is likely wrong and this is the ground truth. |
| B | Any **stream-select / channel / rate verbs** (`0x0D`/`0x05`, `CONTROL_PARAM_STREAM_*`, `chipio_set_stream_channels`, `chipio_set_stream_control`) issued between bind and first commit | Is there a per-bind "enable stream" step we're missing beyond the one-time init `chipio_set_stream_control(0x18,1)`? |
| C | The **hda_streamid / tag value** Windows actually programs for stream 0x18, and WHERE it is written (which exram address, which byte) | Confirm or refute that byte7-of-row-at-`0x81f` (our patch) is the real mechanism. |
| D | The **first memcpy commit** `0x31DF6` record (M record) showing `len` + `destPhys` delta into the ring | Pin the frame's ring offset on a fresh bind so we can replicate pos-gated placement exactly. |

### Minimal form (if the full window is heavy)

At minimum, the **first ~32 8051-EXRAM/stream-control ops** (address + data bytes, in order)
between the moment a host stream is assigned to stream 0x18 and the first commit. That set
contains the bind row we need. If your hook can log 8051-EXRAM address+data as separate
columns, that alone is enough — we can drop everything else.

### Why this unblocks Linux

The Linux driver (`kbuild/ca0132.c`, dma27) already:
- allocates a 0x8000 coherent ring + BDL via `snd_hdac_dsp_prepare`
- binds a tag and routes stream 0x18 (source 0x09 -> dest 0xd0)
- bakes the ASK-A descriptor at ring[0]
- writes byte-exact frames

What it is **guessing** is the one remaining glue: *how Windows tells the DSP which host
stream tag feeds stream 0x18, and whether an explicit arm is needed.* The `0x81f` row patch is
that guess. ASK-D replaces the guess with the actual address+data rows. Once we have them, the
existing `chipio_8051_write_exram` + PARAM paths translate 1:1 and we can finally test the
ring on a verifiable binding.

## ASK-E (2026-09-15): caller-graph / xref check — is stream 0x18 even the LED engine?

### Why (senior-engineer review, after dma29/dma30)

dma29 proved the port-allocation wedge was reload-accumulated (fresh boot → `dsp_allocate_ports_format`
SUCCEEDS, lane2c back to `0x0001c800`). dma30 then routed stream 0x18 with the port-derived
source (src 0xc0 → 0xd0) on a clean bind — **still dark**, same as the static ASI source (0x9).

Two sources, clean binding, zero photons. The senior engineer's new thesis: **stream 0x18 may
be the wrong subsystem entirely** — a real but *irrelevant* generic HDA/ASI audio stream, not
the LED-ring DMA engine. The two mechanisms were merged by rate-arithmetic coincidence
("4-words-per-audio-sample"), never confirmed by a live capture showing the C2 bind firing in
temporal proximity to an LED ring commit. The real LED engine is the object behind the hook
log's ring commit (`CtxHda.sys` RVA 0x31D80/0x31D30/0x31DF6, object `ffffe507ede649e0`,
vtable `vt=fffff8049b234510`, pos register at `0x2104`).

### The ask — no new capture needed, same MEMORY.DMP as ASK-D

A `kd` **caller-graph / xref** question, static-only:

1. **Who calls RVA `0x28d48` (the C2 bind entry), `0x26dd0` (the enable-bind helper), and
   `0x2c310` (the F/R arm handler)?** List the call sites / call stacks.
2. **Do any of those callers sit in the same code path as the LED ring commit (`0x31D80`) or
   the commit object's vtable dispatch — i.e. would they fire *only* when an LED command is
   issued?** Or do they originate from generic PCM-stream-open / audio-init / mixer-setup
   boilerplate that fires on every boot regardless of the LED feature?
3. **Cross-reference the stream-config row writes against the commit object:** does the object
   at `ffffe507ede649e0` (vtable `fffff8049b234510`) ever touch RVA `0x23564`/`0x26dd0`/`0x28d48`
   (the `0x734+id*0xA` row system), or is it a separate driver subsystem that owns its own ring?

### Verdicts (predefined, no interpretation needed)

- **If the C2 bind callers are generic audio-init / unconditional:** stream 0x18 is unrelated
  boilerplate → we STOP pursuing stream 0x18 and instead trace the ring-commit object's vtable
  (`fffff8049b234510`) to whatever function sits between it and hardware (the real LED engine).
- **If the C2 bind callers trace back to the LED IOCTL handler that owns the ring commit:**
  the two mechanisms are meant to cooperate → reopens Q2 (why doesn't a binding that provably
  works reach the ring?) and we continue on stream 0x18.

### Minimal form

Even one line resolves it: for each of RVA `0x28d48` / `0x26dd0` / `0x2c310`, the **top 1–2
callers** and whether that caller is on the LED-IOCTL path or the audio-init path.

## ASK-F (2026-09-15): is the ring-manager coherent ring the same buffer as the azx-stream BDL ring?

### Why (after 35 Linux builds, all mechanisms verified, strip never lit)

Linux now has every downstream mechanism verified working on a cold boot: byte-exact encoding,
Windows-exact ring layout, stream 0x18 row 0x824 + C2 bind verbs, dsp_allocate_ports_format
succeeds, the 0x190000 router routes stream 0x18 to our port block, the ASI dest-0xd0 routes
activate, and the ASK-A descriptor (dword0/4 = scramble(0) = 0, which we proved is CORRECT for
aligned rings — scramble() collapses aligned bases to 0, so the base is NOT in the descriptor).
The strip has still never produced a photon.

The one unverified physical link is: **what host buffer does stream 0x18's DMAC actually read,
and how is its base communicated?** ASK-B said "the azx-style DSP-stream BDL/ASI mechanism
(snd_hdac_dsp)". We create that BDL ring via snd_hdac_dsp_prepare. But Windows allocates its
ring via a **ring-manager object** (vtable 0x101c70, `[vt+0x10]`=0x9978 allocation returns the
0x8000 size; `[vt+0x70]` returns the DMA query object). We need to know whether those are the
same buffer.

### The ask (kd / static on the existing MEMORY.DMP)

1. **Does the ring-manager's allocated ring (vtable 0x101c70, [vt+0x10]=0x9978) get used as
   the azx stream 0x18's BDL buffer, or as a SEPARATE coherent ring the DSP DMAC reads
   directly?** Trace: the ring-manager object's `[vt+0x70]` DMA-query returns a buffer — where
   does that buffer's physical address go? (a) into an HDA BDL for stream 0x18, or (b) into a
   chipio/DSP register or descriptor that the strip DMAC reads directly, with NO HDA stream.
2. **In the dump, is there an HDA azx stream bound to stream 0x18 at all during the LED
   captures?** The hook log (ae5hook5.log) showed memcpy into bufPhys + pos register advance
   with no visible stream-0x18 HDA activity. Confirm whether Windows runs ANY HDA DMA stream
   for the strip, or whether the card's DMAC reads bufPhys standalone.
3. **What is the ring-manager's ring size/alignment and how is its base given to the DSP?**
   If it's a standalone coherent ring (not BDL), is there a chipio/8051 register (or the
   0x32020 descriptor) that carries its physical address?

### Verdicts (predefined)

- **If the ring IS the azx-stream BDL buffer:** our Linux setup should work (it doesn't) ->
   the bug is in HOW we create/point the BDL, and we need the exact Windows BDL setup for
   stream 0x18 (entry count, physical address placement, which HDA stream tag).
- **If the ring is a SEPARATE coherent buffer the DSP DMAC reads directly (no HDA stream):**
   our entire azx-stream transport is wrong; we need to allocate a standalone coherent ring,
   hand its physical base to the DSP via the ring-manager-equivalent mechanism (the 0x32020
   descriptor or a chipio register we haven't found), and skip the azx stream entirely.

### Minimal form

One line: for the ring object at vtable 0x101c70, does `[vt+0x70]` (DMA query) return a buffer
that is (a) referenced by an HDA BDL, or (b) referenced directly by a chipio/DSP-side
address/descriptor with no HDA stream? Plus: does Windows run any HDA azx stream during the
LED ring commit?

## ASK-G (2026-09-15): live send-path capture + ring-buffer identity facts

Complements ASK-F (static). Two asks that are decisive on their own.

### G1 — LIVE capture of a real LED send (new ae5hook run, not static RE)

All prior answers are static RE (MEMORY.DMP) or old hook logs (ae5hook5.log, pre-ASK-D). The
senior engineer twice flagged that a **live confirmation of verb byte-order on the wire** is
still the one gap. During a fresh real LED write (ae5-send.ps1), record timestamped and
interleaved:

| # | What to log | Why |
|---|-------------|-----|
| A | **Any HDA azx stream start/stop** during the ring commit | Empirically answers ASK-F #2 (does Windows run an HDA stream at all, or is the ring DMAC'd standalone). The strip question has hinged on this. |
| B | **Byte-order of `[vt+180h]` / `[vt+60h]` verbs** on the wire (exact bytes, order) | Closes the ASK-D endian/transport-framing gap. |
| C | **Do the C2 bind verbs (0x17-0x1E) fire during an LED write, or only at init?** | Confirms the ASK-E inference (I concluded from the dump that the C2-bind is on the ring object; a live capture proves whether it fires per-send). |
| D | **pos register value immediately before and after the memcpy**, and whether the whole ring is zeroed after the commit | Confirms the descriptor is wiped every commit (relevant to whether our static descriptor survives). |

### G2 — ring-buffer identity facts (kd on the existing MEMORY.DMP)

Cheap, complements ASK-F:
- The ring-manager's DMA buffer (vtable 0x101c70, [vt+0x70] DMA query): **physical address,
  below-4GB status, alignment, and is it the SAME buffer every send** (we know bufPhys =
  0x9ce52000 is fixed across captures).
- Does **bufPhys appear in an HDA BDL entry, or in any chipio/8051 register/descriptor**?

### Minimal form

G1 line: during one real LED send, does **any HDA azx stream start or stop**, and do the
`[vt+180h]` C2-bind verbs fire during the send or only at boot? G2 line: bufPhys address +
below-4GB + alignment + whether it appears in a BDL or a chipio/DSP register.

## ASK-H (2026-09-15): LIVE WinDbg breakpoint trace of the IOCTL->dispatch->bind->commit causal chain

### What has NOT been done

The existing `ae5hook5_g1.log` (19:54 live capture) captured the **ring commit** half (memcpy
0x31DF6 + commit 0x31D30, byte-exact frames, pos at real 0xF43FE104), but does NOT capture the
**IOCTL dispatch front end**. The senior engineer's WinDbg breakpoint plan (no code patch, no
trampoline — just `bp` + `.printf` + `g`) has NOT been run. We need the front end to complete
the causal chain: IOCTL command -> dispatch -> C2 bind -> ring commit.

### The ask: run these WinDbg breakpoints during one real LED send

**Trigger (deterministic, senior-engineer-refined):** the window is now bounded from the
kernel **entry** point, not mid-driver. Break `NtDeviceIoControlFile` **conditional on
`IoControlCode == 0x77772400`**, then single-step forward through the driver to the ring
commit. Drive it with a **scripted** `ae5-send.ps1` call with a known color (e.g.
`.\ae5-send.ps1 -External -Count 10 -R 255 -G 0 -B 0`) — a controlled, repeatable trigger, not
a GUI click. The IOCTL code `0x77772400` and the `gpdhda` path are known facts (SR-REPORT-AE5-LED-PROTOCOL).

Attach live (or to a VM kernel-debug), load symbols, then run a command script:

```
$$ trace.wdbg  (save as trace.wdbg)
$$ kernel entry, filtered to the AE-5 LED IOCTL only
bp nt!NtDeviceIoControlFile  ".if (@rdx = 0x77772400) {.printf \"IOCTL_ENTRY handle=%p code=%p in=%p out=%p\\n\", @rcx, @rdx, @r8, @r9; g} .else {g}"
$$ driver-internal chain (existing ASK-H)
bp CtxHda+0x2f274  ".printf \"DISPATCH rcx=%p rdx=%p r8=%p r9=%p\\n\", @rcx, @rdx, @r8, @r9; g"
bp CtxHda+0x2f9e0  ".printf \"SUBDISPATCH rcx=%p rdx=%p r8=%p r9=%p\\n\", @rcx, @rdx, @r8, @r9; g"
bp CtxHda+0x28d48  ".printf \"C2BIND rcx=%p rdx=%p r8=%p r9=%p\\n\", @rcx, @rdx, @r8, @r9; g"
bp CtxHda+0x31df6  ".printf \"MEMCPY dst=%p src=%p len=%p\\n\", @rcx, @rdx, @r8; g"
bp CtxHda+0x31d30  ".printf \"COMMIT dst=%p len=%p\\n\", @rcx, @rdx; g"
g
```

Run via `$$>a< trace.wdbg` after attaching, then issue the one scripted LED send. Collect the
debugger output.

### What we need from it (map against Ghidra)

- **Ghidra identified** `FUN_0002f274` as the IOCTL dispatch (references the `GPDPALLOCATE`
  IOCTL string) and `FUN_0002f9e0` as its sub-dispatch. Confirm these fire on an LED send.
- Capture the **IOCTL argument values** (the command/IOCTL code + input buffer) to see how the
  LED command flows in.
- Confirm whether **C2 bind (0x28d48) fires per-send or only at init** (G1 suggested only at
  init; this confirms live).
- Confirm the **memcpy->commit** ordering and whether any verbs/HDA-stream activity interleaves
  (G1 said none).

### Minimal form

Even one line per breakpoint type suffices: which of DISPATCH/SUBDISPATCH/C2BIND/MEMCPY/COMMIT
fire during one LED send, in what order, with rcx/rdx/r8 argument values. This completes the
causal chain and tells us definitively whether the IOCTL path reaches the ring commit we've
been modeling.

### Why it matters for Linux

If DISPATCH->C2BIND->COMMIT fire in a simple chain with NO HDA stream and NO verbs (as G1
suggests), that fully confirms the standalone-ring transport and tells us the exact command
payload the Linux driver must synthesize. If C2BIND fires per-send (not just init), there is an
additional per-command step we're missing. Either result is decisive for the next Linux build.
