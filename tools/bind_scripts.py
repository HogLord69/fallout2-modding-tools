#!/usr/bin/env python3
"""
bind_scripts.py - attach the quest scripts to a map gecko generated.

    python tools/bind_scripts.py [--map mod/data/maps/REDWELL.MAP]

Gecko builds the map; it cannot bind scripts. Its Luau API places protos and
paints tiles, but nothing in MapScriptApi writes a script id onto an object or
into the map's script table, so a generated map has Mose standing mute and dung
that ignores a shovel. This does that one step: parse the generated map, copy
it through our writer, and give the quest objects their SIDs.

WHY A ROUND-TRIP. objectLoadAllInternal looks a script up by the object's SID
in the map's script table and then OVERWRITES scriptIndex from it, so both the
table and the SID have to exist and agree. The table is a whole map section, so
adding one means rewriting the file - there is no in-place patch.

SCRIPT INDEX BASES. scripts.lst lines are 1-based and the SCRIPT_* defines in
foc_ids.h are those line numbers. The engine indexes its script array 0-based
(scripts.cc, scriptsGetFileName), which is what a map stores. So every id here
is `define - 1`. Getting this wrong does not error - it silently binds the
NEIGHBOURING script.
"""

from __future__ import annotations

import argparse
import collections
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foclib import (  # noqa: E402
    OBJ_TYPE_CRITTER,
    GameIndex,
    MapFile,
    hex_xy,
    pid_type,
)
from mapbuild import MapBuilder, MapObjectSpec, extras_for  # noqa: E402


def read_critter_extras(data: bytes, off: int):
    """A critter's own combat block, copied verbatim so it keeps the proto's
    hp rather than defaulting to 0 - a critter with hp=0 renders as a corpse."""
    base = off + 72 + 12          # past the header, past the inventory triple
    return struct.unpack_from(">10i", data, base + 4)

ROOT = Path(__file__).resolve().parent.parent

# foc_ids.h carries the 1-based scripts.lst line; a map stores the 0-based index.
SCRIPT_FOCSTART = 1600           # 1-based line: the MAP's own script.
SCRIPT_RWFARMER = 1601 - 1
SCRIPT_RWDUNG = 1602 - 1
SCRIPT_RWSABLE = 1603 - 1
SCRIPT_TYPE_SCENERY = 3          # items and scenery
SCRIPT_TYPE_CRITTER = 4

VILLAGER_PIDS = {(1 << 24) | 3, (1 << 24) | 4}
DUNG_PIDS = {(2 << 24) | n for n in (744, 745, 746, 747)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", default="mod/data/maps/REDWELL.MAP")
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

    # Mose is the villager standing nearest the well. Picking him by proximity
    # rather than by a hardcoded hex means the generator can move the well
    # without silently binding the script to some other villager.
    well_c, well_r = 50, 50
    villagers = [o for o in m.objects
                 if o.pid in VILLAGER_PIDS and 0 <= o.tile < 40000]
    if not villagers:
        sys.exit("no villager on the map - nobody to be Mose")

    def dist2(o):
        hx, hy = hex_xy(o.tile)
        return (hx // 2 - well_c) ** 2 + (hy // 2 - well_r) ** 2

    mose = min(villagers, key=dist2)
    sable = max(villagers, key=dist2)
    mhx, mhy = hex_xy(mose.tile)
    shx, shy = hex_xy(sable.tile)
    print(f"Mose: villager at square ({mhx // 2},{mhy // 2}), "
          f"{dist2(mose) ** 0.5:.1f} squares from the well")
    print(f"Sable: villager at square ({shx // 2},{shy // 2}), "
          f"{dist2(sable) ** 0.5:.1f} squares from the well")

    counts = collections.Counter()
    bound = 0
    for o in m.objects:
        if not (0 <= o.tile < 40000):
            continue
        t = pid_type(o.pid)
        pr = gi.proto(o.pid)
        if pr is None:
            continue
        if t == OBJ_TYPE_CRITTER:
            extras = read_critter_extras(raw, o.off)
        else:
            extras = extras_for(t, o.pid, pr.subtype)

        sid, sidx = -1, -1
        if o is mose:
            sid = mb.add_script(SCRIPT_TYPE_CRITTER, SCRIPT_RWFARMER)
            sidx = SCRIPT_RWFARMER
            counts["mose"] += 1
        elif o is sable:
            sid = mb.add_script(SCRIPT_TYPE_CRITTER, SCRIPT_RWSABLE)
            sidx = SCRIPT_RWSABLE
            counts["sable"] += 1
        elif o.pid in DUNG_PIDS:
            sid = mb.add_script(SCRIPT_TYPE_SCENERY, SCRIPT_RWDUNG)
            sidx = SCRIPT_RWDUNG
            counts["dung"] += 1
        if sid != -1:
            bound += 1

        mb.add(MapObjectSpec(
            pid=o.pid, fid=o.fid, tile=o.tile, elevation=o.elevation,
            rotation=o.rotation, frame=o.frame,
            sid=sid, script_index=sidx, extras=extras))

    print(f"bound {bound} scripts: {dict(counts)}")
    if not counts.get("dung"):
        sys.exit("no dung found - the shovel would have nothing to clear")

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
