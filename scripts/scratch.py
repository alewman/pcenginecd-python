#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Scratch-directory helper: expand a CHD once, remove the expansion later (no shell `rm`).

    python3 scripts/scratch.py extract GAME.chd DIR     # chdman extractcd, niced, into DIR
    python3 scripts/scratch.py remove DIR               # deletes DIR's files (only d.cue/d.bin/*.bin/*.cue)
    python3 scripts/scratch.py size DIR

The expansion is 200-800 MiB per disc: extract one at a time under the scratchpad, never commit.
`remove` refuses a directory that holds anything other than .bin/.cue files.
"""

import subprocess
import sys
from pathlib import Path


def main() -> int:
    cmd, *args = sys.argv[1:]
    if cmd == "extract":
        chd, out = Path(args[0]), Path(args[1])
        out.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [
                "nice",
                "-n",
                "10",
                "chdman",
                "extractcd",
                "-i",
                str(chd),
                "-o",
                str(out / "disc.cue"),
                "-ob",
                str(out / "disc.bin"),
            ],
            check=True,
        )
    elif cmd == "remove":
        out = Path(args[0])
        other = [p for p in out.iterdir() if p.suffix not in (".bin", ".cue")]
        if other:
            print("refusing: not only .bin/.cue files:", other)
            return 1
        for p in out.iterdir():
            p.unlink()
        out.rmdir()
    elif cmd == "size":
        print(sum(p.stat().st_size for p in Path(args[0]).rglob("*") if p.is_file()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
