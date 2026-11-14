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
| `scsi.py`: the bus state machine (`ScsiBus._settle` and the phase handlers), the timing constants, the auto-ACK pulse, the abort path | the docstring and comments: "Run the phase logic until the signals stop changing (Mesen2's `UpdateState`)" (l.332); "Mesen2 counts these in units of 3 master clocks ... converted here" (l.110-111); `pulse_ack` "[emu: Mesen2; the pulse width is its measurement]" (l.318); abort "[emu: Mesen2 from scsitest.pce, verificator.pce]" (l.344) (GPL-3.0) | **rewrite**: the control flow is named after, and its constants converted from, Mesen2's `PceScsiBus.cpp`. Rebuild from the SCSI-2 phase rules, pcetech 8, MAME `nec/pce_cd.cpp` (BSD-3) and ares `pcd/scsi.cpp` (ISC), with timings measured closed-box (the boot harness drives Geargrafx and Beetle PCE) |
| `scsi.py`: command set, lengths, sense codes, status/message bytes | SCSI-2 and the drive's command list (facts); MAME table (BSD-3) | **clean** |
| `unit.py` | pcetech 8 registers; `BRAM_FORMATTED` is the BIOS's `HUBM` format header (a fact of the BIOS's data format); `CHANNEL_LATCH_GUARD`, `DMA_BYTE_CLOCKS` are Mesen2's author's test-ROM results stated in prose (the middle rule) | **clean** (facts; Mesen2 named as reporter) |
| `adpcm.py` | pcetech 8, the Hudson BIOS manual and how the System Card drives the registers (facts read from a community disassembly, not copied); the MSM5205 step table "as modelled by MAME `msm5205.cpp`" (BSD-3); emulator-only choices are named switches | **cite**: name MAME `msm5205.cpp` BSD-3 for the table formula |
| `cdda.py` | Red Book, Hudson BIOS manual fade times; the READ SUBQ status byte values (Mednafen, a fact) | **clean** |
| `arcade.py` | its docstring credits Mednafen, Geargrafx and Mesen2 (GPL); **every behaviour it models is also in MAME `bus/pce/pce_acard.cpp` (BSD-3: ports, base/offset/increment, control bits 0x60 offset-add modes, shift/rotate, `$1AFE` = `$10`, `$1AFF` = `$51`) and ares's Arcade Card boards (ISC)**, checked in those permissive files during this audit; the 2026-11-12 check against the GPL trees found register runs only | **cite**: re-cite to MAME (BSD-3) and ares (ISC) as the readable sources; the emulator-split switches (U10a-e) stay tier 5 |
| `disc.py`, `board.py` | cue/bin layout (facts), pcetech 8 (MSF = LBA + 150) | **clean** |
| `scripts/` (cd_boot, beetle_press, ...) | run Geargrafx, Beetle PCE as closed boxes | **clean** |
| `tests/` | our own tests | **clean** |
| `docs/arcade-sources.md` | quotes the MiSTer core's `rtl/arcade.sv` constants (`8'h10`, `8'h51`, GPL) and names a machine path and a BIOS file's hashes | **cite** (wording): keep the facts, drop the Verilog fragments and the machine path |

Counts: clean 6, cite 5, rewrite 1, unclear 0.

Inherited: this add-on runs on pcengine-python, whose VDC line machine is marked **rewrite** there.

The System Card image is never in this repository: it is the player's own file, passed by path. (README and scripts name a machine path for it as a default: a house-rule matter, not a licence one; romsets and firmware go by environment variable.)

History: 22 commits, no deleted files, no C/C++ code in any added line. `docs/arcade-sources.md`'s
MiSTer fragments and machine path are in the public history since `e093a2b`.
