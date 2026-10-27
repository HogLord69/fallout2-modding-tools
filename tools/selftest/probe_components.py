#!/usr/bin/env python3
"""
Where is the fragment yield going?

Prints the size distribution of floor components per map, so we can see whether
low-yield sources are losing rooms to the MIN/MAX size gates or to segmentation
failing outright.
"""

import collections
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import corpus  # noqa: E402
from foclib import GameIndex, hex_xy, pid_type  # noqa: E402
from foclib.formats import OBJ_TYPE_WALL  # noqa: E402
from port import load_sources  # noqa: E402

SQ_W = 100


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else "olympus"
    n_maps = int(sys.argv[2]) if len(sys.argv) > 2 else 12

    srcs = load_sources()
    gi = GameIndex(Path(srcs[which]["path"]), pristine=False)
    maps = sorted({n for prov in gi.vfs.providers if prov.kind == "dat"
                   for n in prov.dat.names() if n.lower().endswith(".map")},
                  key=str.lower)[:n_maps]

    buckets = collections.Counter()
    total_comps = 0
    for gp in maps:
        try:
            data = gi.vfs.read(gp)
            m = gi.load_map(data)
        except Exception:
            continue
        for ei, elev in enumerate(m.elevations):
            wall_sq = set()
            for o in m.objects:
                if o.elevation == elev and pid_type(o.pid) == OBJ_TYPE_WALL \
                        and 0 <= o.tile < 40000:
                    hx, hy = hex_xy(o.tile)
                    wall_sq.add((hy // 2) * SQ_W + (hx // 2))
            comps = corpus.segment(m, ei, wall_sq)
            total_comps += len(comps)
            for c in comps:
                n = len(c)
                if n < 12:
                    buckets["   <12 (too small)"] += 1
                elif n <= 900:
                    buckets["  12-900 (KEPT)"] += 1
                elif n <= 3000:
                    buckets[" 901-3000 (dropped)"] += 1
                else:
                    buckets[">3000 (dropped)"] += 1

    print(f"{which}: {len(maps)} maps, {total_comps} floor components")
    for k in sorted(buckets):
        print(f"  {k:22s} {buckets[k]:6d}")

    kept = buckets.get("  12-900 (KEPT)", 0)
    lost = total_comps - kept
    print(f"\n  kept {kept}, discarded {lost}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
