# Milestone 8 record: the ADPCM unit (2026-11-06)

Local only when written (on GitHub since 2026-11-11). Base board pinned at `fc923c5` (`pcengine-python`: `5befa54` plus issue 0002, the board calls
`PortDevice.catch_up`, and issue 0003, the board mixes `audio_sources`; both are base changes with
directed tests, described in that repository's `docs/issues/`). The M7 workaround `CdBoard` is gone.
Tiers are those of the base board's [validation.md](https://github.com/alewman/pcengine-python/blob/main/docs/validation.md).

## What was built

- `src/pcenginecd_python/adpcm.py` (378 lines): `Adpcm` (64 KiB RAM, address latch, separate read
  and write pointers with the buffered read, length counter, half and end flags, the sample clock, the
  MSM5205 decoder) and `AdpcmSource` (the audio source for the board mixer). `unit.py` wires the registers
  `$1808-$180E`, the IRQ2 sources (`$04` half, `$08` end, `$1803`, enabled through `$1802`), and sends
  the CD-to-ADPCM DMA through the same write path as `$180A`.
- The decoder: a 12-bit signal and an index 0-48 (step = floor(16 * 1.1^index); delta = step/8 + b0 step/4
  + b1 step/2 + b2 step; index moves -1 -1 -1 -1 +2 +4 +6 +8), high nibble first. The 392-entry delta table
  equals Mesen2's `_stepSize` table (checked by script, not copied).
- Sources, in order of weight: [hw: pcetech 8] register names, `$180E` rate `32/(16-n)` kHz, buffered
  reads, "less than half" for `$1803` bit 2, `$180C` bits, the busy time of about 24 cycles (tier 2);
  [mfr: Hudson BIOS manual and the System Card ROM] `AD_STAT` (reads `$180C` bit 0, `$1803` bit 2, `$180D`
  bit 5, `$180C` bit 3), `AD_PLAY` (rate `32/(16-n)`, auto-stop or repeat), `ad_read_addr_set` (sets bit 3
  then reads `$180A`, so the `latch - 1` read pointer is stepped onto the first byte by that read),
  `ad_write_addr_set`, `ad_length_set` (tier 3); the emulators (Mesen2, Geargrafx, Mednafen, MAME) are
  tier 5 detectors, and each point that rests on them only is a class-attribute switch below.
- Hudson's "Hu7CD" PDFs under `reference/src/turbografx-mister/docs/` were read (BIOS manual: `CD_FADE`,
  `AD_*`); the Software Manual has nothing on the registers.
- `Board.take_audio()` (base) mixes PSG + CD-DA + ADPCM; `scripts/cd_boot.py --wav FILE` writes it.

## Judges and what ran

**Directed tests** (`tests/test_adpcm.py`, 15 tests; 68 in all at that run, 69 after the fade switch, CPython 3.14 and PyPy 3.11 pass, ruff
clean): the step table's shape, sign and magnitude, index steps, saturate and wrap, the rate register
(2 kHz ... 32 kHz), buffered reads and the bit 7 / bit 2 busy times, playback to the end flag and IRQ2
through the enable mask, the playback time at 16 kHz (1.8 ms not done, 2.3 ms done), the length latch
clearing the end flag, the half flag, reset keeping the read buffer, DMA through the write path with the
length counting, the audio source holding the output at 44.1 kHz, the fade aimed at ADPCM scaling only
ADPCM, and the board mixing the source. Two M7 tests were changed to leave the busy time between accesses.

**Pyramid Plunder (USA) (Unl), one niced PyPy run, 3,000 frames, RUN held 20 frames at 450** (the CHD
extracted once into the scratchpad, 2.3 MB, removed with `scripts/scratch.py`): the game now passes the
Aetherbyte-logo wait and reaches its title ("Pyramid Plunder", the pyramid, "Press RUN to Start"; frame
3000). Against **Geargrafx** on the same disc (libretro host, same press): the same picture, same layout
and positions (Geargrafx is 256 x 242, ours 341 x 242 at the board's own dot clock: the known width
difference, not compared pixel by pixel). 12 drive commands (TEST UNIT READY, `DE` x3, READ(6) x8), 114,688
ADPCM samples decoded, the end flag raised twice. Wall time 2,528 s for 3,000 frames at a load average
of about 40 (0.84 s a frame with the audio mix), a reference board, not a fast one.

**ADPCM audio against a referee render** (detector only, tier 5): the board's mix of the same 3,000
frames against Geargrafx's audio of the same run, 50.1 s each. Both are silent until about 15 s, then
play the same sequence of sounds. Per-10 ms envelope correlation at the best lag: 0.905 (12-24 s, Geargrafx
150 ms earlier) and 0.912 (24-48 s, 70 ms earlier). Spectrum (rms ratio Geargrafx / ours): 0.96, 1.08, 0.98
below 4 kHz in the first window, 0.62 (4-8 kHz) and 0.34 (above 8 kHz) there; 1.0-1.3 in every band in the
second window. Overall rms 15-20% lower on ours (Geargrafx's DC-block and low-pass filter, an output scale
of 10 on both). A waveform-level correlation is 0.15-0.49: the two disagree on when the game starts each
sound (the lag above is the CD timing and the 7.5 s BIOS wait, not the decoder), so a sample-exact
comparison needs a ROM that plays one buffer, which does not exist here. **What this does not show:** the
decoder against hardware; it shows it against a second implementation of the same unknown.

**Decisions of 2026-11-07 (Aubrey):** the fade times default to the Hudson BIOS manual's 6 s / 2.5 s
(U/C row C-fade; pcetech's 8 s / 2 s is the `CddaPlayer.PCETECH_FADE` switch), and the 12-bit signal keeps
saturating (U9c; `SATURATE = False` wraps). Directed tests: 69 (the fade test covers both settings for
CD-DA and ADPCM; the saturate/wrap test covers both).

**Re-runs with the M8 code, 2026-11-07** (one at a time, niced PyPy, RUN held 20 frames at 450, each CHD
extracted once and removed with `scripts/scratch.py remove`; load average 10-14 at the starts). New:
`scripts/cd_boot.py --adpcm-writes N` logs writes to `$1808-$180E`. Geargrafx via `scripts/beetle_press.py`
with the same press.

| Disc | Frame reached | Picture vs Geargrafx | ADPCM |
| --- | --- | --- | --- |
| The Addams Family | 3,000 of 3,000 (1,035 s) | the same title screen ("Press Run!", "From NEC", Paramount lines), same layout (ours 341 wide, Geargrafx 341 here: visual match, not pixel-compared) | **yes**: 38 register writes, 18 drive commands (M7 had 10: it used to stop earlier); the game DMAs 16-sector blocks from the disc into ADPCM RAM (`$180B`=02/00 pairs, 9 loads in the run), sets the address and length, plays with `$180D=$60`; 533,755 samples decoded, one end flag |
| Insanity | 3,000 of 3,000 (1,095 s) | the same title ("INSANITY", "PRESS RUN", Aetherbyte/Hurple 2009) and the raster-bar effect (the bars animate, so the phase differs) | **no**: 8 writes, all the BIOS's reset sequence (`$180D` 80/00, `$180B` 00, `$180E` 00, twice); 0 samples |
| Pyramid Plunder | **not re-run** (load average 34 after Insanity); the M8 first run above stands (3,000 frames, title, Geargrafx match) | - | yes (114,688 samples, two ends) |

Not re-run: the base board's 18-picture gate (no VDC/VCE code touched).

## U/C entries (tiers; all provisional)

| Id | Entry | Sources and tier | Built as |
| --- | --- | --- | --- |
| U9a | Playback base 32 kHz (`f = 32/(16-n)`); Mednafen uses 32,087.5 | pcetech, Hudson AD_PLAY (tier 2/3); Mednafen tier 5 | `Adpcm.BASE_HZ` |
| U9b | `$180A` read and write busy 24 CPU cycles (72 clocks) | pcetech for the read (tier 2); write: Mesen2 22-24 cycles, Mednafen 33 clocks (tier 5) | `READ_CLOCKS`, `WRITE_CLOCKS` (0 = immediate) |
| U9c | 12-bit signal: saturate (MAME) or wrap (Mesen2, Geargrafx) | **Decided (Aubrey, 2026-11-07): saturate, as MAME.** The data sheet is not in `reference/`, so no tier above 5 decides it; wrap stays as a switch | `SATURATE` (True; False wraps; both tested) |
| U9d | Output: signal x 10, held, mono on both channels, no filter; Geargrafx DC-blocks and low-passes, Mednafen has an optional LPF, Mesen2 resamples with Hermite | tier 5 | `OUTPUT_SCALE`; no filter |
| U9e | Half flag: length `<` 0x8000 (pcetech "less than half"); Mesen2 and Geargrafx use `<=` while playing | tier 2 vs 5 | one line in `_play_sample` (not a switch: one sample) |
| U9f | A RAM write at length zero raises the end flag; the BIOS clears it with the length latch | Mesen2, Geargrafx (tier 5); Mednafen has none | `END_ON_WRITE_AT_ZERO` |
| U9g | End source is `$1803` bit 3 (`$08`); pcetech documents bit 2 (half) only. `$180C` bit 0 is the end flag (BIOS `AD_STAT`, tier 3) | four emulators agree (tier 5) for `$1803` bit 3 | `IRQ_END` |
| C-ad1 | The decoder restarts (signal 0, index 0) at each play request; Mednafen does not show it | Mesen2, Geargrafx | in `_play_sample` |
| C-ad2 | pcetech says `$180C` bit 1 is "playback halted"; the BIOS never reads it and four emulators leave it 0 | pcetech tier 2 | not modelled |
| C-fade | Fade times. **Decided (Aubrey, 2026-11-07): the manual's values until a better reason to switch.** Default 6 s / 2.5 s: Hudson BIOS manual `CD_FADE` (manufacturer manual, tier 3) outranks pcetech "about 8 s / 2 s" (research, tier 2), and Mesen2 and Mednafen agree with the manual (tier 5). ADPCM is aimed by bit 1 (`$0A`, `$0E`), so ADPCM fades with the same times | tier 3 over tier 2; tier 5 agrees with tier 3 | `CddaPlayer.FADE_SLOW_SECONDS`, `FADE_FAST_SECONDS` (6, 2.5); switch `PCETECH_FADE = True` selects `PCETECH_SLOW_SECONDS`, `PCETECH_FAST_SECONDS` (8, 2); both tested |
| U9h | Playing past the length with bit 6 clear (repeat) wraps the length through 17 bits and keeps reading | Mesen2, Geargrafx (tier 5) | `LENGTH_MASK` |

## Still not built (stated)

- **The Arcade Card** (`$1A00-$1AFF`, 2 MiB RAM, the three discs): not built at M8; built in M9 ([m9-record.md](m9-record.md)).
- **Subchannel Q**: no `$1807` stream, IRQ bit `0x10` never raised (U9 of M7 stands).
- The ADPCM unit's real DRAM slot timing (refresh and read/write slots that Mesen2 and Geargrafx model);
  the fixed 72-clock busy is enough for the BIOS and Pyramid Plunder.
- The 26/38-disc System Card sweeps and a lockstep: no sweep was run (IO constraint).
- (Then) everything stayed local; on GitHub since 2026-11-11.
