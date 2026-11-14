# Changelog

Releases are git tags. Not on PyPI (the base board is pinned by git commit).

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
