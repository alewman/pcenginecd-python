"""The drive's bus and command set through the registers, as the BIOS drives them."""

from discs import disc_audio_then_data, disc_data_only
from helpers import Host

from pcenginecd_python.disc import to_bcd
from pcenginecd_python.scsi import MASTER_HZ, ScsiBus
from pcenginecd_python.unit import CdUnit


def host(disc=None, enable=0):
    unit = CdUnit(disc)
    h = Host(unit)
    h.w(2, enable)
    return h


def test_bus_is_free_until_selected_then_enters_the_command_phase_after_a_delay():
    h = host(disc_data_only())
    assert h.r(0) == 0x00
    h.select()
    assert h.r(0) & 0xF8 == 0  # not yet: the drive takes time to answer the selection
    waited = h.wait(0xD0)
    assert waited >= ScsiBus.SEL_TO_COMMAND_PHASE - 100


def test_test_unit_ready_takes_the_spin_up_time_then_status_good_message_zero():
    h = host(disc_data_only())
    h.command([0, 0, 0, 0, 0, 0])
    began = h.t
    status, message = h.finish()
    assert (status, message) == (0, 0)
    assert h.t - began >= ScsiBus.TEST_UNIT_READY - 20_000


def test_no_disc_is_check_condition_not_ready_and_request_sense_says_why():
    h = host(None)
    h.command([0, 0, 0, 0, 0, 0])
    assert h.finish() == (2, 0)  # CHECK CONDITION
    data, (status, _) = h.run([3, 0, 0, 0, 18, 0], 18)
    assert status == 0
    assert data[0] == 0x70 and data[2] == 0x02 and data[12] == 0x3A  # not ready, no medium


def test_read_one_sector_through_1801():
    h = host(disc_data_only())
    data, (status, message) = h.run([8, 0, 0, 7, 1, 0], 2048)
    assert (status, message) == (0, 0)
    assert data[:6] == [7, 8, 9, 10, 11, 12] and data[2047] == (7 + 2047) & 0xFF


def test_read_via_1808_pulses_ack_by_itself():
    h = host(disc_data_only())
    h.command([8, 0, 0, 3, 1, 0])
    data = h.read_data_bytes(2048, via=8)
    assert data[0] == 3 and data[100] == 103
    assert h.finish() == (0, 0)


def test_read_three_sectors_at_single_speed():
    h = host(disc_data_only())
    h.command([8, 0, 0, 5, 3, 0])
    began = h.t
    data = h.read_data_bytes(3 * 2048, via=8)
    elapsed = h.t - began
    assert [data[0], data[2048], data[4096]] == [5, 6, 7]
    # three sectors: a seek, then 75 a second; never faster than 2 sector-times after the seek
    assert elapsed >= 2 * ScsiBus.SECTOR_CLOCKS
    assert h.finish() == (0, 0)


def test_a_late_reader_waits_for_a_re_read():
    h = host(disc_data_only())
    h.command([8, 0, 0, 0, 2, 0])
    first = h.read_data_bytes(1, via=8)  # take one byte of sector 0, then stall
    h.advance(3 * ScsiBus.SECTOR_CLOCKS)  # sector 1 is due, the buffer is not empty
    assert h.unit.bus.out  # still holding sector 0's bytes
    began = h.t
    rest = h.read_data_bytes(2047 + 1, via=8)
    assert first[0] == 0 and rest[2047] == 1  # the next byte after sector 0 is sector 1's first
    penalty_clocks = MASTER_HZ * ScsiBus.REREAD_PENALTY_MS // 1000
    assert h.t - began >= penalty_clocks // 2


def test_read_beyond_the_disc_is_check_condition_illegal_request():
    h = host(disc_data_only(10))
    h.command([8, 0, 0, 200, 1, 0])
    assert h.finish() == (2, 0)
    assert (h.unit.bus.sense_key, h.unit.bus.sense_asc) == (5, 0x21)


def test_read_count_zero_is_nothing_to_read():
    h = host(disc_data_only())
    h.command([8, 0, 0, 0, 0, 0])
    assert h.finish() == (0, 0)


def test_unknown_command_is_good_with_no_data():
    h = host(disc_data_only())
    h.command([0x42])
    assert h.finish() == (0, 0)


def test_read_toc_modes():
    h = host(disc_audio_then_data(40, 20))
    data, _ = h.run([0xDE, 0, 0, 0, 0, 0, 0, 0, 0, 0], 2)
    assert data == [0x01, 0x03]  # first and last track, BCD
    data, _ = h.run([0xDE, 1, 0, 0, 0, 0, 0, 0, 0, 0], 3)
    assert data == [0x00, 0x03, 0x15]  # lead-out LBA 90 + 150 = 240 frames = 00:03:15
    data, _ = h.run([0xDE, 2, to_bcd(2), 0, 0, 0, 0, 0, 0, 0], 4)
    assert data == [0x00, 0x02, 0x40, 0x04]  # track 2 starts at LBA 40: 00:02:40, data (4)
    data, _ = h.run([0xDE, 2, to_bcd(1), 0, 0, 0, 0, 0, 0, 0], 4)
    assert data == [0x00, 0x02, 0x00, 0x00]  # track 1: 00:02:00, audio


def test_status_message_phases_and_irq_bits_follow_req():
    h = host(disc_data_only(), enable=0x70)
    h.command([0, 0, 0, 0, 0, 0])
    h.wait(0xD8)  # status phase: REQ with I/O and C/D
    assert h.unit.active & 0x20  # status/message-in
    h.handshake()
    h.wait(0xF8)  # message in
    assert h.unit.active & 0x20
    h.handshake()
    h.wait(0, 0xF8)
    assert h.unit.active == 0


def test_data_in_raises_the_data_irq_bit():
    h = host(disc_data_only(), enable=0x70)
    h.command([8, 0, 0, 1, 1, 0])
    h.wait(0xC8)
    assert h.unit.active & 0x40 and not h.unit.active & 0x20


def test_reset_through_1804_aborts_everything():
    h = host(disc_data_only())
    h.command([8, 0, 0, 1, 1, 0])
    h.wait(0xC8)
    h.w(4, 0x02)
    h.w(4, 0x00)
    assert h.r(0) == 0 and h.unit.bus.phase.value == "bus free"


def test_selecting_during_data_in_aborts_with_an_eight_byte_message():
    h = host(disc_data_only())
    h.command([8, 0, 0, 1, 1, 0])
    h.wait(0xC8)
    h.select()
    assert h.unit.bus.phase.value == "status"
    assert len(h.unit.bus.out) == 8
