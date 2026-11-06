"""CD-DA: the audio player behind `AUDIO START/END/PAUSE`, `READ SUBQ`, `$1805-$1806` and the
audio source the board mixes.

Time is exact and lazy: the player keeps an anchor (the master clock at which a given sample of a
given sector played) and computes the position for any `mclk`, so playback does not depend on how
often the host asks for samples. 44,100 stereo samples a second, 588 per 2352-byte sector, 75
sectors a second [hw: Red Book]. Samples are signed 16-bit little-endian pairs.

What is not modelled (U9): the drive's subchannel Q stream (the BIOS's `$1807` read and its IRQ
bit 0x10), the DAC's filtering (Mednafen filters, Mesen2 resamples with a Hermite kernel), and the
real fader curve: `$180F` is tier 2 (pcetech: "silence in about 8 seconds" / "about 2 seconds")
and the shape between is linear here (Mesen2 fades 1% per 60 ms / 25 ms, i.e. 6 s / 2.5 s; MAME
calls its own fader "sketchy and unchecked against real HW").
"""

from __future__ import annotations

import enum
import struct
from collections.abc import Callable, Sequence
from typing import ClassVar

from pcenginecd_python.disc import Disc

MASTER_HZ = 21_477_272
SAMPLE_HZ = 44_100
SAMPLES_PER_SECTOR = 588


class Status(enum.Enum):
    PLAYING = "playing"
    PAUSED = "paused"
    STOPPED = "stopped"  # idle: nothing started, or stopped / a data read took the head
    SEEKING = "seeking"  # moving to the start; becomes PLAYING or PAUSED


class EndMode(enum.IntEnum):
    STOP = 3
    LOOP = 1
    IRQ = 2  # stop at the end and give the busy command its good status


class CddaPlayer:
    # [emu: Mednafen `DoNEC_PCE_READSUBQ`, tier 5] the audio-status byte of READ SUBQ
    SUBQ_STATUS: ClassVar[dict[Status, int]] = {
        Status.PLAYING: 0,
        Status.PAUSED: 2,
        Status.STOPPED: 3,
        Status.SEEKING: 3,
    }
    # [hw: pcetech 8] fade timer: "silence in about 8 seconds" (value 8-9), "about 2 seconds"
    # (C-D); tier 2. Linear.
    FADE_SLOW_SECONDS = 8.0
    FADE_FAST_SECONDS = 2.0

    def __init__(self) -> None:
        self.disc: Disc | None = None
        self.on_good_status: Callable[[], None] = lambda: None  # set by the SCSI bus
        self.status = Status.STOPPED
        self._start = 0
        self._end = 0
        self._end_mode = EndMode.STOP
        self._anchor_clock = 0
        self._anchor_sample = 0  # absolute sample number (sector * 588 + offset) at the anchor
        self._event_at: int | None = None  # seek done, or the end of the range
        self._now = 0
        self._taken = 0  # samples handed out so far, in absolute stream time
        self._take_origin: int | None = None
        self._cache: tuple[int, Sequence[int]] | None = None
        self.fade_register = 0
        self._fade_start = 0
        self.gain = 1.0  # AudioSource socket: the mixer's gain for this source
        self._paused_after_seek = False

    # -- state the bus reads ---------------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self.status is not Status.STOPPED

    @property
    def status_code(self) -> int:
        return self.SUBQ_STATUS[self.status]

    @property
    def position(self) -> int:
        """The sector under the head at the last time the bus ran (`_now`)."""
        return self._sample_at(self._now) // SAMPLES_PER_SECTOR

    def _sample_at(self, mclk: int) -> int:
        if self.status is Status.PLAYING:
            return self._anchor_sample + max(0, mclk - self._anchor_clock) * SAMPLE_HZ // MASTER_HZ
        return self._anchor_sample

    # -- commands --------------------------------------------------------------------------------

    def play(self, start: int, *, paused: bool, seek_clocks: int) -> None:
        """AUDIO START: seek to `start`, then play to the end of its track (or wait for an AUDIO
        END if `paused`). The bus holds BUSY until the seek is done."""
        assert self.disc is not None
        track = self.disc.track_at(start)
        self._start = start
        self._end = (track.end if track else self.disc.sector_count) - 1
        self._end_mode = EndMode.STOP
        self._anchor_sample = start * SAMPLES_PER_SECTOR
        self._anchor_clock = self._now + seek_clocks
        self._event_at = self._anchor_clock
        self._paused_after_seek = paused
        self.status = Status.SEEKING

    def set_end(self, end: int, mode: int) -> None:
        """AUDIO END (modes 1-3): play (or resume) up to sector `end` inclusive."""
        assert self.disc is not None
        self._end = min(end, self.disc.sector_count - 1)
        self._end_mode = EndMode(mode)
        if self.status in (Status.PAUSED, Status.STOPPED):
            self._resume()
        elif self.status is Status.SEEKING:
            self._paused_after_seek = False
        self._schedule_end()

    def _resume(self) -> None:
        self._anchor_clock = self._now
        self.status = Status.PLAYING

    def pause(self) -> None:
        if self.status is Status.PLAYING:
            self._anchor_sample = self._sample_at(self._now)
            self.status = Status.PAUSED
            self._event_at = None
        elif self.status is Status.SEEKING:
            self._paused_after_seek = True

    def stop(self) -> None:
        if self.status is Status.PLAYING:
            self._anchor_sample = self._sample_at(self._now)
        self.status = Status.STOPPED
        self._event_at = None

    def idle(self) -> None:
        """A data read took the head: audio stops."""
        self.stop()

    def _schedule_end(self) -> None:
        if self.status is not Status.PLAYING:
            self._event_at = self._anchor_clock if self.status is Status.SEEKING else None
            return
        remaining = (self._end + 1) * SAMPLES_PER_SECTOR - self._anchor_sample
        self._event_at = self._anchor_clock + -(-remaining * MASTER_HZ // SAMPLE_HZ)

    # -- time ------------------------------------------------------------------------------------

    def next_event(self) -> int | None:
        return self._event_at

    def run_to(self, mclk: int) -> None:
        """Fire the seek-done and end-of-range events due at or before `mclk`."""
        while self._event_at is not None and self._event_at <= mclk:
            at, self._event_at = self._event_at, None
            self._now = at
            if self.status is Status.SEEKING:
                self.status = Status.PAUSED if self._paused_after_seek else Status.PLAYING
                self._anchor_clock = at
                self._schedule_end()
                self.on_good_status()
            elif self.status is Status.PLAYING:
                if self._end_mode is EndMode.LOOP:
                    self._anchor_sample = self._start * SAMPLES_PER_SECTOR
                    self._anchor_clock = at
                    self._schedule_end()
                else:
                    self._anchor_sample = (self._end + 1) * SAMPLES_PER_SECTOR
                    self.status = Status.STOPPED
                    if self._end_mode is EndMode.IRQ:
                        self.on_good_status()
        self._now = max(self._now, mclk)

    # -- samples ---------------------------------------------------------------------------------

    def _frame(self, absolute_sample: int) -> tuple[int, int]:
        assert self.disc is not None
        lba, offset = divmod(absolute_sample, SAMPLES_PER_SECTOR)
        if self._cache is None or self._cache[0] != lba:
            track = self.disc.track_at(lba)
            if track is None or track.is_data:
                values: Sequence[int] = (0,) * (SAMPLES_PER_SECTOR * 2)
            else:
                values = struct.unpack("<1176h", self.disc.read_raw(lba))
            self._cache = (lba, values)
        v = self._cache[1]
        return v[2 * offset], v[2 * offset + 1]

    def latest_sample(self) -> tuple[int, int]:
        """The sample being played at the last time run (`$1805/$1806`): zeros unless playing."""
        if self.status is not Status.PLAYING or self.disc is None:
            return 0, 0
        return self._frame(self._sample_at(self._now))

    def fade_gain(self, mclk: int, adpcm: bool = False) -> float:
        """The `$180F` fader's gain for CD-DA, or for ADPCM (`adpcm=True`: the fade is aimed at
        it by bit 1; pcetech did not test the ADPCM fade, the Hudson BIOS manual's CD_FADE lists
        $0A and $0E for it: U9/M8)."""
        if not self.fade_register & 0x08 or bool(self.fade_register & 0x02) != adpcm:
            return 1.0  # no fade, or it is aimed at the other source
        seconds = self.FADE_FAST_SECONDS if self.fade_register & 0x04 else self.FADE_SLOW_SECONDS
        return max(0.0, 1.0 - (mclk - self._fade_start) / (seconds * MASTER_HZ))

    def write_fade(self, value: int, mclk: int) -> None:
        """`$180F` [hw: pcetech 8]: bit 3 fades, bit 2 chooses the fast fade, bit 1 aims it at
        ADPCM. Rewriting the same value changes nothing; a new value restarts the timer (the
        finer cases in pcetech, a cancelled fade whose timer still runs, are U9)."""
        if value & 0x0F != self.fade_register & 0x0F:
            self._fade_start = mclk
        self.fade_register = value

    def take_samples(self, mclk: int) -> list[tuple[int, int]]:
        """Stereo samples since the last call, one per 1/44100 s of master-clock time (zeros when
        not playing, so a mixer keeps its place). The fader's gain is applied."""
        self.run_to(mclk)
        if self._take_origin is None:
            self._take_origin = mclk
        total = (mclk - self._take_origin) * SAMPLE_HZ // MASTER_HZ
        out: list[tuple[int, int]] = []
        for n in range(self._taken, total):
            at = self._take_origin + -(-n * MASTER_HZ // SAMPLE_HZ)
            if self.disc is not None and self._plays_at(at):
                left, right = self._frame(self._sample_at(at))
                g = self.fade_gain(at)
                out.append((int(left * g), int(right * g)))
            else:
                out.append((0, 0))
        self._taken = total
        return out

    def _plays_at(self, mclk: int) -> bool:
        """Was audio playing at `mclk`? (Past events have already moved the state, so a sample
        before the current anchor or after the end is silence.)"""
        if self.status is Status.PLAYING:
            return mclk >= self._anchor_clock
        return False

    # AudioSource attributes (socket 9): a fixed rate; the mixer applies `gain`
    rate_hz = float(SAMPLE_HZ)
