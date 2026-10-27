#!/usr/bin/env python3
"""
unbind_chest.py - remove the rwchest script binding from the chest objects
in REDWELL.MAP so Gecko can open the map without crashing.

    python tools/unbind_chest.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foclib import GameIndex, MapFile, hex_xy
from mapbuild import MapBuilder, MapObjectSpec, extras_for  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

CHEST_PIDS = [0x020000B4, 0x020000DC]
RWCHEST_SCRIPT = 1609


def main() -> int:
    path = ROOT / "mod" / "data" / "maps" / "REDWELL.MAP"
    gi = GameIndex()
    raw = path.read_bytes()
    m = MapFile.parse(raw, gi.proto)

    # Use the same rebuild approach as bind_chest.py
    from mapbuild import MapBuilder  # noqa: F401
    SCRIPT_FOCSTART = 1600
    SCRIPT_TYPE_SCENERY = 3
    SCRIPT_TYPE_CRITTER = 4

    def read_critter_extras(data: bytes, off: int):
        import struct
        base = off + 72 + 12
        return struct.unpack_from(">10i", data, base + 4)

    mb = MapBuilder(path.name, elevations=tuple(m.elevations),
                    map_id=200, map_script_index=SCRIPT_FOCSTART)
    for i, _elev in enumerate(m.elevations):
        mb.floors[i] = list(m.floors[i])
        mb.roofs[i] = list(m.roofs[i])
    mb.start_tile = m.default_tile
    mb.start_elevation = getattr(m, "default_elevation", 0)
    mb.start_rotation = getattr(m, "default_rotation", 0)

    from foclib import pid_type

    removed = 0
    carried = 0
    for o in m.objects:
        if not (0 <= o.tile < 40000):
            continue
        t = pid_type(o.pid)
        pr = gi.proto(o.pid)
        if pr is None:
            continue
        if t == 1:
            extras = read_critter_extras(raw, o.off)
        else:
            extras = extras_for(t, o.pid, pr.subtype)

        sid, sidx = -1, -1
        if o.pid in CHEST_PIDS and o.script_index == RWCHEST_SCRIPT:
            # Strip the chest script binding
            removed += 1
        elif getattr(o, "script_index", -1) not in (-1, 0xFFFFFFFF):
            stype = SCRIPT_TYPE_CRITTER if t == 1 else SCRIPT_TYPE_SCENERY
            sid = mb.add_script(stype, o.script_index)
            sidx = o.script_index
            carried += 1

        mb.add(MapObjectSpec(
            pid=o.pid, fid=o.fid, tile=o.tile, elevation=o.elevation,
            rotation=o.rotation, frame=o.frame,
            sid=sid, script_index=sidx, extras=extras))

    print(f"removed chest script from: {removed}, carried other scripts: {carried}")

    out = mb.to_bytes()
    path.write_bytes(out)
    print(f"wrote {path.relative_to(ROOT)} ({len(out)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
