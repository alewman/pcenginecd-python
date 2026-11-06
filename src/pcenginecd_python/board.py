"""The CD-ROM² / Super CD-ROM² machine: the pinned PC Engine board plus a System Card and a CD unit.

Composition through the base board's sockets (docs/start-here.md):

- socket 1 (HuCard slot): the System Card (`SystemCard`), which also holds the Super System
  Card's RAM at `$68-$7F` and its id registers;
- socket 2 (expansion port): `CdUnit` claims CD RAM (`$80-$87`), BRAM (`$F7`) and `$1800-$18FF`,
  and pulls the I/O port's bit 7 low (`present`);
- socket 6 (interrupts): the unit's bit "cd" on the board's IRQ2 line;
- socket 9 (audio): the CD-DA player is appended to `board.audio_sources`;
- socket 5 (clock domains): the board catches the unit up to its clock **every advance**
  (base issue 0002, bc31f9c; before that this module subclassed the scheduler, finding S1).
"""

from __future__ import annotations

from pathlib import Path

from pcengine_python.board import Board
from pcengine_python.machine import PC_ENGINE, Machine
from pcengine_python.system import System, build

from pcenginecd_python.disc import Disc
from pcenginecd_python.syscard import SystemCard
from pcenginecd_python.unit import CdUnit


class PcEngineCd:
    """A CD-ROM² system. `system_card` is the BIOS image (bring your own, read in place)."""

    def __init__(
        self,
        system_card: bytes | str | Path,
        disc: Disc | None = None,
        *,
        machine: Machine = PC_ENGINE,
        super_system_card: bool | None = None,
        region_us: bool = False,
        bram: bytes | None = None,
        **board_kwargs,
    ) -> None:
        data = system_card if isinstance(system_card, bytes) else Path(system_card).read_bytes()
        self.card = SystemCard(data, super_system_card=super_system_card, region_us=region_us)
        self.unit = CdUnit(disc, bram=bram, card=self.card)
        self.board = Board(machine, card=self.card, port=self.unit, **board_kwargs)
        self.board.audio_sources.append(self.unit.cdda)
        self.board.audio_sources.append(self.unit.adpcm_source)

    def build(self, cpu_class: type | None = None) -> System:
        """The real HuC6280 core on this board."""
        return build(self.board, cpu_class)
