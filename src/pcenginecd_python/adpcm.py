"""The ADPCM unit: 64 KiB of RAM, its pointers, the MSM5205 decoder and the audio source.

Tiers (the base board's docs/validation.md): [hw: pcetech 8] MacDonald, tier 2, names the registers
and a few bit meanings and says the rest is "currently trying to document"; [mfr: Hudson BIOS manual
and System Card ROM] tier 3, the BIOS source (`AD_STAT`, `AD_PLAY`, `ad_*_addr_set` in
`Super CD-ROM2 System V3.00 (J).ASM`) shows how the registers are driven; [emu] Mesen2
`PceAdpcm.cpp`, Geargrafx `adpcm*.cpp`, Mednafen `pcecd.cpp` and MAME `pce_cd.cpp` are tier 5
detectors: where a behaviour comes only from them it is a class attribute below (a named switch)
with a U/C entry in docs/m8-record.md.

Registers (offsets from `$1800`):

| reg | write | read |
| --- | --- | --- |
| `$08/$09` | the 16-bit address latch (low / high) | (`$08` reads the CD data bus: the unit) |
| `$0A` | the byte for the write pointer, which then steps | the read buffer; next fetch starts |
| `$0B` | DMA control (bit 1 requests CD-to-ADPCM DMA; bit 0 follows a waiting block) | the same |
| `$0C` | -- | bit 7 read busy, bit 3 playing, bit 2 write busy, bit 0 end reached |
| `$0D` | control (below) | the last value written |
| `$0E` | rate: playback at 32 / (16 - n) kHz, n = value & $0F | the same |

Control `$0D`: bit 7 reset (pointers and length to zero, flags cleared, the read buffer is kept),
bit 6 stop at length zero (clear: keep playing), bit 5 play, bit 4 latch the length from the address
latch (a length of zero then means 64 KiB), bit 3 copy the latch to the read pointer on a rising
edge (bit 2 set: as it is; clear: one less, so the first read fetch lands on it), bit 1 the same for
the write pointer (bit 0). [hw: pcetech 8; mfr: the BIOS routines `ad_read_addr_set`,
`ad_write_addr_set`, `ad_length_set`]

Flags: the half flag (IRQ2 source `$04`, `$1803` bit 2) is set while less than half of the length is
left and the end flag (source `$08`, `$180C` bit 0) when the length has run out. [hw: pcetech 8
`$1803` bit 2; mfr: `AD_STAT` reads `$180C` bit 0 then `$1803` bit 2, and `$180C` bit 3 for busy]

Decoder (MSM5205, 4-bit): a 12-bit signal and a step index 0-48. A nibble is a sign bit and three
magnitude bits; the signal moves by `step/8 + step/4*b0 + step/2*b1 + step*b2` (integer divisions of
`step = floor(16 * 1.1 ** index)`), the index by -1 -1 -1 -1 +2 +4 +6 +8 clamped to 0..48. Each byte
holds two samples, the high nibble first. The audio is the signal held between samples
(`AdpcmSource`).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

MASTER_HZ = 21_477_272
ADPCM_RAM_BYTES = 64 * 1024
OUTPUT_HZ = 44_100

IRQ_HALF = 0x04
IRQ_END = 0x08

LENGTH_MASK = 0x1FFFF  # [emu: Mesen2, Geargrafx] 17 bits: a length of 64 KiB needs the 17th

INDEX_STEP = (-1, -1, -1, -1, 2, 4, 6, 8)


def _step_table() -> tuple[int, ...]:
    """`DELTA[index * 8 + magnitude]`, the signal change for a 3-bit magnitude [MSM5205 data sheet
    as modelled by MAME `msm5205.cpp`, Mednafen `okiadpcm.cpp`, Geargrafx: tier 3/5]."""
    steps = [int(16 * 1.1**index) for index in range(49)]
    return tuple(
        step // 8
        + (step // 4 if magnitude & 1 else 0)
        + (step // 2 if magnitude & 2 else 0)
        + (step if magnitude & 4 else 0)
        for step in steps
        for magnitude in range(8)
    )


DELTA = _step_table()


class Adpcm:
    """RAM, pointers, flags and the decoder. Time comes from the unit (`run(mclk)` and the
    `now` of each register access); the unit calls `run` for every event from `next_event`."""

    # -- switches: behaviours only tier 5 gives, or undecidable between sources (docs/m8-record.md)

    # Playback rate base: f = BASE_HZ / (16 - n). [hw: pcetech 8; mfr: BIOS manual AD_PLAY "fKHz=32/
    # (16-n)"] 32 kHz; Mednafen uses 32087.5 (a crystal-derived guess, tier 5).
    BASE_HZ: ClassVar[float] = 32_000.0
    # Master clocks until `$180C` bit 7 clears after a `$180A` read. [hw: pcetech 8: "about 24
    # cycles in high-speed mode"] 24 CPU cycles x 3. Mednafen: 57 clocks; Mesen2: a RAM slot model
    # (30 cycles minimum, 32 safe); 0 = immediate.
    READ_CLOCKS: ClassVar[int] = 24 * 3
    # The same for a `$180A` write (bit 2). [emu: Mesen2: 22 cycles minimum, 24 safe; Mednafen 33
    # clocks] pcetech: the BIOS polls bit 2 after each write, no time given.
    WRITE_CLOCKS: ClassVar[int] = 24 * 3
    # The 12-bit signal saturates at -2048..2047 (MAME's MSM5205 model) or wraps (Mesen2,
    # Geargrafx).
    SATURATE: ClassVar[bool] = True
    # 16-bit output per signal unit. 16 would be full scale; Mesen2 and Geargrafx use 10 (headroom
    # for the PSG and CD-DA). Tier 5.
    OUTPUT_SCALE: ClassVar[int] = 10
    # A write to RAM while the length is zero raises the end flag [emu: Mesen2, Geargrafx]; the
    # BIOS clears it with the length latch afterwards. Mednafen has no such rule.
    END_ON_WRITE_AT_ZERO: ClassVar[bool] = True

    def __init__(self, on_irq: Callable[[int, bool], None]) -> None:
        self._on_irq = on_irq
        self.ram = bytearray(ADPCM_RAM_BYTES)
        self.latch = 0
        self.read_ptr = self.write_ptr = 0
        self.read_buffer = 0
        self.control = 0
        self.dma = 0
        self.rate = 0
        self.length = 0
        self.half = self.end = False
        self.playing = False
        self.play_request = False
        self.high_nibble_next = True  # the next sample is the high nibble of the byte at read_ptr
        self.signal = 0
        self.index = 0
        self._read_due: int | None = None
        self._write_due: int | None = None
        self._write_value = 0
        self._sample_at = 0  # 16.16 fixed-point master clocks
        self.record = False  # the audio source wants (time, output) events
        self.events: list[tuple[int, int]] = []
        self._last_output = 0
        self.sample_count = 0  # decoded samples (statistics)
        self.end_count = 0  # times the end flag was raised (statistics)

    # -- state the unit reads -----------------------------------------------------------------

    @property
    def write_busy(self) -> bool:
        return self._write_due is not None

    @property
    def read_busy(self) -> bool:
        return self._read_due is not None

    @property
    def period_fixed(self) -> int:
        """Master clocks per sample, 16.16 fixed point."""
        return int(MASTER_HZ * 65536 * (16 - (self.rate & 0x0F)) / self.BASE_HZ)

    def reset(self) -> None:
        """Power-on and the `$180D` bit 7 reset (the latter keeps the read buffer)."""
        self.read_ptr = self.write_ptr = 0
        self.latch = 0
        self.length = 0
        self.high_nibble_next = True
        self.signal = 0
        self.index = 0
        self.play_request = False
        self._set_half(False)
        self._set_end(False)

    def power_on(self, at: int = 0) -> None:
        """Power-on at master clock `at` (the output goes idle then, issue 0001 item 3)."""
        self.reset()
        self.control = self.dma = self.rate = 0
        self.read_buffer = 0
        self.playing = False
        self._read_due = self._write_due = None
        self._output(at, 0)

    # -- flags --------------------------------------------------------------------------------

    def _set_half(self, value: bool) -> None:
        if self.half != value:
            self.half = value
            self._on_irq(IRQ_HALF, value)

    def _set_end(self, value: bool) -> None:
        if self.end != value:
            self.end = value
            self.end_count += value
            self._on_irq(IRQ_END, value)

    # -- registers ----------------------------------------------------------------------------

    def write(self, reg: int, value: int, now: int) -> None:
        if reg in (0x08, 0x09):
            if reg == 0x08:
                self.latch = (self.latch & 0xFF00) | value
            else:
                self.latch = (self.latch & 0x00FF) | (value << 8)
            if self.control & 0x10:  # the length latch follows the address while bit 4 is held
                self.length = self.latch
        elif reg == 0x0A:
            self._write_value = value
            self._write_due = now + self.WRITE_CLOCKS
            if self.WRITE_CLOCKS == 0:
                self._finish_write()
        elif reg == 0x0B:
            self.dma = value
        elif reg == 0x0D:
            self._write_control(value, now)
        elif reg == 0x0E:
            self.rate = value

    def read(self, reg: int, now: int) -> int:
        if reg == 0x0A:
            value = self.read_buffer
            self._read_due = now + self.READ_CLOCKS
            if self.READ_CLOCKS == 0:
                self._finish_read()
            return value
        if reg == 0x0B:
            return self.dma
        if reg == 0x0C:
            return (
                (0x01 if self.end else 0)
                | (0x04 if self.write_busy else 0)
                | (0x08 if self.playing else 0)
                | (0x80 if self.read_busy else 0)
            )
        if reg == 0x0D:
            return self.control
        if reg == 0x0E:
            return self.rate
        return 0

    def _write_control(self, value: int, now: int) -> None:
        old, self.control = self.control, value
        if value & 0x02 and not old & 0x02:
            self.write_ptr = (self.latch - (0 if value & 0x01 else 1)) & 0xFFFF
        if value & 0x08 and not old & 0x08:
            self.read_ptr = (self.latch - (0 if value & 0x04 else 1)) & 0xFFFF
        if value & 0x20 and not self.playing:
            if not self.play_request:
                self._sample_at = (now << 16) + self.period_fixed
            self.play_request = True
        if value & 0x10:
            self.length = self.latch
            self._set_end(False)
        if value & 0x80:
            self.reset()
            if not value & 0x20:
                self._stop(now)

    # -- RAM port operations --------------------------------------------------------------------

    def _finish_read(self) -> None:
        self._read_due = None
        self.read_buffer = self.ram[self.read_ptr]
        self.read_ptr = (self.read_ptr + 1) & 0xFFFF
        if not self.control & 0x10:
            if self.length > 0:
                self.length -= 1
                self._set_half(self.length < 0x8000)
            else:
                self._set_end(True)
                self._set_half(False)

    def _finish_write(self) -> None:
        self._write_due = None
        self.ram[self.write_ptr] = self._write_value
        self.write_ptr = (self.write_ptr + 1) & 0xFFFF
        if self.length == 0 and self.END_ON_WRITE_AT_ZERO:
            self._set_end(True)
        self._set_half(self.length < 0x8000)
        if not self.control & 0x10:
            self.length = (self.length + 1) & LENGTH_MASK

    def dma_write(self, value: int, now: int) -> bool:
        """One byte from the CD-to-ADPCM DMA, through the same write path as `$180A`.
        False if the previous write is still in progress (the DMA retries)."""
        if self.write_busy:
            return False
        self.write(0x0A, value, now)
        return True

    # -- time ---------------------------------------------------------------------------------

    def next_event(self) -> int | None:
        due = [t for t in (self._read_due, self._write_due) if t is not None]
        if self.playing or self.play_request:
            due.append(-(-self._sample_at // 65536))
        return min(due) if due else None

    def run(self, mclk: int) -> None:
        """Do every event due at or before `mclk`, in time order."""
        while True:
            at = self.next_event()
            if at is None or at > mclk:
                return
            if self._read_due is not None and self._read_due <= at:
                self._finish_read()
            if self._write_due is not None and self._write_due <= at:
                self._finish_write()
            if (self.playing or self.play_request) and -(-self._sample_at // 65536) <= at:
                self._play_sample(at)

    def _stop(self, at: int) -> None:
        self.playing = False
        self.play_request = False
        self._output(at, 0)

    def _output(self, at: int, value: int) -> None:
        """The decoder output changed at `at` (0 = the DAC is idle)."""
        if value != self._last_output:
            self._last_output = value
            if self.record:
                self.events.append((at, value))

    def _play_sample(self, at: int) -> None:
        control = self.control
        self._sample_at += self.period_fixed
        if control & 0x80:  # reset held: play follows bit 5 but nothing is fetched
            self.playing = bool(control & 0x20)
            self.play_request = False
            if not self.playing:
                self._output(at, 0)
            return
        if (control & 0x40 and self.length == 0) or not control & 0x20:
            self._stop(at)
            return
        if self.play_request:
            self.play_request = False
            self.playing = True
            self.signal = 0
            self.index = 0
        byte = self.ram[self.read_ptr]
        if self.high_nibble_next:
            nibble = byte >> 4
            self.high_nibble_next = False
        else:
            nibble = byte & 0x0F
            self.high_nibble_next = True
            self.read_ptr = (self.read_ptr + 1) & 0xFFFF
            self.length = (self.length - 1) & LENGTH_MASK
        delta = DELTA[self.index * 8 + (nibble & 7)]
        signal = self.signal + (-delta if nibble & 8 else delta)
        signal = (
            max(-2048, min(2047, signal)) if self.SATURATE else ((signal + 2048) & 0xFFF) - 2048
        )
        self.signal = signal
        self.index = max(0, min(48, self.index + INDEX_STEP[nibble & 7]))
        self.sample_count += 1
        self._set_half(self.length < 0x8000)
        if self.length == 0:
            self._set_end(True)
        self._output(at, signal * self.OUTPUT_SCALE)


class AdpcmSource:
    """The ADPCM audio for the board's mixer (socket 9): the decoder output held, sampled at
    44.1 kHz at exact master-clock times, with the `$180F` fader when it is aimed at ADPCM."""

    rate_hz = float(OUTPUT_HZ)
    gain = 1.0

    def __init__(self, unit) -> None:
        self.unit = unit
        self._origin: int | None = None
        self._taken = 0
        self._value = 0

    def take_samples(self, mclk: int) -> list[tuple[int, int]]:
        unit = self.unit
        if mclk > unit.mclk:
            unit.catch_up(mclk)
        adpcm = unit.adpcm
        if self._origin is None:
            self._origin = mclk
            adpcm.record = True
            adpcm.events.clear()
            self._value = adpcm._last_output
            return []
        total = (mclk - self._origin) * OUTPUT_HZ // MASTER_HZ
        events = adpcm.events
        used = 0
        out: list[tuple[int, int]] = []
        for n in range(self._taken, total):
            at = self._origin + -(-n * MASTER_HZ // OUTPUT_HZ)
            while used < len(events) and events[used][0] <= at:
                self._value = events[used][1]
                used += 1
            value = round(self._value * unit.cdda.fade_gain(at, adpcm=True))
            out.append((value, value))
        del events[:used]
        self._taken = total
        return out
