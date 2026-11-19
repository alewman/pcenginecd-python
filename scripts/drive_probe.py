#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Measure the CD drive's bus timing from the CPU's side, on any machine that runs a System Card.

    python3 -I scripts/drive_probe.py --core CORE_libretro.so --out DIR   # a libretro core
    .venv-pypy/bin/python scripts/drive_probe.py --ours --out DIR          # this add-on

The probe is a small HuC6280 program written here (assembled by this script, nothing of any BIOS or
emulator in it) that stands in for the System Card: it drives the drive through `$1800-$1808` the way
the Hudson BIOS does (initiator id `$81` on the data bus, SEL by a write to `$1800`, the REQ/ACK
handshake through `$1802` bit 7) and counts polling-loop turns between the bus events, then leaves
the counts in work RAM (`$2200-`), which the host reads after the run. One loop turn is 15 CPU
cycles at 7.16 MHz = 45 master clocks (`LDA abs` 5, `AND #` 2, `Bcc` not taken 2, `INX` 2, `BNE`
taken 4). The disc is synthetic (`probe.cue`: 40 numbered data sectors, then 600 audio sectors).

Run on a GPL emulator, this is a **closed-box measurement** (docs/restart.md rule 4): the core is
loaded as a library through the libretro ABI and only its work RAM is read. The probe image is put in
a temporary system directory under the name the core looks for (`syscard3.pce`).
"""

from __future__ import annotations

import argparse
import ctypes as C
import json
import math
import struct
import sys
import tempfile
from pathlib import Path

# -- a two-pass assembler for the few instructions the probe needs -----------------------------

IMPLIED = {
    "SEI": 0x78,
    "CLD": 0xD8,
    "CSH": 0xD4,
    "TXS": 0x9A,
    "INX": 0xE8,
    "INY": 0xC8,
    "DEX": 0xCA,
    "DEY": 0x88,
    "RTS": 0x60,
    "NOP": 0xEA,
    "TXA": 0x8A,
    "TAX": 0xAA,
}
IMMEDIATE = {"LDA": 0xA9, "LDX": 0xA2, "LDY": 0xA0, "AND": 0x29, "CMP": 0xC9, "TAM": 0x53}
ABSOLUTE = {
    "CMP": 0xCD,
    "LDA": 0xAD,
    "STA": 0x8D,
    "STZ": 0x9C,
    "STX": 0x8E,
    "STY": 0x8C,
    "INC": 0xEE,
    "LDX": 0xAE,
    "JMP": 0x4C,
    "JSR": 0x20,
}
ABSOLUTE_X = {"STA": 0x9D, "LDA": 0xBD}
BRANCH = {"BNE": 0xD0, "BEQ": 0xF0, "BRA": 0x80, "BCC": 0x90, "BCS": 0xB0}

ORG = 0xC000  # bank 1 at $C000 (MPR6), bank 0 at $E000 (MPR7, the reset bank)
RESULTS = 0x2200  # work RAM (bank $F8 through MPR1), read by the host
DONE = 0x5A  # written to RESULTS[0] when the program ends


class Asm:
    def __init__(self) -> None:
        self.items: list = []
        self.labels: dict[str, int] = {}
        self.unique = 0

    def label(self, name: str) -> None:
        self.items.append(("label", name))

    def fresh(self, stem: str) -> str:
        self.unique += 1
        return f"{stem}_{self.unique}"

    def op(self, mnemonic: str, mode: str = "", value: int | str = 0) -> None:
        self.items.append(("op", mnemonic, mode, value))

    def org(self, address: int) -> None:
        self.items.append(("org", address))

    def assemble(self) -> bytes:
        """The 16 KiB from ORG ($C000) to $FFFF."""
        for _ in range(2):
            pc, mem, top = ORG, bytearray(b"\xff" * 0x4000), ORG
            for item in self.items:
                if item[0] == "label":
                    self.labels[item[1]] = pc
                    continue
                if item[0] == "org":
                    if item[1] < pc:
                        raise ValueError(f"code reaches ${pc:04X}, past ${item[1]:04X}")
                    pc = item[1]
                    continue
                _, m, mode, v = item
                if mode == "":
                    out = bytes([IMPLIED[m]])
                elif mode == "#":
                    out = bytes([IMMEDIATE[m], v & 0xFF])
                elif mode == "far":  # a conditional branch to anywhere: the inverse over a JMP
                    address = self.labels.get(v, 0)
                    out = bytes([BRANCH[m] ^ 0x20, 3, 0x4C, address & 0xFF, address >> 8])
                elif mode == "rel":
                    target = self.labels.get(v, pc)
                    offset = target - (pc + 2)
                    if not -128 <= offset <= 127 and v in self.labels:
                        raise ValueError(f"branch to {v} out of range")
                    out = bytes([BRANCH[m], offset & 0xFF])
                else:
                    address = self.labels.get(v, 0) if isinstance(v, str) else v
                    table = ABSOLUTE_X if mode == "abs,x" else ABSOLUTE
                    out = bytes([table[m], address & 0xFF, address >> 8])
                mem[pc - ORG : pc - ORG + len(out)] = out
                pc += len(out)
                top = max(top, pc)
            if top > 0x10000:
                raise ValueError("probe too big")
        return bytes(mem)


def build_probe() -> tuple[bytes, dict[str, int]]:
    """The probe program and the result addresses (name -> address)."""
    a = Asm()
    slots: dict[str, int] = {}
    cursor = [RESULTS + 1]
    zp = 0x2010  # scratch counters (work RAM, not zero page: the program keeps it simple)

    def slot(name: str, size: int = 3) -> int:
        slots[name] = cursor[0]
        cursor[0] += size
        return slots[name]

    waiters: dict[tuple[int, int, bool], str] = {}

    def wait(reg: int, mask: int, want_set: bool, name: str | None, limit: int = 8) -> None:
        """Count 15-cycle turns until (reg & mask) is set (or clear); a timeout after limit*65536
        turns leaves the high byte at `limit`. One subroutine per (register, mask, sense)."""
        key = (reg, mask, want_set)
        if key not in waiters:
            waiters[key] = f"wait_{reg:04X}_{mask:02X}_{int(want_set)}"
        a.op("LDA", "#", limit)
        a.op("STA", "abs", zp + 1)
        a.op("JSR", "abs", waiters[key])
        if name:
            at = slot(name)
            a.op("STX", "abs", at)
            a.op("STY", "abs", at + 1)
            a.op("LDA", "abs", zp)
            a.op("STA", "abs", at + 2)

    def emit_waiters() -> None:
        for (reg, mask, want_set), name in waiters.items():
            loop, done = a.fresh("w"), a.fresh("wd")
            a.label(name)
            a.op("STZ", "abs", zp)
            a.op("LDX", "#", 0)
            a.op("LDY", "#", 0)
            a.label(loop)
            a.op("LDA", "abs", reg)
            a.op("AND", "#", mask)
            a.op("BNE" if want_set else "BEQ", "rel", done)
            a.op("INX")
            a.op("BNE", "rel", loop)
            a.op("INY")
            a.op("BNE", "rel", loop)
            a.op("INC", "abs", zp)
            a.op("LDA", "abs", zp)
            a.op("CMP", "abs", zp + 1)
            a.op("BNE", "rel", loop)
            a.label(done)
            a.op("RTS")

    def save(reg: int, name: str) -> None:
        a.op("LDA", "abs", reg)
        a.op("STA", "abs", slot(name, 1))

    def ack(name: str | None = None) -> None:
        a.op("LDA", "#", 0x80)
        a.op("STA", "abs", 0x1802)
        wait(0x1800, 0x40, False, name)
        a.op("STZ", "abs", 0x1802)

    def delay(turns_256: int) -> None:
        loop, inner = a.fresh("d"), a.fresh("di")
        a.op("LDY", "#", turns_256)
        a.label(loop)
        a.op("LDX", "#", 0)
        a.label(inner)
        a.op("DEX")
        a.op("BNE", "rel", inner)
        a.op("DEY")
        a.op("BNE", "rel", loop)

    def select(tag: str) -> None:
        a.op("LDA", "#", 0x81)
        a.op("STA", "abs", 0x1801)
        a.op("STA", "abs", 0x1800)
        wait(0x1800, 0x80, True, f"{tag}.sel_bsy")
        wait(0x1800, 0x40, True, f"{tag}.sel_req")
        save(0x1800, f"{tag}.sel_phase")

    def send(tag: str, command: list[int], wait_last: bool = True) -> None:
        for i, byte in enumerate(command):
            a.op("LDA", "#", byte)
            a.op("STA", "abs", 0x1801)
            ack(f"{tag}.ack_req_drop" if i == 0 else None)
            last = i + 1 == len(command)
            if last and not wait_last:
                break
            wait(
                0x1800,
                0x40,
                True,
                f"{tag}.exec" if last else (f"{tag}.next_req" if i == 0 else None),
                limit=80 if last else 8,
            )
        save(0x1800, f"{tag}.exec_phase")

    def drain(tag: str, keep: int = 20) -> None:
        """Take whatever the drive offers (data in through $1801, status, message) until BSY drops;
        keep the first `keep` data bytes, the count, the status and message bytes."""
        loop, data, status, message, end, skip = (
            a.fresh(s) for s in ("dl", "dd", "ds", "dm", "de", "dk")
        )
        count, buf = slot(f"{tag}.data_count", 2), slot(f"{tag}.data", keep)
        st, ms, other = (
            slot(f"{tag}.status", 1),
            slot(f"{tag}.message", 1),
            slot(f"{tag}.other_phase", 1),
        )
        for at in (count, count + 1):
            a.op("STZ", "abs", at)
        a.op("LDA", "#", 0xEE)
        a.op("STA", "abs", st)
        a.op("STA", "abs", ms)
        a.op("STZ", "abs", other)
        a.label(loop)
        wait(0x1800, 0x40, True, None, limit=40)
        a.op("LDA", "abs", 0x1800)
        a.op("AND", "#", 0xF8)
        a.op("CMP", "#", 0xC8)
        a.op("BEQ", "rel", data)
        a.op("CMP", "#", 0xD8)
        a.op("BEQ", "rel", status)
        a.op("CMP", "#", 0xF8)
        a.op("BEQ", "rel", message)
        a.op("STA", "abs", other)
        a.op("JMP", "abs", end)
        a.label(data)
        a.op("LDX", "abs", count)
        a.op("LDA", "abs", 0x1801)
        a.op("STA", "abs", 0x2020)
        a.op("TXA")
        a.op("CMP", "#", keep)
        a.op("BCS", "rel", skip)
        a.op("LDA", "abs", 0x2020)
        a.op("STA", "abs,x", buf)
        a.label(skip)
        a.op("INC", "abs", count)
        nohi = a.fresh("nh")
        a.op("BNE", "rel", nohi)
        a.op("INC", "abs", count + 1)
        a.label(nohi)
        ack()
        a.op("JMP", "abs", loop)
        a.label(status)
        a.op("LDA", "abs", 0x1801)
        a.op("STA", "abs", st)
        ack()
        a.op("JMP", "abs", loop)
        a.label(message)
        a.op("LDA", "abs", 0x1801)
        a.op("STA", "abs", ms)
        ack()
        wait(0x1800, 0x80, False, f"{tag}.free")
        a.label(end)

    def abort_sequence(tag: str) -> None:
        """SEL while the drive is busy, as the BIOS does it ($81, SEL, then $FF on the bus), then
        take every REQ (phase and byte, up to 16) until BSY drops."""
        a.op("LDA", "#", 0x81)
        a.op("STA", "abs", 0x1801)
        a.op("STA", "abs", 0x1800)
        save(0x1800, f"{tag}.after_sel")
        a.op("LDA", "#", 0xFF)
        a.op("STA", "abs", 0x1801)
        wait(0x1800, 0x40, True, f"{tag}.first_req", limit=1)
        seq, n = slot(f"{tag}.seq", 32), slot(f"{tag}.n", 1)
        loop, take, end = a.fresh("al"), a.fresh("at"), a.fresh("ae")
        a.op("STZ", "abs", n)
        a.label(loop)
        wait(0x1800, 0x40, True, None, limit=1)  # REQ within 0.14 s, or look at BSY
        a.op("LDA", "abs", 0x1800)
        a.op("AND", "#", 0x40)
        a.op("BNE", "rel", take)
        a.op("LDA", "abs", 0x1800)
        a.op("AND", "#", 0x80)
        a.op("BEQ", "far", end)
        a.op("JMP", "abs", loop)
        a.label(take)
        a.op("LDX", "abs", n)
        a.op("TXA")
        a.op("CMP", "#", 16)
        a.op("BCS", "far", end)
        a.op("LDA", "abs", 0x1800)
        a.op("STA", "abs,x", seq)
        a.op("LDA", "abs", 0x1801)
        a.op("STA", "abs,x", seq + 16)
        a.op("INC", "abs", n)
        ack()
        a.op("JMP", "abs", loop)
        a.label(end)

    def take_1808(count: int) -> None:
        """Take `count` bytes (1-2048) through $1808, each after its REQ."""
        outer, inner = a.fresh("lo"), a.fresh("li")
        a.op("LDA", "#", (count - 1) // 256 + 1)
        a.op("STA", "abs", 0x2031)
        a.op("LDA", "#", count % 256)
        a.op("STA", "abs", 0x2030)
        a.label(outer)
        a.label(inner)
        wait(0x1800, 0x40, True, None)
        a.op("LDA", "abs", 0x1808)
        a.op("LDX", "abs", 0x2030)
        a.op("DEX")
        a.op("STX", "abs", 0x2030)
        a.op("TXA")
        a.op("BNE", "far", inner)
        a.op("LDX", "abs", 0x2031)
        a.op("DEX")
        a.op("STX", "abs", 0x2031)
        a.op("TXA")
        a.op("BNE", "far", outer)

    def command(tag: str, cmd: list[int], keep: int = 20) -> None:
        select(tag)
        send(tag, cmd)
        drain(tag, keep)

    # -- the program --------------------------------------------------------------------------
    a.label("main")
    a.op("CLD")
    a.op("CSH")
    a.op("LDA", "#", 0xFF)
    a.op("TAM", "#", 0x01)  # MPR0 = $FF: I/O at $0000-$1FFF
    a.op("LDA", "#", 0xF8)
    a.op("TAM", "#", 0x02)  # MPR1 = $F8: work RAM at $2000-$3FFF
    a.op("LDX", "#", 0xFF)
    a.op("TXS")
    a.op("STZ", "abs", RESULTS)
    a.op("STZ", "abs", 0x1802)
    save(0x1800, "power.phase")
    # unit registers: $180B bit 0 with no data waiting, and the $1805 channel toggle seen in
    # $1803 bit 1 after two writes 10 cycles apart, then a third about 1,500 cycles later
    a.op("LDA", "#", 0x03)
    a.op("STA", "abs", 0x180B)
    save(0x180B, "u.dma_readback")
    a.op("STZ", "abs", 0x180B)
    save(0x1803, "u.chan0")
    a.op("STA", "abs", 0x1805)
    save(0x1803, "u.chan1")
    a.op("STA", "abs", 0x1805)
    save(0x1803, "u.chan2")
    delay(1)
    a.op("STA", "abs", 0x1805)
    save(0x1803, "u.chan3")
    delay(2)
    save(0x1803, "u.chan4")
    # one write, then $1803 every 10 cycles for 48 samples, then a write at 480 cycles and again
    delay(4)
    samples = slot("u.chan_samples", 48)
    a.op("STA", "abs", 0x1805)
    for i in range(48):
        a.op("LDA", "abs", 0x1803)
        a.op("STA", "abs", samples + i)
    a.op("STA", "abs", 0x1805)
    later = slot("u.chan_samples2", 48)
    for i in range(48):
        a.op("LDA", "abs", 0x1803)
        a.op("STA", "abs", later + i)
    # pairs of writes N cycles apart (N = the NOPs' cycles + 10): did the second one toggle?
    gaps = (100, 140, 180, 200, 220, 240, 260, 300)
    pairs = slot("u.chan_pairs", 2 * len(gaps))
    for i, gap in enumerate(gaps):
        delay(3)
        a.op("STA", "abs", 0x1805)
        a.op("LDA", "abs", 0x1803)
        a.op("STA", "abs", pairs + 2 * i)
        turns = (gap - 10) // 6  # LDX #n, then n x (DEX, BNE): 6n cycles
        loop = a.fresh("g")
        a.op("LDX", "#", turns)
        a.label(loop)
        a.op("DEX")
        a.op("BNE", "rel", loop)
        for _ in range((gap - 10 - 6 * turns) // 2):
            a.op("NOP")
        a.op("STA", "abs", 0x1805)
        a.op("LDA", "abs", 0x1803)
        a.op("STA", "abs", pairs + 2 * i + 1)
    # 1. the drive straight after power-on: TEST UNIT READY until Good
    command("tur0", [0x00, 0, 0, 0, 0, 0])
    tries, again, good = slot("tur0.tries", 1), a.fresh("again"), a.fresh("good")
    a.op("STZ", "abs", tries)
    a.label(again)
    a.op("LDA", "abs", slots["tur0.status"])
    a.op("BEQ", "far", good)
    a.op("INC", "abs", tries)
    a.op("LDA", "abs", tries)
    a.op("CMP", "#", 200)
    a.op("BEQ", "far", good)
    delay(255)
    command("tur0r", [0x00, 0, 0, 0, 0, 0])
    a.op("LDA", "abs", slots["tur0r.status"])
    a.op("STA", "abs", slots["tur0.status"])
    a.op("JMP", "abs", again)
    a.label(good)
    # 2. a ready drive: TEST UNIT READY, READ TOC kinds 0, 1, 2, REQUEST SENSE
    command("tur", [0x00, 0, 0, 0, 0, 0])
    command("toc0", [0xDE, 0, 0, 0, 0, 0, 0, 0, 0, 0])
    command("toc1", [0xDE, 1, 0, 0, 0, 0, 0, 0, 0, 0])
    command("toc2", [0xDE, 2, 0x02, 0, 0, 0, 0, 0, 0, 0])
    command("sense", [0x03, 0, 0, 0, 18, 0])
    command("subq", [0xDD, 10, 0, 0, 0, 0, 0, 0, 0, 0])
    # 3. READ one sector through $1808: the auto-ACK and the next REQ
    select("rd")
    send("rd", [0x08, 0, 0, 0, 1, 0])
    a.op("LDA", "abs", 0x1808)
    wait(0x1802, 0x80, False, "rd.auto_ack")
    wait(0x1800, 0x40, True, "rd.auto_next_req")
    drain("rd")
    # the auto-ACK sampled every 10 cycles: $1802 (ACK) after one $1808 read, $1800 after another
    select("aa")
    send("aa", [0x08, 0, 0, 3, 1, 0])
    a.op("LDA", "abs", 0x1808)
    ack_samples, req_samples = slot("aa.ack_samples", 12), slot("aa.req_samples", 12)
    for i in range(12):
        a.op("LDA", "abs", 0x1802)
        a.op("STA", "abs", ack_samples + i)
    wait(0x1800, 0x40, True, None)
    a.op("LDA", "abs", 0x1808)
    for i in range(12):
        a.op("LDA", "abs", 0x1800)
        a.op("STA", "abs", req_samples + i)
    drain("aa", keep=2)
    # the CD-to-ADPCM DMA: REQ sampled every 10 cycles after $180B = 2 in data in
    select("dm")
    send("dm", [0x08, 0, 0, 4, 1, 0])
    a.op("LDA", "#", 0x02)
    a.op("STA", "abs", 0x180B)
    dma = slot("dm.req_samples", 64)
    for i in range(64):
        a.op("LDA", "abs", 0x1800)
        a.op("STA", "abs", dma + i)
    wait(0x1800, 0x10, True, "dm.to_status", limit=40)
    a.op("STZ", "abs", 0x180B)
    drain("dm", keep=1)
    # the handshake in data in, and status to message
    select("hs")
    send("hs", [0x08, 0, 0, 5, 1, 0])
    a.op("LDA", "abs", 0x1801)
    ack("hs.ack_drop")
    wait(0x1800, 0x40, True, "hs.next_data_req")
    drain("hs", keep=2)
    select("st")
    send("st", [0x00, 0, 0, 0, 0, 0])
    a.op("LDA", "abs", 0x1801)
    ack("st.ack_drop")
    wait(0x1800, 0x40, True, "st.message_req")
    save(0x1800, "st.message_phase")
    a.op("LDA", "abs", 0x1801)
    ack()
    wait(0x1800, 0x80, False, "st.free")
    # the last data byte to the status phase
    select("ls")
    send("ls", [0x08, 0, 0, 6, 1, 0])
    take_1808(2047)
    wait(0x1800, 0x40, True, None)
    save(0x1800, "ls.last_phase")
    a.op("LDA", "abs", 0x1801)
    ack()
    wait(0x1800, 0x40, True, "ls.status_req")
    save(0x1800, "ls.status_phase")
    drain("ls", keep=1)
    # two sectors taken on time, and two with a stall of about four sector times after one byte
    select("ot")
    send("ot", [0x08, 0, 0, 10, 2, 0])
    take_1808(2048)
    wait(0x1800, 0x40, True, "ot.next_sector")
    save(0x1800, "ot.next_phase")
    drain("ot", keep=1)
    select("late")
    send("late", [0x08, 0, 0, 12, 2, 0])
    take_1808(1)
    delay(255)
    take_1808(2047)
    wait(0x1800, 0x40, True, "late.next_sector")
    save(0x1800, "late.next_phase")
    drain("late", keep=1)
    # the next sector straight after, then one far away
    command("rd2", [0x08, 0, 0, 1, 1, 0], keep=2)
    command("rd3", [0x08, 0, 0, 30, 1, 0], keep=2)
    # 4. SEL while the drive sends data: what it offers until BSY drops
    select("ab")
    send("ab", [0x08, 0, 0, 2, 4, 0])
    for _ in range(10):
        a.op("LDA", "abs", 0x1808)
        wait(0x1800, 0x40, True, None)
    abort_sequence("ab")
    command("tur_ab", [0x00, 0, 0, 0, 0, 0])
    # 5. CD audio: AUDIO START at track 2, play; AUDIO END mode 1 (repeat), then SEL
    command("as", [0xD8, 1, 0x02, 0, 0, 0, 0, 0, 0, 0x80])
    select("ae")
    send("ae", [0xD9, 1, 0x02, 0, 0, 0, 0, 0, 0, 0x80])  # end at track 2's start: mode 1
    save(0x1800, "ae.after")
    delay(200)
    save(0x1800, "ae.later")
    command("ae_sel", [0x00, 0, 0, 0, 0, 0])
    # SEL while a READ seeks (before its first byte), and while AUDIO END mode 2 plays
    select("as2")
    send("as2", [0x08, 0, 0, 0, 1, 0], wait_last=False)
    save(0x1800, "as2.seeking")
    abort_sequence("as2")
    command("as3", [0xD8, 1, 0x02, 0, 0, 0, 0, 0, 0, 0x80])
    select("m2")
    send("m2", [0xD9, 2, 0, 0x00, 0x01, 0x2C, 0, 0, 0, 0x00], wait_last=False)  # to LBA 300
    save(0x1800, "m2.after")
    abort_sequence("m2")
    command("tur_m2", [0x00, 0, 0, 0, 0, 0])
    # 6. after the reset bit (the BIOS's CD_RESET shape): how long until TEST UNIT READY is Good
    a.op("LDA", "#", 0x02)
    a.op("STA", "abs", 0x1804)
    delay(3)
    a.op("STZ", "abs", 0x1804)
    delay(3)
    command("rst", [0x00, 0, 0, 0, 0, 0])
    rtries, ragain, rgood = slot("rst.tries", 1), a.fresh("ragain"), a.fresh("rgood")
    a.op("STZ", "abs", rtries)
    a.label(ragain)
    a.op("LDA", "abs", slots["rst.status"])
    a.op("BEQ", "far", rgood)
    a.op("INC", "abs", rtries)
    a.op("LDA", "abs", rtries)
    a.op("CMP", "#", 200)
    a.op("BEQ", "far", rgood)
    delay(255)
    command("rstr", [0x00, 0, 0, 0, 0, 0])
    a.op("LDA", "abs", slots["rstr.status"])
    a.op("STA", "abs", slots["rst.status"])
    a.op("JMP", "abs", ragain)
    a.label(rgood)
    a.op("LDA", "#", DONE)
    a.op("STA", "abs", RESULTS)
    a.label("halt")
    a.op("JMP", "abs", "halt")
    emit_waiters()
    a.org(0xFF00)  # the reset entry, in bank 0: map bank 1 at $C000, then go
    a.label("reset")
    a.op("SEI")
    a.op("CLD")
    a.op("CSH")
    a.op("LDA", "#", 0x01)
    a.op("TAM", "#", 0x40)  # MPR6 = card bank 1
    a.op("JMP", "abs", "main")
    mem = bytearray(a.assemble())
    reset = a.labels["reset"]
    for vector in (0xFFF6, 0xFFF8, 0xFFFA, 0xFFFC, 0xFFFE):
        mem[vector - ORG : vector - ORG + 2] = struct.pack("<H", reset)
    image = bytes(mem[0x2000:]) + bytes(mem[:0x2000]) + b"\xff" * (256 * 1024 - 0x4000)
    return image, slots


# -- the disc ----------------------------------------------------------------------------------


def write_disc(directory: Path) -> Path:
    sync = b"\x00" + b"\xff" * 10 + b"\x00"
    out = bytearray()
    for lba in range(40):
        f = lba + 150
        header = bytes(
            [
                ((f // 4500) // 10) << 4 | (f // 4500) % 10,
                (((f // 75) % 60) // 10) << 4 | ((f // 75) % 60) % 10,
                ((f % 75) // 10) << 4 | (f % 75) % 10,
                1,
            ]
        )
        out += (sync + header + bytes((lba + i) & 0xFF for i in range(2048))).ljust(2352, b"\0")
    for n in range(600 * 588):
        v = int(8000 * math.sin(2 * math.pi * 441 * n / 44100))
        out += struct.pack("<hh", v, v)
    (directory / "probe.bin").write_bytes(out)
    cue = directory / "probe.cue"
    cue.write_text(
        'FILE "probe.bin" BINARY\n  TRACK 01 MODE1/2352\n    INDEX 01 00:00:00\n'
        "  TRACK 02 AUDIO\n    INDEX 01 00:00:40\n"
    )
    return cue


# -- hosts -------------------------------------------------------------------------------------


def run_libretro(core: Path, cue: Path, system: Path, frames: int) -> bytes:
    lib = C.CDLL(str(core.resolve()))
    keep = []
    sysdir = str(system.resolve()).encode()
    ENV = C.CFUNCTYPE(C.c_bool, C.c_uint, C.c_void_p)
    VIDEO = C.CFUNCTYPE(None, C.c_void_p, C.c_uint, C.c_uint, C.c_size_t)
    SAMPLE = C.CFUNCTYPE(None, C.c_int16, C.c_int16)
    BATCH = C.CFUNCTYPE(C.c_size_t, C.POINTER(C.c_int16), C.c_size_t)
    POLL = C.CFUNCTYPE(None)
    INPUT = C.CFUNCTYPE(C.c_int16, C.c_uint, C.c_uint, C.c_uint, C.c_uint)

    LOG = C.CFUNCTYPE(None, C.c_int, C.c_char_p)  # variadic in C: only the format arrives
    log_cb = LOG(lambda level, fmt: None)
    keep.append(log_cb)

    def env(cmd, data):
        cmd &= 0xFFFF
        if cmd == 27:  # the log interface
            C.cast(data, C.POINTER(C.c_void_p))[0] = C.cast(log_cb, C.c_void_p)
            return True
        if cmd in (9, 31):  # system, save directory
            C.cast(data, C.POINTER(C.c_char_p))[0] = sysdir
            return True
        return cmd == 10  # the pixel format: accepted

    cbs = [
        ENV(env),
        VIDEO(lambda d, w, h, p: None),
        SAMPLE(lambda left, right: None),
        BATCH(lambda d, n: n),
        POLL(lambda: None),
        INPUT(lambda p, d, i, b: 0),
    ]
    keep += cbs
    lib.retro_set_environment(cbs[0])
    lib.retro_set_video_refresh(cbs[1])
    lib.retro_set_audio_sample(cbs[2])
    lib.retro_set_audio_sample_batch(cbs[3])
    lib.retro_set_input_poll(cbs[4])
    lib.retro_set_input_state(cbs[5])
    lib.retro_init()

    class GameInfo(C.Structure):
        _fields_ = [
            ("path", C.c_char_p),
            ("data", C.c_void_p),
            ("size", C.c_size_t),
            ("meta", C.c_char_p),
        ]

    info = GameInfo(str(cue.resolve()).encode(), None, 0, None)
    if not lib.retro_load_game(C.byref(info)):
        raise SystemExit("retro_load_game failed")
    lib.retro_get_memory_data.restype = C.c_void_p
    lib.retro_get_memory_size.restype = C.c_size_t
    for _ in range(frames):
        lib.retro_run()
    size = lib.retro_get_memory_size(2)  # RETRO_MEMORY_SYSTEM_RAM
    return C.string_at(lib.retro_get_memory_data(2), size)


def run_ours(image: bytes, cue: Path, frames: int) -> bytes:
    from pcenginecd_python import Disc, PcEngineCd

    cd = PcEngineCd(image, Disc.from_cue(cue))
    system = cd.build()
    for frame in range(frames):
        system.run_frame()
        if cd.board.ram.data[RESULTS & 0x1FFF] == DONE:
            print(f"done at frame {frame + 1}", file=sys.stderr)
            break
    return bytes(cd.board.ram.data)


def decode(ram: bytes, slots: dict[str, int]) -> dict:
    out: dict = {"done": ram[RESULTS & 0x1FFF] == DONE}
    names = sorted(slots, key=slots.get)
    for i, name in enumerate(names):
        at = slots[name] & 0x1FFF
        size = (slots[names[i + 1]] & 0x1FFF) - at if i + 1 < len(names) else 1
        raw = ram[at : at + size]
        if size == 3:  # a count of 15-cycle turns -> master clocks
            turns = raw[0] | raw[1] << 8 | raw[2] << 16
            out[name] = {"turns": turns, "mclk": turns * 45}
        elif size == 2:
            out[name] = raw[0] | raw[1] << 8
        elif size == 1:
            out[name] = f"{raw[0]:02X}"
        else:
            out[name] = raw.hex(" ")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--core", type=Path)
    ap.add_argument("--ours", action="store_true")
    ap.add_argument("--frames", type=int, default=1800)
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    image, slots = build_probe()
    a.out.mkdir(parents=True, exist_ok=True)
    cue = write_disc(a.out)
    if a.ours:
        ram = run_ours(image, cue, a.frames)
    else:
        with tempfile.TemporaryDirectory() as system:
            for name in ("syscard3.pce", "syscard3u.pce", "syscard.pce"):
                (Path(system) / name).write_bytes(image)
            ram = run_libretro(a.core, cue, Path(system), a.frames)
    result = decode(ram, slots)
    text = json.dumps(result, indent=1)
    (a.out / "probe.json").write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
