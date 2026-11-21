<!-- SPDX-License-Identifier: MIT -->
# Changelog

Releases are git tags. Not on PyPI (the base board is pinned by git commit).

## Unreleased

- 2026-11-20: the pins are on GitHub (pcengine-python 03ac699, huc6280-python 6ce348e,
  6502-python 2146eba); `pip install -e ".[dev]"` resolves them from there again. Checked in a
  fresh PyPy venv: 104 quick tests pass, ruff clean.

- Base board pcengine-python **03ac699** (local): a display that starts before the row is
  cropped and the row keeps its length. Quick suite 104 passed, slow tests 2 passed; nothing here
  changed (docs/restart.md, last section).

Repin to the base board's clean rewrite (docs/restart.md, "Repin to the clean base board"):

- Base board pcengine-python **3318027** (its clean VDC rewrite; core huc6280-python 6ce348e),
  then not yet on GitHub (pushed 2026-11-20; the venvs were installed from the local clones). Save states from
  the old pin do not load. No code used the removed base interfaces; nothing to adapt.
- Judges: 104 quick tests and the two slow tests pass; the six disc boots give the same command
  texts, ADPCM counts and pictures (moved 8 dots left in the row with the base display), command
  times within a few dozen clocks (Addams up to 2,316).
- NOTICE.md: MAME's BSD-3-Clause files the add-on takes facts from (`pce_scdsys.cpp` id bytes,
  `msm5205.cpp` step formula, `nec/pce_cd.cpp` drive facts, `pce_acard.cpp`), with copyright
  holders and the licence text. SPDX headers on every file.
- The System Card is named by `$PCE_SYSTEM_CARD` in the scripts and slow tests (no machine path);
  the base board's checkout defaults to the sibling `../pcengine-python`.

The clean rewrite of the drive's bus (docs/restart.md; the provenance audit's one **rewrite**
item). Before and after: docs/provenance.md, "Clean rewrite, 2026-11-19".

- `scsi.py` replaced: a new SCSI-1 bus written from the SCSI-1 standard, pcetech 8, the Hudson
  CD System BIOS manual and the System Card 3.00 disassembly (how the BIOS drives the bus), with
  facts from MAME `nec/pce_cd.cpp` (BSD-3) and ares (ISC); the withdrawn module was moved aside
  unread. Same interface (`ScsiBus`, `Phase`, the timing attributes), plus `Phase.BUSY`, the
  `data_waiting` count and `head`.
- Timing re-established as closed-box measurements of Geargrafx 57c257d with the new
  `scripts/drive_probe.py` (a probe program of ours standing in for the System Card): SEL to
  command phase 74,940 clocks, command byte 3,030, TEST UNIT READY 449,565, READ TOC 9,015, READ
  SUBQ 3,030, data to status 3,030, status to message and message to bus free 1,500 each, re-read
  290 ms after the missed turn. The auto-ACK pulse is 45 clocks (MAME: 15 CPU cycles).
- SEL during data in (or while a READ seeks): the status phase at once, eight GOOD bytes, then the
  message (closed box). SEL while busy with CD audio or a seek: a new selection after the usual
  time.
- READ: the first sector's REQ comes at Shadoff's seek time less the BIOS's own share of his
  measured interval (332,000 clocks; his test times the whole CD_READ), not one sector after it:
  every READ completes 0.61-0.79 M clocks sooner than before.
- READ TOC kind 3 (a track's LBA, Hudson manual CD_DINFO) and track `$AA` (the lead-out, MAME);
  PAUSE with no audio started answers CHECK CONDITION (MAME, ares); a repeat of an empty range
  plays nothing and stays busy (without that guard the CD-DA player's repeat would never end;
  found by the probe).
- The data bus has two latches: the target's byte while I/O is up, the CPU's `$1801` write
  otherwise (SCSI-1's direction rule; the closed box's abort bytes read `$00`).
- Disc boots: Mad Stalker 426 -> 411 drive commands, Addams 533,755 -> 536,583 ADPCM samples, and
  pictures moved on five discs, closer to Geargrafx where it can be told (docs/provenance.md).
- Comments and documents that named GPL emulators' internals re-cited (`unit.py`, `adpcm.py`,
  `arcade.py`, `cdda.py`, `disc.py`, `docs/arcade-sources.md`, the M7/M8 records); SPDX headers on
  the files touched.

## 0.2.0 (2026-11-14)

- Base board: pcengine-python 0.2.0 (core huc6280-python 0.4.0; the board's issue 0004).

Issue 0001 (what the Rust port found), settled: [docs/issues/0001](docs/issues/0001-findings-from-the-rust-port.md).

- A register access brings the drive, the ADPCM unit and the DMA to its own master clock
  (`CdUnit._run_now`), so a drive timer counts from the write that starts it. Before this, while
  some event waited in the future (CD audio playing), the timers counted from the last event: SEL
  to the command phase took 0 clocks instead of 75,000. CD RAM and BRAM accesses take no clock.
- A power-on reset clears the unit's DMA and `$1805`-guard timers and lets go of the bus's RST;
  the ADPCM unit's idle output is filed at the reset's time, not at 0.
- `ScsiBus.reset` reports the IRQ levels it drops, and no longer clears `rst`: the drive stays in
  reset while `$1804` bit 1 is held (it used to reset only at the edge).
- New switch `ScsiBus.UNKNOWN_COMMAND_CHECK_CONDITION` (default `False`: Good, as before).
- `CdUnit(bram=...)` longer than 2 KiB, and a cue `TRACK` before any `FILE` or `INDEX` before any
  `TRACK`, raise `ValueError`.

## 0.1.0 (2026-11-12)

The first release: the PC Engine CD-ROM², Super CD-ROM² and Arcade Card as an add-on to
pcengine-python. The System Card and every disc are bring-your-own.

- M7: the System Card (with the Super System Card's RAM), the CD unit's interface, the
  SCSI-class controller, bin/cue discs (a CHD through `chdman`), CD audio with the fader, backup RAM.
- M8: the ADPCM unit (MSM5205) as an audio source; fade times from Hudson's BIOS manual.
- M9: the Arcade Card (ports, shift unit, banks `$40-$43`); the library's three Arcade Card discs
  boot on System Card 3.0 plus the card and match Geargrafx at the frames compared.
- Save states through the base board's `pcengine_python.state`; a disc is named by its table of
  contents, never stored.
- Not built: the subchannel Q stream. Not done: playing any disc through; audio compared on one disc.
- Base board: pcengine-python 0.1.0.
