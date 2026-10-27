#!/usr/bin/env python3
"""
Diagnose MDFG's black-floor bug against the conventions real maps follow.

READ-ONLY on the MDFG project; it is the owner's separate, unversioned work.

Real-map convention, measured across all 270 maps in the base:
    flags 0x02 -> elevation 1 absent
    flags 0x04 -> elevation 2 absent
    flags 0x08 -> elevation 0 absent
and 173 of 270 (every single-level map) use flags=0x0C, i.e. the map's one
level is ELEVATION 1. No shipped map uses elevation 0 on its own.

So the question for each MDFG map is: which elevation carries the floor tiles,
which elevation does the player start on, and do those agree?
"""

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from foclib import GameIndex, hex_xy  # noqa: E402

MDFG = Path(r"F:\GOG Games\Fallout 2\data\MAPS")


def main() -> int:
    gi = GameIndex()
    for name in ("MDFGFAC.MAP", "MDFGEXT.MAP", "MDFGSHDY.MAP", "MDFGTODO.MAP"):
        p = MDFG / name
        if not p.is_file():
            print(f"{name}: not present")
            continue
        data = p.read_bytes()
        m = gi.load_map(data)
        start_elev = struct.unpack_from(">i", data, 0x18)[0]
        start_hex = struct.unpack_from(">i", data, 0x14)[0]

        print(f"\n{name}")
        print(f"  flags=0x{m.flags:02X} -> elevations present {m.elevations}")
        print(f"  header default start: hex {start_hex}, elevation {start_elev}")
        for i, e in enumerate(m.elevations):
            floored = sum(1 for f in m.floors[i] if f > 1)
            roofed = sum(1 for r in m.roofs[i] if r > 1)
            objs = sum(1 for o in m.objects if o.elevation == e)
            print(f"    elevation {e}: {floored:5d} floored squares, "
                  f"{roofed:5d} roofed, {objs:5d} objects")

        # the verdict
        idx = {e: i for i, e in enumerate(m.elevations)}
        if start_elev not in idx:
            print(f"  >> start elevation {start_elev} is NOT among the elevations "
                  f"this map declares. The player stands on a level with no tile "
                  f"data at all.")
        else:
            n = sum(1 for f in m.floors[idx[start_elev]] if f > 1)
            if n == 0:
                print(f"  >> elevation {start_elev} exists but carries ZERO floor "
                      f"tiles. Walls and objects draw; the floor cannot.")
            else:
                print(f"  >> start elevation {start_elev} has {n} floored squares "
                      f"- floor data is where the player is.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
