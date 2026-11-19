# SPDX-License-Identifier: MIT
"""The disc: a track table and sectors, from a bin/cue pair, a CHD (through `chdman`), or memory.

Addresses. A sector's **LBA** is its index in the disc image: LBA 0 is the first stored sector,
which is absolute time 00:02:00 (the two-second lead-in gap is not stored). So `msf = lba + 150`
frames. The SCSI READ command and every track start in this module are in this LBA, and the
`READ TOC` answers are MSF = LBA + 150 [doc: pcetech 8; the Hudson BIOS manual's CD_DINFO; emulator
tier: MAME `nec/pce_cd.cpp` (BSD-3) adds 150; OBSERVED, closed box: Geargrafx answers a track at
LBA 40 with 00:02:40]. A raw sector is 2352 bytes; a Mode 1 data
sector keeps its 2048 payload bytes at +16 (12 sync, 4 header).

Nothing is committed: images are read in place, a CHD is expanded by `chdman extractcd` into a
scratch directory the caller names and deletes (`scripts/scratch.py`).
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

RAW_SECTOR = 2352
DATA_SECTOR = 2048
FRAMES_PER_SECOND = 75
LEAD_IN_FRAMES = 150  # the two-second gap before LBA 0 [doc: Red Book; emu: all four]
SYNC = bytes([0x00] + [0xFF] * 10 + [0x00])


def to_bcd(value: int) -> int:
    """Two BCD digits: defined for 0-99 (track numbers, and MSF fields of discs under 100
    minutes); larger values do not fit (issue 0001 item 5, unreachable on a real disc)."""
    return ((value // 10) << 4) | (value % 10)


def from_bcd(value: int) -> int:
    return (value >> 4) * 10 + (value & 15)


def lba_to_msf(lba: int) -> tuple[int, int, int]:
    """The absolute MSF of an LBA (the +150 lead-in applied)."""
    frames = lba + LEAD_IN_FRAMES
    return frames // (60 * FRAMES_PER_SECOND), (frames // FRAMES_PER_SECOND) % 60, frames % 75


def msf_to_lba(minutes: int, seconds: int, frames: int) -> int:
    return (minutes * 60 + seconds) * FRAMES_PER_SECOND + frames - LEAD_IN_FRAMES


def relative_msf(frames: int) -> tuple[int, int, int]:
    """A track-relative position (no lead-in)."""
    return frames // (60 * FRAMES_PER_SECOND), (frames // FRAMES_PER_SECOND) % 60, frames % 75


@dataclass
class Track:
    number: int
    is_data: bool
    start: int  # LBA of INDEX 01
    end: int  # LBA one past the track's last sector
    index0: int | None = None  # LBA of INDEX 00 (the pregap), if the cue gives one


@dataclass
class _Segment:
    """`count` consecutive sectors starting at `lba`, stored in a file or in memory."""

    lba: int
    count: int
    path: Path | None = None
    file_sector: int = 0  # first stored sector inside the file
    data: bytes | None = None  # a whole segment in memory (raw sectors), or None
    virtual: bool = False  # PREGAP/silence the image does not store
    _handle: object = field(default=None, repr=False)


class Disc:
    """A sector store plus a TOC. `sector_count` is the number of LBAs."""

    #: Media, not state (pcengine_python.state): a save state names the disc, it does not hold it.
    STATE_FIXED = True

    def __init__(self, tracks: list[Track], segments: list[_Segment]) -> None:
        self.tracks = tracks
        self._segments = segments
        self.sector_count = max((s.lba + s.count for s in segments), default=0)

    def state_identity(self) -> str:
        """What a save state records of the disc: its table of contents (not its sectors, so two
        discs with one layout are not told apart)."""
        toc = [(t.number, t.is_data, t.start, t.end) for t in self.tracks]
        return hashlib.sha1(repr((toc, self.sector_count)).encode()).hexdigest()

    # -- construction -------------------------------------------------------------------------

    @classmethod
    def from_cue(cls, cue_path: str | Path) -> Disc:
        """A bin/cue pair. Handles `FILE`, `TRACK` (MODE1/2352, AUDIO) and `INDEX 00/01`; several
        FILEs are laid end to end, as one disc. Cue times are positions in their file (chdman
        writes them so, with the pregap stored). `PREGAP` (an unstored gap) is not supported."""
        cue_path = Path(cue_path)
        files: list[tuple[Path, int]] = []  # (path, sectors)
        entries: list[dict] = []
        for raw in cue_path.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if m := re.match(r'FILE\s+"?(.*?)"?\s+\w+$', line, re.I):
                path = cue_path.parent / m.group(1)
                files.append((path, path.stat().st_size // RAW_SECTOR))
            elif m := re.match(r"TRACK\s+(\d+)\s+(\S+)", line, re.I):
                if not files:
                    raise ValueError(f"{cue_path}: TRACK before any FILE")
                mode = m.group(2).upper()
                if mode not in ("AUDIO", "MODE1/2352"):
                    raise ValueError(f"{cue_path}: unsupported track mode {mode}")
                entries.append(
                    {"number": int(m.group(1)), "is_data": mode != "AUDIO", "file": len(files) - 1}
                )
            elif m := re.match(r"INDEX\s+(\d+)\s+(\d+):(\d+):(\d+)", line, re.I):
                if not entries:
                    raise ValueError(f"{cue_path}: INDEX before any TRACK")
                frames = msf_frames(int(m.group(2)), int(m.group(3)), int(m.group(4)))
                entries[-1][f"idx{int(m.group(1))}"] = frames
            elif line.upper().startswith("PREGAP"):
                raise ValueError(f"{cue_path}: PREGAP (an unstored gap) is not supported")
        if not files or not entries:
            raise ValueError(f"{cue_path}: no FILE or TRACK")
        bases, lba = [], 0
        segments = []
        for path, count in files:
            bases.append(lba)
            segments.append(_Segment(lba, count, path=path))
            lba += count
        tracks = []
        for i, e in enumerate(entries):
            base = bases[e["file"]]
            start = base + e["idx1"]
            index0 = base + e["idx0"] if "idx0" in e else None
            if i + 1 < len(entries):
                n = entries[i + 1]
                nbase = bases[n["file"]]
                end = nbase + n["idx0"] if "idx0" in n else nbase + n["idx1"]
            else:
                end = lba
            tracks.append(Track(e["number"], e["is_data"], start, end, index0))
        return cls(tracks, segments)

    @classmethod
    def from_chd(cls, chd_path: str | Path, scratch: str | Path) -> Disc:
        """Expand a CHD with `chdman extractcd` into `scratch` (an empty directory the caller
        owns and removes) and open the result. Run once per disc, niced by the caller."""
        scratch = Path(scratch)
        scratch.mkdir(parents=True, exist_ok=True)
        cue = scratch / "disc.cue"
        subprocess.run(
            [
                "chdman",
                "extractcd",
                "-i",
                str(chd_path),
                "-o",
                str(cue),
                "-ob",
                str(scratch / "disc.bin"),
            ],
            check=True,
            capture_output=True,
        )
        return cls.from_cue(cue)

    @classmethod
    def from_memory(cls, tracks: list[tuple[str, bytes]]) -> Disc:
        """A disc whose tracks are raw 2352-byte sectors in memory: [("data"|"audio", bytes)].
        Used by the tests (`tests/discs.py` builds the bytes)."""
        out: list[Track] = []
        segs: list[_Segment] = []
        lba = 0
        for number, (kind, payload) in enumerate(tracks, 1):
            if len(payload) % RAW_SECTOR:
                raise ValueError("a memory track is whole raw sectors")
            count = len(payload) // RAW_SECTOR
            out.append(Track(number, kind == "data", lba, lba + count))
            segs.append(_Segment(lba, count, data=payload))
            lba += count
        return cls(out, segs)

    # -- reading ------------------------------------------------------------------------------

    def close(self) -> None:
        for s in self._segments:
            if s._handle is not None:
                s._handle.close()  # type: ignore[attr-defined]
                s._handle = None

    def _segment(self, lba: int) -> _Segment | None:
        for s in self._segments:
            if s.lba <= lba < s.lba + s.count:
                return s
        return None

    def read_raw(self, lba: int) -> bytes:
        """2352 bytes of sector `lba`; zeros outside the disc."""
        seg = self._segment(lba)
        if seg is None or seg.virtual:
            return bytes(RAW_SECTOR)
        index = lba - seg.lba
        if seg.data is not None:
            return seg.data[index * RAW_SECTOR : (index + 1) * RAW_SECTOR]
        if seg._handle is None:
            seg._handle = open(seg.path, "rb")  # noqa: SIM115 (closed by Disc.close)
        seg._handle.seek((seg.file_sector + index) * RAW_SECTOR)  # type: ignore[attr-defined]
        return seg._handle.read(RAW_SECTOR).ljust(RAW_SECTOR, b"\0")  # type: ignore[attr-defined]

    def read_data(self, lba: int) -> bytes:
        """The 2048-byte user data of a Mode 1 sector (zeros if it is not a data sector)."""
        track = self.track_at(lba)
        if track is None or not track.is_data:
            return bytes(DATA_SECTOR)
        return self.read_raw(lba)[16 : 16 + DATA_SECTOR]

    # -- the table of contents ----------------------------------------------------------------

    def track_at(self, lba: int) -> Track | None:
        """The track whose range (INDEX 00 .. end) holds `lba`."""
        for t in self.tracks:
            first = t.index0 if t.index0 is not None else t.start
            if first <= lba < t.end:
                return t
        return None

    def track(self, number: int) -> Track | None:
        return next((t for t in self.tracks if t.number == number), None)

    @property
    def first_track(self) -> int:
        return self.tracks[0].number

    @property
    def last_track(self) -> int:
        return self.tracks[-1].number

    @property
    def end_lba(self) -> int:
        return self.sector_count


def msf_frames(minutes: int, seconds: int, frames: int) -> int:
    return (minutes * 60 + seconds) * FRAMES_PER_SECOND + frames
