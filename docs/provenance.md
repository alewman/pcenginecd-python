<!-- SPDX-License-Identifier: MIT -->
# Provenance

## Licence provenance (audit 2026-11-13)

Judged against the family charter ("Licences and provenance", rule 3: nothing copied or transcribed
from GPL/LGPL code; GPL programs are run as closed boxes, their source not opened while writing).
Audited from this repository's records only; no GPL source was opened. The reference trees, their
licences and the check are in pcengine-python's `docs/provenance.md` (same date). In short: MAME's
PC Engine files (`nec/pce_cd.cpp`, `bus/pce/pce_acard.cpp`, `pce_scdsys.cpp`, `sound/msm5205.cpp`)
are all **BSD-3-Clause** and ares is **ISC**, so they may be read and cited; Mednafen, Mesen2,
Geargrafx and the MiSTer core are GPL: closed-box only. `provenance_check.py`, re-run against the
permissive trees, matched only the Super System Card id bytes (`syscard.py` against MAME
`pce_scdsys.cpp`) and two lines of a SCSI table (`scsi.py` against MAME `nec/pce_cd.cpp`): facts from
BSD-3 sources.

| Code | Behaviour source (licence) | Verdict |
| --- | --- | --- |
| `seek.py` | Dave Shadoff's `seektime.c` and measurements, PCECD_seek (MIT); the zone table and the model's shape derive from it | **cite**: the MIT notice is in NOTICE.md and the docstring names the licence; add an SPDX line naming Shadoff's notice when headers are added |
| `syscard.py` | MAME `pce_scdsys.cpp` id registers (BSD-3); RAM and banks from pcetech 8 | **cite**: add MAME's BSD-3 notice to NOTICE.md beside the seek notice (eight id bytes: facts, but the table is MAME's) |
| `scsi.py`: the bus state machine (`ScsiBus._settle` and the phase handlers), the timing constants, the auto-ACK pulse, the abort path | the docstring and comments: "Run the phase logic until the signals stop changing (Mesen2's `UpdateState`)" (l.332); "Mesen2 counts these in units of 3 master clocks ... converted here" (l.110-111); `pulse_ack` "[emu: Mesen2; the pulse width is its measurement]" (l.318); abort "[emu: Mesen2 from scsitest.pce, verificator.pce]" (l.344) (GPL-3.0) | ~~rewrite~~ **rewritten 2026-11-19** ([restart.md](restart.md)): the module was moved aside unread and replaced from SCSI-1, pcetech 8, the Hudson BIOS manual and System Card disassembly, MAME and ares (facts, nothing ported), with the timings measured closed-box on Geargrafx (`scripts/drive_probe.py`). Audit text: the control flow is named after, and its constants converted from, Mesen2's `PceScsiBus.cpp`. Rebuild from the SCSI-2 phase rules, pcetech 8, MAME `nec/pce_cd.cpp` (BSD-3) and ares `pcd/scsi.cpp` (ISC), with timings measured closed-box (the boot harness drives Geargrafx and Beetle PCE) |
| `scsi.py`: command set, lengths, sense codes, status/message bytes | SCSI-2 and the drive's command list (facts); MAME table (BSD-3) | **clean** |
| `unit.py` | pcetech 8 registers; `BRAM_FORMATTED` is the BIOS's `HUBM` format header (a fact of the BIOS's data format); `CHANNEL_LATCH_GUARD`, `DMA_BYTE_CLOCKS` are Mesen2's author's test-ROM results stated in prose (the middle rule) | **clean** (facts; Mesen2 named as reporter) |
| `adpcm.py` | pcetech 8, the Hudson BIOS manual and how the System Card drives the registers (facts read from a community disassembly, not copied); the MSM5205 step table "as modelled by MAME `msm5205.cpp`" (BSD-3); emulator-only choices are named switches | **cite**: name MAME `msm5205.cpp` BSD-3 for the table formula |
| `cdda.py` | Red Book, Hudson BIOS manual fade times; the READ SUBQ status byte values (Mednafen, a fact) | **clean** |
| `arcade.py` | its docstring credits Mednafen, Geargrafx and Mesen2 (GPL); **every behaviour it models is also in MAME `bus/pce/pce_acard.cpp` (BSD-3: ports, base/offset/increment, control bits 0x60 offset-add modes, shift/rotate, `$1AFE` = `$10`, `$1AFF` = `$51`) and ares's Arcade Card boards (ISC)**, checked in those permissive files during this audit; the 2026-11-12 check against the GPL trees found register runs only | **cite**: re-cite to MAME (BSD-3) and ares (ISC) as the readable sources; the emulator-split switches (U10a-e) stay tier 5 |
| `disc.py`, `board.py` | cue/bin layout (facts), pcetech 8 (MSF = LBA + 150) | **clean** |
| `scripts/` (cd_boot, beetle_press, ...) | run Geargrafx, Beetle PCE as closed boxes | **clean** |
| `tests/` | our own tests | **clean** |
| `docs/arcade-sources.md` | quoted the MiSTer core's Verilog constants (GPL) and named a machine path and a BIOS file's hashes | **done 2026-11-19**: the fragments, the path and the hashes dropped; the facts re-cited to MAME and ares |

Counts (2026-11-13): clean 6, cite 5, rewrite 1, unclear 0. After the clean rewrite (2026-11-19): rewrite 0; see below. After the notices of 2026-11-19 (below): **clean 12, cite 0, rewrite 0, unclear 0**.

Inherited: this add-on runs on pcengine-python, whose VDC line machine is marked **rewrite** there.

The System Card image is never in this repository: it is the player's own file, passed by path. (README and scripts name a machine path for it as a default: a house-rule matter, not a licence one; romsets and firmware go by environment variable.)

History: 22 commits, no deleted files, no C/C++ code in any added line. `docs/arcade-sources.md`'s
MiSTer fragments and machine path are in the public history since `e093a2b`.

## Clean rewrite, 2026-11-19

The one **rewrite** item is done: `scsi.py` was moved aside unread (`scratch/withdrawn/`, git-ignored)
and replaced. Rules, sources and what stays open: [restart.md](restart.md). Every timing constant of
the new module is either a document fact, a closed-box measurement of Geargrafx 57c257d through
`scripts/drive_probe.py` (marked OBSERVED), a permissive emulator's value (MAME, BSD-3) or a marked
choice; none was carried over from the withdrawn module.

| Code | Behaviour source (licence) | Verdict |
| --- | --- | --- |
| `scsi.py` (new) | SCSI-1; pcetech 8; Hudson CD System BIOS manual and the System Card 3.00 disassembly (Hudson documents in the MiSTer repository's `docs/`); Shadoff's seek model (MIT, `seek.py`); MAME `nec/pce_cd.cpp` (BSD-3) and ares `pce/pcd` (ISC) for facts, nothing ported; closed-box Geargrafx | **clean** |
| `scripts/drive_probe.py` (new) | our probe program and libretro host; runs GPL cores as libraries, reads only their work RAM | **clean** (tool) |
| `unit.py` | `CHANNEL_LATCH_GUARD` and the `$180B` bit-0 rule now also closed-box measured; `DMA_BYTE_CLOCKS` stays a reported test-ROM value (open: the closed box disagrees) | **clean** |
| `arcade.py`, `adpcm.py`, `cdda.py`, `disc.py` | GPL file and function names removed from comments; facts re-cited to MAME, ares, the Hudson manual or closed-box observation | **clean** (the cite actions for these files are done; the NOTICE.md entries for MAME's id bytes and step formula were added on 2026-11-19, below) |
| `docs/arcade-sources.md`, `docs/m7-record.md`, `docs/m8-record.md` | Verilog fragments, machine path, hashes and a GPL identifier removed; U8 rows re-sourced | **clean** |

### The judges, before and after

Before = HEAD 9dc1637 (the withdrawn module), after = this commit; same base board pin, niced PyPy,
`PYPY_GC_NURSERY=1M`, load average 37-81.

- Quick suite: 103 passed before; 104 passed after (one test added:
  `test_audio_end_repeat_of_an_empty_range_plays_nothing_and_stays_busy`). One test changed:
  `test_selecting_during_data_in_aborts_with_an_eight_byte_message` looked at the withdrawn model's
  internal buffer (`len(bus.out) == 8`); it is now
  `test_selecting_during_data_in_aborts_with_eight_status_bytes_then_the_message`, which takes the
  REQs as the BIOS does and expects eight `$D8`/`$00` then `$F8`/`$00` (the closed box's sequence),
  and then a working READ. The other tests' timing assertions are bounds that hold for the new values
  (`SEL_TO_COMMAND_PHASE`, `TEST_UNIT_READY`, `SECTOR_CLOCKS`, `REREAD_PENALTY_MS` keep their names).
- Slow System Card boot (`tests/test_boot_slow.py`) and the save state taken while the BIOS reads
  (`tests/test_state_slow.py`): pass before and after.
- Disc boots (`scripts/cd_boot.py`, `syscard3.pce`, 3,000 frames, RUN held 20 frames at 450,
  `--png-at 1000,2000,3000`, `--arcade` for the first three), compared at the 9-bit rows and, where
  a picture moved, by eye against Geargrafx (libretro, `scripts/beetle_press.py --core`, same press)
  at the same frame:

| Disc | Drive commands | ADPCM samples | Pictures 1000/2000/3000 | Against Geargrafx |
| --- | --- | --- | --- | --- |
| Ryuuko no Ken (Arcade) | 12 / 12, same | 47,410 / 47,410 (6 ends) | same / same / **moved** | 3000: before a white flash frame, after the grey fade-in of the Hudson/SNK title, which is Geargrafx's picture: **closer** |
| Mad Stalker (Arcade) | **426 / 411** (fewer READ SUBQ polls in the CD-audio wait; each poll now takes the closed box's times) | 0 / 0 | moved / same / moved | 3000: the cutscene's scroll position now matches Geargrafx's: **closer**; 1000: the logo's fade phase differs in all three: undecided |
| Ginga Fukei Densetsu Sapphire (Arcade) | 19 / 19, same | 0 / 0 | same / moved / moved | the same scenes; the converging lines at 3000 are nearer Geargrafx's extent: **closer** by eye, small |
| Pyramid Plunder | 12 / 12, same | 114,688 / 114,688 (2 ends) | same / moved / moved | the title screen in all three; the bird and the scrolling text are at different phases: undecided |
| The Addams Family | 18 / 18, same | **533,755 / 536,583** (1 end) | same / same / same | not rerun (pictures did not move) |
| Insanity | 10 / 10, same | 0 / 0 | same / same / moved | the raster-bar phase differs in all three: undecided |

  The first commands land a little later after (TEST UNIT READY +510 clocks, each READ TOC about
  +3,800: the closed box's command-phase times), and each READ completes 0.61-0.79 M clocks sooner
  (one sector time, 286,363, which the withdrawn module waited after the seek, plus the BIOS's share
  of Shadoff's interval, 332,000, now taken off), so the shift grows with the number of READs (up to
  9.3 M clocks by frame 3,000 on Sapphire). The command texts are the same
  on five discs. Addams' extra ADPCM samples follow its earlier reads (the ADPCM plays longer
  before frame 3,000), with the same end count.

  The six boots ran on the module before its last two changes (the two data latches, and the guard
  for a repeat of an empty range). Mad Stalker and Addams were rerun on the final module: summaries,
  command logs and all three pictures identical to the runs above. (The guard only acts where the
  old run would have hung; the latches only differ when the CPU writes `$1801` and then reads it in
  a phase the target drives, which the BIOS does not do.)

### The probe, before and after (`scripts/drive_probe.py`, master clocks as measured by 45-clock turns)

| Measurement | Geargrafx 57c257d | after | before (withdrawn) |
| --- | --- | --- | --- |
| SEL to command phase (BSY and REQ together) | 74,880 | 74,790 | 74,880 |
| ACK dropped to the next command byte's REQ | 2,970 | 2,970 | 2,925 |
| TEST UNIT READY (also straight after a reset) | 449,505 | 449,055 | 449,460 |
| READ TOC / READ SUBQ answer | 8,955 / 2,970 | 8,955 / 2,970 | 8,955 / 2,925 |
| READ TOC answer lengths, kinds 0/1/2 | 4 / 4 / 4 | 2 / 3 / 4 | 2 / 3 / 4 |
| REQUEST SENSE | GOOD after 450,495, no data | 18 bytes | 18 bytes |
| last data byte to status; status to message; message to bus free | 2,970; 1,440; 1,440 | 2,970; 1,440; 1,440 | 2,925; 0; 0 |
| `$1808` read: ACK at +15 / +45 clocks; REQ back by +45 | set / clear; yes | set / clear; yes | set / clear; yes |
| next data REQ after a handshake | at once | at once | at once |
| a sector missed while the buffer holds the last: next one after the read ends | 6,102,135 and 4,923,720 (two stalls) | 6,102,090 and 4,923,675 | 6,102,090 and 4,923,675 |
| READ of the first / a nearby / a far sector, command to REQ | 3,679,200 / 8,138,430 / 8,138,430 | 4,318,290 / 6,821,280 / 6,821,280 | 4,936,005 / 7,438,995 / 7,438,995 |
| AUDIO START to its status | 3,046,500 | 7,152,930 | 7,152,930 |
| SEL in data in, or while a READ seeks | status at once; 8 x (`$D8`, `$00`), (`$F8`, `$00`), bus free | the same (after the data-latch fix) | status at once; 8 x `$D8` then `$F8` then 7 more data-in REQs |
| SEL while busy in an AUDIO END repeat or IRQ-mode play | command phase after 74,700 / 74,835 | after 74,610 / 74,745 | after 74,700 / 74,835 |
| AUDIO END mode 1 | BSY alone, no REQ for 11 s | the same | the same |
| `$180B` written `$03` with no data waiting | reads `$02` | `$02` | not probed |
| `$1805` writes 225 / 245 CPU cycles apart | second ignored / toggles | the same | not probed |
| CD-to-ADPCM DMA, REQ sampled every 10 cycles | one byte every 90 clocks | one every ~105 (open) | not probed |
| READ SUBQ status byte, nothing played yet | `$01` (still) | `$03` (not playing) | `$03` |

The after column runs about 0.1% short of Geargrafx on long intervals (2 turns at 75,000, 10 at
450,000) although the drive's own times were set from the Geargrafx windows and check exactly at
register level (tests/helpers.py's `Host`): the difference is in the CPU side of the loop on the two
machines, not in the drive. READ and AUDIO START times differ by design: they follow Shadoff's
hardware seek measurements (tier 3), which outrank the closed box.

### What a Rust transcription (pcenginecd-rust) must carry

`scsi.py` is new: transcribe it whole rather than patching the old port. In particular:

- `Phase` gains `BUSY` ("busy": BSY with no information phase). `status_bits` comes from the phase's
  (MSG, C/D, I/O) row plus REQ and BSY (BSY = any phase but bus free).
- Timers: one protocol step (`_step`, `_step_at`), the READ's sector clock (`_sector_at`) and the
  auto-ACK end (`_ack_off_at`); `next_event` is the minimum of those and the CD-DA player's event;
  `run_to` handles, at each due time, the ACK end first, then the step, then the sector, then the
  player, and finally runs the player to the target.
- Constants (master clocks): SEL to command phase 74,940; command byte 3,030; TEST UNIT READY
  449,565; READ TOC 9,015; READ SUBQ 3,030; quick answers (REQUEST SENSE, PAUSE, AUDIO END 0/3,
  errors, READ of 0 sectors) 3,030; unknown opcode 450,555; data to status 3,030; status to message
  1,500; message to bus free 1,500; auto-ACK 45; sector 286,363 (`MASTER_HZ // 75`); re-read
  `MASTER_HZ * 290 // 1000` = 6,228,408 after the missed turn; abort status bytes 8; first sector
  of a READ at `max(seek - 332,000, 286,363)` with `seek = round(seek_time_ms * MASTER_HZ / 1000)`
  from the head (the CD-DA position while audio is active, else the sector after the last one read).
- Handshake: REQ drops at ACK rising (the byte is taken then: command byte appended, data byte
  counted, status byte counted); at ACK falling the next step is scheduled: command byte REQ, or
  execute when the block is complete (6 bytes for `00 03 08`, 10 for `D8-DA DD DE`, 1 for any other
  opcode); in data in the next byte's REQ at once, or the status after `DATA_TO_STATUS` when the
  last sector is taken; in status, REQ again at once while abort bytes remain, else the message
  after `STATUS_TO_MESSAGE`; in message in, bus free after `MESSAGE_TO_FREE`. A sector that arrives
  while ACK is high waits for ACK to fall.
- SEL: ignored while RST is held or a selection is pending; from bus free or `BUSY` a selection
  (the pending step and any audio wait dropped, audio plays on); in data in the abort (read
  stopped, block emptied, status phase at once with eight GOOD bytes); in the command, status or
  message phase ignored.
- After the last command byte the phase is `DATA_IN` (REQ low) for commands that answer with data
  and for READ, `BUSY` for the others; the answer step then offers the data or the status.
- Commands: as `_execute` and the handlers; no disc gives CHECK CONDITION NOT READY / `$3A`
  except for REQUEST SENSE; READ beyond the disc ILLEGAL REQUEST / `$21`; PAUSE without audio
  ILLEGAL REQUEST / `$2C`; READ TOC kind 3 (LBA + control) and track `$AA` (lead-out) are new;
  AUDIO END in track mode ends before the named track; a repeat (mode 1) of an empty range stops
  the audio and stays busy; AUDIO END mode 0 stops the audio.
- `reset()` also stops the CD-DA player and clears `head`, `_took`, the sector clock and the abort
  count; `set_reset(True)` resets on every write that holds the line.
- Two data latches: `data` (what the target drives) and `initiator_data` (the CPU's `$1801`
  write); `read_data()` returns `data` while I/O is up and `initiator_data` otherwise; a command
  byte is taken from `initiator_data`.
- `ScsiBus.data_waiting` (bytes of the current block not yet taken) replaces `len(bus.out)` in
  `CdUnit` (the `$180B` bit-0 rule and the DMA's end of sector); `out` is still there for tests.
- `CddaPlayer.start` (new read-only property) is the last AUDIO START's sector.
- No other module's behaviour changed: `unit.py`, `adpcm.py`, `arcade.py`, `cdda.py`, `disc.py`
  changed comments only (plus `start`).

## Notices and headers, 2026-11-19 (after the base board's repin)

The cite items' last actions, done; no behaviour changed.

| Item | What was done |
| --- | --- |
| `syscard.py` (id bytes) | NOTICE.md: MAME `src/devices/bus/pce/pce_scdsys.cpp`, BSD-3-Clause, copyright Fabio Priuli, Wilbert Pol (licence line checked), with the BSD-3 text; a header line in the file |
| `adpcm.py` (MSM5205 step formula) | NOTICE.md: MAME `src/devices/sound/msm5205.cpp`, BSD-3-Clause, copyright Aaron Giles |
| `scsi.py` (command table facts) | NOTICE.md: MAME `src/mame/nec/pce_cd.cpp`, BSD-3-Clause, copyright Wilbert Pol, Angelo Salese (the two table lines `provenance_check.py` matched are facts; the notice is kept anyway) |
| `arcade.py` | NOTICE.md: MAME `src/devices/bus/pce/pce_acard.cpp`, BSD-3-Clause, copyright Fabio Priuli, Angelo Salese |
| `seek.py` | SPDX header and a line naming Shadoff's MIT notice (already in NOTICE.md) |
| every Python file, `pyproject.toml`, `NOTICE.md` | SPDX headers where missing |
| scripts and slow tests | the System Card is named by `$PCE_SYSTEM_CARD` and the base board's checkout defaults to the sibling `../pcengine-python`: no machine path left in code (house rule; the audit's note above). Some older records under `docs/` still name paths as history |
