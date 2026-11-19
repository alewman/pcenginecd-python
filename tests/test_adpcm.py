# SPDX-License-Identifier: MIT
"""The ADPCM unit from the register semantics of pcetech 8, the Hudson BIOS routines (AD_STAT,
AD_PLAY, the `ad_*_addr_set` helpers) and the MSM5205 decoder. Directed tests, no emulator."""

from helpers import Host
from pcengine_python.sockets import BoardPins, IrqLine

from pcenginecd_python.adpcm import DELTA, INDEX_STEP, MASTER_HZ, Adpcm
from pcenginecd_python.unit import CdUnit


def make():
    unit = CdUnit()
    irq = IrqLine("IRQ2")
    unit.bind(BoardPins(irq2=irq, hold=lambda n: None))
    return unit, irq, Host(unit)


def load(h, address, data):
    """AD_WRITE: set the write pointer, then write bytes polling `$180C` bit 2."""
    h.w(0x08, address & 0xFF)
    h.w(0x09, address >> 8)
    h.w(0x0D, 0x03)  # write pointer = latch (bit 0 set: no step back)
    h.w(0x0D, 0x02)
    for byte in data:
        h.w(0x0A, byte)
        while h.r(0x0C) & 0x04:
            h.advance(12)
    h.w(0x0D, 0x00)


def start(h, address, length, *, rate=0x0E, stop_at_end=True):
    """AD_PLAY as the BIOS drives it: read pointer (with the priming read), length, rate, play."""
    h.w(0x08, address & 0xFF)
    h.w(0x09, address >> 8)
    h.w(0x0D, 0x08)  # read pointer = latch - 1 ...
    h.advance(100)
    h.r(0x0A)  # ... and the priming read steps it onto the first byte
    h.advance(100)
    h.w(0x0D, 0x00)
    h.w(0x08, length & 0xFF)
    h.w(0x09, length >> 8)
    h.w(0x0D, 0x10)  # latch the length
    h.w(0x0D, 0x00)
    h.w(0x0E, rate)
    h.w(0x0D, 0x20 | (0x40 if stop_at_end else 0))


def test_the_step_table_has_the_msm5205_shape():
    assert len(DELTA) == 49 * 8
    assert DELTA[:8] == (2, 6, 10, 14, 18, 22, 26, 30)  # step 16: step/8 + b0 step/4 + ...
    assert DELTA[-8:] == (194, 582, 970, 1358, 1746, 2134, 2522, 2910)  # step 1552
    assert INDEX_STEP == (-1, -1, -1, -1, 2, 4, 6, 8)


def test_the_decoder_moves_the_signal_by_sign_and_magnitude_and_the_index_by_the_magnitude():
    a = Adpcm(lambda mask, level: None)
    a.ram[0] = 0x77  # +magnitude 7, then +7 (high nibble first)
    a.ram[1] = 0xF9  # sign bit and magnitude 7 (negative), then +1
    a.control, a.length, a.rate = 0x20, 4, 0x0F
    a.play_request, a._sample_at = True, 0
    a.run(0)
    assert (a.signal, a.index) == (DELTA[7], 8)
    a.run(a.next_event())
    assert (a.signal, a.index) == (DELTA[7] + DELTA[8 * 8 + 7], 16)
    a.run(a.next_event())  # high nibble 0xF: negative, magnitude 7
    assert (a.signal, a.index) == (DELTA[7] + DELTA[8 * 8 + 7] - DELTA[16 * 8 + 7], 24)


def test_the_signal_saturates_by_default_and_wraps_with_the_switch():
    for saturate in (True, False):
        a = Adpcm(lambda mask, level: None)
        a.SATURATE = saturate
        a.signal, a.index = 2000, 48
        a.playing = True
        a.ram[0] = 0x70
        a.control, a.length, a._sample_at = 0x20, 2, 0
        a.run(0)
        if saturate:
            assert a.signal == 2047
        else:
            assert a.signal == ((2000 + DELTA[48 * 8 + 7] + 2048) & 0xFFF) - 2048 == 814


def test_the_rate_register_sets_32_over_16_minus_n_kilohertz():
    a = Adpcm(lambda mask, level: None)
    for n, hz in ((0, 2000.0), (0x0E, 16000.0), (0x0F, 32000.0)):
        a.rate = n | 0xF0  # only the low four bits count
        assert abs(MASTER_HZ * 65536 / a.period_fixed - hz) < 0.01


def test_a_read_is_buffered_and_bit_7_of_180c_clears_in_about_24_cycles():
    unit, _, h = make()
    load(h, 0x0100, [0x11, 0x22])
    h.w(0x08, 0x00)
    h.w(0x09, 0x01)
    h.w(0x0D, 0x08 | 0x04)  # read pointer = latch
    first = h.r(0x0A)
    assert first == 0  # the old buffer
    assert h.r(0x0C) & 0x80  # busy
    h.advance(unit.adpcm.READ_CLOCKS)
    assert not h.r(0x0C) & 0x80
    assert h.r(0x0A) == 0x11


def test_a_write_is_busy_for_the_same_time_and_the_pointer_steps_after_it():
    unit, _, h = make()
    h.w(0x0D, 0x02 | 0x01)
    h.w(0x0A, 0x5A)
    assert h.r(0x0C) & 0x04
    assert unit.adpcm.ram[0] == 0
    h.advance(unit.adpcm.WRITE_CLOCKS)
    assert not h.r(0x0C) & 0x04
    assert unit.adpcm.ram[0] == 0x5A and unit.adpcm.write_ptr == 1


def test_playback_runs_to_the_end_flag_and_raises_irq2_through_the_enable_mask():
    unit, irq, h = make()
    load(h, 0x0000, [0x77, 0x77, 0x77, 0x77])
    h.w(0x02, 0x08)  # enable the ADPCM end source
    start(h, 0x0000, 4)
    assert not irq.level and not h.r(3) & 0x08
    t = h.t
    h.advance(MASTER_HZ // 100)  # 10 ms is far longer than 8 samples at 16 kHz
    assert irq.level and h.r(3) & 0x08
    assert h.r(0x0C) & 0x01  # end reached
    assert not h.r(0x0C) & 0x08  # no longer playing
    assert unit.adpcm.read_ptr == 4 and unit.adpcm.length == 0
    assert h.t - t > 0


def test_playback_takes_the_time_the_rate_says():
    _unit, _, h = make()
    load(h, 0x0000, [0x11] * 16)
    start(h, 0x0000, 16, rate=0x0E)  # 16 bytes = 32 samples at 16 kHz = 2 ms
    h.advance(MASTER_HZ * 18 // 10_000)  # 1.8 ms
    assert not h.r(0x0C) & 0x01 and h.r(0x0C) & 0x08
    h.advance(MASTER_HZ * 5 // 10_000)  # 2.3 ms in all
    assert h.r(0x0C) & 0x01 and not h.r(0x0C) & 0x08


def test_the_end_source_stays_off_without_its_enable_bit_and_clears_with_a_new_length():
    unit, irq, h = make()
    load(h, 0x0000, [0x11, 0x11])
    start(h, 0x0000, 2)
    h.advance(MASTER_HZ // 100)
    assert unit.active & 0x08 and not irq.level
    h.w(0x08, 0x10)
    h.w(0x09, 0x00)
    h.w(0x0D, 0x10)  # the length latch clears the end flag
    assert not unit.active & 0x08 and not h.r(0x0C) & 0x01


def test_the_half_flag_is_set_while_less_than_half_of_the_buffer_is_left():
    unit, _, h = make()
    a = unit.adpcm
    a.ram[0] = 0x11
    h.w(0x08, 0x00)
    h.w(0x09, 0x00)
    h.w(0x0D, 0x08 | 0x04)
    h.advance(100)
    a.length = 0x9000  # more than half left: playing does not set it
    h.w(0x0E, 0x0F)
    h.w(0x0D, 0x20)
    h.advance(MASTER_HZ // 1000)
    assert not unit.active & 0x04
    a.length = 0x7FFF  # (the tests may set the counter directly)
    h.advance(MASTER_HZ // 1000)
    assert unit.active & 0x04 and h.r(3) & 0x04


def test_reset_zeroes_pointers_and_length_and_keeps_the_read_buffer():
    unit, _, h = make()
    load(h, 0x0000, [0xC3])
    h.w(0x08, 0x00)
    h.w(0x09, 0x00)
    h.w(0x0D, 0x0C)
    h.advance(100)
    h.r(0x0A)
    h.advance(100)
    buffered = unit.adpcm.read_buffer
    assert buffered == 0xC3
    h.w(0x0D, 0x80)
    h.w(0x0D, 0x00)
    a = unit.adpcm
    assert (a.read_ptr, a.write_ptr, a.length) == (0, 0, 0) and a.read_buffer == buffered


def test_the_cd_dma_goes_through_the_write_path_and_counts_the_length():
    # AD_TRANS bytes arrive as writes: the length counter follows (the half/end rules apply)
    unit, _, h = make()
    a = unit.adpcm
    h.w(0x0D, 0x03)
    h.w(0x0D, 0x02)
    for value in (1, 2, 3):
        assert a.dma_write(value, h.t)
        assert not a.dma_write(9, h.t)  # still busy: the DMA must retry
        h.advance(a.WRITE_CLOCKS)
    assert bytes(a.ram[:3]) == b"\x01\x02\x03" and a.length == 3


def test_the_audio_source_holds_the_decoder_output_at_44100_hz():
    unit, _, h = make()
    source = unit.adpcm_source
    assert source.take_samples(h.t) == []  # the origin
    load(h, 0x0000, [0x77] * 8)
    start(h, 0x0000, 8, rate=0x0E)
    h.advance(MASTER_HZ // 200)  # 5 ms
    samples = source.take_samples(h.t)
    assert 200 < len(samples) < 230  # 44.1 kHz for 5 ms plus the loads above
    left = [s[0] for s in samples]
    assert max(left) > 0  # the signal climbed
    assert all(a == b for a, b in samples)  # mono on both channels
    assert left[-1] == 0  # the unit stopped at the end: the DAC is idle


def test_the_fade_aimed_at_adpcm_scales_only_adpcm():
    unit, _, h = make()
    source = unit.adpcm_source
    source.take_samples(h.t)
    load(h, 0x0000, [0x77] * 200)
    start(h, 0x0000, 200, rate=0x0E, stop_at_end=True)
    unit.cdda.write_fade(0x0A, h.t)  # ADPCM, slow fade (the Hudson BIOS manual's CD_FADE $0A)
    h.advance(MASTER_HZ * 9 // 1000)
    early = [s[0] for s in source.take_samples(h.t)]
    assert unit.cdda.fade_gain(h.t) == 1.0  # CD-DA untouched
    assert unit.cdda.fade_gain(h.t + MASTER_HZ * 20, adpcm=True) == 0.0
    assert abs(unit.cdda.fade_gain(h.t + MASTER_HZ * 3, adpcm=True) - 0.5) < 0.01  # 6 s default
    unit.cdda.PCETECH_FADE = True
    assert abs(unit.cdda.fade_gain(h.t + MASTER_HZ * 4, adpcm=True) - 0.5) < 0.01  # 8 s switch
    assert max(early) > 0


def test_the_board_mixes_adpcm_with_the_other_sources(tmp_path):
    from pcenginecd_python.board import PcEngineCd

    machine = PcEngineCd(bytes(0x40000))
    assert machine.unit.adpcm_source in machine.board.audio_sources
    machine.board.take_audio()  # CD-DA and ADPCM start their streams at the first call
    machine.board.advance(MASTER_HZ // 100)
    out = machine.board.take_audio()
    assert out and len(out) > 100
