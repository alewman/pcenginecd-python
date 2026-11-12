# Arcade Card sources (searched 2026-11-09)

**Verdict: NO tier 1-3 source for the Arcade Card exists in the library.** No hardware capture, no
Hudson/NEC document, no research prose describes any Arcade Card register. Every source that does is an
emulator or FPGA core (tier 5: detectors, not judges). All defaults in `m9-record.md` U10 therefore stay
tier 5; nothing here contradicts a default at a better tier, so **no code was changed**.

## What was searched

Under `/data/emu/pcengine-python/reference/` (read in place):

- `docs/pcetech.txt`, `docs/sgxtech.txt`, `docs/pcedev-wiki/*.txt`, `docs/covell-cpu-test.html`
- the ten Hudson/NEC PDFs in `src/turbografx-mister/docs/` (BIOS Manual, Software Manual, PSG Driver,
  HuC6260, HuC6270, HuC6280 hardware and software, CD Unit SCH, `Hu7CD_final.pdf`, TG16 service manual),
  extracted with `pdftotext -layout` to the scratchpad; plus `memmap.txt`, `pcetech.txt` copy, `vdcdox.txt`
  and the commented `Super CD-ROM2 System V3.00 (J).ASM` disassembly
- `src/oss-pce-cd-bios/docs`, `src/mame/hash/pcecd.xml`, the MAME, ares, Mednafen, Geargrafx, Mesen2 and
  MiSTer sources

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
- **TurboGrafx16 MiSTer** `rtl/arcade.sv` (Melnikov, GPL, FPGA-core): same map, `$1AFE=8'h10`,
  `$1AFF=8'h51`, `$1AE4/5` stored as `[3:0]`, unmapped reads `8'hFF`, reset clears everything.
- Mednafen, Geargrafx, Mesen2: already cited in `m9-record.md` (not re-read).

## Mapping to m9-record entries

| Entry | Best source now | Better tier? |
|---|---|---|
| U10a `UNMAPPED_READ=0xFF` | MAME and MiSTer `0xFF` (with Mednafen, Geargrafx); ares and Mesen2 open bus | no, tier 5 split 4:2 supports `0xFF` |
| U10b `SHIFT_READ_MASK=0x0F` | MAME, MiSTer, ares all store 4 bits | no, tier 5 (5 of 6 agree) |
| U10c `TRIGGER_REG_READ=0` | MAME/MiSTer `0xFF`; ares open bus; Mesen2/Geargrafx 0 | no; tier 5 **disagrees**, left at 0 |
| U10d `POWER_ON_RAM_BYTE=0` | none say anything beyond zero or random | no |
| U10e `RESET_CLEARS_REGISTERS=False` | MAME `device_reset` and MiSTer `RST_N` clear on reset, but both model whole-machine reset, which is not the CD's warm-reset button | no; flagged: 3 of 6 tier-5 clear on a reset event, still unresolved |
| U10f-h | MAME/ares/MiSTer arithmetic for shift/rotate bit 3 differs between them (16 vs 8 offsets, 32-bit width); ares/MAME agree on `16-n` | no; shift/rotate remain "untested" everywhere |
| U10i `$10`/`$51`, `$1AFC/D`=0 | MAME, ares, MiSTer all agree (`$1AFE=0x10`, `$1AFF=0x51`, `$1AFD`=0) | no; consistent with default, 5-6 emulators |
| U10k BIOS | no Arcade System Card ROM present | see below |

## Arcade System Card image

**Not in the library.** Only `/data/emu/share/batocera/bios/syscard3.pce` (262144 bytes, CRC32
`6d9a73ef`, SHA-1 `79f5ff55dd10187c7fd7b8daab0b3ffbd1f56a2c`) and `disksys.rom` (8192 bytes, CRC32
`5e607dcf`) exist. MAME's `acard_pro` ROM is cited in `m9-record.md` as a baddump and is not on disk.

## The three Arcade discs

Per MAME `hash/pcecd.xml`: Sapphire (serial HCD5080), Mad Stalker (`supported="partial"`), Ryuuko no Ken
all carry `usage = "CD-ROM² Arcade System Card required"` and `sharedfeat requirement = pce:acardpro`.
That is the **only** requirement any source states; none says what registers or RAM they touch, nor
whether System Card 3.0 plus the card suffices. Answered up to the discs' openings by the runs of 2026-11-09 with the ID/data access
counters (`summary.json["arcade"]`, m9-record "Disc results"): System Card 3.0 plus the card suffices that far.
