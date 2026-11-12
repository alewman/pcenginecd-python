"""Save states: the base board's `state.py` over the CD machine (unit, drive, ADPCM, Arcade Card).

The card here is NOPs; the run that exercises the drive is tests/test_state_slow.py."""

import json
import zlib

import pytest
from discs import disc_audio_then_data, disc_data_only
from pcengine_python.state import StateError, load_state, save_state

from pcenginecd_python import PcEngineCd


def image() -> bytes:
    """A System Card that is only NOPs and its reset vector (to $E000)."""
    data = bytearray([0xEA]) * (256 * 1024)
    data[-2:] = b"\x00\xe0"
    return bytes(data)


def running(disc=None, **kwargs):
    cd = PcEngineCd(image(), disc if disc is not None else disc_data_only(), **kwargs)
    return cd, cd.build()


def test_the_unit_the_adpcm_ram_and_the_arcade_card_come_back():
    cd, system = running(arcade_card=True)
    cd.unit.adpcm.ram[0x1234] = 0x5A
    cd.unit.adpcm.write_ptr = 0x2345
    cd.arcade.ram[0x1F_0000] = 0xA5
    cd.arcade.base[2] = 0x12_3456
    for _ in range(2000):
        system.step()
    other, loaded = running(arcade_card=True)
    load_state(loaded, save_state(system))
    assert other.unit.adpcm.ram[0x1234] == 0x5A and other.unit.adpcm.write_ptr == 0x2345
    assert other.arcade.ram[0x1F_0000] == 0xA5 and other.arcade.base[2] == 0x12_3456
    assert other.board.port is other.unit and other.board.audio_sources[1] is other.unit.cdda
    assert save_state(loaded) == save_state(system)
    for _ in range(2000):
        system.step()
        loaded.step()
    assert save_state(loaded) == save_state(system)


def test_a_state_names_the_disc_by_its_contents_table_and_holds_no_sector():
    _cd, system = running()
    state = save_state(system)
    body = json.loads(zlib.decompress(state))
    assert "pcenginecd_python" in body["packages"]
    assert len(state) < 200_000  # no disc, no System Card image
    _other, loaded = running(disc_audio_then_data())
    with pytest.raises(StateError, match="other media"):
        load_state(loaded, state)


def test_a_machine_without_the_arcade_card_refuses_a_state_made_with_it():
    _cd, system = running(arcade_card=True)
    state = save_state(system)
    _other, plain = running()
    with pytest.raises(StateError):
        load_state(plain, state)
