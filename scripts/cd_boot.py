#!/usr/bin/env python3
"""Boot a disc on the CD board for N frames; log the drive's commands; save pictures.

    nice -n 10 .venv-pypy/bin/python scripts/cd_boot.py DISC.cue --frames 900 \
        --png-at 300,600,900 --out RUNDIR [--system-card PATH] [--trace-regs N]

DISC is a `.cue` (a bin/cue pair, for instance extracted from a CHD with `chdman extractcd` into
the scratchpad: `scripts/scratch.py extract GAME.chd DIR`) or a `.chd` (extracted once into
`--scratch DIR`, which the caller deletes with `scripts/scratch.py remove DIR`). The System Card is
bring-your-own, read in place (default: the Batocera BIOS pack). One run, niced: this board is
slow by design (a reference board, not a fast one), and the machine is shared.

Writes to RUNDIR: `frameNNNNN.pkl` pictures (9-bit rows + the VCE's RGB table; turn them into
PNGs with the system python3: `python3 scripts/rows_png.py RUNDIR`), `commands.txt` (the SCSI commands with master-clock time,
frame), `regs.txt` (the first N accesses of `$1800-$18FF`) and `summary.json`. The pictures are for
looking at; compare at the 9-bit rows, never at RGB (docs/validation.md of the base board).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

DEFAULT_CARD = "/data/emu/share/batocera/bios/syscard3.pce"


def save_frame(board, path: Path) -> None:
    """The last frame as 9-bit rows plus the VCE's RGB table (pickle); `scripts/rows_png.py` turns
    it into a PNG under the system python3 (Pillow is not in the PyPy venv)."""
    import pickle

    frame = board.capture.last_frame
    path.write_bytes(
        pickle.dumps({"rows": [list(r) for r in frame.rows], "rgb": list(board.vce.rgb_table)})
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("disc", type=Path)
    ap.add_argument("--system-card", type=Path, default=Path(DEFAULT_CARD))
    ap.add_argument("--frames", type=int, default=600)
    ap.add_argument("--png-at", default="", help="comma list of frame numbers")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--scratch", type=Path, help="where a .chd is expanded (caller deletes it)")
    ap.add_argument("--trace-regs", type=int, default=0)
    ap.add_argument(
        "--press-run-at", type=int, default=0, help="hold RUN from this frame (0: never)"
    )
    ap.add_argument(
        "--hold-frames", type=int, default=0, help="release RUN after this many frames (0: never)"
    )
    ap.add_argument(
        "--press-again", default="", help="comma list of frames at which to tap RUN for 10 frames"
    )
    a = ap.parse_args()

    from pcengine_python import pads

    from pcenginecd_python import Disc, PcEngineCd

    a.out.mkdir(parents=True, exist_ok=True)
    if a.disc.suffix.lower() == ".chd":
        if a.scratch is None:
            ap.error(".chd needs --scratch")
        disc = Disc.from_chd(a.disc, a.scratch)
    else:
        disc = Disc.from_cue(a.disc)
    pad = pads.Pad2()
    cd = PcEngineCd(a.system_card, disc, pad=pad)
    unit, board = cd.unit, cd.board
    unit.bus.record_log = True

    regs: list[str] = []
    if a.trace_regs:
        read, write = unit.read, unit.write

        def traced_read(address, mclk):
            value = read(address, mclk)
            if address >> 8 == 0x1FF8 and len(regs) < a.trace_regs:
                regs.append(f"{mclk} R {address & 0xFFF:04X} {value:02X}")
            return value

        def traced_write(address, value, mclk):
            if address >> 8 == 0x1FF8 and len(regs) < a.trace_regs:
                regs.append(f"{mclk} W {address & 0xFFF:04X} {value:02X}")
            write(address, value, mclk)

        unit.read, unit.write = traced_read, traced_write
        board.pages.claim(0x1FF8, 0x1FF8, unit)

    system = cd.build()
    taps = {int(x) for x in a.press_again.split(",") if x}
    shots = {int(x) for x in a.png_at.split(",") if x}
    began = time.monotonic()
    for frame in range(1, a.frames + 1):
        if a.press_run_at and frame == a.press_run_at:
            pad.pressed |= pads.RUN
        if a.hold_frames and frame == a.press_run_at + a.hold_frames:
            pad.pressed &= ~pads.RUN
        if frame in taps:
            pad.pressed |= pads.RUN
        if frame - 10 in taps:
            pad.pressed &= ~pads.RUN
        system.run_frame()
        if frame in shots:
            save_frame(board, a.out / f"frame{frame:05d}.pkl")
        if frame % 50 == 0:
            print(f"frame {frame} {time.monotonic() - began:.0f}s", file=sys.stderr, flush=True)

    (a.out / "commands.txt").write_text("\n".join(f"{t} {text}" for t, text in unit.bus.log) + "\n")
    (a.out / "regs.txt").write_text("\n".join(regs) + "\n")
    summary = {
        "frames": a.frames,
        "seconds": round(time.monotonic() - began, 1),
        "commands": len(unit.bus.log),
        "pc": hex(system.cpu.pc),
        "irq2_sources": sorted(board.irq2.sources),
        "bus_phase": unit.bus.phase.value,
    }
    (a.out / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main())
