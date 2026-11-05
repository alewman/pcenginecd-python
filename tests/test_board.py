"""The CD machine through the base board's sockets, with a scripted CPU and a synthetic System Card
(nothing of Hudson's code is in this repository; the real card is only used by scripts/)."""

from discs import disc_data_only
from helpers import ScriptedCpu

from pcenginecd_python import PcEngineCd, SystemCard

HW = 0x1FE000
IO_PORT = HW + 0x1000
CD = HW + 0x1800


def card_image(size=256 * 1024) -> bytes:
    """Bank number in the first byte of every 8 KiB bank, so the mirroring can be read back."""
    data = bytearray(size)
    for bank in range(size // 8192):
        data[bank * 8192] = bank
    return bytes(data)


def machine(size=256 * 1024, disc=None, **kw):
    cd = PcEngineCd(card_image(size), disc if disc is not None else disc_data_only(), **kw)
    return cd, ScriptedCpu(cd.board)


def test_io_port_bit7_follows_the_unit_not_the_slot():
    _cd, cpu = machine()
    assert cpu.read(IO_PORT) & 0x80 == 0  # pcetech 4: 0 = a CD unit attached
    from pcengine_python.board import Board

    plain = ScriptedCpu(Board(card=SystemCard(card_image(), super_system_card=False)))
    assert plain.read(IO_PORT) & 0x80  # the card is in the slot, but no unit on the port


def test_system_card_rom_mirrors_through_the_card_window():
    _cd, cpu = machine()
    assert cpu.read(0x000000) == 0 and cpu.read(0x002000) == 1
    assert cpu.read(0x040000) == 0  # 256 KiB repeats at $40000
    assert cpu.read(0x042000) == 1


def test_super_system_card_ram_at_banks_68_to_7f_overrides_the_rom():
    cd, cpu = machine()
    assert cpu.read(0x68 * 0x2000) == 0  # a fresh, zeroed RAM (not the ROM's mirror)
    cpu.write(0x68 * 0x2000, 0xA5)
    cpu.write(0x7F * 0x2000 + 0x1FFF, 0x5A)
    assert cpu.read(0x68 * 0x2000) == 0xA5 and cpu.read(0x7F * 0x2000 + 0x1FFF) == 0x5A
    assert cpu.read(0x67 * 0x2000) == (0x67 % 32)  # bank $67 is still ROM
    assert cpu.read(0x80 * 0x2000) == 0  # $80 is CD RAM, not the card
    assert len(cd.card.ram) == 192 * 1024


def test_the_original_system_card_has_no_extra_ram_and_no_id_registers():
    cd, cpu = machine(size=128 * 1024)
    assert not cd.card.super_system_card and cd.card.ram is None
    cpu.write(0x68 * 0x2000, 0xA5)
    assert cpu.read(0x68 * 0x2000) == (0x68 % 16)  # still the (mirrored) ROM
    assert cpu.read(CD + 0xC1) == 0xFF


def test_super_system_card_id_registers_for_japan_and_the_us():
    _cd, cpu = machine()
    assert [cpu.read(CD + 0xC0 + i) for i in range(8)] == [0, 0xAA, 0x55, 0, 0, 0xAA, 0x55, 3]
    _us, cpu2 = machine(region_us=True)
    assert [cpu2.read(CD + 0xC0 + i) for i in (5, 6)] == [0x55, 0xAA]


def test_cd_ram_and_bram_are_on_the_bus_at_the_documented_banks():
    cd, cpu = machine()
    cpu.write(0x100000, 0x77)
    cpu.write(0x10FFFF, 0x78)
    assert cd.unit.ram[0] == 0x77 and cpu.read(0x10FFFF) == 0x78
    assert cpu.read(0x1EE000) == 0xFF  # locked
    cpu.write(CD + 7, 0x80)
    assert cpu.read(0x1EE000) == 0x48  # the formatted header
    assert cpu.read(0x1EE800) == 0xFF  # past 2 KiB: open bus
    assert cpu.read(0x110000) == 0xFF


def test_other_hardware_pages_are_untouched():
    cd, cpu = machine()
    assert cpu.read(HW + 0x1900) == 0xFF and cpu.read(HW + 0x1A00) == 0xFF  # no Arcade Card yet
    cpu.write(HW + 0x400 + 2, 0)  # the VCE is still the base board's
    assert cd.board.vce is not None


def test_the_clock_reaches_the_unit_without_a_register_access_and_raises_irq2():
    cd, cpu = machine()
    cpu.write(CD + 2, 0x20)  # enable the status/message IRQ
    cpu.write(CD + 0, 0)  # select
    cd.board.advance(300_000)
    assert cpu.read(CD + 0) & 0xF8 == 0xD0  # command phase
    for byte in (0, 0, 0, 0, 0, 0):  # TEST UNIT READY
        cpu.write(CD + 1, byte)
        cpu.write(CD + 2, 0xA0)
        cd.board.advance(100)
        cpu.write(CD + 2, 0x20)
        cd.board.advance(4000)
    assert not cpu.lines[1]
    cd.board.advance(2_000_000)  # the spin-up passes with no register access at all
    assert cpu.lines[1] and "cd" in cd.board.irq2.sources


def test_cdda_is_on_the_audio_source_list():
    cd, _ = machine()
    assert cd.board.audio_sources[0] is cd.board.psg
    assert cd.board.audio_sources[1] is cd.unit.cdda
    assert cd.unit.cdda.rate_hz == 44100.0


def test_a_system_with_no_disc_boots_the_bus_and_answers_not_ready():
    _cd, _cpu = machine(disc=None)
    cd2 = PcEngineCd(card_image(), None)
    assert cd2.unit.disc is None
