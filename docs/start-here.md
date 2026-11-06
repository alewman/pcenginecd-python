# Start here: the CD-ROM² as an add-on

Read the base board's [docs/cd.md](../../pcengine-python/docs/cd.md) (what the hardware is, what ran
elsewhere), [docs/sockets.md](../../pcengine-python/docs/sockets.md) (the sockets, "What the CD needs"),
[docs/handoff-brief.md](../../pcengine-python/docs/handoff-brief.md) (M7/M8 rows, decisions 5-10 and the
user's decisions) and MacDonald's `pcetech.txt` section 8 (`pcengine-python/reference/docs/pcetech.txt`,
tier 2) first.

## The machine

[hw: pcetech 8] A CD-ROM² set is the **interface unit** (IFU-30, on the EXT BUS: 64 KiB CD RAM, 64 KiB
ADPCM RAM, 2 KiB battery RAM, the SCSI-class CD controller and the MSM5205 ADPCM chip), a
**single-speed drive**, and the **System Card** (a HuCard with the BIOS). The Super System Card adds
192 KiB of RAM at banks `$68-$7F`. The Duo/R/RX integrate all of it. There is **no second CPU**: the
drive's firmware is not emulated; the controller is a bus state machine
([scsi.py](../src/pcenginecd_python/scsi.py)).

```
 HuC6280 ──bus── page table ──┬─ System Card (slot)   ROM $00-$7F, Super RAM $68-$7F
                              ├─ CdUnit (port)        $80-$87 CD RAM, $F7 BRAM, $1800-$18FF
                              └─ base: work RAM $F8, VDC/VCE/PSG/timer/I-O/IRQ in $FF
 CdUnit ── ScsiBus ── drive: Disc (bin/cue or CHD) + CddaPlayer
 IRQ2 (wired-OR, bit "cd")   audio list: PSG, CD-DA   I/O bit 7 = 0 (unit present)
```

## The sockets used (base board `docs/sockets.md` numbering)

| Socket | Use here |
| --- | --- |
| 1 HuCard slot | `SystemCard(RomCard)`: the BIOS image mirrored through `$00-$67`, Super RAM `$68-$7F` (a card is not confined to the ROM window), the id registers it answers through the unit |
| 2 expansion port | `CdUnit` is the `PortDevice`: claims pages `$1000-$10FF` (CD RAM), `$1EE0-$1EE7` (BRAM), `$1FF8` (registers); `present` drives I/O bit 7 low |
| 3 one decode | all three claims replace the base page handlers; the card's own claim covers `$00-$7F` |
| 5 clock domains | `CdUnit.catch_up(mclk)` runs the drive; the board calls it every advance (finding S1 below, fixed in the base by issue 0002) |
| 6 interrupts | the unit's bit `"cd"` on `board.irq2`: set while `(enable mask & active bits) != 0` |
| 9 audio | `CddaPlayer` and `AdpcmSource` appended to `board.audio_sources` (44.1 kHz stereo, `take_samples(mclk)`); the base `Mixer` sums them (`Board.take_audio()`) |
| 10 reset | `reset(ResetKind.POWER_ON)` re-locks BRAM and clears the bus; the CD is reset by `$1804` bit 1 inside the unit |

Not used: pixel path, controller port, video timing, second VDC.

### What the base board did not do for an add-on (documented socket findings)

- **S1 (fixed in the base, 2026-11-06): `PortDevice.catch_up` was never called by the board.** A device that
  must act by itself (the drive's REQ, a sector arriving, an audio command ending) would only see time at
  its own register accesses and could not raise IRQ2 between them. M7 worked around it with a `CdBoard`
  subclass; the base now calls `self.port.catch_up(target)` after the loop (pcengine-python issue 0002,
  bc31f9c), and `CdBoard` is gone. Cost: one Python call per CPU cycle with a cheap early-out.
- **S2: two devices share the `$1800` page.** The Super System Card answers `$18C1-$18C7`, the CD unit
  the rest of the page, and the page table is 256-byte granular (the Sega finding again). The unit asks
  the card (`SystemCard.register_read`) for `$18C0-$18C7`. A finer decode in the base would be the
  cleaner answer if the Arcade Card (`$1A00`) and a third device collide.
- **S3 (fixed in the base, 2026-11-06): no audio mixer.** `audio_sources` was a list nothing consumed.
  The base now has `Mixer` and `Board.take_audio()` (issue 0003, fc923c5); the CD-DA player and the
  ADPCM source are appended to the list and `scripts/cd_boot.py --wav` writes the mix.

## Module shape

```
pcenginecd_python/
  disc.py     Disc, Track: LBA/MSF, bin/cue, CHD via chdman, in-memory discs for tests
  seek.py     Shadoff's measured seek model (tier 3)
  cdda.py     CddaPlayer: lazy-time audio player, samples, $1805 latch, fader
  scsi.py     ScsiBus: signals, phases, REQ/ACK, the command set, sector delivery, timing attributes
  unit.py     CdUnit: registers, CD RAM, BRAM, IRQ2, the CD-to-ADPCM DMA
  adpcm.py    Adpcm (RAM, pointers, flags, MSM5205 decoder) and AdpcmSource (the audio source)
  syscard.py  SystemCard: BIOS image, Super RAM, id registers
  board.py    PcEngineCd (card + unit + board)
scripts/
  cd_boot.py   boot a disc N frames, log commands/registers, dump frames as pickles
  rows_png.py  pickles to PNGs (system python3, Pillow)
  scratch.py   extract a CHD once / remove the expansion (no shell rm)
```

## Running

BIOS and discs are read in place; run one niced job at a time (this board is slow by design, about
1.5 s of wall time per emulated frame under load; the machine is shared):

```sh
nice -n 10 .venv-pypy/bin/python scripts/cd_boot.py DISC.cue --frames 600 --png-at 300,600 --out RUN
python3 -I scripts/rows_png.py RUN
```
