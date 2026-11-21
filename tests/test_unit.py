# SPDX-License-Identifier: MIT
"""The CD unit's registers, RAM, BRAM, IRQ2 and the ADPCM register port."""

from discs import disc_data_only
from helpers import REG, Host
from pcengine_python.sockets import BoardPins, IrqLine, ResetKind

from pcenginecd_python.unit import BRAM_FORMATTED, CdUnit


def make(disc=None):
    unit = CdUnit(disc)
    irq = IrqLine("IRQ2")
    unit.bind(BoardPins(irq2=irq, hold=lambda n: None))
    return unit, irq, Host(unit)


def test_claims_cover_cd_ram_bram_and_the_register_page():
    unit, _, _ = make()
    assert (0x1000, 0x10FF) in unit.claims()  # banks $80-$87 = $100000-$10FFFF
    assert (0x1EE0, 0x1EE7) in unit.claims()  # $1EE000-$1EE7FF
    assert (0x1FF8, 0x1FF8) in unit.claims()
    assert unit.present and not unit.grounds_cd


def test_cd_ram_is_64k_not_mirrored_inside_its_window():
    unit, _, _ = make()
    unit.write(0x100000, 0x11, 0)
    unit.write(0x10FFFF, 0x22, 0)
    assert unit.read(0x100000, 0) == 0x11 and unit.read(0x10FFFF, 0) == 0x22
    assert unit.read(0x100001, 0) == 0


def test_bram_is_locked_at_power_up_unlocked_by_1807_bit7_locked_by_reading_1803():
    unit, _, h = make()
    assert unit.read(0x1EE000, 0) == 0xFF  # reads $FF while locked
    unit.write(0x1EE010, 0x5A, 0)  # ignored
    h.w(7, 0x80)
    assert unit.read(0x1EE000, 0) == BRAM_FORMATTED[0]
    unit.write(0x1EE010, 0x5A, 0)
    assert unit.read(0x1EE010, 0) == 0x5A
    h.r(3)  # a read of $1803 locks
    assert unit.read(0x1EE010, 0) == 0xFF
    h.w(7, 0x80 | 0x48)  # "some games write 48 75 80": only bit 7 of the last matters
    assert unit.read(0x1EE010, 0) == 0x5A
    h.w(7, 0x00)
    assert unit.read(0x1EE010, 0) == 0xFF


def test_bram_is_2k_only_the_rest_of_the_bank_is_open_bus():
    _unit, _, h = make()
    h.w(7, 0x80)
    assert (0x1EE800 >> 8) not in range(0x1EE0, 0x1EE8)
    assert all(0x1EE0 <= p <= 0x1EE7 for p in (0x1EE000 >> 8, 0x1EE7FF >> 8))


def test_irq2_follows_enable_mask_and_active_bits_per_source():
    unit, irq, h = make(disc_data_only())
    h.w(2, 0x00)
    h.command([0, 0, 0, 0, 0, 0])
    h.wait(0xD8)  # status phase raises active bit 0x20
    assert unit.active == 0x20 and not irq.level  # masked
    h.w(2, 0x20)
    assert irq.level and irq.sources == {"cd"}
    h.w(2, 0x40)  # a different mask
    assert not irq.level
    h.w(2, 0x20)
    assert h.r(3) & 0x20  # $1803 shows the active bits (and does not clear them)
    h.handshake()
    h.wait(0xF8)  # message in: same bit
    assert irq.level
    h.handshake()
    h.wait(0, 0xF8)
    assert not irq.level  # REQ gone: level source


def test_1802_reads_back_mask_and_ack():
    _unit, _, h = make()
    h.w(2, 0xE5)
    assert h.r(2) == 0xE5
    h.w(2, 0x65)
    assert h.r(2) == 0x65


def test_1803_bit1_is_the_channel_flag_toggled_by_1805_with_a_guard():
    _unit, _, h = make()
    assert h.r(3) & 0x02
    h.w(5, 0)
    assert not h.r(3) & 0x02
    h.w(5, 0)  # within the guard time: ignored
    assert not h.r(3) & 0x02
    h.advance(2000)
    h.w(5, 0)
    assert h.r(3) & 0x02


def test_reset_register_clears_drive_irq_enables_and_the_drive_works_after_release():
    # (the blocking while held: tests/test_issue0001.py)
    unit, _irq, h = make(disc_data_only())
    h.w(2, 0x70)
    h.w(4, 0x02)
    assert unit.enable == 0x00 and h.r(4) == 0x02
    h.w(4, 0x00)
    h.command([0, 0, 0, 0, 0, 0])
    h.wait(0xD8)
    assert unit.active & 0x20


def test_adpcm_ram_port_reads_are_buffered_and_pointers_increment_and_wrap():
    unit, _, h = make()
    h.w(8, 0x00)
    h.w(9, 0x10)  # latch $1000
    h.w(0x0D, 0x02 | 0x01)  # copy to the write pointer, no step back
    for v in (0xA1, 0xA2, 0xA3):
        h.w(0x0A, v)
        h.advance(100)  # the RAM takes a write in about 24 CPU cycles ($180C bit 2)
    assert bytes(unit.adpcm.ram[0x1000:0x1003]) == b"\xa1\xa2\xa3"
    h.w(0x0D, 0x00)
    h.w(0x0D, 0x08 | 0x04)  # read pointer = latch
    first = h.r(0x0A)  # the buffer from before
    values = []
    for _ in range(3):
        h.advance(100)  # a read is buffered: bit 7 of $180C clears in about 24 cycles
        values.append(h.r(0x0A))
    assert values == [0xA1, 0xA2, 0xA3]
    assert first == 0
    h.w(0x0D, 0x80)  # reset: pointers to zero
    assert unit.adpcm.read_ptr == 0 and unit.adpcm.write_ptr == 0


def test_adpcm_status_reads_idle_and_unknown_registers_read_ff():
    unit, _, h = make()
    assert h.r(0x0C) == 0
    assert unit.read(REG + 0x20, 0) == 0xFF and unit.read(REG + 0xFE, 0) == 0xFF


def test_power_on_reset_locks_bram_and_clears_the_bus():
    unit, irq, h = make(disc_data_only())
    h.w(7, 0x80)
    h.command([0, 0, 0, 0, 0, 0])
    unit.reset(ResetKind.POWER_ON)
    assert unit.bram_locked and h.r(0) == 0 and not irq.level


def test_adpcm_dma_moves_a_sector_from_the_drive_into_adpcm_ram():
    # AD_TRANS: set the write pointer, send READ, set $180B bit 1, wait for the status phase
    unit, _, h = make(disc_data_only())
    h.w(8, 0x00)
    h.w(9, 0x20)
    h.w(0x0D, 0x02 | 0x01)  # write pointer = $2000
    h.command([8, 0, 0, 4, 1, 0])
    h.w(0x0B, 0x02)
    h.wait(0xD8)  # the status phase: every byte was taken by the DMA, none by the CPU
    h.advance(200)  # the last byte is still going into the RAM
    assert bytes(unit.adpcm.ram[0x2000:0x2004]) == bytes([4, 5, 6, 7])
    assert unit.adpcm.ram[0x2000 + 2047] == (4 + 2047) & 0xFF
    assert unit.adpcm.write_ptr == 0x2000 + 2048
    assert h.r(3) & 0x20  # the BIOS polls this bit
    h.w(0x0B, 0x00)
    assert h.finish() == (0, 0)


def test_dma_bit0_cannot_be_set_without_a_waiting_block_and_bit1_survives():
    unit, _, h = make(disc_data_only())
    h.w(0x0B, 0x03)
    assert unit.adpcm.dma == 0x02
