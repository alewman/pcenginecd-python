# pcenginecd-python

A readable, pure-Python **PC Engine CD-ROM² / Super CD-ROM²** (1988-1991), built as an **add-on to
[pcengine-python](../pcengine-python)**: the base board runs the HuC6280, the VCE, the PSG and the
VDC; this repository adds what the CD set has beyond a PC Engine, through the base board's
documented sockets and nothing copied: the **System Card** (a HuCard holding the BIOS, with the
Super System Card's 192 KiB of RAM and id registers), the **CD unit** (64 KiB CD RAM, 2 KiB backup
RAM, the `$1800-$180F` interface), the drive's **SCSI-class controller** (bus phases, REQ/ACK
handshake, the System Card's command set), the **track table** from bin/cue (or a CHD through
`chdman`) and **CD-DA** playback to the board's audio list.

**Status (2026-11-07): Milestone 9 (Arcade Card built, disc pictures not yet run), local only (no remote, no push).** See
[docs/m9-record.md](docs/m9-record.md) for the Arcade Card, [docs/m8-record.md](docs/m8-record.md) for the ADPCM unit, the judges and the U/C entries,
[docs/m7-record.md](docs/m7-record.md) for the CD unit core and [docs/m7-plan.md](docs/m7-plan.md) for
the M7 plan. The subchannel Q stream is **not built**; the Arcade Card (`PcEngineCd(..., arcade_card=True)`) is built
but its three discs have **not** been run (machine load, see the M9 record).
Python floor 3.11 (PyPy supports it); this is a reference board, correct, not fast.

```sh
python -m venv .venv-pypy   # PyPy 3.11 is the platform; CPython works for the tests
.venv-pypy/bin/python -m pip install -e ".[dev]"
.venv-pypy/bin/python -m pytest -q
```

The base board is pinned by git revision in `pyproject.toml` (github.com/alewman/pcengine-python); `docs/start-here.md`
says which sockets are used and what the base board does not do for an add-on. The System Card is
**bring-your-own**, read in place by path, and discs are read in place (bin/cue) or expanded by
`chdman extractcd` into a scratch directory: nothing of either is ever committed.

```python
from pcenginecd_python import Disc, PcEngineCd

cd = PcEngineCd("syscard3.pce", Disc.from_cue("game.cue"))
system = cd.build()  # the real HuC6280 core on the board
for _ in range(900):
    system.run_frame()
rows = cd.board.capture.last_frame.rows  # 242 rows of 9-bit palette values
```
