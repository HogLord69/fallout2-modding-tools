#!/usr/bin/env python3
"""
clcamp_links.py - join the refugee camp (CLCAMP.MAP) to Clairemont with exit
grids. The camp had none, and the Clairemont area has no town-map screen, so
nothing could reach it.

    python tools/clcamp_links.py --preview build/cl    # write test copies + renders, nothing else
    python tools/clcamp_links.py                       # write both maps (backups kept)

The camp lies south of town, out past the farm shacks:
  * Clairemont.map: a strip along the bottom edge of the map, below the
    brahmin pen and the farm shack, leads to the camp's top edge
  * CLCAMP.MAP: a strip along the top edge, above Boot Hill and the shooting
    range, leads back into town just above the strip there
Both strips run along a straight screen edge, which on the hex grid is a line
of constant  s = y - (199 - x) // 2.  Only floored hexes the player can walk
to from the map's start are used. Data only: nothing on either map moves.
Both copies of each map (mod/data/maps and base/mods/foc/maps) are written
when they match; old files go to _safety_backups/clcamp_links/. Refuses while
gecko or the game is running.
"""

from __future__ import annotations

import argparse
import shutil
import struct
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foclib import GameIndex  # noqa: E402
from foclib.formats import MapFile  # noqa: E402
from mapbuild import MapBuilder, MapObjectSpec  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
AUTH = ROOT / "mod" / "data" / "maps"
DEPL = ROOT / "base" / "mods" / "foc" / "maps"
BACKUP = ROOT / "_safety_backups" / "clcamp_links"
W = 200
DIRS = {0: (-1, W - 1, W, W + 1, 1, -W), 1: (-W - 1, -1, W, 1, 1 - W, -W)}
EXIT_PID = 0x05000010
CLAIREMONT_ID, CLCAMP_ID = 210, 213

# name: (map id, x range, s range of the strip, destination map id, destination tile)
STRIPS = {
    "Clairemont.map": (CLAIREMONT_ID, range(134, 153), range(124, 127), CLCAMP_ID, 39 * W + 53),
    "CLCAMP.MAP": (CLCAMP_ID, range(46, 61), range(-43, -40), CLAIREMONT_ID, 149 * W + 140),
}


def s_of(t):
    return t // W - (199 - t % W) // 2


def reachable(raw, m, gi, start):
    blocked, exits = set(), set()
    for o in m.objects:
        if o.elevation != 0 or not (0 <= o.tile < 40000):
            continue
        t = o.pid >> 24
        flags = struct.unpack_from(">I", raw, o.off + 0x24)[0]
        if t == 5 and 0x05000010 <= o.pid <= 0x05000017:
            exits.add(o.tile)
        elif t in (2, 3) and not flags & 0x10:
            pr = gi.proto(o.pid) if t == 2 else None
            if pr is not None and pr.subtype == 0:
                continue
            blocked.add(o.tile)
    fl = m.floors[m.elevations.index(0)]

    def floor(t):
        return fl[(t // W // 2) * 100 + (t % W) // 2] > 1
    seen = {start}
    q = deque([start])
    while q:
        t = q.popleft()
        if t in exits:
            continue
        for d in DIRS[(t % W) & 1]:
            x = t + d
            if 0 <= x < 40000 and abs(x % W - t % W) <= 1 and x not in seen and x not in blocked and floor(x):
                seen.add(x)
                q.append(x)
    return seen, exits


def build(name, gi):
    raw = (AUTH / name).read_bytes()
    if (DEPL / name).read_bytes() != raw:
        sys.exit(f"{name}: the deployed copy differs from mod/data/maps; run tools/sync_maps.py first")
    m = MapFile.parse(raw, gi.proto)
    map_id, xs, ss, dest_map, dest_tile = STRIPS[name]
    if any(0x05000010 <= o.pid <= 0x05000017 and o.elevation == 0 and
           struct.unpack_from(">i", raw, MapFile._read_object(raw, o.off, gi.proto)[1] - 16)[0] == dest_map
           for o in m.objects):
        sys.exit(f"{name}: already has exit grids to map {dest_map}")
    seen, exits = reachable(raw, m, gi, m.default_tile)
    tiles = sorted(t for t in seen if t % W in xs and s_of(t) in ss and t not in exits)
    if not tiles:
        sys.exit(f"{name}: no hexes for the strip")
    builder = MapBuilder(name, elevations=tuple(m.elevations), map_id=map_id)
    pr = gi.proto(EXIT_PID)
    flags = pr.flags - (1 << 32) if pr.flags >= 1 << 31 else pr.flags
    extra = bytearray()
    for t in tiles:
        buf = bytearray()
        builder._write_object(buf, MapObjectSpec(pid=EXIT_PID, fid=pr.fid, tile=t, elevation=0, flags=flags,
                                                 extras=(dest_map, dest_tile, 0, 0)))
        extra += buf
    # append to elevation 0: total count, then the elevation-0 count, then its records
    first = m.objects[0].off
    total_off = first - 8
    total = struct.unpack_from(">i", raw, total_off)[0]
    e0 = struct.unpack_from(">i", raw, total_off + 4)[0]
    e0_objs = [o for o in m.objects if o.elevation == 0]
    e0_end = MapFile._read_object(raw, e0_objs[-1].off, gi.proto)[1] if e0_objs else total_off + 8
    out = bytearray(raw[:e0_end]) + extra + raw[e0_end:]
    struct.pack_into(">i", out, total_off, total + len(tiles))
    struct.pack_into(">i", out, total_off + 4, e0 + len(tiles))
    MapFile.parse(bytes(out), gi.proto)
    xs_used = [t % W for t in tiles]
    print(f"{name}: {len(tiles)} exit grids, x {min(xs_used)}-{max(xs_used)}, "
          f"-> map {dest_map} tile {dest_tile} ({dest_tile % W},{dest_tile // W})")
    return bytes(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--preview", metavar="DIR")
    args = ap.parse_args()
    running = subprocess.run(["tasklist"], capture_output=True, text=True).stdout.lower()
    if not args.preview and ("gecko" in running or "fallout2" in running):
        sys.exit("close gecko and the game first")
    gi = GameIndex(pristine=False)
    results = {name: build(name, gi) for name in STRIPS}
    if args.preview:
        d = Path(args.preview)
        d.mkdir(parents=True, exist_ok=True)
        for name, data in results.items():
            (d / f"preview_{name}").write_bytes(data)
        print(f"--preview: test copies in {d}; nothing written")
        return 0
    BACKUP.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    for name, data in results.items():
        shutil.copy2(AUTH / name, BACKUP / f"{name}.{stamp}")
        (AUTH / name).write_bytes(data)
        (DEPL / name).write_bytes(data)
        print(f"wrote {name} (old copy in {BACKUP.relative_to(ROOT)})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
