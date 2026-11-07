"""The CD unit: the expansion-port device that owns `$1800-$18FF`, CD RAM and the backup RAM.

It plugs into the base board's socket 2 (`PortDevice`): `claims()` lists the pages, every access
carries its master-clock time, `catch_up(mclk)` runs the drive up to it (the board calls it every
cycle, base issue 0002), `present` pulls the I/O port's bit 7 low, and IRQ2 is the
board's wired-OR line with this unit's own bit, "cd".

Registers [hw: pcetech 8 for the names; the bit-level behaviour is emulator-derived, tier 5, and
each is marked]:

| addr | read | write |
| --- | --- | --- |
| `$1800` | SCSI status: D3 I/O, D4 C/D, D5 MSG, D6 REQ, D7 BSY | select the drive (SEL pulse) |
| `$1801` | the SCSI data bus | the data bus (command bytes) |
| `$1802` | IRQ enable mask (D6-D0) and ACK (D7) | the same: D7 sets ACK, D6-D0 the mask |
| `$1803` | active IRQ bits, D1 = left/right flag; **locks BRAM** | -- |
| `$1804` | the reset register | D1 = SCSI reset (the BIOS's CD_RESET sets then clears it) |
| `$1805` | CD-DA sample, low byte | toggles left/right and latches that channel's sample |
| `$1806` | CD-DA sample, high byte | -- |
| `$1807` | subchannel byte (not modelled: 0) | D7 set **unlocks BRAM** |
| `$1808` | the SCSI data bus; a read of data in pulses ACK | ADPCM address low |
| `$1809` | -- | ADPCM address high |
| `$1808/9`, `$180A-$180E` | the ADPCM unit (adpcm.py); `$180B` bit 1 = CD-to-ADPCM DMA | the same |
| `$180F` | the fader register | fade control |
| `$1A00-$1AFF`, banks `$40-$43` | the Arcade Card, when fitted (arcade.py) | the same |
| `$18C0-$18C7` | the Super System Card id registers (answered by the card) | -- |

IRQ2 = (enable mask & active bits) != 0. Active bits: 0x04 ADPCM half, 0x08 ADPCM end, 0x10
subchannel, 0x20 status/message-in (REQ in those phases), 0x40 data-in (REQ in data in). The
status/message and data-in bits are derived from the bus levels, the ADPCM bits are the unit's half
and end flags (adpcm.py), the subchannel bit is U9.
"""

from __future__ import annotations

from pcengine_python.sockets import BoardPins, IrqLine, ResetKind

from pcenginecd_python.adpcm import Adpcm, AdpcmSource
from pcenginecd_python.arcade import REGISTER_PAGE as ARCADE_REGISTER_PAGE
from pcenginecd_python.arcade import ArcadeCard
from pcenginecd_python.cdda import CddaPlayer
from pcenginecd_python.disc import Disc
from pcenginecd_python.scsi import ScsiBus

CD_RAM_BYTES = 64 * 1024
BRAM_BYTES = 2 * 1024

# The pages of the 256-byte-granular decode (docs/sockets.md of the base board).
CD_RAM_PAGES = (0x1000, 0x10FF)  # banks $80-$87, physical $100000-$10FFFF [hw: pcetech 8]
BRAM_PAGES = (0x1EE0, 0x1EE7)  # $1EE000-$1EE7FF, the first 2 KiB of bank $F7 [hw: pcetech 8]
REGISTER_PAGE = 0x1FF8  # $1800-$18FF

IRQ_ADPCM_HALF = 0x04
IRQ_ADPCM_END = 0x08
IRQ_SUBCODE = 0x10
IRQ_STATUS_MESSAGE = 0x20
IRQ_DATA_IN = 0x40

# [emu: Mesen2 `PceCdRom.cpp`] the BRAM the BIOS leaves after "initialise": a header, rest zero.
# The real RAM is battery-backed and its content at an owner's first power-up is unknown (U36);
# unformatted RAM makes some games (Far East of Eden) misbehave [emu: Mesen2 comment].
BRAM_FORMATTED = bytes([0x48, 0x55, 0x42, 0x4D, 0x00, 0xA0, 0x10, 0x80])


class CdUnit:
    """CD RAM, backup RAM, the registers, the SCSI bus and the CD-DA player."""

    # [emu: Mesen2 `PceCdRom.cpp`, from its test ROMs] a second write to $1805 within this many
    # master clocks of the first is ignored (tier 5)
    CHANNEL_LATCH_GUARD = 700
    # [emu: Mesen2 `PceAdpcm.cpp`, "verificator" test ROM: values 18 to 22 CPU-ticks pass, higher
    # or lower fail; one tick = 3 master clocks] master clocks from REQ to the DMA taking the byte
    DMA_BYTE_CLOCKS = 20 * 3

    grounds_cd = False  # the unit is not a card: the System Card grounds /CD
    present = True  # K7 low: the I/O port reports "CD unit attached" (C6 polarity)

    def __init__(
        self,
        disc: Disc | None = None,
        *,
        bram: bytes | None = None,
        card=None,
        arcade: ArcadeCard | None = None,
    ) -> None:
        self.cdda = CddaPlayer()
        self.cdda.disc = disc
        self.bus = ScsiBus(disc, self.cdda, self._bus_irq)
        self.cdda.on_good_status = self.bus.good_status
        self.adpcm = Adpcm(self._adpcm_irq)
        self.adpcm_source = AdpcmSource(self)
        self.ram = bytearray(CD_RAM_BYTES)
        self.bram = bytearray(BRAM_BYTES)
        header = BRAM_FORMATTED if bram is None else bram
        self.bram[: len(header)] = header
        self.bram_locked = True  # [hw: pcetech 8] locked at power-up
        self.arcade = (
            arcade  # the Arcade Card, if fitted: banks $40-$43 and $1A00-$1AFF (arcade.py)
        )
        self.card = card  # for the $18C0-$18C7 id registers (a Super System Card answers them)
        self.irq2: IrqLine | None = None
        self.enable = 0
        self.active = 0
        self.reset_register = 0
        self.right_channel = False
        self.sample_latch = 0
        self._latch_guard_until = 0
        self._next_event: int | None = None
        self._dma_at: int | None = None
        self.mclk = 0

    @property
    def disc(self) -> Disc | None:
        return self.bus.disc

    def insert(self, disc: Disc | None) -> None:
        self.bus.disc = disc
        self.cdda.disc = disc

    # -- the PortDevice socket -------------------------------------------------------------------

    def bind(self, pins: BoardPins) -> None:
        self.irq2 = pins.irq2

    def claims(self) -> list[tuple[int, int]]:
        pages = [CD_RAM_PAGES, BRAM_PAGES, (REGISTER_PAGE, REGISTER_PAGE)]
        if self.arcade is not None:
            pages += self.arcade.claims()
        return pages

    def reset(self, kind: ResetKind) -> None:
        if self.arcade is not None:
            self.arcade.reset(kind)
        if kind is ResetKind.POWER_ON:
            self.bram_locked = True
            self.bus.reset()
            self.adpcm.power_on()
            self.enable = self.active = self.reset_register = 0
            self.right_channel = False
            self.sample_latch = 0
            self._update_irq()

    def catch_up(self, mclk: int) -> None:
        if self._next_event is None or mclk >= self._next_event:
            self._run(mclk)
        self.mclk = mclk

    def _run(self, mclk: int) -> None:
        """Run the drive, the ADPCM unit and the ADPCM DMA, event by event, up to `mclk`."""
        bus, adpcm = self.bus, self.adpcm
        while True:
            at = self._soonest()
            if at is None or at > mclk:
                break
            bus.run_to(at)
            adpcm.run(at)
            if self._dma_at == at:
                self._dma_at = None
                self._dma_step(at)
            self._dma_arm()
        bus.run_to(mclk)
        adpcm.run(mclk)
        self._dma_arm()
        self._next_event = self._soonest()

    def _soonest(self) -> int | None:
        times = [
            t
            for t in (self.bus.next_event(), self._dma_at, self.adpcm.next_event())
            if t is not None
        ]
        return min(times) if times else None

    # -- CD to ADPCM DMA (AD_TRANS): `$180B` bits 1/0 [hw: pcetech 8, "no DMA to RAM ... only one
    # sector at a time into ADPCM RAM"; the BIOS sets bit 1, polls `$180C` bit 2 and `$1803` bit 5].
    # One byte at a time: the drive's data is taken while REQ is up in data in, then ACK pulses.

    def _dma_arm(self) -> None:
        bus = self.bus
        if (
            self.adpcm.dma & 0x03
            and self._dma_at is None
            and bus.req
            and bus.io
            and not bus.cd
            and not bus.ack
        ):
            self._dma_at = bus.now + self.DMA_BYTE_CLOCKS

    def _dma_step(self, at: int) -> None:
        bus, adpcm = self.bus, self.adpcm
        if not (adpcm.dma & 0x03 and bus.req and bus.io and not bus.cd and not bus.ack):
            return
        if not adpcm.dma_write(bus.read_data(), at):
            self._dma_at = at + 3  # the RAM is still taking the last byte: ask again
            return
        bus.pulse_ack()
        if not bus.out:
            adpcm.dma &= ~0x01  # the sector is through (bit 1, the request, stays until cleared)

    # -- IRQ2 ------------------------------------------------------------------------------------

    def _bus_irq(self, mask: int, level: bool) -> None:
        if level:
            if not self.reset_register & 0x02:  # no IRQ while the drive is held in reset
                self.active |= mask
        else:
            self.active &= ~mask
        self._update_irq()

    def _adpcm_irq(self, mask: int, level: bool) -> None:
        """The ADPCM half and end flags: IRQ2 sources `$04` and `$08` (the drive's reset does not
        hold them off)."""
        if level:
            self.active |= mask
        else:
            self.active &= ~mask
        self._update_irq()

    def _update_irq(self) -> None:
        if self.irq2 is not None:
            self.irq2.set("cd", bool(self.enable & self.active))

    # -- the bus ---------------------------------------------------------------------------------

    def read(self, address: int, mclk: int) -> int:
        page = address >> 8
        if self.arcade is not None and (page < 0x1000 or page == ARCADE_REGISTER_PAGE):
            return self.arcade.read(address, mclk)  # no clock: skip the catch-up
        self.catch_up(mclk)
        if CD_RAM_PAGES[0] <= page <= CD_RAM_PAGES[1]:
            return self.ram[address & 0xFFFF]
        if BRAM_PAGES[0] <= page <= BRAM_PAGES[1]:
            return 0xFF if self.bram_locked else self.bram[address & 0x7FF]
        return self._read_register(address & 0xFF, mclk)

    def write(self, address: int, value: int, mclk: int) -> None:
        page = address >> 8
        if self.arcade is not None and (page < 0x1000 or page == ARCADE_REGISTER_PAGE):
            self.arcade.write(address, value, mclk)
            return
        self.catch_up(mclk)
        if CD_RAM_PAGES[0] <= page <= CD_RAM_PAGES[1]:
            self.ram[address & 0xFFFF] = value
        elif BRAM_PAGES[0] <= page <= BRAM_PAGES[1]:
            if not self.bram_locked:
                self.bram[address & 0x7FF] = value
        else:
            self._write_register(address & 0xFF, value, mclk)
        self._dma_arm()
        self._next_event = self._soonest()

    def _read_register(self, reg: int, mclk: int) -> int:
        bus = self.bus
        if reg == 0x00:
            return bus.status_bits
        if reg == 0x01:
            return bus.read_data()
        if reg == 0x02:
            return self.enable | (0x80 if bus.ack else 0)
        if reg == 0x03:
            self.bram_locked = True  # [hw: pcetech 8] a read of $1803 locks BRAM
            return self.active | (0 if self.right_channel else 0x02)
        if reg == 0x04:
            return self.reset_register
        if reg == 0x05:
            return self.sample_latch & 0xFF
        if reg == 0x06:
            return (self.sample_latch >> 8) & 0xFF
        if reg == 0x07:
            return 0  # the subchannel byte (U9)
        if reg == 0x08:
            value = bus.read_data()
            if bus.req and bus.io and not bus.cd:
                bus.pulse_ack()
                self._dma_arm()
                self._next_event = self._soonest()
            return value
        if 0x09 <= reg <= 0x0E:
            value = self.adpcm.read(reg, mclk)
            self._next_event = self._soonest()
            return value
        if reg == 0x0F:
            return self.cdda.fade_register
        if 0xC0 <= reg <= 0xC7 and self.card is not None and hasattr(self.card, "register_read"):
            return self.card.register_read(reg & 7)
        return 0xFF

    def _write_register(self, reg: int, value: int, mclk: int) -> None:
        bus = self.bus
        if reg == 0x00:
            bus.select()
        elif reg == 0x01:
            bus.write_data(value)
        elif reg == 0x02:
            bus.set_ack(bool(value & 0x80))
            self.enable = value & 0x7F
            self._update_irq()
        elif reg == 0x04:
            self.reset_register = value & 0x0F
            reset = bool(value & 0x02)
            bus.set_reset(reset)
            if reset:
                self.enable &= 0x8F  # the drive's three IRQ enables drop
                self.active &= 0x8F
                self._update_irq()
        elif reg == 0x05:
            if mclk >= self._latch_guard_until:
                self.right_channel = not self.right_channel
                left, right = self.cdda.latest_sample()
                self.sample_latch = (right if self.right_channel else left) & 0xFFFF
                self._latch_guard_until = mclk + self.CHANNEL_LATCH_GUARD
        elif reg == 0x07:
            self.bram_locked = not value & 0x80
        elif 0x08 <= reg <= 0x0E:
            if reg == 0x0B and not bus.out:
                value &= ~0x01  # bit 0 cannot be set when no data block is waiting [emu: Mesen2]
            self.adpcm.write(reg, value, mclk)
        elif reg == 0x0F:
            self.cdda.write_fade(value, mclk)
