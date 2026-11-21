# SPDX-License-Identifier: MIT
"""The Arcade Card: ports, auto-increment, the offset triggers, the shift unit, ID and mirrors.

The semantics are those the three emulator sources agree on (tier 5, arcade.py); the tests state
them, they do not judge the card against hardware. Registers are driven by physical address as the
board's page table hands them to the unit: `$1A00 + n` is `0x1FF800 + 0x200 + n`.
"""

from helpers import ScriptedCpu
from test_board import card_image

from pcenginecd_python import ArcadeCard, PcEngineCd
from pcenginecd_python.arcade import ARCADE_RAM_BYTES
from pcenginecd_python.unit import CdUnit

AC = 0x1FFA00


def port(n: int) -> int:
    return AC + 0x10 * n


def setup(card=None):
    card = card or ArcadeCard()
    return card, CdUnit(arcade=card)


def set_base(card, n, base):
    for i in range(3):
        card.write(port(n) + 2 + i, (base >> (8 * i)) & 0xFF)


def set_offset(card, n, offset):
    card.write(port(n) + 5, offset & 0xFF)
    card.write(port(n) + 6, offset >> 8)


def set_increment(card, n, inc):
    card.write(port(n) + 7, inc & 0xFF)
    card.write(port(n) + 8, inc >> 8)


def test_ram_is_two_mebibytes_and_the_unit_claims_banks_40_43_and_the_1a_page():
    card, unit = setup()
    assert len(card.ram) == ARCADE_RAM_BYTES == 2 * 1024 * 1024
    assert (0x0800, 0x087F) in unit.claims() and (0x1FFA, 0x1FFA) in unit.claims()
    assert (0x0800, 0x087F) not in CdUnit().claims()  # nothing claimed without a card


def test_id_and_version():
    card, _ = setup()
    assert card.read(AC + 0xFF) == 0x51 and card.read(AC + 0xFE) == 0x10
    assert card.read(AC + 0xFC) == 0 and card.read(AC + 0xFD) == 0


def test_plain_port_write_then_read_at_the_base_with_no_increment():
    card, _ = setup()
    set_base(card, 0, 0x01234)
    card.write(port(0), 0xAB)
    assert card.ram[0x1234] == 0xAB
    assert card.read(port(0)) == 0xAB and card.read(port(0) + 1) == 0xAB  # $0 and $1 both data
    assert card.read(port(0) + 2) == 0x34 and card.read(port(0) + 3) == 0x12
    assert card.read(port(0) + 4) == 0x00


def test_the_four_ports_are_independent():
    card, _ = setup()
    for n in range(4):
        set_base(card, n, 0x100 * (n + 1))
        card.write(port(n), n + 1)
    assert [card.ram[0x100 * (n + 1)] for n in range(4)] == [1, 2, 3, 4]


def test_auto_increment_of_the_offset_with_add_offset():
    card, _ = setup()
    set_base(card, 1, 0x100)
    set_increment(card, 1, 2)
    card.write(port(1) + 9, 0x03)  # auto-increment + add offset to the base for the access
    for i in range(3):
        card.write(port(1), 0x10 + i)
    assert (card.ram[0x100], card.ram[0x102], card.ram[0x104]) == (0x10, 0x11, 0x12)
    assert card.read(port(1) + 5) == 6 and card.read(port(1) + 2) == 0x00  # offset moved, base not


def test_auto_increment_without_add_offset_moves_only_the_offset_register():
    card, _ = setup()
    set_base(card, 0, 0x40)
    set_increment(card, 0, 1)
    card.write(port(0) + 9, 0x01)
    card.write(port(0), 1)
    card.write(port(0), 2)
    assert card.ram[0x40] == 2 and card.ram[0x41] == 0  # the address ignores the offset
    assert card.read(port(0) + 5) == 2


def test_auto_increment_of_the_base_when_bit_4_is_set():
    card, _ = setup()
    set_base(card, 0, 0x200)
    set_increment(card, 0, 0x10)
    card.write(port(0) + 9, 0x11)
    card.write(port(0), 7)
    card.write(port(0), 8)
    assert card.ram[0x200] == 7 and card.ram[0x210] == 8
    assert card.read(port(0) + 2) == 0x20 and card.read(port(0) + 3) == 0x02
    assert card.read(port(0) + 5) == 0  # the offset stayed


def test_increment_wraps_the_offset_at_16_bits_and_the_base_at_24_bits():
    card, _ = setup()
    set_offset(card, 0, 0xFFFF)
    set_increment(card, 0, 1)
    card.write(port(0) + 9, 0x01)
    card.read(port(0))
    assert card.read(port(0) + 5) == 0 and card.read(port(0) + 6) == 0
    set_base(card, 1, 0xFFFFFF)
    set_increment(card, 1, 2)
    card.write(port(1) + 9, 0x11)
    card.read(port(1))
    assert [card.read(port(1) + i) for i in (2, 3, 4)] == [1, 0, 0]
    # the carry crosses bit 16 into the top byte (a 16-bit wrap would leave $12 there)
    set_base(card, 2, 0x12FFFF)
    set_increment(card, 2, 2)
    card.write(port(2) + 9, 0x11)
    card.read(port(2))
    assert [card.read(port(2) + i) for i in (2, 3, 4)] == [1, 0, 0x13]


def test_effective_address_is_21_bits():
    card, _ = setup()
    set_base(card, 0, 0x200005)  # bit 21 is not decoded: wraps to 5
    card.write(port(0), 0x77)
    assert card.ram[5] == 0x77
    set_base(card, 0, 0xFFFFFF)
    card.write(port(0), 0x78)
    assert card.ram[0x1FFFFF] == 0x78


def test_add_offset_with_a_signed_offset_reaches_below_the_base():
    card, _ = setup()
    set_base(card, 0, 0x100)
    set_offset(card, 0, 0xFFF0)  # -16 as a 16-bit value
    card.write(port(0) + 9, 0x0A)  # add offset, signed
    card.write(port(0), 0x5A)
    assert card.ram[0xF0] == 0x5A
    card.write(port(0) + 9, 0x02)  # unsigned: base + 0xFFF0
    card.write(port(0), 0x5B)
    assert card.ram[0x100 + 0xFFF0] == 0x5B


def test_offset_trigger_modes_add_the_offset_into_the_base():
    card, _ = setup()
    # trigger on the low-byte write (bits 6-5 = 1)
    set_base(card, 0, 0x1000)
    card.write(port(0) + 9, 0x20)
    card.write(port(0) + 6, 0x01)  # high byte: no add
    assert card.read(port(0) + 3) == 0x10
    card.write(port(0) + 5, 0x05)  # low byte: base += 0x0105
    assert (card.read(port(0) + 2), card.read(port(0) + 3)) == (0x05, 0x11)
    # trigger on the high-byte write (2)
    set_base(card, 1, 0)
    card.write(port(1) + 9, 0x40)
    card.write(port(1) + 5, 0x34)
    assert card.read(port(1) + 2) == 0
    card.write(port(1) + 6, 0x12)  # base += 0x1234
    assert (card.read(port(1) + 2), card.read(port(1) + 3)) == (0x34, 0x12)
    # trigger on a write to register $A (3), whatever the value, repeatedly
    set_base(card, 2, 0x10)
    set_offset(card, 2, 3)
    card.write(port(2) + 9, 0x60)
    card.write(port(2) + 0x0A, 0)
    card.write(port(2) + 0x0A, 0xFF)
    assert card.read(port(2) + 2) == 0x16
    assert card.read(port(2) + 0x0A) == 0  # reads 0
    # trigger 0 never adds
    set_base(card, 3, 0x10)
    card.write(port(3) + 9, 0x00)
    set_offset(card, 3, 3)
    card.write(port(3) + 0x0A, 0)
    assert card.read(port(3) + 2) == 0x10


def test_signed_trigger_subtracts_through_the_ff0000_add():
    card, _ = setup()
    set_base(card, 0, 0x1000)
    card.write(port(0) + 9, 0x68)  # trigger 3, signed offset
    set_offset(card, 0, 0xFFFE)  # -2
    card.write(port(0) + 0x0A, 0)
    assert (card.read(port(0) + 2), card.read(port(0) + 3), card.read(port(0) + 4)) == (
        0xFE,
        0x0F,
        0,
    )


def test_control_register_keeps_seven_bits():
    card, _ = setup()
    card.write(port(0) + 9, 0xFF)
    assert card.read(port(0) + 9) == 0x7F


def test_port_groups_mirror_at_1a40_and_unused_port_registers_read_ff():
    card, _ = setup()
    set_base(card, 2, 0x12345)
    assert card.read(AC + 0x40 + 0x20 + 2) == 0x45  # port 2 again, at $1A60
    card.write(AC + 0x40 + 0x20 + 3, 0x99)
    assert card.read(port(2) + 3) == 0x99
    assert card.read(port(0) + 0x0B) == 0xFF and card.read(AC + 0x90) == 0xFF
    assert card.read(AC + 0xE6) == 0xFF and card.read(AC + 0xFB) == 0xFF


def test_banks_40_to_43_are_port_0_to_3_data_at_any_offset():
    card, unit = setup()
    set_base(card, 2, 0x300)
    set_increment(card, 2, 1)
    card.write(port(2) + 9, 0x11)
    unit.write(0x42 * 0x2000 + 0x1234, 0xC1, 0)  # bank $42 = port 2, the in-bank offset ignored
    unit.write(0x42 * 0x2000, 0xC2, 0)
    assert card.ram[0x300] == 0xC1 and card.ram[0x301] == 0xC2
    set_base(card, 2, 0x300)
    assert unit.read(0x42 * 0x2000 + 0x1FFF, 0) == 0xC1


def test_shift_unit_value_register_and_shifts():
    card, _ = setup()
    for i, b in enumerate((0x78, 0x56, 0x34, 0x12)):
        card.write(AC + 0xE0 + i, b)
    assert [card.read(AC + 0xE0 + i) for i in range(4)] == [0x78, 0x56, 0x34, 0x12]
    card.write(AC + 0xE4, 0x04)  # left by 4
    assert [card.read(AC + 0xE0 + i) for i in range(4)] == [0x80, 0x67, 0x45, 0x23]
    assert card.read(AC + 0xE4) == 4
    card.write(AC + 0xE4, 0x0C)  # bit 3: right by 16 - 12 = 4
    assert [card.read(AC + 0xE0 + i) for i in range(4)] == [0x78, 0x56, 0x34, 0x02]
    card.write(AC + 0xE4, 0x08)  # right by 8
    assert [card.read(AC + 0xE0 + i) for i in range(4)] == [0x56, 0x34, 0x02, 0x00]
    card.write(AC + 0xE4, 0x0F)  # right by 1
    assert card.read(AC + 0xE0) == 0x2B
    card.write(AC + 0xE4, 0x00)  # no shift
    assert card.read(AC + 0xE0) == 0x2B


def test_left_shift_drops_bits_off_the_top_of_32():
    card, _ = setup()
    card.write(AC + 0xE3, 0x81)
    card.write(AC + 0xE4, 0x01)
    assert [card.read(AC + 0xE0 + i) for i in range(4)] == [0, 0, 0, 0x02]


def test_rotate_unit_wraps_bits():
    card, _ = setup()
    card.write(AC + 0xE3, 0x81)
    card.write(AC + 0xE0, 0x01)
    card.write(AC + 0xE5, 0x01)  # rotate left by 1
    assert [card.read(AC + 0xE0 + i) for i in range(4)] == [0x03, 0, 0, 0x02]
    assert card.read(AC + 0xE5) == 1
    card.write(AC + 0xE5, 0x0F)  # rotate right by 1: back
    assert [card.read(AC + 0xE0 + i) for i in range(4)] == [0x01, 0, 0, 0x81]


def test_switches_for_the_emulator_only_choices():
    class Mesen(ArcadeCard):
        UNMAPPED_READ = 0x00
        SHIFT_READ_MASK = 0xFF
        TRIGGER_REG_READ = 0xFF

    card = Mesen()
    card.write(AC + 0xE4, 0x13)
    assert card.read(AC + 0xE4) == 0x13 and ArcadeCard().read(AC + 0xE4) == 0
    assert card.read(AC + 0x90) == 0 and card.read(port(0) + 0x0A) == 0xFF


def test_power_on_clears_ram_and_registers_a_warm_reset_keeps_registers():
    from pcengine_python.sockets import ResetKind

    card, _ = setup()
    card.write(port(0), 9)
    set_base(card, 0, 0x55)
    card.write(AC + 0xE0, 0x12)
    card.reset(ResetKind.BUTTON)
    assert card.ram[0] == 9 and card.read(port(0) + 2) == 0x55 and card.read(AC + 0xE0) == 0x12
    card.reset(ResetKind.POWER_ON)
    assert card.ram[0] == 0 and card.read(port(0) + 2) == 0 and card.read(AC + 0xE0) == 0

    class Clears(ArcadeCard):
        RESET_CLEARS_REGISTERS = True

    other = Clears()
    set_base(other, 0, 0x55)
    other.reset(ResetKind.BUTTON)
    assert other.read(port(0) + 2) == 0


def test_the_board_wires_the_card_through_the_unit_and_without_it_nothing_answers():
    cd = PcEngineCd(card_image(), arcade_card=True)
    cpu = ScriptedCpu(cd.board)
    assert cpu.read(0x1FFAFF) == 0x51
    cpu.write(0x1FFA00 + 2, 0x10)  # port 0 base = 0x10
    cpu.write(0x40 * 0x2000, 0x6C)  # bank $40
    assert cd.arcade.ram[0x10] == 0x6C
    assert cpu.read(0x1FFA00) == 0x6C
    assert cpu.read(0x1FF800) in range(256)  # the CD unit's own page still answers
    bare = PcEngineCd(card_image())
    cpu2 = ScriptedCpu(bare.board)
    assert bare.arcade is None
    assert cpu2.read(0x1FFAFF) != 0x51
    assert cpu2.read(0x40 * 0x2000) == 0x40 % 32  # the System Card's ROM mirror, as before
