# SPDX-License-Identifier: MIT
"""The CD drive as the interface unit sees it: a SCSI-1 target on an 8-bit bus with REQ/ACK.

Written 2026-11-19 for the clean rewrite (docs/restart.md) from the sources below; the module it
replaces was withdrawn unread. Evidence tags as in the family's methodology; "closed box" means a
value measured from outside a GPL emulator run as a library (scripts/drive_probe.py: a probe
program of ours stands in for the System Card and counts 45-clock polling turns; Geargrafx
libretro 57c257d), never its source.

Sources, in the order they are trusted:

- [DOC: SCSI-1, X3.131-1986] the phases and their signals (MSG, C/D, I/O: command 010, data in 001,
  status 011, message in 111), the REQ/ACK handshake (the target raises REQ, the initiator raises
  ACK, the target drops REQ, the initiator drops ACK), selection (the initiator puts its id and the
  target's on the data bus and raises SEL, the target answers with BSY), the status byte (GOOD
  `$00`, CHECK CONDITION `$02`), COMMAND COMPLETE (`$00`), REQUEST SENSE (allocation length 0 means
  4 bytes), the group-0 six-byte command block, and bus free when BSY drops.
- [DOC: pcetech 8] the drive is "SCSI compatible" with TEST UNIT READY, REQUEST SENSE, READ and the
  vendor commands D8, D9, DA, DD, DE; data bytes arrive through `$1801` (handshake) or `$1808`.
- [DOC: Hudson BIOS manual, Hu7 CD System BIOS Ver1.00] CD_PLAY's end modes (0 "mute play" with
  status at once, 1 repeat, busy "until the next command issuance", 2 busy "until playback
  completion", 3 status at once), CD_SEARCH (the drive is busy during the search), CD_SUBQ's
  status byte (`$00` playing, `$01` still, `$02` pause, `$03` not playing) and its ten bytes,
  CD_DINFO's four kinds (track range, lead-out MSF, a track's MSF and control, a track's LBA and
  control).
- [DOC: the System Card 3.00 disassembly in the MiSTer repository's docs/ (a Hudson document)] how
  the BIOS drives the bus: `$81` then a write to `$1800` to select; the handshake at `$EC0B`
  (ACK up, wait for REQ to drop, ACK down); after the command it returns on `$1800 & $B8` = `$98`,
  `$88` or `$80`; if BSY is up when it wants to select, it selects anyway, puts `$FF` on the bus and
  takes every REQ until BSY drops; it reads a sector through `$1808` at one byte per 26-44 CPU
  cycles without looking at REQ, so the auto-ACK and the next REQ fit in 26 cycles (78 clocks).
- [OBSERVED, closed box: Geargrafx 57c257d] the response times below, the abort's eight status
  bytes, the re-read after a missed sector.
- [emulator tier, permissive: MAME `nec/pce_cd.cpp` (BSD-3-Clause, Wilbert Pol, Angelo Salese) and
  ares `pce/pcd/scsi.cpp` (ISC, ares team)] facts only, no code ported: the 10-byte vendor command
  blocks, READ TOC answer lengths 2/3/4 (MAME), the auto-ACK pulse of 15 CPU cycles (MAME), a READ
  of zero sectors answering GOOD (both), PAUSE without audio answering CHECK CONDITION (both), an
  unknown opcode answered at its first byte (ares).

Shape: one protocol step is pending at a time (`_step_at` and the name of what happens then,
`_step`), plus the sector clock of a READ (`_sector_at`) and the end of an auto-ACK pulse
(`_ack_off_at`). The CD-DA player's events run through `run_to` too, so `next_event` covers them.
"""

from __future__ import annotations

import enum
from collections.abc import Callable
from typing import ClassVar

from pcenginecd_python.cdda import CddaPlayer, EndMode
from pcenginecd_python.disc import Disc, from_bcd, lba_to_msf, msf_to_lba, to_bcd
from pcenginecd_python.seek import seek_time_ms

MASTER_HZ = 21_477_272

GOOD = 0x00
CHECK_CONDITION = 0x02  # [DOC: SCSI-1] status byte bit 1
COMMAND_COMPLETE = 0x00  # [DOC: SCSI-1] the message after the status

SENSE_NONE = 0x00
SENSE_NOT_READY = 0x02
SENSE_ILLEGAL_REQUEST = 0x05
ASC_INVALID_COMMAND = 0x20  # [DOC: SCSI-2 additional sense codes]
ASC_LBA_OUT_OF_RANGE = 0x21
ASC_SEQUENCE_ERROR = 0x2C
ASC_NO_MEDIUM = 0x3A

IRQ_STATUS_MESSAGE = 0x20  # the unit's active bits (unit.py): REQ in status or message in
IRQ_DATA_IN = 0x40  # REQ in data in

# Command block lengths [DOC: SCSI-1 group 0 = 6 bytes; the vendor commands are 10 bytes: the
# BIOS sends ten, MAME and ares take ten]. Any other opcode is answered at its first byte.
COMMAND_LENGTHS = {0x00: 6, 0x03: 6, 0x08: 6, 0xD8: 10, 0xD9: 10, 0xDA: 10, 0xDD: 10, 0xDE: 10}


class Phase(enum.Enum):
    BUS_FREE = "bus free"
    COMMAND = "command"
    DATA_IN = "data in"
    STATUS = "status"
    MESSAGE_IN = "message in"
    BUSY = "busy"  # BSY with no information phase: the drive is working (a seek, CD audio)


# (MSG, C/D, I/O) for each phase [DOC: SCSI-1 information transfer phases]
LINES = {
    Phase.BUS_FREE: (False, False, False),
    Phase.COMMAND: (False, True, False),
    Phase.DATA_IN: (False, False, True),
    Phase.STATUS: (False, True, True),
    Phase.MESSAGE_IN: (True, True, True),
    Phase.BUSY: (False, False, False),
}


def _clocks(window_low: int, window_high: int) -> int:
    """A closed-box window (low, high] in master clocks, as the middle multiple of 3 (one CPU
    cycle): the probe can say no more."""
    return (window_low + window_high) // 2 // 3 * 3


class ScsiBus:
    """The bus signals and the drive behind them. `now` is the drive's clock (master clocks)."""

    # -- timing, master clocks. Closed-box windows from scripts/drive_probe.py on Geargrafx
    #    57c257d (one turn = 45 clocks, first sample 84 clocks after the write that starts it).
    # SEL written to BSY, C/D and REQ of the command phase (BSY and REQ rise together)
    # [OBSERVED: closed box, (74,919, 74,964]]. The BIOS gives up after about 20 ms [DOC].
    SEL_TO_COMMAND_PHASE: ClassVar[int] = _clocks(74_919, 74_964)
    # ACK dropped after a command byte to REQ for the next one [OBSERVED: closed box,
    # (3,009, 3,054]]
    COMMAND_BYTE_CLOCKS: ClassVar[int] = _clocks(3_009, 3_054)
    # The last command byte's ACK dropped to the answer's first REQ [OBSERVED: closed box]:
    # TEST UNIT READY (449,544, 449,589], READ TOC (8,994, 9,039], READ SUBQ (3,009, 3,054].
    # The Hudson manual says a drive just reset takes "a few seconds" to become ready: not
    # modelled (the closed box answers TEST UNIT READY after a reset as quickly as ever).
    TEST_UNIT_READY: ClassVar[int] = _clocks(449_544, 449_589)
    TOC_CLOCKS: ClassVar[int] = _clocks(8_994, 9_039)
    SUBQ_CLOCKS: ClassVar[int] = _clocks(3_009, 3_054)
    # Everything else that answers at once (REQUEST SENSE, PAUSE, AUDIO END modes 0 and 3, an
    # error): [HYPOTHESIS] the quickest answer the closed box shows, READ SUBQ's.
    QUICK_ANSWER: ClassVar[int] = _clocks(3_009, 3_054)
    # An opcode the drive does not know: [OBSERVED: closed box] Geargrafx, which has no REQUEST
    # SENSE, answers that opcode with GOOD after (450,534, 450,579]; taken as its unknown-opcode
    # time, provisional.
    UNKNOWN_COMMAND_CLOCKS: ClassVar[int] = _clocks(450_534, 450_579)
    # Last data byte's ACK dropped to the status REQ [OBSERVED: closed box, (3,009, 3,054]]
    DATA_TO_STATUS: ClassVar[int] = _clocks(3_009, 3_054)
    # Status byte's ACK dropped to the message REQ, and the message's to BSY dropping (bus free)
    # [OBSERVED: closed box, both (1,479, 1,524]]
    STATUS_TO_MESSAGE: ClassVar[int] = _clocks(1_479, 1_524)
    MESSAGE_TO_FREE: ClassVar[int] = _clocks(1_479, 1_524)
    # In data in, REQ for the next byte comes as ACK drops [OBSERVED: closed box, within the
    # first sample]; REQ drops as ACK rises, in every phase [DOC: SCSI-1; closed box likewise].
    # A read of `$1808` pulses ACK for 15 CPU cycles [emulator tier: MAME, BSD-3]; the closed box
    # shows ACK low again within (15, 45] clocks of the read, and the BIOS needs it within 78.
    AUTO_ACK_CLOCKS: ClassVar[int] = 45
    # What Shadoff's seek times include besides the drive's seek: his test (seektest2_huc/seek2.c)
    # times the whole BIOS CD_READ of one sector, so its numbers also hold the selection and the
    # six command bytes (about 92,000 clocks at the times above), the BIOS reading 2,048 bytes
    # through `$1808` at 38 CPU cycles a byte (233,472) and the status and message (about 7,000).
    # The first sector's REQ comes this much before his time. [DOC: his test program; the sum is
    # this model's own times, so provisional]
    SEEK_MEASUREMENT_EXTRA: ClassVar[int] = 332_000
    # One sector at single speed [DOC: Red Book, 75 sectors a second]
    SECTOR_CLOCKS: ClassVar[int] = MASTER_HZ // 75
    # A sector that comes round while the last one is still in the buffer is missed; the drive
    # delivers it this long after its turn [OBSERVED: closed box, 6.22 M clocks = 290 ms after
    # the missed turn, the same whether the stall was 0.3 or 1.6 sector times].
    REREAD_PENALTY_MS: ClassVar[int] = 290
    # SEL while the drive sends data (or waits to): it stops and offers this many status bytes,
    # GOOD, then the message and bus free [OBSERVED: closed box, eight `$D8` REQs carrying `$00`,
    # then `$F8`, both when the data had started and while the READ still sought].
    ABORT_STATUS_BYTES: ClassVar[int] = 8
    # An unknown opcode: GOOD (closed box; MAME's table has no entry for one) or CHECK
    # CONDITION with ILLEGAL REQUEST / INVALID COMMAND (SCSI's rule; ares answers CHECK
    # CONDITION). Decision C22: GOOD.
    UNKNOWN_COMMAND_CHECK_CONDITION: ClassVar[bool] = False

    def __init__(
        self, disc: Disc | None, cdda: CddaPlayer, irq: Callable[[int, bool], None]
    ) -> None:
        self.disc = disc
        self.cdda = cdda
        self._irq = irq
        self._irq_levels = (False, False)  # (data in, status/message) as last reported
        self.rst = False  # the reset line, as `$1804` bit 1 holds it
        self.record_log = False
        self.log: list[tuple[int, str]] = []
        self.now = 0
        self.reset()

    # -- the lines ------------------------------------------------------------------------------

    @property
    def bsy(self) -> bool:
        return self.phase is not Phase.BUS_FREE

    @property
    def msg(self) -> bool:
        return LINES[self.phase][0]

    @property
    def cd(self) -> bool:
        return LINES[self.phase][1]

    @property
    def io(self) -> bool:
        return LINES[self.phase][2]

    @property
    def status_bits(self) -> int:
        """`$1800`: D3 I/O, D4 C/D, D5 MSG, D6 REQ, D7 BSY [DOC: pcetech 8, the BIOS's masks]."""
        msg, cd, io = LINES[self.phase]
        return (
            (0x80 if self.phase is not Phase.BUS_FREE else 0)
            | (0x40 if self.req else 0)
            | (0x20 if msg else 0)
            | (0x10 if cd else 0)
            | (0x08 if io else 0)
        )

    @property
    def out(self) -> bytes:
        """The data-in bytes of the current block not yet taken (the one on the bus first)."""
        return bytes(self._block[self._taken :])

    @property
    def data_waiting(self) -> int:
        """How many data-in bytes of the current block are not yet taken."""
        return len(self._block) - self._taken

    def read_data(self) -> int:
        """The data bus: the target drives it while I/O is up (data in, status, message in),
        the initiator otherwise [DOC: SCSI-1, I/O gives the direction; OBSERVED: closed box, the
        abort's status bytes read `$00` after the BIOS-style `$FF` write]."""
        return self.data if self.io else self.initiator_data

    def write_data(self, value: int) -> None:
        """`$1801` written: what the initiator drives (a command byte, or the BIOS's ids)."""
        self.initiator_data = value & 0xFF

    # -- reset ----------------------------------------------------------------------------------

    def reset(self) -> None:
        """The drive's own reset (power-on, or RST): bus free, nothing pending, audio stopped
        (MAME and ares stop CD audio on the drive's reset: emulator tier)."""
        self.phase = Phase.BUS_FREE
        self.req = False
        self.ack = False
        self._took = False  # a byte changed hands during the present ACK
        self.data = 0  # what the target drives
        self.initiator_data = 0  # what the CPU last wrote to `$1801`
        self.cdb = bytearray()
        self._step: str | None = None
        self._step_at: int | None = None
        self._ack_off_at: int | None = None
        self._selecting = False
        self._block = bytearray()
        self._taken = 0
        self._read_next = 0  # the next LBA a READ delivers
        self._read_left = 0  # sectors still to deliver
        self._sector_at: int | None = None
        self._status = GOOD
        self._status_left = 0
        self._audio_wait = False  # BUSY until the CD-DA player reports (AUDIO START, END mode 2)
        self.head = 0  # the LBA under the head when no audio plays
        self.sense_key = SENSE_NONE
        self.sense_asc = 0
        self.cdda.stop()
        self._update_irq()

    def set_reset(self, level: bool) -> None:
        """`$1804` bit 1: the drive is reset while the line is held [DOC: pcetech 8 (it names
        bit 2, the BIOS's CD_RESET sets and clears bit 1, `$02`)]."""
        self.rst = level
        if level:
            self.reset()

    # -- the initiator's side --------------------------------------------------------------------

    def select(self) -> None:
        """A write to `$1800`: SEL, with whatever the CPU left on the data bus (the BIOS: `$81`)."""
        if self.rst or self._selecting:
            return
        if self.phase is Phase.BUS_FREE or self.phase is Phase.BUSY:
            # A busy drive (CD audio, a seek) takes a new selection as from bus free [OBSERVED:
            # closed box, AUDIO END modes 1 and 2: BSY stays up, the command phase comes after
            # the usual time]; what it was waiting for is dropped (the audio plays on).
            self._audio_wait = False
            self._selecting = True
            self._schedule("command_phase", self.now + self.SEL_TO_COMMAND_PHASE)
        elif self.phase is Phase.DATA_IN:
            self._abort()
        # In the command, status or message phase SEL is ignored [HYPOTHESIS: no source; the BIOS
        # only selects a busy drive between handshakes it has finished].

    def set_ack(self, level: bool) -> None:
        """`$1802` bit 7: the CPU's ACK."""
        self._ack_off_at = None
        if level and not self.ack:
            self.ack = True
            self._ack_rises()
        elif not level and self.ack:
            self.ack = False
            self._ack_falls()

    def pulse_ack(self) -> None:
        """A read of `$1808` in data in: ACK up for AUTO_ACK_CLOCKS, then down."""
        if self.ack:
            return
        self.ack = True
        self._ack_rises()
        self._ack_off_at = self.now + self.AUTO_ACK_CLOCKS

    def _ack_rises(self) -> None:
        """The target takes the byte (or sees its own taken) and drops REQ [DOC: SCSI-1]."""
        if not self.req:
            self._took = False
            return
        self.req = False
        self._took = True
        if self.phase is Phase.COMMAND:
            self.cdb.append(self.initiator_data)
        elif self.phase is Phase.DATA_IN:
            self._taken += 1
        elif self.phase is Phase.STATUS:
            self._status_left -= 1
        self._update_irq()

    def _ack_falls(self) -> None:
        if not self._took:
            if self.phase is Phase.DATA_IN and self._taken < len(self._block):
                self._offer_data()  # a sector that arrived while ACK was held
            return
        self._took = False
        phase = self.phase
        if phase is Phase.COMMAND:
            want = COMMAND_LENGTHS.get(self.cdb[0], 1)
            if len(self.cdb) < want:
                self._schedule("command_req", self.now + self.COMMAND_BYTE_CLOCKS)
            else:
                self._execute()
        elif phase is Phase.DATA_IN:
            if self._taken < len(self._block):
                self._offer_data()
            elif self._read_left == 0:
                self._schedule("status_phase", self.now + self.DATA_TO_STATUS)
            # else: the next sector raises REQ when it arrives
        elif phase is Phase.STATUS:
            if self._status_left > 0:
                self.req = True  # the abort's further status bytes [HYPOTHESIS: at once]
                self._update_irq()
            else:
                self._schedule("message_phase", self.now + self.STATUS_TO_MESSAGE)
        elif phase is Phase.MESSAGE_IN:
            self._schedule("bus_free", self.now + self.MESSAGE_TO_FREE)

    def good_status(self) -> None:
        """The CD-DA player's report: a seek ended (AUDIO START), or the range ended in IRQ
        mode (AUDIO END mode 2). The drive answers the command it was busy with."""
        if self._audio_wait and self.phase is Phase.BUSY:
            self._audio_wait = False
            self._enter_status(GOOD)

    # -- time -----------------------------------------------------------------------------------

    def next_event(self) -> int | None:
        times = [
            t
            for t in (self._step_at, self._sector_at, self._ack_off_at, self.cdda.next_event())
            if t is not None
        ]
        return min(times) if times else None

    def run_to(self, mclk: int) -> None:
        """Do everything that falls due up to `mclk`, in time order, then stand at `mclk`."""
        while True:
            at = self.next_event()
            if at is None or at > mclk:
                break
            self.now = max(self.now, at)
            if self._ack_off_at is not None and self._ack_off_at <= at:
                self._ack_off_at = None
                self.ack = False
                self._ack_falls()
            elif self._step_at is not None and self._step_at <= at:
                step, self._step, self._step_at = self._step, None, None
                getattr(self, "_" + step)()
            elif self._sector_at is not None and self._sector_at <= at:
                self._sector_at = None
                self._sector_turn(at)
            else:
                self.cdda.run_to(at)
        self.now = max(self.now, mclk)
        self.cdda.run_to(self.now)

    def _schedule(self, step: str, at: int) -> None:
        self._step, self._step_at = step, at

    # -- protocol steps ---------------------------------------------------------------------------

    def _command_phase(self) -> None:
        """The selection answered: BSY, C/D and REQ for the first command byte."""
        self._selecting = False
        self.phase = Phase.COMMAND
        self.cdb = bytearray()
        self.req = True
        self._update_irq()

    def _command_req(self) -> None:
        self.req = True
        self._update_irq()

    def _status_phase(self) -> None:
        self._enter_status(self._status)

    def _message_phase(self) -> None:
        self.phase = Phase.MESSAGE_IN
        self.data = COMMAND_COMPLETE
        self.req = True
        self._update_irq()

    def _bus_free(self) -> None:
        self.phase = Phase.BUS_FREE
        self.req = False
        self._update_irq()

    def _answer(self) -> None:
        """An answer's data (READ TOC, READ SUBQ, REQUEST SENSE) or, with none, its status."""
        if self._block:
            self.phase = Phase.DATA_IN
            self._offer_data()
        else:
            self._enter_status(self._status)

    def _enter_status(self, status: int, count: int = 1) -> None:
        self.phase = Phase.STATUS
        self._status = status
        self._status_left = count
        self.data = status
        self.req = True
        self._update_irq()

    def _offer_data(self) -> None:
        if self.ack:
            return  # REQ waits for ACK to drop
        self.data = self._block[self._taken]
        self.req = True
        self._update_irq()

    def _abort(self) -> None:
        """SEL during data in: the read stops at once and the status phase offers
        ABORT_STATUS_BYTES bytes of GOOD [OBSERVED: closed box]; the BIOS takes them all."""
        self._read_left = 0
        self._sector_at = None
        self._block = bytearray()
        self._taken = 0
        self._step, self._step_at = None, None
        self._enter_status(GOOD, self.ABORT_STATUS_BYTES)

    # -- commands -------------------------------------------------------------------------------

    def _execute(self) -> None:
        cdb = bytes(self.cdb)
        if self.record_log:
            self.log.append((self.now, "cmd " + " ".join(f"{b:02X}" for b in cdb)))
        self.cdda.run_to(self.now)
        self._block = bytearray()
        self._taken = 0
        self._status = GOOD
        handler = {
            0x00: self._test_unit_ready,
            0x03: self._request_sense,
            0x08: self._read,
            0xD8: self._audio_start,
            0xD9: self._audio_end,
            0xDA: self._audio_pause,
            0xDD: self._read_subq,
            0xDE: self._read_toc,
        }.get(cdb[0])
        if handler is None:
            if self.UNKNOWN_COMMAND_CHECK_CONDITION:
                self._fail(SENSE_ILLEGAL_REQUEST, ASC_INVALID_COMMAND)
            else:
                self._reply(GOOD, self.UNKNOWN_COMMAND_CLOCKS)
            return
        if cdb[0] != 0x03 and self.disc is None:
            self._fail(SENSE_NOT_READY, ASC_NO_MEDIUM)
            return
        handler(cdb)

    def _reply(self, status: int, after: int, data: bytes = b"") -> None:
        """Answer `after` clocks from now: the data (if any), then the status."""
        self._status = status
        self._block = bytearray(data)
        self._taken = 0
        self.phase = Phase.DATA_IN if data else Phase.BUSY
        self.req = False
        self._update_irq()
        self._schedule("answer", self.now + after)

    def _fail(self, key: int, asc: int) -> None:
        self.sense_key, self.sense_asc = key, asc
        self._reply(CHECK_CONDITION, self.QUICK_ANSWER)

    def _test_unit_ready(self, cdb: bytes) -> None:
        self._reply(GOOD, self.TEST_UNIT_READY)

    def _request_sense(self, cdb: bytes) -> None:
        """Extended sense, 18 bytes [DOC: SCSI-1 extended sense format `$70`]; allocation length
        0 means 4 [DOC: SCSI-1]. The sense is cleared once reported."""
        sense = bytearray(18)
        sense[0] = 0x70
        sense[2] = self.sense_key
        sense[7] = 10  # additional sense length
        sense[12] = self.sense_asc
        length = cdb[4] or 4
        self.sense_key, self.sense_asc = SENSE_NONE, 0
        self._reply(GOOD, self.QUICK_ANSWER, bytes(sense[:length]))

    def _position(self) -> int:
        return self.cdda.position if self.cdda.active else self.head

    def _seek_clocks(self, target: int) -> int:
        """Shadoff's measured seek time (seek.py, tier 3) in master clocks."""
        return round(seek_time_ms(self._position(), target) * MASTER_HZ / 1000)

    def _read(self, cdb: bytes) -> None:
        """READ(6): a 21-bit LBA and a count of 2048-byte sectors [DOC: SCSI-1, pcetech 8]."""
        assert self.disc is not None
        lba = (cdb[1] & 0x1F) << 16 | cdb[2] << 8 | cdb[3]
        count = cdb[4]
        if count == 0:
            # [emulator tier: MAME, ares] nothing is read and the answer is GOOD; SCSI-1 reads 256
            # sectors for a count of 0 (decision C18 stands: provisional).
            self._reply(GOOD, self.QUICK_ANSWER)
            return
        if lba + count > self.disc.sector_count:
            self._fail(SENSE_ILLEGAL_REQUEST, ASC_LBA_OUT_OF_RANGE)
            return
        seek = max(self._seek_clocks(lba) - self.SEEK_MEASUREMENT_EXTRA, self.SECTOR_CLOCKS)
        self.cdda.idle()  # a data read takes the head: CD audio stops [emulator tier: MAME]
        self._read_next, self._read_left = lba, count
        self.phase = Phase.DATA_IN  # I/O up, REQ waits for the sector [OBSERVED: closed box `$88`]
        self.req = False
        self._update_irq()
        self._sector_at = self.now + seek

    def _sector_turn(self, at: int) -> None:
        """A sector of the READ comes under the head."""
        if self._taken < len(self._block):
            # missed: the buffer still holds the last one [OBSERVED: closed box]
            self._sector_at = at + MASTER_HZ * self.REREAD_PENALTY_MS // 1000
            return
        assert self.disc is not None
        lba = self._read_next
        self._block = bytearray(self.disc.read_data(lba))
        self._taken = 0
        self._read_next += 1
        self._read_left -= 1
        self.head = self._read_next
        if self._read_left:
            self._sector_at = at + self.SECTOR_CLOCKS
        self._offer_data()

    def _address(self, cdb: bytes) -> int | None:
        """The LBA a D8/D9 command names: byte 9 bits 7-6 = 00 LBA (bytes 3-5), 01 absolute MSF
        in BCD (bytes 2-4), 10 a track number in BCD (byte 2) [DOC: Hudson BIOS manual CD_PLAY's
        address types; the byte positions as the BIOS fills them]."""
        assert self.disc is not None
        kind = cdb[9] & 0xC0
        if kind == 0x00:
            lba = cdb[3] << 16 | cdb[4] << 8 | cdb[5]
        elif kind == 0x40:
            lba = msf_to_lba(from_bcd(cdb[2]), from_bcd(cdb[3]), from_bcd(cdb[4]))
        elif kind == 0x80:
            track = self.disc.track(from_bcd(cdb[2]))
            if track is None:
                return None
            lba = track.start
        else:
            return None
        return lba if 0 <= lba < self.disc.sector_count else None

    def _audio_start(self, cdb: bytes) -> None:
        """D8: seek to the start, then play (byte 1 bit 0) or pause there. BUSY until the seek
        ends, then GOOD [DOC: Hudson BIOS manual CD_SEARCH; OBSERVED: closed box]."""
        start = self._address(cdb)
        if start is None:
            self._fail(SENSE_ILLEGAL_REQUEST, ASC_LBA_OUT_OF_RANGE)
            return
        self.cdda.play(start, paused=not cdb[1] & 0x01, seek_clocks=self._seek_clocks(start))
        self._busy_until_audio()

    def _audio_end(self, cdb: bytes) -> None:
        """D9: where playing stops, and how (byte 1 bits 1-0) [DOC: Hudson BIOS manual CD_PLAY]:
        0 stop (the manual: "mute play", status at once; MAME and ares stop), 1 repeat and stay
        busy until the next selection, 2 play and stay busy until the range ends, 3 play with
        the status at once. A track number names the end of the track before it."""
        assert self.disc is not None
        mode = cdb[1] & 0x03
        end = self._address(cdb)
        if (cdb[9] & 0xC0) == 0x80 and end is not None:
            end -= 1
        if end is None:
            self._fail(SENSE_ILLEGAL_REQUEST, ASC_LBA_OUT_OF_RANGE)
            return
        if mode == 0:
            self.cdda.stop()
            self._reply(GOOD, self.QUICK_ANSWER)
            return
        if mode == 1 and end < self.cdda.start:
            # A repeat of an empty range plays nothing [emulator tier: MAME's note that an end
            # before the start plays nothing "according to real HW refs"]; the drive stays busy
            # as for any repeat [DOC; OBSERVED: closed box, BSY alone for 11 s].
            self.cdda.stop()
        else:
            self.cdda.set_end(end, {1: EndMode.LOOP, 2: EndMode.IRQ, 3: EndMode.STOP}[mode])
        if mode == 1:
            self.phase = Phase.BUSY  # until the next selection [DOC; OBSERVED: closed box]
            self.req = False
            self._update_irq()
        elif mode == 2:
            self._busy_until_audio()
        else:
            self._reply(GOOD, self.QUICK_ANSWER)

    def _busy_until_audio(self) -> None:
        self.phase = Phase.BUSY
        self.req = False
        self._audio_wait = True
        self._update_irq()

    def _audio_pause(self, cdb: bytes) -> None:
        """DA: pause [DOC: Hudson BIOS manual CD_PAUSE]; with no audio started, CHECK CONDITION
        [emulator tier: MAME, ares] (the sense code is a choice: SCSI-2's sequence error)."""
        if not self.cdda.active:
            self._fail(SENSE_ILLEGAL_REQUEST, ASC_SEQUENCE_ERROR)
            return
        self.cdda.pause()
        self._reply(GOOD, self.QUICK_ANSWER)

    def _read_subq(self, cdb: bytes) -> None:
        """DD: ten bytes [DOC: Hudson BIOS manual CD_SUBQ]: play status, control/ADR, track,
        index, the track-relative MSF and the absolute MSF, all BCD."""
        assert self.disc is not None
        lba = self._position()
        track = self.disc.track_at(lba)
        control = 0x04 if track is not None and track.is_data else 0x00
        number = track.number if track is not None else 0
        index = 1 if track is not None and lba >= track.start else 0
        relative = abs(lba - track.start) if track is not None else 0
        rm, rs, rf = relative // 4500, (relative // 75) % 60, relative % 75
        am, as_, af = lba_to_msf(lba)
        data = bytes(
            [self.cdda.status_code, control << 4 | 0x01, to_bcd(number), to_bcd(index)]
            + [to_bcd(v) for v in (rm, rs, rf, am, as_, af)]
        )
        self._reply(GOOD, self.SUBQ_CLOCKS, data)

    def _read_toc(self, cdb: bytes) -> None:
        """DE [DOC: Hudson BIOS manual CD_DINFO's kinds]: 0 first and last track (BCD), 1 the
        lead-out's absolute MSF, 2 a track's absolute MSF and its control (`$04` data, `$00`
        audio), 3 a track's LBA and control. Answer lengths 2, 3, 4, 4 [emulator tier: MAME for
        0-2 (the closed box sends 4 each); kind 3 from ares]."""
        assert self.disc is not None
        disc, kind = self.disc, cdb[1]
        if kind == 0:
            data = bytes([to_bcd(disc.first_track), to_bcd(disc.last_track)])
        elif kind == 1:
            data = bytes(to_bcd(v) for v in lba_to_msf(disc.sector_count))
        elif kind in (2, 3):
            if cdb[2] == 0xAA:  # the lead-out as a track [emulator tier: MAME]
                lba, control = disc.sector_count, 0x04
            else:
                track = disc.track(from_bcd(cdb[2]))
                if track is None:
                    self._fail(SENSE_ILLEGAL_REQUEST, ASC_LBA_OUT_OF_RANGE)
                    return
                lba, control = track.start, 0x04 if track.is_data else 0x00
            if kind == 2:
                data = bytes([*(to_bcd(v) for v in lba_to_msf(lba)), control])
            else:
                data = bytes([lba >> 16 & 0xFF, lba >> 8 & 0xFF, lba & 0xFF, control])
        else:
            self._fail(SENSE_ILLEGAL_REQUEST, ASC_INVALID_COMMAND)
            return
        self._reply(GOOD, self.TOC_CLOCKS, data)

    # -- IRQ2 levels ----------------------------------------------------------------------------

    def _update_irq(self) -> None:
        """Report each level that changed: data in (`$40`) is REQ in data in, status/message
        (`$20`) is REQ in status or message in [DOC: the BIOS's IRQ2 handler reads the status
        and message on `$20` and starts the ADPCM DMA on `$40`; pcetech 8]."""
        data_in = self.req and self.phase is Phase.DATA_IN
        status = self.req and self.phase in (Phase.STATUS, Phase.MESSAGE_IN)
        old_data, old_status = self._irq_levels
        self._irq_levels = (data_in, status)
        if data_in != old_data:
            self._irq(IRQ_DATA_IN, data_in)
        if status != old_status:
            self._irq(IRQ_STATUS_MESSAGE, status)
