"""CD-DA: audio start/end/pause, READ SUBQ, the sample source, the $1805 latch, the fader."""

import struct

from discs import audio_sectors, disc_audio_then_data
from helpers import Host

from pcenginecd_python.cdda import SAMPLE_HZ, Status
from pcenginecd_python.disc import to_bcd
from pcenginecd_python.unit import CdUnit

MASTER = 21_477_272


def make(disc=None):
    unit = CdUnit(disc or disc_audio_then_data(40, 20))
    return unit, Host(unit)


def play_track(h, track=1, mode=1):
    # AUDIO START by track number (mode bits 7-6 = 10) then wait for the busy phase to end
    h.command([0xD8, mode, to_bcd(track), 0, 0, 0, 0, 0, 0, 0x80])
    return h.finish()


def test_audio_start_is_busy_until_the_seek_ends_then_good_status():
    unit, h = make()
    h.command([0xD8, 1, 0x01, 0, 0, 0, 0, 0, 0, 0x80])
    h.wait(0x80)  # BSY alone: the drive is busy while it finds the sector
    began = h.t
    assert h.finish() == (0, 0)
    assert h.t - began > 1_000_000  # a seek costs milliseconds, not microseconds
    assert unit.cdda.status is Status.PLAYING


def test_subq_reports_position_track_and_status_while_playing():
    _unit, h = make()
    play_track(h, 1)
    h.advance(MASTER // 75 * 5 + 1000)  # five sectors of playing
    data, _ = h.run([0xDD] + [0] * 9, 10)
    assert data[0] == 0  # playing
    assert data[1] == 0x01  # ADR 1, audio
    assert data[2] == 0x01 and data[3] == 1  # track 1, index 1
    assert data[4:7] == [0, 0, 5]  # five frames into the track (relative BCD)
    assert data[7:10] == [0, 2, 5]  # absolute: 00:02:05


def test_pause_freezes_the_position_and_reports_paused():
    unit, h = make()
    play_track(h, 1)
    h.advance(MASTER // 75 * 3)
    h.run([0xDA] + [0] * 9)
    assert unit.cdda.status is Status.PAUSED
    frozen = unit.cdda.position
    h.advance(MASTER // 75 * 10)
    assert unit.cdda.position == frozen
    data, _ = h.run([0xDD] + [0] * 9, 10)
    assert data[0] == 2


def test_audio_end_mode_2_keeps_the_bus_busy_until_the_range_ends():
    unit, h = make()
    h.command([0xD8, 0, 0x01, 0, 0, 0, 0, 0, 0, 0x80])  # start, paused
    h.finish()
    assert unit.cdda.status is Status.PAUSED
    # end at LBA 9 (inclusive) by LBA address, mode 2 = busy until done, then status
    h.command([0xD9, 2, 0, 0, 0, 9, 0, 0, 0, 0x00])
    h.wait(0x80)
    began = h.t
    assert h.finish() == (0, 0)
    ten_sectors = 10 * MASTER // 75
    assert abs((h.t - began) - ten_sectors) < ten_sectors * 0.15
    assert unit.cdda.status is Status.STOPPED


def test_audio_end_mode_1_loops():
    unit, h = make()
    h.command([0xD8, 0, 0x01, 0, 0, 0, 0, 0, 0, 0x80])
    h.finish()
    h.command([0xD9, 1, 0, 0, 0, 3, 0, 0, 0, 0x00])
    h.advance(MASTER // 75 * 20)  # five times the 4-sector range
    assert unit.cdda.status is Status.PLAYING
    assert 0 <= unit.cdda.position <= 3


def test_start_by_msf_uses_the_absolute_time_with_the_lead_in():
    unit, h = make()
    # 00:02:10 = LBA 10, in track 1
    h.command([0xD8, 1, 0x00, 0x02, 0x10, 0, 0, 0, 0, 0x40])
    h.finish()
    assert unit.cdda._start == 10


def test_samples_come_out_at_44100_and_match_the_disc():
    unit, h = make()
    play_track(h, 1)
    cdda = unit.cdda
    start = h.t
    cdda.take_samples(start)  # set the origin
    out = cdda.take_samples(start + MASTER // 10)
    assert abs(len(out) - SAMPLE_HZ // 10) <= 1
    pairs = struct.unpack(f"<{2 * 588 * 12}h", audio_sectors(12))
    first_sectors = set(zip(pairs[0::2], pairs[1::2], strict=True))
    played = [s for s in out if s != (0, 0)]
    assert len(played) > 3000  # the 0.1 s window is nearly all playing, 12 sectors' worth
    assert set(played) <= first_sectors  # exactly the disc's samples, none invented
    assert max(abs(s[0]) for s in played) > 1000 and max(abs(s[1]) for s in played) > 1000


def test_samples_are_silence_when_not_playing_but_still_counted():
    unit, _h = make()
    unit.cdda.take_samples(0)
    out = unit.cdda.take_samples(MASTER // 100)
    assert len(out) >= 440 and set(out) == {(0, 0)}


def test_1805_latches_left_then_right_sample():
    _unit, h = make()
    play_track(h, 1)
    h.advance(MASTER // 75 * 2 + 5000)
    h.w(5, 0)  # toggles to right
    right = h.r(5) | (h.r(6) << 8)
    h.advance(2000)
    h.w(5, 0)  # toggles to left
    left = h.r(5) | (h.r(6) << 8)
    assert (left, right) != (0, 0)


def test_fader_fades_cd_audio_over_about_eight_or_two_seconds():
    unit, h = make()
    c = unit.cdda
    h.w(0x0F, 0x08)
    assert c.fade_gain(h.t) == 1.0
    assert abs(c.fade_gain(h.t + 4 * MASTER) - 0.5) < 0.01
    assert c.fade_gain(h.t + 9 * MASTER) == 0.0
    h.w(0x0F, 0x0C)  # fast: a different value restarts the timer
    assert abs(c.fade_gain(h.t + 1 * MASTER) - 0.5) < 0.01
    h.w(0x0F, 0x00)
    assert c.fade_gain(h.t + 100 * MASTER) == 1.0
    h.w(0x0F, 0x0A)  # aimed at ADPCM: CD audio unaffected
    assert c.fade_gain(h.t + 100 * MASTER) == 1.0
