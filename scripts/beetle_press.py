#!/usr/bin/env python3
"""Run Beetle PCE (libretro, detector, tier 5) on a CD with RUN held from frame N, save the picture.

    python3 -I scripts/beetle_press.py DISC.chd --frames 900 --press-at 300 --png out.png [--hold 0]

It reuses the base board's `scripts/libretro_run.py` (loaded by path, not copied) and replaces its
input and poll callbacks: RUN is libretro's START (id 3) and SELECT id 2 on port 0; `--hold N`
releases it after N frames (0 = never). Needs Pillow: system python3.
"""

import argparse
import ctypes
import importlib.util
import sys
from pathlib import Path

BASE = Path("/data/emu/pcengine-python")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("disc", type=Path)
    ap.add_argument("--frames", type=int, default=900)
    ap.add_argument("--press-at", type=int, default=300)
    ap.add_argument("--hold", type=int, default=0)
    ap.add_argument("--png", type=Path, required=True)
    ap.add_argument("--audio", type=Path)
    ap.add_argument("--system", type=Path, default=Path("/data/emu/share/batocera/bios"))
    ap.add_argument(
        "--core", type=Path, default=BASE / "reference/src/beetle-pce/mednafen_pce_libretro.so"
    )
    a = ap.parse_args()
    spec = importlib.util.spec_from_file_location("libretro_run", BASE / "scripts/libretro_run.py")
    lr = importlib.util.module_from_spec(spec)
    state = {"frame": 0}
    spec.loader.exec_module(lr)

    def poll():
        state["frame"] += 1

    def pressed(port, device, index, button):
        state["queries"] = state.get("queries", 0) + 1
        state.setdefault("seen", set()).add((port, device, index, button))
        held = state["frame"] >= a.press_at and (not a.hold or state["frame"] < a.press_at + a.hold)
        if port != 0 or not held:
            return 0
        if button == 256:  # RETRO_DEVICE_ID_JOYPAD_MASK: all buttons as a bit mask
            return 1 << 3
        state["hits"] = state.get("hits", 0) + (button == 3)
        return 1 if button == 3 else 0

    # libretro_run builds its callbacks inside main(): intercept ctypes.CFUNCTYPE so the poll
    # (no arguments, no result) and input (four uints, int16) prototypes wrap our functions.
    real = ctypes.CFUNCTYPE

    def cfunctype(restype, *argtypes):
        proto = real(restype, *argtypes)
        if restype is None and len(argtypes) == 4 and argtypes[3] is ctypes.c_size_t:

            def wrap(f):
                def video(data, w, h, pitch):
                    state["video_calls"] = state.get("video_calls", 0) + 1
                    if data:
                        state["video_data"] = state.get("video_data", 0) + 1
                        state["video_last"] = (state["frame"], w, h)
                    f(data, w, h, pitch)

                return proto(video)

            return wrap
        if restype is None and not argtypes:
            return lambda _f: proto(poll)
        if restype is ctypes.c_int16 and len(argtypes) == 4:
            return lambda _f: proto(pressed)
        return proto

    ctypes.CFUNCTYPE = cfunctype
    sys.argv = [
        "libretro_run",
        str(a.core),
        str(a.disc),
        "--system",
        str(a.system),
        "--frames",
        str(a.frames),
        "--png",
        str(a.png),
    ] + (["--audio", str(a.audio)] if a.audio else [])
    result = lr.main()
    print(
        "input queries",
        state.get("queries"),
        sorted(state.get("seen", ()))[:12],
        "polls",
        state["frame"],
        "hits",
        state.get("hits"),
        "video",
        state.get("video_calls"),
        state.get("video_data"),
        state.get("video_last"),
    )
    return result


if __name__ == "__main__":
    sys.exit(main())
