# SPDX-License-Identifier: MIT
"""Synthetic discs for the tests: nothing here is a real disc, a real sector, or anything copied."""

from __future__ import annotations

import math
import struct

from pcenginecd_python.disc import RAW_SECTOR, SYNC, Disc, to_bcd


def data_sector(lba: int, payload: bytes = b"") -> bytes:
    """A Mode 1 raw sector: sync, header (MSF, mode 1), 2048 payload bytes, zero EDC/ECC."""
    minutes, seconds, frames = (lba + 150) // 4500, ((lba + 150) // 75) % 60, (lba + 150) % 75
    header = bytes([to_bcd(minutes), to_bcd(seconds), to_bcd(frames), 1])
    body = payload.ljust(2048, b"\0")[:2048]
    return (SYNC + header + body).ljust(RAW_SECTOR, b"\0")


def numbered_data(first_lba: int, count: int) -> bytes:
    """`count` data sectors whose payload bytes are (lba + index) & 0xFF: easy to assert."""
    return b"".join(
        data_sector(first_lba + n, bytes(((first_lba + n) + i) & 0xFF for i in range(2048)))
        for n in range(count)
    )


def audio_sectors(count: int, *, left_hz: float = 441.0, right_hz: float = 882.0) -> bytes:
    """`count` audio sectors of two sine waves (a different one each channel)."""
    out = bytearray()
    for n in range(count * 588):
        left = int(12000 * math.sin(2 * math.pi * left_hz * n / 44100))
        right = int(12000 * math.sin(2 * math.pi * right_hz * n / 44100))
        out += struct.pack("<hh", left, right)
    return bytes(out)


def disc_data_only(sectors: int = 40) -> Disc:
    return Disc.from_memory([("data", numbered_data(0, sectors))])


def disc_audio_then_data(audio: int = 40, data: int = 20) -> Disc:
    """Track 1 audio, track 2 data (as Insanity), then track 3 audio."""
    return Disc.from_memory(
        [
            ("audio", audio_sectors(audio)),
            ("data", numbered_data(audio, data)),
            ("audio", audio_sectors(30)),
        ]
    )
