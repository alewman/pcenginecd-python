"""A save state taken while the real System Card reads a (synthetic) disc: the loaded run continues
as the run that was not interrupted. Slow (`pytest -m slow`), skipped without the BIOS and without
the base repository's working tree (its scripts/state_roundtrip.py is the check: tooling)."""

import os
import sys
from pathlib import Path

import pytest
from discs import disc_audio_then_data
from pcengine_python import pads

from pcenginecd_python import PcEngineCd

BIOS = Path("/data/emu/share/batocera/bios/syscard3.pce")
BASE = Path(os.environ.get("PCENGINE_PYTHON", "/data/emu/pcengine-python"))

pytestmark = [
    pytest.mark.slow,
    pytest.mark.skipif(not BIOS.exists(), reason="syscard3.pce not on this machine"),
    pytest.mark.skipif(not (BASE / "scripts/state_roundtrip.py").exists(), reason="no base tree"),
]


def test_a_state_saved_while_the_bios_reads_the_disc_continues_the_same():
    sys.path.insert(0, str(BASE / "scripts"))
    import presses
    from state_roundtrip import roundtrip

    def make():
        pad = pads.Pad2()
        cd = PcEngineCd(BIOS, disc_audio_then_data(40, 400), pad=pad)
        return cd.board, cd.build, pad

    passed, what = roundtrip(make, at=480, to=540, presses=presses.parse(["run@450+20"]))
    assert passed, what
