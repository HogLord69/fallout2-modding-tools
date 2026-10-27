#!/usr/bin/env python3
"""
make_blank.py - a genuinely blank Redwell: open desert, nothing on it.

    python tools/make_blank.py [--name REDWELL_BLANK.MAP]

Copying a real map's tile layer wholesale is how you inherit somebody else's
landmarks. Arroyo's cave mouth, its tilled crop rows and a stone face are all
TILES, not objects, so stripping objects never removed them - the "blank" map
still had a cave in the corner and a face in the middle of the desert.

So this keeps the SHAPE of a real map's ground - which squares are floored, and
therefore where the walkable area is and how its edge is ragged - and replaces
every tile with plain desert ground drawn from the same map's own ground
vocabulary. That keeps the human tile variety (a median real map uses 91
distinct floor tiles; a single-tile fill reads as generated at a glance) while
carrying across no features at all.
"""

from __future__ import annotations

import argparse
import collections
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foclib import GameIndex, MapFile, parse_lst  # noqa: E402
from mapbuild import MapBuilder  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DONOR = "maps/ARVILLAG.MAP"

# Plain ground families. edg* are Fallout's transition/ground tiles and carry no
# scenery of their own; anything else in a desert map is a FEATURE - a cave, a
# ploughed row, a carved face - and is exactly what must not come across.
GROUND_PREFIXES = ("edg",)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="REDWELL_BLANK.MAP")
    ap.add_argument("--donor", default=DONOR)
    args = ap.parse_args()

    gi = GameIndex()
    rnd = random.Random(7)
    tiles = parse_lst(gi.vfs.read("art/tiles/tiles.lst"))

    donor = gi.load_map(gi.vfs.read(args.donor))
    di = donor.elevations.index(0) if 0 in donor.elevations else 0
    src = donor.floors[di]

    # the donor's own ground vocabulary, weighted as the donor uses it
    counts = collections.Counter()
    for tid in src:
        if 1 < tid < len(tiles) and tiles[tid]:
            n = tiles[tid].lower()
            if any(n.startswith(p) for p in GROUND_PREFIXES):
                counts[tid] += 1
    if not counts:
        sys.exit("donor has no plain ground tiles")
    pool = [tid for tid, c in counts.items() for _ in range(max(1, c // 8))]
    print(f"ground vocabulary: {len(counts)} distinct tiles from {args.donor}")

    mb = MapBuilder(args.name, elevations=(0,), map_id=201)
    kept = replaced = 0
    for sq, tid in enumerate(src):
        if tid <= 1:
            continue                       # outside the walkable shape
        n = tiles[tid].lower() if tid < len(tiles) and tiles[tid] else ""
        if any(n.startswith(p) for p in GROUND_PREFIXES):
            mb.floors[0][sq] = tid         # already plain ground
            kept += 1
        else:
            mb.floors[0][sq] = rnd.choice(pool)   # a feature - overwrite it
            replaced += 1
    mb.roofs[0] = [1] * 10000              # nothing is built yet
    mb.start_tile = 20100

    out = ROOT / "mod" / "data" / "maps" / args.name.upper()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(mb.to_bytes())

    m = MapFile.parse(out.read_bytes(), gi.proto)
    floored = sum(1 for v in m.floors[0] if v > 1)
    distinct = len({v for v in m.floors[0] if v > 1})
    print(f"  kept {kept} ground tiles, replaced {replaced} feature tiles")
    print(f"  {out.relative_to(ROOT)}: {len(m.objects)} objects, "
          f"{floored} floored squares, {distinct} distinct tiles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
