<!-- SPDX-License-Identifier: MIT -->
# Restart: the drive's bus, rewritten clean (2026-11-19)

The provenance audit of 2026-11-13 ([provenance.md](provenance.md)) marked one part of this add-on
**rewrite**: the SCSI bus state machine in `src/pcenginecd_python/scsi.py`, whose control flow was
named after a GPL emulator's (Mesen2's) and whose timing constants were converted from that
emulator's code. That module was withdrawn and replaced on 2026-11-19 under the rules below
(the PC Engine family's clean-rewrite pass, after the sound cores' restart:
`sn76489-python/docs/restart.md`).

## The rules of this pass

1. **No GPL or LGPL source is read**: Mednafen, Beetle PCE, Mesen2, Geargrafx, the TurboGrafx16
   MiSTer core, MAME's GPL files. Not to learn, not to check a constant, not when a comparison
   fails.
2. **The code being replaced is not read.** `scsi.py` was moved aside, unread, into the git-ignored
   `scratch/withdrawn/` before anything was written, and was not opened again. The interface was
   taken from its call sites (`unit.py`, `cdda.py`, `board.py`, `scripts/cd_boot.py`) and the tests.
   Documents that described the old machine in the GPL emulator's terms were not used as sources.
3. **Permitted sources**, licence checked in each file: the SCSI-1 standard; MacDonald's
   `pcetech.txt`; Hudson's documents in the MiSTer repository's `docs/` folder (the CD System BIOS
   manual, and the System Card 3.00 disassembly, which shows how the BIOS drives the bus); Dave
   Shadoff's MIT seek measurements (already `seek.py`); MAME `nec/pce_cd.cpp` (BSD-3-Clause) and
   ares `pce/pcd/` (ISC), for facts only: nothing was ported from either, so no notice is owed;
   they are cited where used.
4. **GPL emulators are run as closed boxes.** `scripts/drive_probe.py` (new) is a small HuC6280
   program of ours that stands in for the System Card: it drives the drive through `$1800-$1808` as
   the BIOS does and counts 45-clock polling turns between bus events, then the host reads its
   results from work RAM. Run on Geargrafx (libretro, 57c257d) it measures response times; a
   constant fitted to it is marked "OBSERVED: closed box" and gives way to any document or hardware
   result. Beetle PCE answers every step at once (no timing model) and fails a READ of the probe's
   synthetic sectors, so it was only a second opinion on answer lengths.
5. **Every rule in the new code names its source** (DOC, OBSERVED, HYPOTHESIS, emulator tier) or
   says it is a choice.
6. **The gates are external**: the quick suite, the slow System Card boot, the disc boots compared
   with Geargrafx, and the probe itself compared with Geargrafx. The withdrawn module's results
   are the "before" column, never a target.
7. Chip-level questions are answered with the best-supported option and marked provisional.

## What was replaced

| Item (audit) | Now | Source |
| --- | --- | --- |
| `scsi.py`: the bus state machine | a new module: one pending protocol step, a sector clock and the auto-ACK end; phases and signals from SCSI-1; command lengths by opcode; the handshake as SCSI-1 and the BIOS's `$EC0B` routine | DOC (SCSI-1, pcetech 8, the BIOS disassembly) |
| the timing constants | re-measured: SEL to command phase, command byte REQ, TEST UNIT READY, READ TOC, READ SUBQ, data to status, status to message, message to bus free, re-read penalty | OBSERVED, closed box (Geargrafx 57c257d) |
| the auto-ACK pulse | 45 clocks (15 CPU cycles) | emulator tier: MAME (BSD-3); the closed box's window (15, 45]; the BIOS needs it within 78 |
| the abort path | SEL in data in (or while a READ seeks): the read stops, the status phase offers 8 GOOD bytes, then the message and bus free; SEL while busy with no phase (CD audio, a seek): a new selection, the busy wait dropped | OBSERVED, closed box; the BIOS's busy-select routine (DOC) shows why it works |
| READ timing | the first sector's REQ at Shadoff's seek time less the BIOS's own share of his measured interval (selection, command, reading 2,048 bytes, status: 332,000 clocks at this model's times), then one sector per 1/75 s; a sector missed while the buffer is full comes 290 ms after its turn | DOC (Shadoff's test program times the whole CD_READ), Red Book; OBSERVED closed box for the re-read |
| command details | REQUEST SENSE format, READ(6), READ TOC kinds 0-3, READ SUBQ's ten bytes, AUDIO START/END/PAUSE | DOC (SCSI-1, Hudson BIOS manual); MAME, ares for lengths and corner answers |
| docs naming GPL internals | `docs/arcade-sources.md` (the MiSTer Verilog fragments and a machine path dropped), `arcade.py`, `adpcm.py`, `cdda.py`, `disc.py`, `unit.py` comments, `m7-record.md` U8 rows, `m8-record.md` | re-cited to permissive or closed-box sources |

Also re-sourced in `unit.py` (the audit called these clean; the probe now measures them):
`CHANNEL_LATCH_GUARD` (closed box: the guard is in (675, 735] clocks, 700 kept) and the `$180B`
bit 0 rule (closed box: `$03` reads back `$02`). `DMA_BYTE_CLOCKS` keeps its reported test-ROM
value; the closed box disagrees (below).

## What stays open

- **DMA rate.** The closed box takes a CD byte into ADPCM RAM every 90 clocks; this add-on takes
  one every 60 + 45 = 105 (the reported test-ROM window for REQ-to-take, plus the auto-ACK).
- **A drive just reset.** The Hudson manual says it takes "a few seconds" to become ready; the
  closed box answers TEST UNIT READY after a reset as quickly as ever, and so does this add-on.
- **AUDIO END mode 0.** The manual calls it "mute play" with the status at once; MAME and ares stop
  the audio, and so does this add-on.
- **READ with a count of 0** answers GOOD with nothing (MAME, ares); SCSI-1 reads 256 sectors.
- **SEL in the command, status or message phase** is ignored (no source).
- **A repeat of an empty range** (AUDIO END mode 1 ending before the start) plays nothing and the
  drive stays busy (MAME's note, the closed box's busy repeat). Without this guard the CD-DA
  player's repeat would never end; found by the probe.
- **The BIOS's share of Shadoff's interval** (332,000 clocks) is computed from this model's own bus
  times, so it moves if they do.
- **The abort's further status bytes** come at once after each ACK (only the first was timed).
- Every closed-box number is one emulator's model, not the hardware: a hardware capture of the
  same probe would settle all of them (the probe runs on any machine that boots a System Card
  image; on a real console it would need a flash cart that can stand in for the card).

The results before and after, and what a Rust transcription must carry, are in
[provenance.md](provenance.md) ("Clean rewrite, 2026-11-19").

## Repin to the clean base board (2026-11-19)

After the drive's rewrite, the base board's own clean rewrite (pcengine-python 3318027: a new VDC
line machine from Hudson's manual, pcetech and MAME's BSD-3 files; core huc6280-python 6ce348e)
became this add-on's pin. Neither commit is on GitHub yet: `pyproject.toml` names the full hash on
GitHub as usual, and until Aubrey pushes both, the venvs are installed from the local clones:

```sh
for v in .venv-pypy .venv; do
  $v/bin/python -m pip install --force-reinstall --no-deps \
    "git+file://$PWD/../huc6280-python@6ce348e13c9ef3009bd07e7938c4b48956eeadc6" \
    "git+file://$PWD/../pcengine-python@3318027e5c34f1e211515f95233a0853938a5f53"
done
```

**Interfaces.** Nothing in this add-on used what the base board removed (`vertical_at_line_start`,
`latch_byr`, `latch_bxr`, `_step_bg_y`, `line_counter_step`, `commit_unless_dma`,
`force_complete`, `SAT_DOTS`, `DMA_DOTS_PER_WORD`, `CLOCKS_PER_SPRITE`): the CD unit is a port
device and an audio source on the base board's sockets. No code adaptation was needed. Save states
from the old pin do not load (the base board's sequencer state changed).

**The judges, before (base 4c32f26, the drive rewrite's final runs) and after (base 3318027).**
Niced PyPy, `PYPY_GC_NURSERY=1M`; the six disc boots exactly as the drive rewrite ran them
(`scripts/cd_boot.py`, `syscard3.pce` from `$PCE_SYSTEM_CARD`, 3,000 frames, RUN held 20 frames at
450, `--png-at 1000,2000,3000`, `--adpcm-writes 40`, `--arcade` for the first three; CHDs extracted
one per run into the scratchpad and removed after).

- Quick suite: 104 passed before and after (PyPy and CPython).
- Slow System Card boot and the save state taken while the BIOS reads: pass before and after
  (2 passed).
- Disc boots:

| Disc | Drive commands | ADPCM samples (ends) | Pictures 1000 / 2000 / 3000 | Command times |
| --- | --- | --- | --- | --- |
| Ryuuko no Ken (Arcade) | 12 / 12, same texts | 47,410 / 47,410 (6) | identical, 8 dots left | 18-45 clocks earlier |
| Mad Stalker (Arcade) | 411 / 411, same texts | 0 / 0 | identical, 8 dots left | -52 to +164 clocks |
| Ginga Fukei Densetsu Sapphire (Arcade) | 19 / 19, same texts | 0 / 0 | identical, 8 dots left | 18-45 clocks earlier |
| Pyramid Plunder | 12 / 12, same texts | 114,688 / 114,688 (2) | identical, 8 dots left | 16-55 clocks earlier |
| The Addams Family | 18 / 18, same texts | 536,583 / 536,583 (1) | identical, 8 dots left | -45 to +2,316 clocks |
| Insanity | 10 / 10, same texts | 0 / 0 | identical, 8 dots left | 28-45 clocks earlier |

  "Identical, 8 dots left": every one of the 242 rows of every picture equals the old picture's row
  moved 8 dots left (the base board's display now starts 8 dots earlier in the row), at the 9-bit
  value. The ADPCM register logs are the same; the final PCs differ by 0-8 bytes (Ryuuko `$8B9A`
  / `$8BA2`, Addams `$41A5` / `$41A7`), presumably the same wait loops caught at another phase
  (the CPU's phase against the beam moved with the new line machine; not checked further). Because every
  picture is the same picture, the comparison with Geargrafx recorded in provenance.md ("Clean
  rewrite, 2026-11-19") stands unchanged; Geargrafx (the closed box) was not rerun, as nothing on
  its side moved.

**What pcenginecd-rust must carry**: nothing of this add-on's behaviour changed; it takes the base
board's changes through its pcengine-rust pin (pcengine-python `docs/restart.md`, "What the Rust
transcription must carry"). Comments and headers only otherwise: SPDX headers, the NOTICE.md
entries for MAME's BSD-3 files, and `$PCE_SYSTEM_CARD` in the scripts and slow tests in place of
a machine path.
