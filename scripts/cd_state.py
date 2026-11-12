#!/usr/bin/env python3
"""Save states on the CD machine: a run saved and loaded continues as the run that wasn't.

    .venv-pypy/bin/python scripts/cd_state.py DISC.cue [--arcade] [--at 900] [--to 960]
        [--extra 777] [--press BUTTONS@FRAME+HOLD ...] [--system-card syscard3.pce]

The check is the base board's (`scripts/state_roundtrip.py`, loaded from the base repository's
working tree: tooling, not chips): every CPU bus cycle, the picture, the mixed audio (PSG, CD
audio, ADPCM) and the CPU's state of every frame after the save, on a fresh machine and on one that
had run. The state itself is `pcengine_python.state`; this package registers its classes. The disc
is media: a state names it by its table of contents, and each machine here opens the disc itself.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from pcengine_python import pads

from pcenginecd_python import Disc, PcEngineCd

BASE = Path(os.environ.get("PCENGINE_PYTHON", "/data/emu/pcengine-python"))
sys.path.insert(0, str(BASE / "scripts"))
import presses as press_script  # noqa: E402
from state_roundtrip import roundtrip  # noqa: E402

DEFAULT_CARD = "/data/emu/share/batocera/bios/syscard3.pce"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("disc", type=Path, help="a .cue (extract a .chd with scripts/scratch.py)")
    p.add_argument("--system-card", type=Path, default=Path(DEFAULT_CARD))
    p.add_argument("--arcade", action="store_true", help="fit the Arcade Card")
    p.add_argument("--at", type=int, default=900)
    p.add_argument("--to", type=int, default=960)
    p.add_argument("--extra", type=int, default=777, help="instructions past frame --at")
    p.add_argument("--press", action="append", default=[], metavar="BUTTONS@FRAME+HOLD")
    a = p.parse_args()

    def make():
        pad = pads.Pad2()
        cd = PcEngineCd(a.system_card, Disc.from_cue(a.disc), pad=pad, arcade_card=a.arcade)
        return cd.board, cd.build, pad

    ok, what = roundtrip(make, a.at, a.to, a.extra, press_script.parse(a.press))
    print(f"{'ok  ' if ok else 'FAIL'} {a.disc.parent.name}: {what}", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
