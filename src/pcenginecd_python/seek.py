# SPDX-License-Identifier: MIT
# The zone table and the model's shape derive from Dave Shadoff's seektime.c (PCECD_seek), MIT,
# Copyright (c) 2019 David Shadoff: notice in NOTICE.md.
"""Seek time between two sectors, from Dave Shadoff's measurements on re-capped original hardware
(`reference/src/pce-cd-seek`, `seektime.c` and `measurements/`; MIT). Tier 3: measured by a
person who published the method, not a manufacturer; resolution is one VSYNC (1/60 s).

The disc is divided into 14 zones of constant sectors per revolution; the head travels about
1606.48 tracks across each full zone. The time is a step function of the track distance plus half
a rotation at the target zone, in VSYNCs of 1000/60 ms:

| track distance | time |
| --- | --- |
| sector gap < 5 | 9 VSYNC + half a rotation |
| <= 80 | 16 VSYNC + half a rotation |
| <= 160 | 22 VSYNC + half a rotation |
| <= 644 | 22 VSYNC + half a rotation + (distance - 161) * 16.66 / 80 ms |
| more | 36 VSYNC + (distance - 644) * 16.66 / 195 ms |

C20: `seektime.c` begins with `if (gap < 2) {3 VSYNC}` and then `if (gap < 5)` (not `else if`), so
the 3-VSYNC value is always overwritten and a gap of 0-1 costs 9 VSYNC + half a rotation as for 2-4;
the printed number is that of the code as written, which is what is built here. The audio-seek
measurement (`seekaud_huc`: confirmation versus actual playback) is not applied (U8).
"""

from __future__ import annotations

VSYNC_MS = 1000 / 60
TRACKS_PER_FULL_ZONE = 1606.48

# (sectors per revolution, first sector, last sector, rotation ms)
ZONES = (
    (10, 0, 12572, 133.47),
    (11, 12573, 30244, 146.82),
    (12, 30245, 49523, 160.17),
    (13, 49524, 70408, 173.51),
    (14, 70409, 92900, 186.86),
    (15, 92901, 116998, 200.21),
    (16, 116999, 142703, 213.56),
    (17, 142704, 170014, 226.90),
    (18, 170015, 198932, 240.25),
    (19, 198933, 229456, 253.60),
    (20, 229457, 261587, 266.95),
    (21, 261588, 295324, 280.29),
    (22, 295325, 330668, 293.64),
    (23, 330669, 333012, 306.99),
)


def _zone(lba: int) -> int:
    for i, (_, first, last, _) in enumerate(ZONES):
        if first <= lba <= last:
            return i
    return 0 if lba < 0 else len(ZONES) - 1 if lba > ZONES[-1][2] else 0


def seek_time_ms(start: int, target: int) -> float:
    src, dst = _zone(start), _zone(target)
    per_rev = ZONES[dst][0]
    if src == dst:
        tracks = abs(target - start) // per_rev
    elif dst > src:
        tracks = (ZONES[src][2] - start) // ZONES[src][0] + (target - ZONES[dst][1]) // per_rev
        tracks += TRACKS_PER_FULL_ZONE * (dst - src - 1)
    else:
        tracks = (start - ZONES[src][1]) // ZONES[src][0] + (ZONES[dst][2] - target) // per_rev
        tracks += TRACKS_PER_FULL_ZONE * (src - dst - 1)
    half = ZONES[dst][3] / 2
    gap = abs(target - start)
    if gap < 5:
        return 9 * VSYNC_MS + half
    if tracks <= 80:
        return 16 * VSYNC_MS + half
    if tracks <= 160:
        return 22 * VSYNC_MS + half
    if tracks <= 644:
        return 22 * VSYNC_MS + half + (tracks - 161) * 16.66 / 80
    return 36 * VSYNC_MS + (tracks - 644) * 16.66 / 195
