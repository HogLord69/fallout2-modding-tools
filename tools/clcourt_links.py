#!/usr/bin/env python3
"""
clcourt_links.py - reconnect the owner's courthouse (CLCOURT.MAP) after the
owner moved its ground floor in gecko (2026-10-15): the stairs from the
basement and from the second floor still landed where the stairs used to
be, and the map's exit grids were gone, so nobody could walk back to town.

    python tools/clcourt_links.py --dry-run
    python tools/clcourt_links.py

Data only; nothing the owner built moves:
  * the basement staircase (elevation 1) lands beside the stairwell down on
    the ground floor, and the second floor's stairwell lands beside the
    staircase up (each stair object's destination, tile | elevation << 29)
  * a strip of exit grids across the end of the road at the bottom of the
    car park leads back to Clairemont (CLAIREMONT.MAP tile 14616)
  * Clairemont.map's exit grids into the courthouse land at the road end
    instead of out in the sand
Both map copies (mod/data/maps and base/mods/foc/maps) are written when they
match; the old files go to _safety_backups/clcourt_links/. Refuses while gecko
or the game is running.
"""

from __future__ import annotations

import argparse
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foclib import GameIndex  # noqa: E402
from foclib.formats import MapFile  # noqa: E402
from mapbuild import MapBuilder, MapObjectSpec  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
AUTH = ROOT / "mod" / "data" / "maps"
DEPL = ROOT / "base" / "mods" / "foc" / "maps"
BACKUP = ROOT / "_safety_backups" / "clcourt_links"
W = 200
CLAIREMONT_ID, CLCOURT_ID = 210, 212
TOWN_ARRIVAL = 14616

STAIR, STAIRWELL = 0x0200015C, 0x02000164
# (elevation, tile of the stair object) -> (destination elevation, landing tile)
STAIR_FIX = {
    (1, 109 * W + 94): (0, 43 * W + 102),    # basement stairs up -> beside the stairwell at (101,42)
    (2, 120 * W + 122): (0, 47 * W + 150),   # second floor stairwell -> beside the stairs at (150,49)
}
ROAD_END_GRID = [(x, y) for y in (160, 161) for x in range(122, 136)]
COURT_ARRIVAL = 156 * W + 128                # the road, just above the exit strip
EXIT_PID = 0x05000010


def spans(raw: bytes, m: MapFile, gi):
    out = []
    for o in m.objects:
        _, end = MapFile._read_object(raw, o.off, gi.proto)
        out.append((o, o.off, end))
    return out


def rebuild(raw: bytes, m: MapFile, gi, edits, extra):
    """Rewrite the object section: edits(o, data) patches a record in place,
    extra is a list of (elevation, bytes) to append."""
    sp = spans(raw, m, gi)
    groups = {0: [], 1: [], 2: []}
    for o, a, b in sp:
        data = bytearray(raw[a:b])
        edits(o, data)
        groups[o.elevation].append(bytes(data))
    for e, d in extra:
        groups[e].append(d)
    out = bytearray(raw[:sp[0][1] - 8])
    out += struct.pack(">i", sum(len(g) for g in groups.values()))
    for e in (0, 1, 2):
        out += struct.pack(">i", len(groups[e]))
        for d in groups[e]:
            out += d
    MapFile.parse(bytes(out), gi.proto)
    return bytes(out)


def main() -> int:
    sys.exit("CLCOURT.MAP was moved to the middle of the grid by tools/shift_map.py (2026-10-18, --dx -34 --dy 14): the hexes below no longer apply, and the links were carried over by that move")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    running = subprocess.run(["tasklist"], capture_output=True, text=True).stdout.lower()
    if not args.dry_run and ("gecko" in running or "fallout2" in running):
        sys.exit("close gecko and the game first")
    gi = GameIndex(pristine=False)
    results = {}

    # --- the courthouse
    name = "CLCOURT.MAP"
    raw = (AUTH / name).read_bytes()
    if (DEPL / name).read_bytes() != raw:
        sys.exit(f"{name}: the deployed copy differs from mod/data/maps; run tools/sync_maps.py first")
    m = MapFile.parse(raw, gi.proto)
    have_grids = {o.tile for o in m.objects if o.elevation == 0 and 0x05000010 <= o.pid <= 0x05000017}
    fixed = []

    def court_edit(o, data):
        key = (o.elevation, o.tile)
        if o.pid in (STAIR, STAIRWELL) and key in STAIR_FIX:
            de, dt = STAIR_FIX[key]
            struct.pack_into(">i", data, 88, dt | (de << 29))
            struct.pack_into(">i", data, 92, -1)
            fixed.append(f"stairs e{o.elevation} ({o.tile % W},{o.tile // W}) -> e{de} ({dt % W},{dt // W})")

    builder = MapBuilder(name, elevations=tuple(m.elevations), map_id=CLCOURT_ID)
    pr = gi.proto(EXIT_PID)
    extra = []
    for x, y in ROAD_END_GRID:
        if y * W + x in have_grids:
            continue
        spec = MapObjectSpec(pid=EXIT_PID, fid=pr.fid, tile=y * W + x, elevation=0,
                             flags=pr.flags - (1 << 32) if pr.flags >= 1 << 31 else pr.flags,
                             extras=(CLAIREMONT_ID, TOWN_ARRIVAL, 0, 0))
        buf = bytearray()
        builder._write_object(buf, spec)
        extra.append((0, bytes(buf)))
    results[name] = rebuild(raw, m, gi, court_edit, extra)
    print(f"{name}: " + "; ".join(fixed) + f"; {len(extra)} exit grids to Clairemont")

    # --- Clairemont's way in
    name = "Clairemont.map"
    raw = (AUTH / name).read_bytes()
    if (DEPL / name).read_bytes() != raw:
        sys.exit(f"{name}: the deployed copy differs from mod/data/maps; run tools/sync_maps.py first")
    m = MapFile.parse(raw, gi.proto)
    n = [0]

    def town_edit(o, data):
        if 0x05000010 <= o.pid <= 0x05000017:
            dm = struct.unpack_from(">i", data, 88)[0]
            if dm == CLCOURT_ID:
                struct.pack_into(">i", data, 92, COURT_ARRIVAL)
                n[0] += 1

    results[name] = rebuild(raw, m, gi, town_edit, [])
    print(f"{name}: {n[0]} exit grids now land at ({COURT_ARRIVAL % W},{COURT_ARRIVAL // W}) on the courthouse road")

    if args.dry_run:
        print("--dry-run: nothing written")
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
