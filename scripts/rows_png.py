#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Turn the `frameNNNNN.pkl` files of a `cd_boot.py` run into PNGs (needs Pillow: system python3).

    python3 -I scripts/rows_png.py RUNDIR [--scale 2]

Pictures are for looking at. Compare at the 9-bit rows, never at RGB.
"""

import argparse
import pickle
import sys
from pathlib import Path

from PIL import Image


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("rundir", type=Path)
    ap.add_argument("--scale", type=int, default=1)
    a = ap.parse_args()
    for path in sorted(a.rundir.glob("frame*.pkl")):
        data = pickle.loads(path.read_bytes())
        rows, rgb = data["rows"], data["rgb"]
        width = max(len(r) for r in rows)
        image = Image.new("RGB", (width, len(rows)))
        pixels = image.load()
        for y, row in enumerate(rows):
            for x in range(width):
                pixels[x, y] = tuple(rgb[row[min(x, len(row) - 1)]])
        if a.scale > 1:
            image = image.resize((width * a.scale, len(rows) * a.scale), Image.NEAREST)
        image.save(path.with_suffix(".png"))
        print(path.with_suffix(".png"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
