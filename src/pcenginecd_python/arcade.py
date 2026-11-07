"""The Arcade Card: 2 MiB of RAM behind four address ports, and a 32-bit shift/rotate unit.

An Arcade Card (Hudson, 1994) sits on the same EXT BUS as the CD unit; here it is a component of
`CdUnit`, which claims its pages (one add-on repository: CD-ROM² + Arcade Card). It has no
clock: every access is immediate, so it takes no part in `catch_up`.

Sources, and what is tier what. **No hardware documentation of the card is in `reference/`**: the
card is not in MacDonald's `pcetech.txt`, and the only text the sources cite for it is Mednafen's
header ("based on information provided by Ki and David Shadoff"). So every behaviour below is
[emu: Mednafen `arcade_card.cpp`, Geargrafx `arcade_card_mapper*`, Mesen2 `PceArcadeCard.cpp`]
(tier 5, detectors) and holds where **all three agree**; where they differ the choice is a named
class attribute and a U/C entry in docs/m9-record.md.

Address map [emu, all three]:

| where | what |
| --- | --- |
| banks `$40-$43` | the data of port `bank & 3` at any offset, as `$1A00 + 16 * port` |
| `$1A00-$1A7F` | four port groups, `port = (addr >> 4) & 3`: `$1A40-$1A7F` mirrors `$1A00` |
| `$1AE0-$1AE3` | the 32-bit value register, low byte first |
| `$1AE4` | shift: write n (4 bits) shifts the value, read returns n |
| `$1AE5` | rotate: write n (4 bits) rotates the value, read returns n |
| `$1AFE`, `$1AFF` | version `$10` and ID `$51` |

Port registers (low nibble of the address):

| reg | meaning |
| --- | --- |
| `$0`, `$1` | data: read or write RAM at the effective address, then auto-increment |
| `$2-$4` | base address, 24 bits, low byte first |
| `$5`, `$6` | offset, 16 bits, low byte then high byte |
| `$7`, `$8` | increment, 16 bits |
| `$9` | control (below) |
| `$A` | trigger write (reads 0) |

Control bits: D0 auto-increment; D1 add the offset to the base for the access; D2 signed increment
(no emulator uses it); D3 signed offset; D4 the increment goes to the base (else to the offset);
D6-D5 when the offset is written it is added into the base: 0 never, 1 on the low-byte write, 2 on
the high-byte write, 3 on a write to `$A`.

The effective address is `(base [+ offset [+ $FF0000 if signed]]) & $1FFFFF` (2 MiB).
"""

from __future__ import annotations

from pcengine_python.sockets import ResetKind

ARCADE_RAM_BYTES = 2 * 1024 * 1024
FIRST_PORT_BANK = 0x40
PORT_BANKS = 4
PORT_BANK_PAGES = (0x0800, 0x087F)  # banks $40-$43 at physical $080000-$087FFF (8 KiB banks)
REGISTER_PAGE = 0x1FFA  # $1A00-$1AFF

CTL_AUTO_INCREMENT = 0x01
CTL_ADD_OFFSET = 0x02
CTL_SIGNED_OFFSET = 0x08
CTL_INCREMENT_BASE = 0x10
CTL_TRIGGER_SHIFT = 5
TRIGGER_NONE, TRIGGER_LOW, TRIGGER_HIGH, TRIGGER_REG_A = 0, 1, 2, 3


class ArcadeCard:
    """The card's RAM, four ports and the shift unit."""

    # [emu: Mednafen, Geargrafx $FF; Mesen2 returns the open bus] a read of a decoded address the
    # card has no register at ($1A0B-$1A0F per port group, $1A80-$1ADF, $1AE6-$1AFD, $1B00-$1BFF)
    UNMAPPED_READ = 0xFF
    # [emu: Mednafen, Geargrafx mask to 4 bits; Mesen2 returns the byte written] $1AE4 / $1AE5 reads
    SHIFT_READ_MASK = 0x0F
    # [emu: Mesen2, Geargrafx read 0; Mednafen falls through to $FF] port register $A on a read
    TRIGGER_REG_READ = 0x00
    # [emu: Mednafen zeroes the RAM at power-up; Mesen2 uses its configurable random fill] the real
    # RAM is unspecified (U7 again)
    POWER_ON_RAM_BYTE = 0x00
    # [emu: Geargrafx clears the ports and the shift unit on reset; Mednafen has no reset, Mesen2
    # none visible] a warm reset leaves the registers alone unless this is True
    RESET_CLEARS_REGISTERS = False

    def __init__(self) -> None:
        self.ram = bytearray([self.POWER_ON_RAM_BYTE]) * ARCADE_RAM_BYTES
        self.base = [0] * 4
        self.offset = [0] * 4
        self.increment = [0] * 4
        self.control = [0] * 4
        self.value = 0  # the 32-bit shift register, $1AE0-$1AE3
        self.shift = 0
        self.rotate = 0

    # -- the socket ------------------------------------------------------------------------------

    def claims(self) -> list[tuple[int, int]]:
        return [PORT_BANK_PAGES, (REGISTER_PAGE, REGISTER_PAGE)]

    def reset(self, kind: ResetKind) -> None:
        if kind is ResetKind.POWER_ON:
            self.ram[:] = bytes([self.POWER_ON_RAM_BYTE]) * ARCADE_RAM_BYTES
            self._clear_registers()
        elif self.RESET_CLEARS_REGISTERS:
            self._clear_registers()

    def _clear_registers(self) -> None:
        self.base = [0] * 4
        self.offset = [0] * 4
        self.increment = [0] * 4
        self.control = [0] * 4
        self.value = 0
        self.shift = 0
        self.rotate = 0

    def read(self, address: int, mclk: int = 0) -> int:
        """A physical address in the claimed pages: a bank `$40-$43` byte or a `$1Axx` register."""
        if (address >> 8) < REGISTER_PAGE:
            return self.read_data((address >> 13) & 3)
        return self.read_register(address & 0xFF)

    def write(self, address: int, value: int, mclk: int = 0) -> None:
        if (address >> 8) < REGISTER_PAGE:
            self.write_data((address >> 13) & 3, value)
        else:
            self.write_register(address & 0xFF, value)

    # -- the ports -------------------------------------------------------------------------------

    def effective_address(self, port: int) -> int:
        address = self.base[port]
        control = self.control[port]
        if control & CTL_ADD_OFFSET:
            address += self.offset[port]
            if control & CTL_SIGNED_OFFSET:
                address += 0xFF0000
        return address & 0x1FFFFF

    def _auto_increment(self, port: int) -> None:
        control = self.control[port]
        if control & CTL_AUTO_INCREMENT:
            if control & CTL_INCREMENT_BASE:
                self.base[port] = (self.base[port] + self.increment[port]) & 0xFFFFFF
            else:
                self.offset[port] = (self.offset[port] + self.increment[port]) & 0xFFFF

    def _add_offset_to_base(self, port: int) -> None:
        total = self.base[port] + self.offset[port]
        if self.control[port] & CTL_SIGNED_OFFSET:
            total += 0xFF0000
        self.base[port] = total & 0xFFFFFF

    def read_data(self, port: int) -> int:
        value = self.ram[self.effective_address(port)]
        self._auto_increment(port)
        return value

    def write_data(self, port: int, value: int) -> None:
        self.ram[self.effective_address(port)] = value
        self._auto_increment(port)

    def _trigger(self, port: int) -> int:
        return (self.control[port] >> CTL_TRIGGER_SHIFT) & 3

    # -- the registers ---------------------------------------------------------------------------

    def read_register(self, reg: int) -> int:
        """`reg` is the low byte of the address within `$1A00-$1AFF`."""
        if reg < 0x80:
            port = (reg >> 4) & 3
            n = reg & 0x0F
            if n < 2:
                return self.read_data(port)
            if n <= 4:
                return (self.base[port] >> (8 * (n - 2))) & 0xFF
            if n <= 6:
                return (self.offset[port] >> (8 * (n - 5))) & 0xFF
            if n <= 8:
                return (self.increment[port] >> (8 * (n - 7))) & 0xFF
            if n == 9:
                return self.control[port]
            if n == 0x0A:
                return self.TRIGGER_REG_READ
            return self.UNMAPPED_READ
        if reg < 0xE0:
            return self.UNMAPPED_READ
        n = reg & 0x1F
        if n < 4:
            return (self.value >> (8 * n)) & 0xFF
        if n == 4:
            return self.shift & self.SHIFT_READ_MASK
        if n == 5:
            return self.rotate & self.SHIFT_READ_MASK
        if n == 0x1C or n == 0x1D:
            return 0x00
        if n == 0x1E:
            return 0x10  # version [emu: all three; Mednafen: "we should verify this"]
        if n == 0x1F:
            return 0x51  # ID
        return self.UNMAPPED_READ

    def write_register(self, reg: int, value: int) -> None:
        if reg < 0x80:
            port = (reg >> 4) & 3
            n = reg & 0x0F
            if n < 2:
                self.write_data(port, value)
            elif n <= 4:
                shift = 8 * (n - 2)
                self.base[port] = (self.base[port] & ~(0xFF << shift)) | (value << shift)
            elif n == 5:
                self.offset[port] = (self.offset[port] & 0xFF00) | value
                if self._trigger(port) == TRIGGER_LOW:
                    self._add_offset_to_base(port)
            elif n == 6:
                self.offset[port] = (self.offset[port] & 0x00FF) | (value << 8)
                if self._trigger(port) == TRIGGER_HIGH:
                    self._add_offset_to_base(port)
            elif n == 7:
                self.increment[port] = (self.increment[port] & 0xFF00) | value
            elif n == 8:
                self.increment[port] = (self.increment[port] & 0x00FF) | (value << 8)
            elif n == 9:
                self.control[port] = value & 0x7F
            elif n == 0x0A and self._trigger(port) == TRIGGER_REG_A:
                self._add_offset_to_base(port)
            return
        if reg < 0xE0:
            return
        n = reg & 0x1F
        if n < 4:
            shift = 8 * n
            self.value = (self.value & ~(0xFF << shift)) | (value << shift)
        elif n == 4:
            self.shift = value
            count = value & 0x0F
            if count:
                if count & 8:
                    self.value >>= 16 - count  # right by 8..1 for 8..15
                else:
                    self.value = (self.value << count) & 0xFFFFFFFF
        elif n == 5:
            self.rotate = value
            count = value & 0x0F
            if count:
                v = self.value
                if count & 8:
                    sa = 16 - count
                    self.value = ((v >> sa) | (v << (32 - sa))) & 0xFFFFFFFF
                else:
                    self.value = ((v << count) | (v >> (32 - count))) & 0xFFFFFFFF
