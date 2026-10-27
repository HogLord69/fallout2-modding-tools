#!/usr/bin/env python3
"""
Probe: is the tileset "grammar" of a map actually extractable from the bytes?

Reads the square-tile block of every map in the base and asks:
  - how many distinct floor tiles does one map use?
  - do tiles cluster into reusable kits (tiles that keep appearing together)?

If the answer is yes, a fragment/kit library is buildable from the ~1300 maps
on this machine. If maps each use a scattered, unrepeatable mix, it is not.
"""

import collections
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from foclib import GameIndex, parse_lst  # noqa: E402


def tile_block(data: bytes, m) -> tuple[list[int], list[int]]:
    """Floor and roof ids for every square of every elevation. Big-endian."""
    p = 0xEC + 4 * m.num_global_vars + 4 * m.num_local_vars
    floors, roofs = [], []
    for _ in m.elevations:
        for _sq in range(10000):
            roof, floor = struct.unpack_from(">HH", data, p)
            p += 4
            roofs.append(roof)
            floors.append(floor)
    return floors, roofs


def main() -> int:
    gi = GameIndex()
    names = sorted({n for prov in gi.vfs.providers if prov.kind == "dat"
                    for n in prov.dat.names() if n.lower().endswith(".map")},
                   key=str.lower)
    tiles_lst = parse_lst(gi.vfs.read("art\\tiles\\tiles.lst"))

    per_map: dict[str, collections.Counter] = {}
    for n in names:
        data = gi.vfs.read(n)
        m = gi.load_map(data)
        floors, _ = tile_block(data, m)
        c = collections.Counter(f for f in floors if f > 1)   # 1 == no tile
        if c:
            per_map[n] = c

    print(f"maps with floor data : {len(per_map)} / {len(names)}")
    sizes = sorted(len(c) for c in per_map.values())
    print(f"distinct floor tiles per map: min {sizes[0]}, "
          f"median {sizes[len(sizes)//2]}, max {sizes[-1]}")

    # Which tiles co-occur? Count how many maps each pair shares.
    pair = collections.Counter()
    solo = collections.Counter()
    for c in per_map.values():
        top = [t for t, _ in c.most_common(12)]
        for t in top:
            solo[t] += 1
        for i in range(len(top)):
            for j in range(i + 1, len(top)):
                pair[tuple(sorted((top[i], top[j])))] += 1

    def name_of(tid):
        return tiles_lst[tid - 1] if 0 < tid <= len(tiles_lst) else f"<{tid}>"

    print("\nStrongest tile pairings (appear together as majority floor across maps):")
    for (a, b), n in pair.most_common(12):
        print(f"  {n:4d} maps   {name_of(a):<14s} + {name_of(b)}")

    print("\nMost reused floor tiles overall:")
    for t, n in solo.most_common(10):
        print(f"  {n:4d} maps   {name_of(t)}")

    print("\nExample: floor vocabulary of three interiors")
    for n in ("maps\\ARCAVES.MAP", "maps\\denbus1.map", "maps\\vault13.map"):
        if n in per_map:
            top = per_map[n].most_common(6)
            total = sum(per_map[n].values())
            print(f"  {n}  ({total} squares)")
            for t, c in top:
                print(f"      {c:6d}  {name_of(t)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
