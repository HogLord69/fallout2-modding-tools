#!/usr/bin/env python3
"""
ruins_vault.py - finish the concrete ruin in RWRUINS.MAP into the locked room
of Kilgore's ruins trip (scripts_src/foc/rw_vault.h).

    python tools/ruins_vault.py --preview build/rwruins_vault.png   # render only
    python tools/ruins_vault.py --write                             # write the map

city1's ruin north-west of the arrival point already has three walls and a
Fallout 1 door frame (dorfrm3/dorfrm4). This adds the missing corner in the
same concrete-block pieces (nec*.frm), swaps the ragged wall end at (66,93)
for a whole piece, and puts Fallout 1's necdoor2 in the frame and a
footlocker inside, so the room is part of the map and shows in gecko. The
door's script and lock, and what is in the locker, are added at runtime
(gl_foc.ssl attaches rwvdoor; rwruins.ssl fills the locker), because gecko
cannot write script ids.

The result is sealed: a flood fill from inside reaches the outside only
through the door hex (checked before writing).

--write refuses unless mod/data/maps and base/mods/foc/maps hold the same
RWRUINS.MAP (an unsynced gecko edit), and moves the old copy to
mod/data/maps/_replaced first. Run it once: it refuses a map that already
has the door.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foclib import GameIndex  # noqa: E402
from foclib.formats import MapFile, pid_type  # noqa: E402
from map_crop import AUTHORED, DEPLOYED, stash_existing  # noqa: E402
from mapbuild import MapBuilder, MapObjectSpec, extras_for  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NAME = "RWRUINS.MAP"
W = 200
DIR = [[-1, W - 1, W, W + 1, 1, -W], [-W - 1, -1, W, 1, 1 - W, -W]]

# pids, as in rw_vault.h
NEC_ROW = [50332236, 50332235, 50332239, 50332237, 50332238, 50332240, 50332236]  # nec096 095 099 097 098 100 096
NEC_CORNER = 50332154       # nec012
NEC_COL = 50332249          # nec109
NEC_BROKEN_END = 50332282   # nec140
NEC_BLOCK = 50332270        # block.frm
DOOR = 33554691             # necdoor2
LOCKER = 128                # PID_FOOTLOCKER_CLEAN_LEFT

DOOR_TILE = 92 * W + 82
INSIDE_TILE = 94 * W + 74
LOCKER_TILE = 95 * W + 72
BROKEN_END_TILE = 93 * W + 66


def additions() -> list[tuple[int, int]]:
    out = [(pid, 89 * W + x) for pid, x in zip(NEC_ROW, range(73, 66, -1))]
    out.append((NEC_CORNER, 89 * W + 66))
    out += [(NEC_BLOCK, 90 * W + x) for x in (67, 69, 71, 73)]
    out += [(NEC_COL, y * W + 66) for y in (90, 91, 92, 93)]
    out += [(DOOR, DOOR_TILE), (LOCKER, LOCKER_TILE)]
    return out


def build(gi: GameIndex, m: MapFile) -> MapBuilder:
    if any(o.pid == DOOR and o.tile == DOOR_TILE for o in m.objects):
        sys.exit(f"{NAME} already has the door; nothing to do")
    if m.num_global_vars or m.num_local_vars:
        sys.exit(f"{NAME} carries map vars; this round-trip would drop them")
    if any(o.script_index not in (-1, 0xFFFFFFFF) for o in m.objects):
        sys.exit(f"{NAME} has scripted objects; this round-trip does not carry them")
    mb = MapBuilder(NAME, elevations=tuple(m.elevations), map_id=m.map_id,
                    map_script_index=m.map_script_id)
    for i, _ in enumerate(m.elevations):
        mb.floors[i] = list(m.floors[i])
        mb.roofs[i] = list(m.roofs[i])
    mb.start_tile = m.default_tile
    mb.start_elevation = m.default_elevation
    mb.start_rotation = m.default_orientation
    for o in m.objects:
        if o.pid == NEC_BROKEN_END and o.tile == BROKEN_END_TILE:
            continue
        pr = gi.proto(o.pid)
        mb.add(MapObjectSpec(pid=o.pid, fid=o.fid, tile=o.tile, elevation=o.elevation,
                             rotation=o.rotation, frame=o.frame,
                             extras=extras_for(pid_type(o.pid), o.pid, pr.subtype if pr else None)))
    for pid, tile in additions():
        pr = gi.proto(pid)
        mb.add(MapObjectSpec(pid=pid, fid=pr.fid, tile=tile, elevation=0, rotation=0, frame=0,
                             extras=extras_for(pid_type(pid), pid, pr.subtype)))
    return mb


def sealed(gi: GameIndex, data: bytes) -> tuple[bool, int]:
    m = MapFile.parse(data, gi.proto)
    block = set()
    for o in m.objects:
        if o.elevation:
            continue
        t = pid_type(o.pid)
        pr = gi.proto(o.pid)
        if t == 3 or (t == 2 and pr and not (pr.flags & 0x10)):
            block.add(o.tile)
    seen, q = {INSIDE_TILE}, deque([INSIDE_TILE])
    while q:
        u = q.popleft()
        for d in DIR[(u % W) & 1]:
            n = u + d
            if 0 <= n < 40000 and abs(n % W - u % W) <= 1 and n not in seen and n not in block:
                seen.add(n)
                q.append(n)
    return DOOR_TILE in block and len(seen) < 400, len(seen)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--preview", type=Path)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    gi = GameIndex(pristine=False)
    src = AUTHORED / NAME
    raw = src.read_bytes()
    mb = build(gi, MapFile.parse(raw, gi.proto))
    out = mb.to_bytes()
    ok, n = sealed(gi, out)
    print(f"room: {n} hexes inside, {'sealed but for the door' if ok else 'NOT sealed'}")
    if not ok:
        return 1
    if args.preview:
        tmp = ROOT / "build" / "rwruins_vault_preview.MAP"
        tmp.write_bytes(out)
        subprocess.run([str(ROOT / "reference" / "gecko" / "build" / "gecko-cli.exe"), "map", "render",
                        "--map", str(tmp), "--out", str(args.preview), "--crop-hex", str(INSIDE_TILE),
                        "--crop-extent", "500", "--data", str(ROOT / "base" / "master.dat"),
                        "--data", str(ROOT / "base" / "critter.dat")], check=False)
    if args.write:
        dep = DEPLOYED / NAME
        if dep.is_file() and dep.read_bytes() != raw:
            sys.exit(f"{dep} differs from {src}: sync the gecko edit first (tools/sync_maps.py)")
        old = stash_existing(src)
        src.write_bytes(out)
        if dep.is_file():
            dep.write_bytes(out)
        print(f"wrote {src.relative_to(ROOT)} (old copy: {old.relative_to(ROOT) if old else 'none'})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
