# SPDX-License-Identifier: MIT
"""Issue 0001 (findings from the Rust port): one directed test per settled item."""

import pytest
from discs import disc_audio_then_data, disc_data_only
from helpers import REG, Host
from pcengine_python.sockets import BoardPins, IrqLine, ResetKind

from pcenginecd_python.disc import Disc
from pcenginecd_python.scsi import MASTER_HZ, ScsiBus
from pcenginecd_python.unit import BRAM_BYTES, CdUnit

# -- item 1: a timer counts from the register write that starts it ----------------------------


def sel_to_command_phase(play_audio: bool) -> int:
    """Master clocks from a SEL write to the command phase, a second after the drive was last
    used (looked for every 12 clocks, the board's catch-up between looks)."""
    h = Host(CdUnit(disc_audio_then_data(400, 20)))
    if play_audio:
        h.command([0xD8, 1, 0x01, 0, 0, 0, 0, 0, 0, 0x80])  # AUDIO START, track 1 (5.3 s)
        h.finish()
        assert h.unit.bus.next_event() is not None  # the end of the track waits in the future
    h.advance(MASTER_HZ)
    h.select()
    began = h.t
    while h.unit.read(REG, h.t) & 0xF8 != 0xD0:
        h.t += 12
        h.unit.catch_up(h.t)
    return h.t - began


def test_sel_to_the_command_phase_takes_the_same_time_with_cd_audio_playing():
    idle = sel_to_command_phase(play_audio=False)
    playing = sel_to_command_phase(play_audio=True)
    assert ScsiBus.SEL_TO_COMMAND_PHASE <= idle < ScsiBus.SEL_TO_COMMAND_PHASE + 24
    assert playing == idle  # before the fix: 0 (the timer was filed a second in the past)


def test_a_register_access_brings_the_drive_clock_to_its_own_time():
    h = Host(CdUnit(disc_audio_then_data(400, 20)))
    h.command([0xD8, 1, 0x01, 0, 0, 0, 0, 0, 0, 0x80])
    h.finish()
    h.advance(MASTER_HZ // 2)
    h.r(0)
    assert h.unit.bus.now == h.t and h.unit.cdda._now == h.t


# -- item 2: CD RAM and BRAM accesses need no clock; the card's never had one ------------------


def test_memory_accesses_do_not_run_the_drive():
    h = Host(CdUnit(disc_data_only()))
    h.select()
    t = h.t
    h.unit.write(0x100000, 0x5A, t + MASTER_HZ)  # CD RAM, a second later
    assert h.unit.read(0x100000, t + MASTER_HZ) == 0x5A
    assert h.unit.bus.now == t  # only a register access (or the board's catch-up) moves it


# -- item 3: a power-on reset forgets the unit's own timers -----------------------------------


def test_power_on_reset_clears_the_units_timers_and_files_the_adpcm_idle_at_the_reset():
    unit = CdUnit(disc_data_only())
    h = Host(unit)
    h.w(5, 0)  # the $1805 guard runs for CHANNEL_LATCH_GUARD clocks
    unit._dma_at = h.t + 10_000
    unit.adpcm.record = True
    unit.adpcm._last_output = 123  # the decoder was playing
    h.advance(100)
    unit.reset(ResetKind.POWER_ON)
    assert unit._dma_at is None and unit._latch_guard_until == 0
    assert unit._next_event == unit._soonest()
    assert unit.adpcm.events[-1] == (h.t, 0)  # before: (0, 0), behind later events
    h.w(5, 0)  # within the old guard window: the latch now takes it
    assert unit.right_channel


# -- item 4: a bus reset reports the IRQ levels it drops --------------------------------------


def test_a_bus_reset_tells_the_unit_that_req_dropped():
    calls = []
    h = Host(CdUnit(disc_data_only()))
    h.command([0, 0, 0, 0, 0, 0])
    h.wait(0xD8)  # status phase: the status/message level is up
    h.unit.bus._irq = lambda mask, level: calls.append((mask, level))
    h.unit.bus.reset()
    assert calls == [(0x20, False)]  # before: nothing


# -- item 5: the small ones -------------------------------------------------------------------


def test_bram_longer_than_the_ram_is_refused():
    assert len(CdUnit(bram=bytes(BRAM_BYTES)).bram) == BRAM_BYTES
    with pytest.raises(ValueError):
        CdUnit(bram=bytes(BRAM_BYTES + 1))


def test_a_cue_track_or_index_before_its_file_or_track_is_refused(tmp_path):
    (tmp_path / "d.bin").write_bytes(bytes(2352 * 4))
    (tmp_path / "a.cue").write_text('TRACK 01 MODE1/2352\nFILE "d.bin" BINARY\nINDEX 01 00:00:00\n')
    with pytest.raises(ValueError, match="TRACK before any FILE"):
        Disc.from_cue(tmp_path / "a.cue")
    (tmp_path / "b.cue").write_text('FILE "d.bin" BINARY\nINDEX 01 00:00:00\n')
    with pytest.raises(ValueError, match="INDEX before any TRACK"):
        Disc.from_cue(tmp_path / "b.cue")


@pytest.mark.parametrize("check", [False, True])
def test_an_unknown_command_answers_good_or_check_condition_with_the_switch(check, monkeypatch):
    monkeypatch.setattr(ScsiBus, "UNKNOWN_COMMAND_CHECK_CONDITION", check)
    h = Host(CdUnit(disc_data_only()))
    h.command([0x42])
    assert h.finish() == ((0x02, 0) if check else (0, 0))
    sense, _ = h.run([0x03, 0, 0, 0, 18, 0], 18)
    assert (sense[2], sense[12]) == ((0x05, 0x20) if check else (0, 0))


def test_reset_register_held_keeps_the_drive_irqs_off():
    unit = CdUnit(disc_data_only())
    irq = IrqLine("IRQ2")
    unit.bind(BoardPins(irq2=irq, hold=lambda n: None))
    h = Host(unit)
    h.w(2, 0x70)
    h.w(4, 0x02)  # the drive held in reset
    h.w(2, 0x70)  # enables written again while held
    h.select()
    h.w(1, 0)
    h.advance(ScsiBus.SEL_TO_COMMAND_PHASE + ScsiBus.TEST_UNIT_READY + 10_000)
    assert unit.active & 0x60 == 0 and not irq.level and h.r(0) == 0
    h.w(4, 0x00)
    h.command([0, 0, 0, 0, 0, 0])
    h.wait(0xD8)
    assert unit.active & 0x20 and irq.level  # released: the status IRQ comes again
