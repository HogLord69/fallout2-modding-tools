#!/usr/bin/env python3
"""
map_finalize.py - adopt a hand-authored map as the playable REDWELL.MAP.

    python tools/map_finalize.py [--map <file.map>] [--dry-run]

The owner built "Redwell Fin" in gecko/Mapper2 (a vanilla ruined-city map
edited by hand). This tool turns that raw map into the mod's tier-0 map:

  * copies it to mod/data/maps/REDWELL.MAP
  * retitles the header name to REDWELL.MAP
  * sets the FOC map id (200) and binds focstart.int as the map script
  * binds the five named colony NPCs to the critters standing at fixed
    squares, by SQUARE not by proto - the owner was explicit that the
    critter sprites are just the look, so identity is position-based.
    Any critter at those squares is that character, whatever it wears.

NPC binding table (square (col,row) -> script):
    (49,31)  rwleadr  Arren, the north leader (gathered group)
    (56,44)  rwelder  Callum, the Elder (by the core building)
    (52,28)  rwghoul  Nettle, the ghoul
    (50,27)  rwkeeper Sable, the memory-keeper / farmhand
    (49,23)  rwwatch  Rem, the lookout (north group)

Uses the same MapBuilder round-trip as bind_scripts.py (MIT-relied on the
validated writer/reader symmetry), so object bytes and script tables are
rebuilt consistently. Vanilla-only assets: gecko cannot resolve rpu.dat.
"""

from __future__ import annotations

import argparse
import shutil
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
from car_blockers import blocker_specs  # noqa: E402


def read_critter_extras(data: bytes, off: int):
    """A critter's own combat block, copied verbatim so it keeps the proto's
    hp rather than defaulting to 0 - a critter with hp=0 renders as a corpse."""
    base = off + 72 + 12          # past the header, past the inventory triple
    return struct.unpack_from(">10i", data, base + 4)


ROOT = Path(__file__).resolve().parent.parent

# foc_ids.h carries the 1-based scripts.lst line; a map stores the 0-based index.
SCRIPT_FOCSTART = 1600           # 1-based line: the MAP's own script.
SCRIPT_RWDUNG = 1601 - 1
SCRIPT_RWLEADR = 1602 - 1
SCRIPT_RWELDER = 1603 - 1
SCRIPT_RWGHOUL = 1604 - 1
SCRIPT_RWKEEPER = 1605 - 1
SCRIPT_RWWATCH = 1606 - 1
SCRIPT_RWMERC1 = 1607 - 1
SCRIPT_RWMERC2 = 1608 - 1
SCRIPT_RWKILG = 1609 - 1
SCRIPT_TYPE_SCENERY = 3          # items and scenery
SCRIPT_TYPE_CRITTER = 4

# The named colonists, by the square they stand on. Identity is by
# position, NOT by proto (the owner: sprites are just the look).
#
# IMPORTANT: some critters on the map are brahmin (livestock), not people.
# The mabrom sprite (art index 15) is a brahmin. Keep those squares out of
# this table - a brahmin is not a colonist. Rem (rwwatch) therefore sits at
# square (48,28), a human nmmaxx, NOT at the old mabrom square (49,23).
NPC_BY_POS = {
    (49, 31): SCRIPT_RWLEADR,   # Arren - north leader (hmmaxx)
    (56, 44): SCRIPT_RWELDER,   # Callum - the Elder (narobe)
    (52, 28): SCRIPT_RWGHOUL,   # Nettle - the ghoul (naghul)
    (50, 27): SCRIPT_RWKEEPER,  # Sable - memory-keeper / farmhand (hflthr)
    (48, 28): SCRIPT_RWWATCH,   # Rem - lookout (nmmaxx, human)
    (54, 45): SCRIPT_RWMERC1,   # Dozer - hired gun (hmbmet, metal armor)
    (54, 46): SCRIPT_RWMERC2,   # Wren  - hired gun (nfmetl, metal armor)
    (53, 46): SCRIPT_RWKILG,    # Kilgore - trapper / beast-handler (nmlthr)
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", default=str(ROOT / "reference" / "gecko" / "build"
                                         / "resources" / "maps" / "Redwell Fin.map"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-car-blockers", action="store_true",
                    help="skip filling car / caravan-cart footprints with "
                         "invisible blocking hexes")
    args = ap.parse_args()

    gi = GameIndex()
    src = Path(args.map)
    if not src.is_file():
        sys.exit(f"source map not found: {src}")

    out_path = ROOT / "mod" / "data" / "maps" / "REDWELL.MAP"
    raw = src.read_bytes()
    m = MapFile.parse(raw, gi.proto)

    mb = MapBuilder("REDWELL.MAP", elevations=tuple(m.elevations),
                    map_id=200, map_script_index=SCRIPT_FOCSTART)
    for i, _elev in enumerate(m.elevations):
        mb.floors[i] = list(m.floors[i])
        mb.roofs[i] = list(m.roofs[i])
    mb.start_tile = m.default_tile
    mb.start_elevation = getattr(m, "default_elevation", 0)
    mb.start_rotation = getattr(m, "default_rotation", 0)

    # index critters by square for NPC binding
    by_sq: dict[tuple[int, int], list] = {}
    for o in m.objects:
        if pid_type(o.pid) != OBJ_TYPE_CRITTER:
            continue
        if not (0 <= o.tile < 40000):
            continue
        sq = ((o.tile % 200) // 2, (o.tile // 200) // 2)
        by_sq.setdefault(sq, []).append(o)

    counts = {k: 0 for k in ("leadr", "elder", "ghoul", "keeper", "watch",
                              "merc1", "merc2", "kilg")}
    bound = 0
    dung_seen = 0
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
        sq = ((o.tile % 200) // 2, (o.tile // 200) // 2)
        if t == OBJ_TYPE_CRITTER:
            want = NPC_BY_POS.get(sq)
            if want is not None:
                # bind only if this is a critter at that square
                sid = mb.add_script(SCRIPT_TYPE_CRITTER, want)
                sidx = want
                bound += 1
                for nm, s in (("leadr", SCRIPT_RWLEADR), ("elder", SCRIPT_RWELDER),
                                              ("ghoul", SCRIPT_RWGHOUL), ("keeper", SCRIPT_RWKEEPER),
                                              ("watch", SCRIPT_RWWATCH), ("merc1", SCRIPT_RWMERC1),
                                              ("merc2", SCRIPT_RWMERC2), ("kilg", SCRIPT_RWKILG)):
                    if s == want:
                        counts[nm] += 1
        elif (t in (0, 2)) and (o.pid & 0xFFFFFF) in (744, 745, 746, 747):
            # dung piles in any map keep the rwdung shovel quest
            sid = mb.add_script(SCRIPT_TYPE_SCENERY, SCRIPT_RWDUNG)
            sidx = SCRIPT_RWDUNG
            dung_seen += 1
            bound += 1

        mb.add(MapObjectSpec(
            pid=o.pid, fid=o.fid, tile=o.tile, elevation=o.elevation,
            rotation=o.rotation, frame=o.frame,
            sid=sid, script_index=sidx, extras=extras))

    print(f"adopted {src.name}: {len(m.objects)} objects, {len(m.elevations)} elevations")
    print(f"  map id 200, focstart map script, name REDWELL.MAP")
    print(f"  bound {bound} scripts: {counts} + dung {dung_seen}")

    if not args.no_car_blockers:
        specs = blocker_specs(m, gi)
        for s in specs:
            mb.add(s)
        print(f"  car/cart blocking hexes added: {len(specs)}")

    out_bytes = mb.to_bytes()

    check = MapFile.parse(out_bytes, gi.proto)
    scripted = [o for o in check.objects if o.script_index not in (-1, 0xFFFFFFFF)]
    print(f"  -> {len(check.objects)} objects, {len(scripted)} scripted")

    if args.dry_run:
        print("dry run: would write", out_path)
        return 0

    out_path.write_bytes(out_bytes)
    print(f"wrote {out_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
