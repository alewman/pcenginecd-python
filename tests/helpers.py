"""A host that talks to the CD unit the way the System Card does (handshakes through
`$1800-$1802`, `$1801`/`$1808`), and a scripted CPU for the board-level tests."""

from __future__ import annotations

from pcenginecd_python.unit import CdUnit

REG = 0x1FF800


class Host:
    """Register-level driver with its own master clock."""

    def __init__(self, unit: CdUnit) -> None:
        self.unit = unit
        self.t = 0

    def r(self, reg: int) -> int:
        self.t += 12
        return self.unit.read(REG + reg, self.t)

    def w(self, reg: int, value: int) -> None:
        self.t += 12
        self.unit.write(REG + reg, value, self.t)

    def advance(self, clocks: int) -> None:
        self.t += clocks
        self.unit.catch_up(self.t)

    def status(self) -> int:
        return self.r(0) & 0xF8

    def wait(self, want: int, mask: int = 0xF8, limit: int = 400_000_000, step: int = 3000) -> int:
        """Advance until `$1800 & mask == want`; returns the clocks waited."""
        start = self.t
        while self.r(0) & mask != want:
            self.advance(step)
            assert self.t - start < limit, f"timeout waiting for {want:02X}, now {self.r(0):02X}"
        return self.t - start

    def handshake(self) -> None:
        """ACK up, REQ drops, ACK down (the BIOS's $EC0B shape)."""
        self.w(2, 0x80 | self.unit.enable)
        self.wait(0, 0x40)
        self.w(2, self.unit.enable)

    def select(self) -> None:
        self.w(0, 0)

    def command(self, cmd: list[int]) -> None:
        self.select()
        self.wait(0xD0)  # BSY CD REQ, no I/O: command phase
        for i, byte in enumerate(cmd):
            self.w(1, byte)
            self.handshake()
            if i + 1 < len(cmd):
                self.wait(0xD0)

    def read_data_bytes(self, count: int, via: int = 1) -> list[int]:
        """Take `count` bytes in data-in (REQ + I/O, no C/D); `via` is the register."""
        out = []
        for _ in range(count):
            self.wait(0xC8)
            out.append(self.r(via))
            if via == 1:
                self.handshake()
            else:
                self.advance(60)  # the auto-ack pulse (21 clocks) drops REQ and raises it again
        return out

    def finish(self) -> tuple[int, int]:
        """Take the status byte and the message byte; the bus ends free."""
        self.wait(0xD8)
        status = self.r(1)
        self.handshake()
        self.wait(0xF8)
        message = self.r(1)
        self.handshake()
        self.wait(0, 0xF8)
        return status, message

    def run(self, cmd: list[int], count: int = 0, via: int = 1):
        self.command(cmd)
        data = self.read_data_bytes(count, via) if count else []
        return data, self.finish()


class ScriptedCpu:
    """One bus callback per CPU cycle, as the core makes them."""

    def __init__(self, board, *, high_speed: bool = False) -> None:
        self.board = board
        self.high_speed = high_speed
        self.irq_disable = 0
        self.lines = (False, False, False)
        board.attach_cpu(self)

    def set_irq_lines(self, irq1: bool, irq2: bool, tiq: bool) -> None:
        self.lines = (irq1, irq2, tiq)

    def read(self, address: int) -> int:
        return self.board.read_byte(address)

    def write(self, address: int, value: int) -> None:
        self.board.write_byte(address, value)

    def idle(self, cycles: int = 1) -> None:
        for _ in range(cycles):
            self.board.idle(None)
