#!/usr/bin/env python3
"""
Which hex -> square mapping is right?

tile.cc mirrors x on BOTH grids (gridWidth - 1 - tile % gridWidth) and the
square's screen step is exactly 2x the hex's, so square = hex // 2 on both
axes. But the mirroring makes the off-by-one easy to get wrong, so decide it
with data instead of algebra.

Discriminator: objects overwhelmingly stand on floored ground. Score each
candidate formula by the fraction of objects that land on a square carrying a
real floor tile. The right formula should win clearly.
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from foclib import GameIndex  # noqa: E402

HEX_W = 200
SQ_W = 100


def floors_for(data, m):
    """Floor id per square, per elevation index."""
    p = 0xEC + 4 * m.num_global_vars + 4 * m.num_local_vars
    per_elev = []
    for _ in m.elevations:
        f = [0] * 10000
        for sq in range(10000):
            roof, floor = struct.unpack_from(">HH", data, p)
            p += 4
            f[sq] = floor
        per_elev.append(f)
    return per_elev


CANDIDATES = {
    "sq=(hy//2)*100+(hx//2)": lambda hx, hy: (hy // 2) * SQ_W + (hx // 2),
    "mirrored: 99-((199-hx)//2)": lambda hx, hy: (hy // 2) * SQ_W + (99 - ((199 - hx) // 2)),
    "sq=(hy//2)*100+((hx+1)//2)": lambda hx, hy: (hy // 2) * SQ_W + ((hx + 1) // 2),
}


def main() -> int:
    gi = GameIndex()
    names = sorted({n for prov in gi.vfs.providers if prov.kind == "dat"
                    for n in prov.dat.names() if n.lower().endswith(".map")},
                   key=str.lower)[:60]

    hits = {k: 0 for k in CANDIDATES}
    total = 0
    for n in names:
        data = gi.vfs.read(n)
        m = gi.load_map(data)
        if not m.elevations:
            continue
        per_elev = floors_for(data, m)
        elev_index = {e: i for i, e in enumerate(m.elevations)}
        for o in m.objects:
            if o.tile < 0 or o.tile >= 40000:
                continue
            ei = elev_index.get(o.elevation)
            if ei is None:
                continue
            floors = per_elev[ei]
            hx, hy = o.tile % HEX_W, o.tile // HEX_W
            total += 1
            for k, fn in CANDIDATES.items():
                sq = fn(hx, hy)
                if 0 <= sq < 10000 and floors[sq] > 1:
                    hits[k] += 1

    print(f"objects tested: {total} across {len(names)} maps\n")
    for k, v in sorted(hits.items(), key=lambda kv: -kv[1]):
        print(f"  {v/total:6.1%}  on a floored square   {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
