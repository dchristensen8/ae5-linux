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
