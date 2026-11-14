# Milestone 7 record: the CD unit core (2026-11-05)

Local only when written (on GitHub since 2026-11-11). Base board pinned at `5befa54` (`pcengine-python`, HEAD when this run started; it brings
huc6280-python `a379416`). **No file in `pcengine-python` was edited.** One socket gap is documented
below (S1) and worked around in this repository. Tiers are those of the base board's
[validation.md](https://github.com/alewman/pcengine-python/blob/main/docs/validation.md): 2 hardware-verified research (pcetech), 3 manufacturer
or a published measurement, 4 community, 5 emulator-derived (detectors, never judges).

## What was built

Modules and judges are in [m7-plan.md](m7-plan.md) and [start-here.md](start-here.md). Size: about 1,300 lines of
source, 53 directed tests (CPython 3.14 and PyPy 3.11 both pass, ruff clean) plus one slow test that boots the
real BIOS (`pytest -m slow`).

## Judges and what ran

**1. The System Card boots to its screen (exit item 1: met).** `syscard3.pce` (Super CD-ROM² System v3.0
Japan, 256 KiB, read in place from the Batocera BIOS pack, SHA-1 as in the base board's `cd.md`) on this board
draws the "PC Engine SUPER CD-ROM² SYSTEM VER. 3.00" logo and then "PUSH RUN BUTTON!". Against **Beetle PCE**
(detector, 256 wide, text at 300 and 900 frames): same layout and text; a crude resample statistic (mean
absolute RGB difference over a 256x224 resample) is 9.9 for ours at frame 600 versus Beetle at frame 900, and 78.1
for an unrelated control picture. Tier 2 pcetech for the registers the BIOS touched in boot (`$1804`,
`$1802`, `$180F`, `$180D`, `$180B`, `$180E`, `$1803`, then `$18C5-$18C7`, the Super System Card id registers);
the BIOS reads `$18C5=AA, $18C6=55, $18C7=03` and accepts them. The BIOS waits about 7.5 s of emulated time
(161.6 M master clocks) before it will take RUN, issues no drive command until RUN, and the first drive command
is TEST UNIT READY.

**2. A data CD's first sectors through the SCSI path (exit item 2: met).** `tests/test_scsi.py` and
`tests/test_unit.py` drive the registers as the BIOS does (SEL write, command bytes with the REQ/ACK handshake,
data in through `$1801` with the handshake or `$1808` with the auto-ACK pulse, status and message bytes, bus
free) on **synthetic discs built in the tests** (`tests/discs.py`): READ of one and three sectors, a late
reader's re-read penalty, out-of-range READ (CHECK CONDITION, ILLEGAL REQUEST), TEST UNIT READY timing, REQUEST
SENSE with no disc, READ TOC kinds 0-2, SEL during data-in aborting with an 8-byte message, RST through `$1804`,
IRQ2 bits following REQ per phase, and the CD-to-ADPCM DMA (AD_TRANS shape: `$180B` bit 1, then the status
phase). The real BIOS issues TEST UNIT READY, READ TOC (0, 1, 2) and READ(6) on every disc below, with absolute
LBAs (Insanity's data track starts at LBA 1977 and the BIOS's first READ is `0x7B9` = 1977, from the TOC answer).

**3. Three simple titles to a first picture (exit item 3: met, with one caveat).** One niced run each on the
extracted bin/cue (each CHD expanded once into the scratchpad with `chdman extractcd`, 2-222 MB; delete with
`scripts/scratch.py remove`), RUN held for 20 frames at frame 450. Detector: **Geargrafx** (libretro host,
`scripts/beetle_press.py --core ...geargrafx_libretro.so`).

| Disc | Our result at 3,000 frames | Detector |
| --- | --- | --- |
| The Addams Family (USA), one data track | **the title screen** ("Press Run!", Paramount line); 10 drive commands (TUR, TOC x3, READ 0 x2, 2 x16, four loads at `$0BC5-$0BC8`) | Geargrafx draws the same screen; content-box resample statistic 30.9 against 131.8 for a control (dither and palette conversion differ: the known colour artefact) |
| Insanity (USA) (Unl), audio track 1, data track 2, 12 audio tracks | **the title screen** ("INSANITY", "PRESS RUN", Aetherbyte/Hurple 2009; a raster-bar effect runs); `AUDIO START` (`D8`) and `AUDIO END` (`D9` mode 1, loop) were issued and the bus is BUSY as the BIOS leaves it | Geargrafx: the publisher logo at 2,400 frames and the same bar effect at 4,000 |
| Pyramid Plunder (USA) (Unl), one data track | the publisher logo ("Aetherbyte"), the game's first picture; it **does not get further**: the game polls `$180C`/`$1803`/`$180D` once a frame with `$180D = $60` (ADPCM play) and waits for an ADPCM end that this board does not produce | Geargrafx reaches the title ("Pyramid Plunder / Press RUN to Start"); **ADPCM playback timing is M8** |

Beetle PCE is a detector for the BIOS screen only: with RUN sent from the host (verified: 50 of 50 polls saw
START) it clears the "PUSH RUN" text and then stays on the splash for 30,000 frames, silent, on five discs (the
cue and the CHD of Pyramid Plunder, Addams, Bonk III, Insanity). Whether that is the host (this ctypes libretro
frontend), a core option, or the core is **not investigated** (U38). Geargrafx and our board agree; no title was
compared against a second detector.

**Speed.** 3,000 frames of a CD boot take 150-180 s of wall time under PyPy at low machine load (about 0.05-0.06
s a frame), 1.4 s a frame at load average 45. A reference board, not a fast one.

## Findings on the base board's sockets (details in start-here.md)

- **S1** (fixed 2026-11-06 by base issue 0002, `CdBoard` removed): `PortDevice.catch_up` was never called by the board. Worked around by `CdBoard._run_to`. Proposed base
  change (not made): call `self.port.catch_up(target)` after the device loop in `Board._run_to`.
- **S2**: two devices share the `$1800` page (card id registers, CD registers); solved by the unit asking the card.
- **S3**: no audio mixer consumes `board.audio_sources`.
- The sockets otherwise worked as drawn: the card's claim of `$00-$7F` with RAM inside it, the unit's three page
  ranges replacing base handlers, the per-source IRQ2 bit, the I/O port's bit 7 following `port.present`.
- No lockstep gate was run: MAME's CD is its weakest part (cd.md) and no instruction-stream referee exists here.

## U/C entries (tiers; all provisional unless said)

| Id | Entry | Sources and tier | Built as |
| --- | --- | --- | --- |
| U8 | Drive timings: SEL to command phase 25,000 ticks, TEST UNIT READY 150,000 ticks (about 100x shorter than real), TOC 3,000, status 1,000, abort 300,000, ACK pulse 21 clocks; a tick is 3 master clocks | Mesen2 comments citing test ROMs on hardware (tier 5, claimed) | `ScsiBus` class attributes `SEL_TO_COMMAND_PHASE`, `TEST_UNIT_READY`, ...; each counts from the register access that starts it (until issue 0001, 2026-11-13, from the drive's last event while another was pending) |
| U8 | Sector rate: one sector's bytes every 286,363 clocks (75 a second) | Red Book rate, tier 2-3; the delivery phase relative to the READ is undecidable | `ScsiBus.SECTOR_CLOCKS` |
| U8 | Re-read after a missed sector: 290 ms | Mesen2 (Sherlock Holmes), tier 5 | `REREAD_PENALTY_MS` |
| U8 | `$1805` second write within 700 clocks ignored | Mesen2 test ROM, tier 5 | `CdUnit.CHANNEL_LATCH_GUARD` |
| U8 | CD-to-ADPCM DMA takes a byte 60 clocks after REQ | Mesen2 "verificator" ROM (18-22 ticks pass), tier 5 | `CdUnit.DMA_BYTE_CLOCKS` |
| C20 | Seek model: Shadoff's zones and steps; his `seektime.c` makes the `< 2` case dead code (9 VSYNC + half a rotation for 0-4); Mesen2 uses older numbers (18 VSYNC for short seeks) | measurements on re-capped hardware, tier 3 | `seek.py` (the code as written) |
| U9 | Audio: no subchannel Q stream (`$1807` reads 0, IRQ bit 0x10 never), no DAC filter, fade linear 8 s / 2 s (Mesen2: 6 s / 2.5 s; MAME "sketchy") | pcetech tier 2 for the times; shape undecidable | `CddaPlayer.FADE_*` |
| U9 | ADPCM: RAM port, pointers, DMA done; **no playback, length, half/end flags or IRQs** (the Pyramid Plunder block); `$180C` always reads idle | pcetech "currently trying to document", MAME TODO | done in M8 ([m8-record.md](m8-record.md)) |
| U36 | BRAM at power-up: formatted-empty (header `48 55 42 4D 00 A0 10 80`), locked; `bram=` overrides | Mesen2 (tier 5); pcetech silent; Far East of Eden dislikes garbage | `BRAM_FORMATTED` |
| U37 | A 256 KiB card is a Super System Card (192 KiB RAM at `$68-$7F`, id registers); 128 KiB cards are not | MAME and Mednafen pick by card type/identity (tier 5); no hardware document | `SystemCard(super_system_card=None)` |
| C14 | REQUEST SENSE: 18-byte fixed-format sense, length from CDB byte 4 (0 = 4); never issued by the BIOS in the three boots | Mednafen sends 18 bytes, Mesen2 sends nothing (tier 5) | `ScsiBus._request_sense` |
| C15 | READ TOC answer lengths 2, 3, 4 (kinds 0, 1, 2); the BIOS accepted them | Mednafen (its comment: "not confirmed on real PCE"); Mesen2 sends 4, 4, 4 | `TOC_ANSWER_BYTES` |
| C16 | `$18C3` reads 00 (version `$80`) | MAME; Mesen2 returns 03 | `SystemCard.register_read` |
| C17 | `$1800-$18BF` is not mirrored every 16 bytes; unknown registers read `$FF` | Mesen2 decodes `& $3FF`; MAME mirrors `& $F` (tier 5) | `CdUnit._read_register` |
| C18 | READ(6) with count 0 transfers nothing (Good status) | Mesen2; Mednafen reads 256 as SCSI-2 says (tier 5) | `ScsiBus._read` |
| C19 | AUDIO START holds BUSY until the seek ends, then Good (Mednafen answers Good at once) | Mesen2 vs Mednafen, tier 5 | `ScsiBus._audio_start` |
| C21 | pcetech names `$1804` "bit 2" and the BIOS writes `$02`: bit 1 in 0-based counting | pcetech tier 2 text, BIOS behaviour | reset = value & 2 |
| C22 | An unknown opcode: Good status, no data (Mesen2, Geargrafx) or CHECK CONDITION with ILLEGAL REQUEST / INVALID COMMAND (`$05`/`$20`) for REQUEST SENSE (Mednafen; SCSI-2's rule, which this drive is not known to follow). The answer comes at the first byte either way (Mednafen first waits for the opcode group's CDB length). Added 2026-11-13 (issue 0001 item 5) | tier 5 both | `ScsiBus.UNKNOWN_COMMAND_CHECK_CONDITION` (False: Good; both tested) |
| U38 | Beetle PCE in the libretro host does not leave the splash after RUN | measured here | not investigated |
| U16 | Which emulator is closest for the CD: Geargrafx and this board agree on three titles; Beetle undecided | measured here | no referee |

The tier-4 "CD Unit SCH.pdf" (a community redraw) was not read in this run; nothing here depends on it.

## Not done (stated)

- ADPCM playback and the Arcade Card (M8), subchannel Q, a pure-Python CHD reader (decision 10: chdman only).
- The 80-disc library: **no sweep** was run (IO constraint); three discs, one extraction each.
- A lockstep against a referee; the 26/38-disc System Card sets of the M7 row.
- (Then) no push, no remote, and `pyproject.toml` pinned `git+file://`; since 2026-11-11 the repository is on GitHub, pins the base board's GitHub commit, and CI runs.

**Rerun 2026-11-13 (issue 0001, the drive's clock at register accesses):** Addams Family, Insanity and Pyramid Plunder rerun before and after, same commands as above; see [issues/0001](issues/0001-findings-from-the-rust-port.md) "The discs, before and after".
