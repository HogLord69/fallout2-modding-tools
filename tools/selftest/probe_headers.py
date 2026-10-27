#!/usr/bin/env python3
"""
What does a .map header actually look like in maps that render correctly?

MDFG's authored maps loaded with zero errors and bound every script, but their
floors drew black. Its notes eliminated tile ids, light sources, the darkness
field and the roof word. So before writing a map generator, find out what real
maps agree on - especially the flags/elevation relationship, since writing one
elevation of tiles while claiming three would desynchronise nothing that the
loader checks but everything that the renderer reads.
"""

import collections
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from foclib import GameIndex  # noqa: E402


def main() -> int:
    gi = GameIndex()
    names = sorted({n for prov in gi.vfs.providers if prov.kind == "dat"
                    for n in prov.dat.names() if n.lower().endswith(".map")},
                   key=str.lower)

    flags = collections.Counter()
    elev_counts = collections.Counter()
    darkness = collections.Counter()
    gvars = collections.Counter()
    lvars = collections.Counter()
    versions = collections.Counter()
    flag_vs_elev = collections.Counter()
    roof_usage = collections.Counter()

    for n in names:
        data = gi.vfs.read(n)
        m = gi.load_map(data)
        versions[m.version] += 1
        flags[m.flags] += 1
        elev_counts[len(m.elevations)] += 1
        darkness[struct.unpack_from(">i", data, 0x2C)[0]] += 1
        gvars[m.num_global_vars] += 1
        lvars[m.num_local_vars] += 1
        flag_vs_elev[(m.flags, tuple(m.elevations))] += 1
        for e in range(len(m.elevations)):
            has_roof = any(r > 1 for r in m.roofs[e])
            roof_usage["roofed" if has_roof else "no roof"] += 1

    print(f"{len(names)} maps\n")
    print("version        :", dict(versions))
    print("flags          :", dict(flags.most_common()))
    print("elevation count:", dict(elev_counts.most_common()))
    print("darkness (0x2C):", dict(darkness.most_common()))
    print("num_global_vars:", dict(gvars.most_common(6)))
    print("num_local_vars :", dict(lvars.most_common(6)))
    print("roof layer     :", dict(roof_usage))
    print("\nflags -> which elevations exist:")
    for (f, e), c in sorted(flag_vs_elev.items()):
        print(f"  flags=0x{f:02X}  elevations={e}  ({c} maps)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
