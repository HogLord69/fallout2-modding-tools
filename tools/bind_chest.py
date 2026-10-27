#!/usr/bin/env python3
"""
bind_chest.py - attach the rwchest starting-gear script to the barracks chest.

    python tools/bind_chest.py --pid 0x020000B4 [--square 53,29]

Round-trips the map through MapBuilder (same mechanism as bind_scripts.py),
PRESERVING every object's existing script binding (the deployed map has the
8 NPC scripts + focstart from map_finalize - a naive rebuild would silently
strip them), and adds the chest's SID to the scenery script table.

Script index bases: scripts.lst lines are 1-based (foc_ids.h SCRIPT_*
defines are those lines); a map stores the 0-based index, so every id here
is `define - 1`.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foclib import (  # noqa: E402
    GameIndex,
    MapFile,
    hex_xy,
    pid_type,
)
from mapbuild import MapBuilder, MapObjectSpec, extras_for  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

SCRIPT_RWCHEST = 1610 - 1          # 0-based scripts.lst index (registry line 11)
SCRIPT_FOCSTART = 1600             # 1-based: the map's own header script
SCRIPT_TYPE_SCENERY = 3            # items and scenery
SCRIPT_TYPE_CRITTER = 4


def read_critter_extras(data: bytes, off: int):
    base = off + 72 + 12
    return struct.unpack_from(">10i", data, base + 4)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", default="mod/data/maps/REDWELL.MAP")
    ap.add_argument("--pid", required=True, help="chest proto pid, e.g. 0x020000B4")
    ap.add_argument("--square", default=None, help="row,col to disambiguate repeated pids")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    gi = GameIndex()
    path = ROOT / args.map
    raw = path.read_bytes()
    m = MapFile.parse(raw, gi.proto)

    mb = MapBuilder(path.name, elevations=tuple(m.elevations),
                    map_id=200, map_script_index=SCRIPT_FOCSTART)
    for i, _elev in enumerate(m.elevations):
        mb.floors[i] = list(m.floors[i])
        mb.roofs[i] = list(m.roofs[i])
    mb.start_tile = m.default_tile
    mb.start_elevation = getattr(m, "default_elevation", 0)
    mb.start_rotation = getattr(m, "default_rotation", 0)

    # locate the chest object
    pid_int = int(args.pid, 0)
    matches = [o for o in m.objects
               if o.pid == pid_int and 0 <= o.tile < 40000]
    if not matches:
        sys.exit(f"no object with pid 0x{pid_int:08X} on the map")
    if args.square:
        sr, sc = (int(x) for x in args.square.split(","))

        def dist2(o):
            hx, hy = hex_xy(o.tile)
            return (hx // 2 - sc) ** 2 + (hy // 2 - sr) ** 2

        matches.sort(key=dist2)
    chest = matches[0]
    hx, hy = hex_xy(chest.tile)
    print(f"chest: square ({hx // 2},{hy // 2}) pid=0x{chest.pid:08X} "
          f"({len(matches)} match(es) for pid)")

    chest_sid = mb.add_script(SCRIPT_TYPE_SCENERY, SCRIPT_RWCHEST)

    bound = 0
    carried = 0
    for o in m.objects:
        if not (0 <= o.tile < 40000):
            continue
        t = pid_type(o.pid)
        pr = gi.proto(o.pid)
        if pr is None:
            continue
        if t == 1:  # critter
            extras = read_critter_extras(raw, o.off)
        else:
            extras = extras_for(t, o.pid, pr.subtype)

        sid, sidx = -1, -1
        if o is chest:
            sid = chest_sid
            sidx = SCRIPT_RWCHEST
            bound += 1
        elif getattr(o, "script_index", -1) not in (-1, 0xFFFFFFFF):
            # carry the existing binding: type from pid_type, index as stored
            stype = SCRIPT_TYPE_CRITTER if t == 1 else SCRIPT_TYPE_SCENERY
            sid = mb.add_script(stype, o.script_index)
            sidx = o.script_index
            carried += 1

        mb.add(MapObjectSpec(
            pid=o.pid, fid=o.fid, tile=o.tile, elevation=o.elevation,
            rotation=o.rotation, frame=o.frame,
            sid=sid, script_index=sidx, extras=extras))

    print(f"bound chest: {bound}, carried existing scripts: {carried}")

    out = mb.to_bytes()
    if args.dry_run:
        print(f"dry run: would write {len(out)} bytes to {path}")
        return 0
    path.write_bytes(out)

    check = MapFile.parse(path.read_bytes(), gi.proto)
    scripted = [o for o in check.objects if o.script_index not in (-1, 0xFFFFFFFF)]
    print(f"  {path.relative_to(ROOT)}: {len(check.objects)} objects, "
          f"{len(scripted)} carrying a script")
    for o in scripted:
        hx, hy = hex_xy(o.tile)
        print(f"    square ({hx // 2:2d},{hy // 2:2d})  pid=0x{o.pid:08X}  "
              f"script_index={o.script_index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())