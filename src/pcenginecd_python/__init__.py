"""pcenginecd-python: the CD-ROM² / Super CD-ROM² add-on to pcengine-python, through its sockets."""

from pcengine_python.state import register_package

from pcenginecd_python.arcade import ArcadeCard
from pcenginecd_python.board import PcEngineCd
from pcenginecd_python.disc import Disc, Track
from pcenginecd_python.syscard import SystemCard
from pcenginecd_python.unit import CdUnit

# Save states (pcengine_python.state) hold this package's objects too: the CD unit, the drive, the
# ADPCM unit, the Arcade Card; the disc is media and is named by its table of contents only.
register_package("pcenginecd_python")

__all__ = ["ArcadeCard", "CdUnit", "Disc", "PcEngineCd", "SystemCard", "Track"]
