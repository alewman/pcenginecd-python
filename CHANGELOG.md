# Changelog

Releases are git tags. Not on PyPI (the base board is pinned by git commit).

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
