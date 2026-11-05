# Milestone 7 plan: CD-ROM² boot (the CD unit core)

Scope decided by Aubrey (base board `docs/handoff-brief.md`): CD-ROM² and the Arcade Card are **one**
add-on repository; BIOS bring-your-own, read in place; images are bin/cue (a CHD through `chdman
extractcd` into scratch); the CD is out of the base board's first build and arrives here.
This run is **M7 = the CD unit core**; ADPCM sound, the Arcade Card and the fader's finer cases are M8.

## Built

| Part | Module | Judge |
| --- | --- | --- |
| Disc and TOC from bin/cue, CHD via chdman, memory discs | `disc.py` | directed tests (`test_disc.py`); chdman's cue shape checked on three real discs |
| SCSI bus: phases, REQ/ACK, status/message, abort, reset | `scsi.py` | directed tests through the registers (`test_scsi.py`); pcetech 8 (tier 2) for the registers; emulators (tier 5) for bit-level behaviour |
| Commands: TEST UNIT READY, REQUEST SENSE, READ(6), AUDIO START/END/PAUSE, READ SUBQ, READ TOC | `scsi.py` | same; the BIOS issuing them is the test (`commands.txt` of a boot run) |
| Sector delivery at 75/s, seek from Shadoff's table, re-read penalty | `scsi.py`, `seek.py` | `SECTOR_CLOCKS` etc. are named class attributes, tier 3-5, provisional |
| CD RAM, BRAM with its lock, registers `$1800-$180F`, IRQ2 | `unit.py` | directed tests; the BIOS booting |
| System Card, Super System Card RAM `$68-$7F`, id registers | `syscard.py` | directed tests with a synthetic card; the real card only in scripts |
| CD-DA player, `$1805/6` latch, fader register | `cdda.py` | directed tests; no referee for the audio (U9) |
| ADPCM RAM port as registers | `unit.py` | directed tests only; no sound (M8) |

## Judge and exit for M7

1. The System Card boots to its screen: picture against Beetle PCE (detector, tier 5), tier 2 for registers.
2. A data CD's first sectors read through the SCSI path: directed tests with synthetic discs.
3. About three of the simplest titles reach their first picture; every difference triaged against Beetle PCE
   (and Mednafen/Geargrafx where run). **Not** the 80-disc library; no sweeps (the machine's IO budget).

## U/C entries carried (full text with tiers in m7-record.md)

U8 timings; U9 audio/ADPCM/subchannel; U36 BRAM contents; U37 Super System Card detection; C14 REQUEST SENSE
length; C15 READ TOC answer lengths; C16 `$18C3`; C17 `$1800` mirroring; C18 READ(6) count 0; C19 audio
busy semantics; C20 seek model; S1-S3 socket findings (start-here.md).
