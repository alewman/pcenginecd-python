# Milestone 9 record: the Arcade Card (2026-11-07)

Local only. Base board pinned at `a0114c5` (`pcengine-python` on GitHub, which brings `huc6280-python`
v0.2.0 / f31b630). Tiers as in the base board's [validation.md](../../pcengine-python/docs/validation.md).
**Status: the card is built and directed-tested; the three Arcade Card discs have NOT been run.** The
machine's load average was 38-45 for the whole session (limit for disc runs: about 20), so no disc was
extracted or booted and no detector was run. Nothing below claims a disc picture.

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
the Hudson BIOS manual under `reference/src/turbografx-mister/docs/` was not found to (a targeted
grep of the Oss-PCE-CD-BIOS docs finds only "later target only"); MAME has the card as a cartridge
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

**Not run.** Load average at every check: 38.9, 44.6, 40.3 (limit 20). Per disc, the command to run when
the machine is quiet (one at a time, niced, extract once, remove after):

```sh
python3 -I scripts/scratch.py extract "/data/emu/roms-retrobat/pcenginecd/NAME.chd" $SCRATCH/NAME
nice -n 10 .venv-pypy/bin/python scripts/cd_boot.py $SCRATCH/NAME/disc.cue --arcade \
    --frames 3000 --png-at 1500,3000 --press-run-at 450 --hold-frames 20 --out $SCRATCH/NAME-run
python3 -I scripts/scratch.py remove $SCRATCH/NAME
```

then `summary.json["arcade"]` says whether the game found the card (`id_reads`) and used it
(`data_accesses`); the detectors are Geargrafx (`scripts/beetle_press.py` with its libretro core, Arcade
Card by its game database) and Mednafen/Beetle (Beetle's `pce.arcadecard` option) for the first picture.

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
