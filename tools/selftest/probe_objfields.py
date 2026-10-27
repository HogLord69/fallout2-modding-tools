#!/usr/bin/env python3
"""
What do real maps put in the object fields a generator has to invent?

objectRead takes 18 int32s. Some are obvious (tile, pid, fid, elevation), but
id / x / y / sx / sy / cid / lightDistance / lightIntensity / outline are values
a writer has to make up. If real maps overwhelmingly store one value, use it;
if they vary, the engine probably recomputes and anything sane will do.
"""

import collections
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from foclib import GameIndex  # noqa: E402

FIELDS = ["id", "tile", "x", "y", "sx", "sy", "frame", "rotation", "fid",
          "flags", "elevation", "pid", "cid", "lightDist", "lightInt",
          "outline", "sid", "scriptIndex"]
INVENT = ["id", "x", "y", "sx", "sy", "cid", "lightDist", "lightInt", "outline"]


def main() -> int:
    gi = GameIndex()
    names = sorted({n for prov in gi.vfs.providers if prov.kind == "dat"
                    for n in prov.dat.names() if n.lower().endswith(".map")},
                   key=str.lower)[:80]

    dist = {f: collections.Counter() for f in INVENT}
    total = 0
    for n in names:
        data = gi.vfs.read(n)
        m = gi.load_map(data)
        for o in m.objects:
            vals = struct.unpack_from(">18i", data, o.off)
            total += 1
            for f in INVENT:
                dist[f][vals[FIELDS.index(f)]] += 1

    print(f"{total} objects across {len(names)} maps\n")
    for f in INVENT:
        top = dist[f].most_common(4)
        frac = top[0][1] / total
        print(f"  {f:11s} most common {top[0][0]:>10}  ({frac:.0%})   "
              f"next: {[v for v, _ in top[1:]]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
