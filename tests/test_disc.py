# SPDX-License-Identifier: MIT
"""The disc model: LBA/MSF, tracks from a cue, data sectors, chdman's cue shape."""

from discs import audio_sectors, data_sector, disc_audio_then_data, disc_data_only, numbered_data

from pcenginecd_python.disc import Disc, from_bcd, lba_to_msf, msf_to_lba, to_bcd


def test_bcd_and_msf_round_trip():
    assert to_bcd(59) == 0x59 and from_bcd(0x59) == 59
    assert lba_to_msf(0) == (0, 2, 0)  # LBA 0 is 00:02:00: the lead-in gap is not stored
    assert lba_to_msf(75 * 60 - 150) == (1, 0, 0)
    for lba in (0, 1, 74, 75, 4349, 4350, 99999):
        assert msf_to_lba(*lba_to_msf(lba)) == lba


def test_memory_disc_reads_its_payload_and_zeros_outside():
    disc = disc_data_only(10)
    assert disc.sector_count == 10
    assert disc.read_data(3)[:4] == bytes([3, 4, 5, 6])
    assert disc.read_data(100) == bytes(2048)
    assert disc.read_raw(3)[:12] == data_sector(3)[:12]  # sync pattern


def test_tracks_and_audio_are_not_data():
    disc = disc_audio_then_data(40, 20)
    kinds = [(t.number, t.is_data, t.start, t.end) for t in disc.tracks]
    assert kinds == [(1, False, 0, 40), (2, True, 40, 60), (3, False, 60, 90)]
    assert disc.track_at(45).number == 2
    assert disc.read_data(10) == bytes(2048)  # an audio sector has no data
    assert disc.read_data(40)[0] == 40


def test_cue_with_pregap_index_00(tmp_path):
    # The shape chdman extractcd writes: one FILE, INDEX 00 (stored pregap) then INDEX 01.
    bin_ = audio_sectors(10) + numbered_data(10, 20) + audio_sectors(10)
    (tmp_path / "d.bin").write_bytes(bin_)
    (tmp_path / "d.cue").write_text(
        'FILE "d.bin" BINARY\n'
        "  TRACK 01 AUDIO\n    INDEX 01 00:00:00\n"
        "  TRACK 02 MODE1/2352\n    INDEX 00 00:00:10\n    INDEX 01 00:00:15\n"
        "  TRACK 03 AUDIO\n    INDEX 01 00:00:30\n"
    )
    disc = Disc.from_cue(tmp_path / "d.cue")
    t1, t2, t3 = disc.tracks
    assert (t1.start, t1.end) == (0, 10)  # track 1 ends where track 2's pregap begins
    assert (t2.index0, t2.start, t2.end) == (10, 15, 30)
    assert (t3.start, t3.end) == (30, 40)
    assert disc.sector_count == 40
    assert disc.read_data(12)[0] == 12  # the pregap sectors of a data track are readable
    disc.close()


def test_two_files_lie_end_to_end(tmp_path):
    (tmp_path / "a.bin").write_bytes(numbered_data(0, 5))
    (tmp_path / "b.bin").write_bytes(audio_sectors(7))
    (tmp_path / "d.cue").write_text(
        'FILE "a.bin" BINARY\n  TRACK 01 MODE1/2352\n    INDEX 01 00:00:00\n'
        'FILE "b.bin" BINARY\n  TRACK 02 AUDIO\n    INDEX 01 00:00:00\n'
    )
    disc = Disc.from_cue(tmp_path / "d.cue")
    assert [(t.start, t.end) for t in disc.tracks] == [(0, 5), (5, 12)]
    disc.close()
