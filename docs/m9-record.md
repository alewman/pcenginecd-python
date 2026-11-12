# Milestone 9 record: the Arcade Card (2026-11-07)

Local only. Base board pinned at `a0114c5` (`pcengine-python` on GitHub, which brings `huc6280-python`
v0.2.0 / f31b630). Tiers as in the base board's [validation.md](../../pcengine-python/docs/validation.md).
**Status: the card is built and directed-tested, and the three Arcade Card discs HAVE now been run (2026-11-09,
section "Disc results" below): all three boot on `syscard3.pce` plus the card and match Geargrafx.**
(The first session had load 38-45 and ran nothing.)

## What was built

- `src/pcenginecd_python/arcade.py` (`ArcadeCard`, about 230 lines): 2 MiB RAM; four ports (base 24 bit,
  offset 16 bit, increment 16 bit, control 7 bit); the data registers `$0/$1`; the offset triggers; the
  32-bit value register `$1AE0-$1AE3` with the shift (`$1AE4`) and rotate (`$1AE5`) units; version `$10`
  and ID `$51` at `$1AFE/$1AFF`; banks `$40-$43` as the data of ports 0-3. The card has no clock.
- It is a component of `CdUnit` (one add-on, one expansion-port device): `CdUnit(arcade=...)` adds the
  pages `$0800-$087F` (banks `$40-$43`) and `$1FFA` (`$1A00-$1AFF`) to its claims, forwards reads and
  writes there without a catch-up, and forwards `reset`. `PcEngineCd(..., arcade_card=True)` fits one
  (default: not fitted, so the M7/M8 results are unchanged). `scripts/cd_boot.py --arcade` fits it and
  reports register/ID/data access counts in `summary.json`.
- 21 directed tests in `tests/test_arcade.py` (ports independent, offset auto-increment, base
  auto-increment, wraps at 16 / 24 bits, the 21-bit effective address, signed offsets, the three trigger
  modes and trigger 0, control keeping 7 bits, the `$1A40` mirror, banks `$40-$43`, the shift and rotate
  results, the four switches, power-on and reset, the board wiring with and without a card). The whole
  suite is 90 tests, CPython and PyPy pass, ruff clean.

## Sources, and the limit of this build

**There is no hardware-tier (2/3) source for the card in `reference/`.** `pcetech.txt` does not mention it;
the Hudson PDFs under `reference/src/turbografx-mister/docs/` were NOT searched this session (PDF, no
text tool run); the Oss-PCE-CD-BIOS docs say only "later target only"; MAME has the card as a cartridge
device and its `pce.xml` marks the Pro's BIOS "baddump" (`cd.md`). The register behaviour is therefore
[emu: Mednafen `arcade_card.cpp` ("based on information provided by Ki and David Shadoff"), Geargrafx
`arcade_card_mapper*`, Mesen2 `PceArcadeCard.cpp`], **tier 5, three independent implementations**, and
this build takes what all three agree on. They agree on: the port layout and mirror, the effective address
(`base [+ offset [+ $FF0000]]` & `$1FFFFF`), auto-increment of the offset or (D4) the base, the three
offset triggers, the 7-bit control, the shift/rotate arithmetic, `$10/$51`, banks `$40-$43` = ports
0-3. Where Aubrey's brief said "tier 2/3 defaults": there is nothing above tier 5 to default to.

## U/C entries (all tier 5 unless stated)

| Id | Entry | Sources | Built as |
| --- | --- | --- | --- |
| U10a | Reads of decoded addresses without a register: `$FF` (Mednafen, Geargrafx) or the open bus (Mesen2) | tier 5 | `ArcadeCard.UNMAPPED_READ` (`0xFF`) |
| U10b | `$1AE4/$1AE5` read: low 4 bits (Mednafen, Geargrafx) or the byte written (Mesen2) | tier 5 | `SHIFT_READ_MASK` (`0x0F`) |
| U10c | Port register `$A` on a read: 0 (Mesen2, Geargrafx) or `$FF` (Mednafen falls through) | tier 5 | `TRIGGER_REG_READ` (0) |
| U10d | Power-up RAM: zero (Mednafen) or random fill (Mesen2); the real RAM is unspecified | tier 5, U7 again | `POWER_ON_RAM_BYTE` (0) |
| U10e | A warm reset (`ResetKind.BUTTON`) clears the ports and the shift unit (Geargrafx) or not (Mednafen, Mesen2 show none) | tier 5 | `RESET_CLEARS_REGISTERS` (False) |
| U10f | The signed-offset form adds `$FF0000` (a literal subtract of `$10000` from a 16-bit offset, so only offsets with bit 15 set go below the base); all three agree, none cites hardware | tier 5 | in `effective_address`, tested |
| U10g | Control bit D2 ("signed increment"): stored, used by no emulator; Mednafen has a commented-out experiment | tier 5 | not modelled |
| U10h | The rotate unit: Mednafen marks it "untested", Mesen2 "untested"; the three agree on the arithmetic | tier 5, no referee | in `write_register` |
| U10i | The version byte `$10`: Mednafen "we should verify this"; `$1AFC/$1AFD` read 0 (Mednafen, Geargrafx), unmapped in Mesen2 | tier 5 | fixed |
| U10j | The Arcade Card Duo's own decode of `$80-$87` is CD RAM here already; a bare-Pro `$80-$87` question is moot while the unit is fitted | `cd.md` | none |
| U10k | **BIOS**: the library holds only the Super System Card 3.0 (`syscard3.pce`) and `disksys.rom`, no "Arcade System Card" image (MAME's Pro ROM is a baddump, and the three discs' usage line says "Arcade System Card required"). Mednafen loads the same System Card 3.0 and adds the card; this build does the same. Whether the Arcade discs run on it is **unanswered** | tier 5 | `PcEngineCd(syscard3.pce, ..., arcade_card=True)` |

## The three discs (library: `/data/emu/roms-retrobat/pcenginecd/`)

The library's Arcade-Card titles (MAME `pcecd.xml` "Arcade System Card required", matched by title):
**Ginga Fukei Densetsu Sapphire (Japan)**, **Mad Stalker - Full Metal Force (Japan)**, **Ryuuko no Ken
(Japan) (En,Ja,Es) (FACT)**.

## Disc results (2026-11-09)

One disc at a time, niced PyPy, CHD extracted once to the scratchpad and removed with `scripts/scratch.py
remove`, `--arcade`, `syscard3.pce` read in place, 3,000 frames, RUN held 20 frames at 450. Load average
at the starts: 18.9, 13.9, 4.2. Detector: **Geargrafx** (libretro, `scripts/beetle_press.py --core
.../geargrafx_libretro.so`, the CHD read in place, same press), compared by eye at the same frame numbers
(ours 341 wide, Geargrafx 256: known width difference; not pixel-compared). Beetle not tried (U38).
`cd_boot.py` now also records `arcade_touched` (registers read/written, per-port min..max RAM address) in
`summary.json`.

| Disc | Frames, wall time | Outcome | Geargrafx | Arcade accesses | Registers / RAM touched |
| --- | --- | --- | --- | --- | --- |
| Ginga Fukei Densetsu Sapphire | 3,000 (1,314 s second run; 1,892 s first run at load 21; identical results) | "NOW LOADING" with the ship at 1000, then the intro demo (city at 2000, converging-lines effect at 3000); 19 drive commands, last `D8`/`D9` (audio play) at about frame 1,800; PC `$7465` at the end | the same three scenes at frames 1000, 2000, 3000 | 39 register reads (1 ID read `$FF`), 2,100,161 register writes, 2,565,120 data accesses | regs read `02-09,12-19,22-29,32-39,E0-E5,FF`; written `00,02-09,12-20,22-30,32-39,E0-E5`; RAM written port0 `000000-1BFFFF`, port2 `1C0000-1DFFFF`, port3 `1E0000-1FFFFF`; read port0 `0A0000-140A7F`. The whole 2 MiB is filled (it loads the disc into card RAM), then read back |
| Mad Stalker - Full Metal Force | 3,000 (363 s) | Kogado logo (fading), "NOW LOADING 02" with the three mechs, then the opening cutscene (a car/figure scene at 3000); 455 drive commands (streaming reads); bus free; PC `$6078` | the same three scenes (logo fade phase and mech pose differ by animation phase) | 237,968 register reads, **0 ID reads**, 1,040,873 register writes, 1,278,464 data accesses | ports 0-2 (regs `00-04,12-14,22-24,32-34`); RAM read and written port0 across `000000-1FFFFF` (it uses the card as a 2 MiB data cache and never asks for the ID) |
| Ryuuko no Ken | 3,000, then 3,600 (192 s / 221 s) | Opening (the broken portrait at 1000, a fight scene with Japanese caption at 2000), the Hudson/SNK title at 3000 and "PUSH RUN BUTTON" blinking from about 3100; 12 drive commands; PC `$3929` at 3600 | the same scenes at 1000, 2000 and the title from 2800 on (animation phase differs by a few frames: at 3000 ours was a white flash frame, Geargrafx the grey fade-in; both show the title at 3100-3600) | 433,699 reads (1 ID read), 34,393 register writes, 556,225 data accesses | regs read also `10,FD,FE,FF` (version, ID area); RAM written port0 `0E0000-0FFFFF`, read port0 `0E0010-100005`, port1 `0E009D-0E02D2`. ADPCM works with it: 38,971 ADPCM register writes, 47,410 samples decoded, 6 end flags |

**Findings.** (1) All three Arcade Card discs run on `syscard3.pce` with the card fitted; no "Arcade System
Card" image was needed to reach pictures, so U10k is now answered for these discs up to the point reached
(they check the ID `$51` or not at all, and the System Card 3.0 is enough to load them). (2) No board or
add-on bug turned up, so no code change besides the logging. (3) Sapphire, the one that stayed at the intro
demo, is not stalled: its pictures keep changing; its last drive command is an audio play, no ADPCM use
(0 samples). Mad Stalker likewise had 0 ADPCM samples by frame 3,000 (only the BIOS reset writes).
(4) Untested: gameplay (no input beyond RUN), audio against Geargrafx (not rendered), and any later
stage of any disc; the Arcade Card against hardware stays tier 5 (agreement with Geargrafx says that two
implementations agree).

Commands run, per disc (as below, with `--png-at` and `--adpcm-writes 40`):

```sh
python3 -I scripts/scratch.py extract "/data/emu/roms-retrobat/pcenginecd/NAME.chd" $SCRATCH/NAME
nice -n 10 .venv-pypy/bin/python scripts/cd_boot.py $SCRATCH/NAME/disc.cue --arcade \
    --frames 3000 --png-at 1000,2000,3000 --press-run-at 450 --hold-frames 20 --out $SCRATCH/NAME-run
python3 -I scripts/scratch.py remove $SCRATCH/NAME
```

**Rerun 2026-11-12** after the repin to pcengine-python b914413 (core 9c47c98, decimal `ADC`/`SBC`
with an invalid BCD digit follow Mednafen's formulas): Ryuuko no Ken and Mad Stalker, the commands
above, with the core before (f31b630) and after. The three frames, `commands.txt`, `regs.txt` and
every field of `summary.json` except the wall time are identical before and after (251-291 s a run).
Sapphire and the M7/M8 discs were not rerun, and Geargrafx was not rerun.

## What is not known to be enough

- Whether each disc needs more than the card (ADPCM edge cases, subchannel Q, CD seek timing): **unknown**,
  because no disc ran. Insanity-style ADPCM (the half flag) and the DRAM slot timing are the known
  open items from M8; a game that boots to a picture on the card alone would show they are not needed.
- The card against hardware: no referee exists (U10 all tier 5). If a disc runs with the same picture on
  the detectors, that says the three implementations and this one agree, not that the card is right.

## Part 1 of the session: the repin

`supergrafx-python` and `pcenginecd-python` pin `pcengine-python@a0114c58cc57443ba637af621adb23a0f2690124`
by `git+https://github.com/alewman/pcengine-python`; the core arrives as huc6280-python 0.2.0 (the public
`HuC6280.opcode` exists; supergrafx-python keeps its `_opcode` fallback, tested). Tests: supergrafx 38 pass
on CPython and PyPy, pcenginecd 90 pass on both; ruff check and format clean in both. The System Card
boot slow test was **not run** (load above 20).
