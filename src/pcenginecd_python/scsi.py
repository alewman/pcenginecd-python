"""The drive's SCSI-class controller: bus signals, phases, the REQ/ACK handshake, the commands.

The CD unit's controller is not emulated as a microcontroller (there is no second CPU on this
machine); it is a bus state machine that the System Card drives through `$1800-$1802` and
`$1808` [hw: pcetech 8; emu: Mesen2 `PceScsiBus.cpp`, Geargrafx `scsi_controller.cpp`, Mednafen
`scsicd.cpp`, ares `pcd/scsi.cpp`, MAME `pce_cd.cpp` all do the same]. Everything here is time in
**master clocks** (21.477272 MHz); the unit calls `run_to(mclk)` before every register access
and the bus then runs its own timers up to that instant.

Signals (`$1800` read): D3 I/O, D4 C/D, D5 MSG, D6 REQ, D7 BSY. Phases and the signals they hold:

| phase       | BSY | C/D | I/O | MSG | REQ | what the CPU does                      |
| ----------- | --- | --- | --- | --- | --- | -------------------------------------- |
| bus free    |     |     |     |     |     | writes `$1800` (selects the drive)     |
| command     |  1  |  1  |     |     |  1  | writes command bytes to `$1801`        |
| data in     |  1  |     |  1  |     | (1) | reads bytes from `$1801`/`$1808`       |
| status      |  1  |  1  |  1  |     | (1) | reads the status byte                  |
| message in  |  1  |  1  |  1  |  1  | (1) | reads the message byte                 |
| busy        |  1  |     |     |     |     | waits (an audio command in progress)   |

Every byte is a REQ/ACK handshake: the drive raises REQ, the CPU sets ACK (`$1802` bit 7), the
drive drops REQ, the CPU drops ACK. IRQ2 sources (`$1803` bits): data-in 0x40 and status/message
0x20 are REQ held in those phases (`CdUnit` turns the levels into IRQ2).

The timings are class attributes, all provisional (U8): the only measurements of this hardware
are Shadoff's seek table (`reference/src/pce-cd-seek`, tier 3) and the test ROMs Mesen2's author
ran on a real console (tier 5, claimed in his source comments).
"""

from __future__ import annotations

import enum
from collections import deque
from collections.abc import Callable

from pcenginecd_python.cdda import CddaPlayer
from pcenginecd_python.disc import (
    DATA_SECTOR,
    Disc,
    from_bcd,
    lba_to_msf,
    msf_to_lba,
    relative_msf,
    to_bcd,
)
from pcenginecd_python.seek import seek_time_ms

MASTER_HZ = 21_477_272


class Phase(enum.Enum):
    BUS_FREE = "bus free"
    COMMAND = "command"
    DATA_IN = "data in"
    MESSAGE_IN = "message in"
    STATUS = "status"
    BUSY = "busy"


class Update(enum.Enum):
    """What a queued drive timer does when it fires."""

    NONE = 0
    COMMAND_PHASE = 1
    REQ = 2
    DATA_IN_PHASE = 3
    GOOD_STATUS = 4


# SCSI status byte
GOOD = 0x00
CHECK_CONDITION = 0x02

# Commands the System Card issues [hw: pcetech 8]. REQUEST SENSE (0x03) is a standard SCSI-2
# command the BIOS sends after commands; Mesen2 does not implement it (it answers Good with no
# data), Mednafen sends an 18-byte fixed-format block (C14).
CMD_TEST_UNIT_READY = 0x00
CMD_REQUEST_SENSE = 0x03
CMD_READ = 0x08
CMD_AUDIO_START = 0xD8
CMD_AUDIO_END = 0xD9
CMD_PAUSE = 0xDA
CMD_READ_SUBQ = 0xDD
CMD_READ_TOC = 0xDE

COMMAND_LENGTH = {
    CMD_TEST_UNIT_READY: 6,
    CMD_REQUEST_SENSE: 6,
    CMD_READ: 6,
    CMD_AUDIO_START: 10,
    CMD_AUDIO_END: 10,
    CMD_PAUSE: 10,
    CMD_READ_SUBQ: 10,
    CMD_READ_TOC: 10,
}

# Sense keys / additional codes used (SCSI-2)
SENSE_NOT_READY = 0x02
SENSE_ILLEGAL_REQUEST = 0x05
ASC_MEDIUM_NOT_PRESENT = 0x3A
ASC_INVALID_COMMAND = 0x20
ASC_LBA_OUT_OF_RANGE = 0x21


class ScsiBus:
    """Signals, phase, timers and the command set. `irq` is called with (mask, level) when the
    REQ-held-in-a-phase conditions change (mask 0x40 data in, 0x20 status/message)."""

    # --- timing (master clocks), provisional; tier in the comment --------------------------
    # [emu: Mesen2, "approximations ... haven't been validated beyond what validator.pce checks"]
    # Mesen2 counts these in units of 3 master clocks (one fast CPU cycle); converted here.
    SEL_TO_COMMAND_PHASE = 25_000 * 3  # tier 5: SEL to the drive entering the command phase
    NEXT_COMMAND_BYTE_REQ = 1_000 * 3  # tier 5: REQ for the next command byte
    TEST_UNIT_READY = 150_000 * 3  # tier 5, deliberately ~100x shorter than the real spin-up
    TOC_ANSWER = 3_000 * 3  # tier 5
    SUBQ_ANSWER = 1_000 * 3  # tier 5
    DONE_STATUS = 1_000 * 3  # tier 5: last data byte taken to the good status
    ABORT_TO_COMMAND = 300_000 * 3  # tier 5: SEL during data in ("verificator.pce")
    ACK_CLEAR = 21  # tier 5: an auto-ack pulse ("hardware measurements show ~1 us")
    # [hw: Red Book] single speed: 75 sectors a second; one sector's bytes are delivered this
    # often (tier 2 for the rate, the delivery phase is U8).
    SECTOR_CLOCKS = MASTER_HZ * DATA_SECTOR // 153_600
    # [emu: Mesen2 comment, Sherlock Holmes] software that misses a sector waits for a re-read
    REREAD_PENALTY_MS = 290  # tier 5
    # The seek model is `seek.py` (Shadoff's measurements, tier 3 for the shape).
    SEEK_SCALE = 1.0
    # Bytes in the READ TOC answers for kinds 0 (first/last track), 1 (lead-out), 2 (a track).
    # Mednafen sends 2, 3, 4 ("returned data lengths on real PCE are not confirmed", its own
    # comment); Mesen2 sends 4, 4, 4 (C15). Tier 5 both; the BIOS must read the same number.
    TOC_ANSWER_BYTES = (2, 3, 4)

    def __init__(
        self,
        disc: Disc | None,
        cdda: CddaPlayer,
        irq: Callable[[int, bool], None],
    ) -> None:
        self.disc = disc
        self.cdda = cdda
        self._irq = irq
        cdda.disc = disc
        cdda.on_good_status = self.good_status
        self.now = 0
        self.log: list[tuple[int, str]] = []  # (mclk, text) of commands, for the tests and runs
        self.record_log = False
        self.reset()

    # -- state ---------------------------------------------------------------------------------

    def reset(self) -> None:
        self.bsy = self.sel = self.cd = self.io = self.msg = self.req = self.ack = False
        self.atn = False
        self.rst = False
        self.phase = Phase.BUS_FREE
        self.data_port = 0  # what the CPU wrote
        self.read_port = 0  # what the drive presents
        self.message_done = False
        self.sector = 0  # next LBA to deliver
        self.sectors_left = 0
        self.last_lba = 0  # where the head is (for seek times)
        self.cmd: list[int] = []
        self.out: deque[int] = deque()
        self._changed = False
        self._update = Update.NONE
        self._update_at: int | None = None
        self._read_at: int | None = None
        self._ack_at: int | None = None
        self.sense_key = 0
        self.sense_asc = 0
        self.cdda.stop()
        self._irq_levels = (False, False)
        self._update_irq()

    @property
    def status_bits(self) -> int:
        """`$1800` read: I/O D3, C/D D4, MSG D5, REQ D6, BSY D7 [emu: all]."""
        return (
            (0x08 if self.io else 0)
            | (0x10 if self.cd else 0)
            | (0x20 if self.msg else 0)
            | (0x40 if self.req else 0)
            | (0x80 if self.bsy else 0)
        )

    def current_lba(self) -> int:
        return self.cdda.position if self.cdda.active else self.last_lba

    # -- time ----------------------------------------------------------------------------------

    def next_event(self) -> int | None:
        times = [
            t
            for t in (self._update_at, self._read_at, self._ack_at, self.cdda.next_event())
            if t is not None
        ]
        return min(times) if times else None

    def run_to(self, mclk: int) -> None:
        """Fire every timer due at or before `mclk`, in time order."""
        while True:
            at = self.next_event()
            if at is None or at > mclk:
                break
            self.now = max(self.now, at)
            if self.cdda.next_event() == at:
                self.cdda.run_to(at)
            elif self._ack_at == at:
                self._ack_at = None
                self._set(ack=False)
            elif self._update_at == at:
                kind, self._update_at = self._update, None
                self._fire(kind)
            elif self._read_at == at:
                self._read_at = None
                self._sector_ready()
            self._settle()
        self.now = max(self.now, mclk)
        self.cdda.run_to(self.now)

    def _queue(self, kind: Update, delay: int) -> None:
        if kind is not self._update or self._update_at is None:
            self._update = kind
            self._update_at = self.now + delay

    def _fire(self, kind: Update) -> None:
        if kind is Update.COMMAND_PHASE:
            self._phase(Phase.COMMAND)
        elif kind is Update.REQ:
            self._set(req=True)
        elif kind is Update.DATA_IN_PHASE:
            self._phase(Phase.DATA_IN)
        elif kind is Update.GOOD_STATUS:
            self.good_status()

    # -- signals and phases ----------------------------------------------------------------------

    def _set(self, **signals: bool) -> None:
        for name, value in signals.items():
            if getattr(self, name) != value:
                setattr(self, name, value)
                self._changed = True
        self._update_irq()

    def _update_irq(self) -> None:
        held = self.req and self.io and self.bsy
        levels = (held and not self.cd, held and self.cd)  # (data in 0x40, status/message 0x20)
        if levels != self._irq_levels:
            for mask, old, new in zip((0x40, 0x20), self._irq_levels, levels, strict=True):
                if old != new:
                    self._irq(mask, new)
            self._irq_levels = levels

    def _phase(self, phase: Phase) -> None:
        if self.phase is phase:
            return
        self._update_at = None  # a phase change cancels a queued drive timer
        self._changed = True
        self.phase = phase
        self.bsy = self.cd = self.io = self.msg = self.req = False
        if phase is Phase.COMMAND:
            self._read_at = None  # leaving data in stops any pending sector
            self.sectors_left = 0
            self.bsy = self.cd = self.req = True
        elif phase is Phase.DATA_IN:
            self.bsy = self.io = True
        elif phase is Phase.MESSAGE_IN:
            self.bsy = self.cd = self.io = self.msg = self.req = True
        elif phase is Phase.STATUS:
            self.bsy = self.cd = self.io = self.req = True
        elif phase is Phase.BUSY:
            self.bsy = True
        self._update_irq()

    def status_message(self, status: int = GOOD, message: int = 0, length: int = 1) -> None:
        """Enter the status phase with `status`; `length` message bytes follow."""
        self.out = deque([message] * length)
        self.message_done = False
        self.read_port = status
        self._phase(Phase.STATUS)

    def good_status(self) -> None:
        self.status_message(GOOD)
        self._settle()

    # -- CPU side ------------------------------------------------------------------------------

    def select(self) -> None:
        """A write to `$1800`: SEL pulses. From any phase but data in this starts a command."""
        self.sel = True
        self._changed = True
        self._settle()
        self.sel = False
        self._changed = True
        self._settle()

    def write_data(self, value: int) -> None:
        self.data_port = value

    def read_data(self) -> int:
        if self.phase in (Phase.STATUS, Phase.DATA_IN, Phase.MESSAGE_IN):
            return self.read_port
        return self.data_port

    def set_ack(self, level: bool) -> None:
        self._set(ack=level)
        self._settle()

    def pulse_ack(self) -> None:
        """A `$1808` data read: ACK for a moment, so the next byte is presented without the
        CPU's own handshake [emu: Mesen2; the pulse width is its measurement]."""
        self._set(ack=True)
        self._ack_at = self.now + self.ACK_CLEAR
        self._settle()

    def set_reset(self, level: bool) -> None:
        """`$1804` bit 1: the SCSI RST line."""
        self.rst = level
        self._changed = True
        self._settle()

    # -- the state machine ---------------------------------------------------------------------

    def _settle(self) -> None:
        """Run the phase logic until the signals stop changing (Mesen2's `UpdateState`)."""
        while self._changed:
            self._changed = False
            if self.rst:
                self.reset()
                return
            if self.sel:
                self._update_at = None
                if self.phase is not Phase.DATA_IN:
                    self._queue(Update.COMMAND_PHASE, self.SEL_TO_COMMAND_PHASE)
                else:
                    # Aborting a transfer yields an 8-byte message, then the command phase comes
                    # back on its own [emu: Mesen2 from scsitest.pce, verificator.pce]
                    self.status_message(GOOD, 0, 8)
                    self._queue(Update.COMMAND_PHASE, self.ABORT_TO_COMMAND)
                    break
            elif self.phase is Phase.COMMAND:
                self._command_phase()
            elif self.phase is Phase.DATA_IN:
                self._data_in_phase()
            elif self.phase is Phase.STATUS:
                self._status_phase()
            elif self.phase is Phase.MESSAGE_IN:
                self._message_phase()

    def _handshake_done(self) -> bool:
        return not self.req and not self.ack

    def _command_phase(self) -> None:
        if self.req and self.ack:
            self._set(req=False)
            self.cmd.append(self.data_port)
        elif self._handshake_done() and self.cmd:
            length = COMMAND_LENGTH.get(self.cmd[0])
            if length is None:
                # An unknown command: Good, no data [emu: Mesen2]
                self.cmd.clear()
                self.status_message(GOOD)
            elif len(self.cmd) >= length:
                cmd, self.cmd = self.cmd, []
                self._execute(cmd)
            else:
                self._queue(Update.REQ, self.NEXT_COMMAND_BYTE_REQ)

    def _data_in_phase(self) -> None:
        if self.req and self.ack:
            self._set(req=False)
        elif self._handshake_done():
            if self.out:
                self.read_port = self.out.popleft()
                self._set(req=True)
            elif self.sectors_left == 0 and self._read_at is None:
                self._queue(Update.GOOD_STATUS, self.DONE_STATUS)

    def _status_phase(self) -> None:
        if self.req and self.ack:
            self._set(req=False)
        elif self._handshake_done() and self.out:
            self.read_port = self.out.popleft()
            if not self.out:
                self._phase(Phase.MESSAGE_IN)
            else:
                self._set(req=True)

    def _message_phase(self) -> None:
        if self.req and self.ack:
            self._set(req=False)
            self.message_done = True
        elif self._handshake_done() and self.message_done:
            self.message_done = False
            self._phase(Phase.BUS_FREE)

    # -- sector delivery -----------------------------------------------------------------------

    def _sector_ready(self) -> None:
        if self.out:
            # The program has not taken the last sector: the drive has to find it again.
            self._read_at = self.now + int(MASTER_HZ * self.REREAD_PENALTY_MS / 1000)
            return
        assert self.disc is not None
        self.out = deque(self.disc.read_data(self.sector))
        self.last_lba = self.sector
        self.sector = (self.sector + 1) & 0x1FFFFF
        self.sectors_left -= 1
        self._read_at = self.now + self.SECTOR_CLOCKS if self.sectors_left else None
        self._changed = True  # the data-in logic presents the first byte
        self._phase(Phase.DATA_IN)

    # -- the commands --------------------------------------------------------------------------

    def _note(self, text: str) -> None:
        if self.record_log:
            self.log.append((self.now, text))

    def _fail(self, key: int, asc: int) -> None:
        self.sense_key, self.sense_asc = key, asc
        self.status_message(CHECK_CONDITION)

    def _execute(self, cmd: list[int]) -> None:
        op = cmd[0]
        self._note("cmd " + " ".join(f"{b:02X}" for b in cmd))
        if self.disc is None and op not in (CMD_TEST_UNIT_READY, CMD_REQUEST_SENSE):
            self._fail(SENSE_NOT_READY, ASC_MEDIUM_NOT_PRESENT)
            return
        if op == CMD_TEST_UNIT_READY:
            if self.disc is None:
                self._fail(SENSE_NOT_READY, ASC_MEDIUM_NOT_PRESENT)
            else:
                self._queue(Update.GOOD_STATUS, self.TEST_UNIT_READY)
        elif op == CMD_REQUEST_SENSE:
            self._request_sense(cmd)
        elif op == CMD_READ:
            self._read(cmd)
        elif op == CMD_AUDIO_START:
            self._audio_start(cmd)
        elif op == CMD_AUDIO_END:
            self._audio_end(cmd)
        elif op == CMD_PAUSE:
            self.cdda.pause()
            self.status_message(GOOD)
        elif op == CMD_READ_SUBQ:
            self._read_subq()
        elif op == CMD_READ_TOC:
            self._read_toc(cmd)

    def _data_answer(self, data: list[int], delay: int) -> None:
        self.out = deque(data)
        self._queue(Update.DATA_IN_PHASE, delay)

    def _request_sense(self, cmd: list[int]) -> None:
        # Fixed-format sense data, SCSI-2: 0x70, segment, key, information[4], additional length,
        # command-specific[4], ASC, ASCQ, FRU, sense-key specific[3]. The allocation length is
        # cmd[4]; 0 means 4 bytes in SCSI-1 (C14: whether the drive honours it is unknown).
        block = [0x70, 0, self.sense_key, 0, 0, 0, 0, 10, 0, 0, 0, 0, self.sense_asc, 0, 0, 0, 0, 0]
        length = cmd[4] if cmd[4] else 4
        self.sense_key = self.sense_asc = 0
        self._data_answer(block[: min(length, len(block))], self.SUBQ_ANSWER)

    def _read(self, cmd: list[int]) -> None:
        lba = cmd[3] | (cmd[2] << 8) | ((cmd[1] & 0x1F) << 16)
        count = cmd[4]
        if count == 0:
            self.status_message(GOOD)
            return
        assert self.disc is not None
        if lba >= self.disc.sector_count:
            self._fail(SENSE_ILLEGAL_REQUEST, ASC_LBA_OUT_OF_RANGE)
            return
        self.sector, self.sectors_left = lba, count
        seek = self._clocks(seek_time_ms(self.current_lba(), lba) * self.SEEK_SCALE)
        self.cdda.idle()
        self.out.clear()
        self._read_at = self.now + seek + self.SECTOR_CLOCKS
        # The phase goes to data in at once: Ys IV expects it soon after the command
        # [emu: Mesen2 comment]. No REQ until the first sector is in the buffer.
        self._phase(Phase.DATA_IN)

    @staticmethod
    def _clocks(ms: float) -> int:
        return int(MASTER_HZ * ms / 1000)

    def _position(self, cmd: list[int]) -> int:
        """The audio command's address; the mode is cmd[9] bits 7-6 [hw: pcetech 8; emu]."""
        assert self.disc is not None
        mode = cmd[9] & 0xC0
        if mode == 0x00:  # LBA
            return (cmd[3] << 16) | (cmd[4] << 8) | cmd[5]
        if mode == 0x40:  # MSF in BCD (absolute)
            return msf_to_lba(from_bcd(cmd[2]), from_bcd(cmd[3]), from_bcd(cmd[4]))
        if mode == 0x80:  # track number in BCD
            track = self.disc.track(from_bcd(cmd[2]))
            return track.start if track else 0
        return 0

    def _audio_start(self, cmd: list[int]) -> None:
        assert self.disc is not None
        start = self._position(cmd)
        if start >= self.disc.sector_count:
            self.status_message(GOOD)
            return
        delay = self._clocks(seek_time_ms(self.current_lba(), start) * self.SEEK_SCALE)
        self.cdda.play(start, paused=cmd[1] == 0, seek_clocks=delay)
        # Busy until playback starts; the player ends it with good status
        self._phase(Phase.BUSY)

    def _audio_end(self, cmd: list[int]) -> None:
        end = self._position(cmd)
        mode = cmd[1]
        if mode == 0:
            self.cdda.stop()
        elif mode in (1, 2, 3):
            self.cdda.set_end(end, mode)
        if mode in (1, 2):
            self._phase(Phase.BUSY)  # in mode 2 until playback ends
        else:
            self.status_message(GOOD)

    def _read_subq(self) -> None:
        assert self.disc is not None
        lba = self.current_lba()
        track = self.disc.track_at(lba)
        number = track.number if track else 0
        is_data = bool(track and track.is_data)
        rel = relative_msf(lba - track.start) if track and lba >= track.start else (0, 0, 0)
        absolute = lba_to_msf(lba)
        data = [
            self.cdda.status_code,
            0x01 | (0x40 if is_data else 0),  # ADR 1 (position), control bit 6 = data track
            to_bcd(number),
            1,  # index
            *map(to_bcd, rel),
            *map(to_bcd, absolute),
        ]
        self._data_answer(data, self.SUBQ_ANSWER)

    def _read_toc(self, cmd: list[int]) -> None:
        assert self.disc is not None
        kind = cmd[1]
        if kind == 0:  # first and last track numbers
            data = [to_bcd(self.disc.first_track), to_bcd(self.disc.last_track), 0, 0]
        elif kind == 1:  # lead-out
            data = [*map(to_bcd, lba_to_msf(self.disc.end_lba)), 0]
        elif kind == 2:  # a track's start and type
            number = from_bcd(cmd[2]) or 1
            track = self.disc.track(number)
            if track is None:
                data = [*map(to_bcd, lba_to_msf(self.disc.end_lba)), 0]
            else:
                data = [*map(to_bcd, lba_to_msf(track.start)), 4 if track.is_data else 0]
        else:
            self.status_message(GOOD)
            return
        want = self.TOC_ANSWER_BYTES[kind]
        self._data_answer((data + [0] * 4)[:want], self.TOC_ANSWER)
