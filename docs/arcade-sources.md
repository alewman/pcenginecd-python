# Arcade Card sources (searched 2026-11-09)

**Verdict: NO tier 1-3 source for the Arcade Card exists in the library.** No hardware capture, no
Hudson/NEC document, no research prose describes any Arcade Card register. Every source that does is an
emulator or FPGA core (tier 5: detectors, not judges). All defaults in `m9-record.md` U10 therefore stay
tier 5; nothing here contradicts a default at a better tier, so **no code was changed**.

## What was searched

Under the base board's `reference/` (read in place):

- `docs/pcetech.txt`, `docs/sgxtech.txt`, `docs/pcedev-wiki/*.txt`, `docs/covell-cpu-test.html`
- the ten Hudson/NEC PDFs in `src/turbografx-mister/docs/` (BIOS Manual, Software Manual, PSG Driver,
  HuC6260, HuC6270, HuC6280 hardware and software, CD Unit SCH, `Hu7CD_final.pdf`, TG16 service manual),
  extracted with `pdftotext -layout` to the scratchpad; plus `memmap.txt`, `pcetech.txt` copy, `vdcdox.txt`
  and the commented `Super CD-ROM2 System V3.00 (J).ASM` disassembly
- `src/oss-pce-cd-bios/docs`, `src/mame/hash/pcecd.xml`, and the permissively licensed emulator sources
  (MAME's BSD-3 files, ares). (The search of 2026-11-09 also opened the GPL sources: Mednafen, Geargrafx,
  Mesen2 and the MiSTer core. Under the clean-rewrite rules of 2026-11-19 (docs/restart.md) they are run
  as closed boxes only; what this page said of their code is withdrawn and not repeated.)

Terms: arcade, ACD, `$1A00`, `$1AE0`, `$1AFE/$1AFF`, shift, rotate, 2MB, base/offset/increment.

## Tier 1-3 results (all negative)

| File | Result |
|---|---|
| Hudson PDFs (all ten) | zero hits for "arcade"; no `$1A..` register text. The scans are OCR with errors, so a garbled hit is possible, but every non-OCR cross-check (`1AE0`, `1AFE`, `1AFF`) also found nothing. The only "2MB" hit is Software Manual: "2MB can be controlled" about CD contents files, unrelated |
| `pcetech.txt` (MacDonald, tier 2 research, tested on TG-16) | no Arcade Card text (it predates wide ACD documentation) |
| `sgxtech.txt` l.475 | "Strider ... was released as a CD game which required the Arcade Card" (trivia only, no registers) |
| pcedev-wiki memory map/addresses | the CD's 64 KiB extra RAM only; no Arcade Card |
| System Card V3.00 (J) disassembly | no `$1AE0`/`$1AFE` access; BIOS 3.0 does not probe the card (the games do) |
| `oss-pce-cd-bios/docs` | "Arcade Card: Later target only", "separate dedicated RAM/bank access and BIOS requirements" (specification.md l.33); no register facts |

## Tier 5 sources (emulator-derived, detectors)

- **MAME** `src/devices/bus/pce/pce_acard.cpp` (credited: Priuli, Salese; "TODO: Proper Arcade Card Duo
  support"). `peripheral_r`: ports at `$1A00-$1A09`, shift latch `$1AE0-$1AE3`, `$1AE4` returns
  `m_shift_reg` (stored `data & 0x0f`), `$1AE5` rotate, `$1AFC/$1AFD` 0, `$1AFE` `0x10` ("Version number
  (MSB?)"), `$1AFF` `0x51` ("Arcade Card ID"); other decoded reads `0xff`; `$1A0A` is not a read register
  (falls to `0xff`). `device_reset` clears ports, shift, rotate. RAM window `$080000-$087fff` (banks
  `$40-$43`) decoded through the same handler.
- **ares** `cartridge/board/arcade-card-{duo,pro}.cpp`: `$1AFD` 0 ("version# (low)"), `$1AFE` `0x10`,
  `$1AFF` `0x51` ("identifier"); `$1AE4/5` return the stored 4-bit values; reads outside registers
  return the open-bus `data`; `power()` clears pages and the ALU. The Pro board has System Card ROM
  slots, 2 MiB `dynamic.ram`.
- Mednafen, Geargrafx, Mesen2 and the MiSTer core (GPL): closed boxes only; their behaviour is not
  described here from their code.

## Mapping to m9-record entries

| Entry | Best source now | Better tier? |
|---|---|---|
| U10a `UNMAPPED_READ=0xFF` | MAME `0xFF`; ares open bus | no; the permissive sources split, `0xFF` kept |
| U10b `SHIFT_READ_MASK=0x0F` | MAME and ares store 4 bits | no, emulator tier |
| U10c `TRIGGER_REG_READ=0` | MAME `0xFF`; ares open bus | no; emulator tier **disagrees**, left at 0 |
| U10d `POWER_ON_RAM_BYTE=0` | none say anything beyond zero or random | no |
| U10e `RESET_CLEARS_REGISTERS=False` | MAME `device_reset` and ares `power()` clear, but both model a whole-machine reset, which is not the CD's warm-reset button | no; still unresolved |
| U10f-h | MAME and ares agree on `16-n` for shift/rotate bit 3 | no; shift/rotate remain untested on hardware |
| U10i `$10`/`$51`, `$1AFC/D`=0 | MAME and ares agree (`$1AFE` = `$10`, `$1AFF` = `$51`, `$1AFD` = 0) | no; consistent with the default |
| U10k BIOS | no Arcade System Card ROM present | see below |

## Arcade System Card image

**Not in the library.** Only the Super System Card 3.0 image and `disksys.rom` exist there (player-supplied
files, never in this repository). MAME's `acard_pro` ROM is cited in `m9-record.md` as a baddump and is not on disk.

## The three Arcade discs

Per MAME `hash/pcecd.xml`: Sapphire (serial HCD5080), Mad Stalker (`supported="partial"`), Ryuuko no Ken
all carry `usage = "CD-ROM² Arcade System Card required"` and `sharedfeat requirement = pce:acardpro`.
That is the **only** requirement any source states; none says what registers or RAM they touch, nor
whether System Card 3.0 plus the card suffices. Answered up to the discs' openings by the runs of 2026-11-09 with the ID/data access
counters (`summary.json["arcade"]`, m9-record "Disc results"): System Card 3.0 plus the card suffices that far.
