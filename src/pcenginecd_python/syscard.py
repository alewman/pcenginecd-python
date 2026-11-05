"""The System Card: a HuCard holding the BIOS, and on a Super System Card 192 KiB more RAM.

[hw: pcetech 8, 8.1] The Super System Card (v3.0) maps 192 KiB of RAM at banks `$68-$7F` and
answers identification registers `$18C1-$18C6` (and `$18C7`) in the CD unit's register page; with
the unit's own 64 KiB at `$80-$87` that is 256 KiB. The BIOS tests `$18C5 == $55 && $18C6 == $AA`
(US) or `$18C1 == $AA && $18C2 == $55` with `$18C3` as a version (Japan) and refuses to run
without them ("Dragon Slayer will run for a bit like this").

How a card is recognised as a Super System Card is not documented by the hardware sources: MAME
makes it a separate cartridge type from its software list, Mednafen picks it by the card's
identity in its own database; here a 256 KiB image is a Super System Card (the System Card
v1/v2 images are 128 KiB) -- U37, tier 5. `super_system_card=` overrides.

The id registers' values are MAME's (`pce_scdsys_shared::register_r`: `$1`=AA, `$2`=55, `$3`=00,
`$5`=AA/55, `$6`=55/AA for Japan/US, `$7`=03); Mesen2 answers `$C0-$C3` = 00 AA 55 03 instead (C16:
they differ at `$18C3`, which only changes the X value the BIOS reports).
"""

from __future__ import annotations

from pcengine_python.cards import BANK, RomCard
from pcengine_python.sockets import ResetKind

SUPER_RAM_FIRST_BANK = 0x68
SUPER_RAM_BANKS = 24  # $68-$7F
SUPER_SYSTEM_CARD_BYTES = 256 * 1024


class SystemCard(RomCard):
    def __init__(
        self, data: bytes, *, super_system_card: bool | None = None, region_us: bool = False
    ) -> None:
        super().__init__(data)
        if super_system_card is None:
            super_system_card = len(self.data) == SUPER_SYSTEM_CARD_BYTES
        self.super_system_card = super_system_card
        self.region_us = region_us
        self.ram = bytearray(SUPER_RAM_BANKS * BANK) if super_system_card else None

    def reset(self, kind: ResetKind) -> None:
        if kind is ResetKind.POWER_ON and self.ram is not None:
            self.ram[:] = bytes(len(self.ram))  # U7: power-up RAM is arbitrary; Mednafen zeroes it

    def read(self, address: int, mclk: int) -> int:
        if self.ram is not None:
            bank = (address >> 13) & 0xFF
            if SUPER_RAM_FIRST_BANK <= bank < SUPER_RAM_FIRST_BANK + SUPER_RAM_BANKS:
                return self.ram[address - SUPER_RAM_FIRST_BANK * BANK]
        return super().read(address, mclk)

    def write(self, address: int, value: int, mclk: int) -> None:
        if self.ram is not None:
            bank = (address >> 13) & 0xFF
            if SUPER_RAM_FIRST_BANK <= bank < SUPER_RAM_FIRST_BANK + SUPER_RAM_BANKS:
                self.ram[address - SUPER_RAM_FIRST_BANK * BANK] = value

    def register_read(self, offset: int) -> int:
        """`$18C0 + offset`, called by the CD unit (it owns the page)."""
        if not self.super_system_card:
            return 0xFF
        us = self.region_us
        return {
            1: 0xAA,
            2: 0x55,
            3: 0x00,
            5: 0x55 if us else 0xAA,
            6: 0xAA if us else 0x55,
            7: 0x03,
        }.get(offset, 0x00)
