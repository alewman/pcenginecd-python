# SPDX-License-Identifier: MIT
"""Boot the real Super System Card (bring-your-own, read in place) with a synthetic data disc.

Slow (about two minutes on PyPy under load: `pytest -m slow`) and skipped when the BIOS is not on
this machine. The disc is synthetic, so the BIOS reaches its screen and, after RUN, reads the disc
and finds no IPL; what is asserted is what the BIOS itself decides: the screen appears, the
drive is selected, and the BIOS's own commands (TEST UNIT READY, READ TOC, READ) go through the
SCSI path. Nothing of the BIOS is stored in the repository.
"""

import os
from pathlib import Path

import pytest
from discs import disc_audio_then_data
from pcengine_python import pads

from pcenginecd_python import PcEngineCd

# The System Card is the player's own image, named by $PCE_SYSTEM_CARD (never a path in
# the repository).
BIOS = Path(os.environ.get("PCE_SYSTEM_CARD", "/nonexistent/syscard3.pce"))

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not BIOS.exists(), reason="PCE_SYSTEM_CARD not set"),
]


def test_the_system_card_reaches_its_screen_and_reads_the_disc_after_run():
    pad = pads.Pad2()
    cd = PcEngineCd(BIOS, disc_audio_then_data(40, 400), pad=pad)
    cd.unit.bus.record_log = True
    system = cd.build()
    for frame in range(1, 701):
        if frame == 450:
            pad.pressed |= pads.RUN
        if frame == 470:
            pad.pressed &= ~pads.RUN
        system.run_frame()
        if frame == 300:
            splash = [list(r) for r in cd.board.capture.last_frame.rows]
    final = cd.board.capture.last_frame.rows
    lit = sum(1 for row in splash for v in row if v != splash[0][0])
    assert lit > 3000  # the logo is drawn
    commands = [text.split()[1] for _, text in cd.unit.bus.log]
    assert commands[:3] == ["00", "DE", "DE"]  # TEST UNIT READY, then READ TOC twice
    assert "08" in commands  # and it reads sectors
    assert final is not None
