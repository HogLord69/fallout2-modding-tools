#!/usr/bin/env python3
"""
build_rwfac3.py - lay out RWFAC3, the Root Chamber at the bottom of the Facility
Below (REDWELL_DESIGN 1.3 and "Q1 facility"): the trial station's observation
room at the mouth of the natural cavern the Redwell mould has grown through,
reached by the approach up from the annex's galleries (RWFAC2).

    python tools/build_rwfac3.py --preview build/rwfac3      # map + labelled renders, nothing installed

Built with tools/build_rwfac2.py's machinery and the same rules:
  * the observation room in the military set (mmb) the trial station is built
    in, its back wall a window onto the cavern beside the vault door into it,
    and a door at its front onto the approach; plate floor in the vtgsl frame,
    vents and a light on its back walls; the station's consoles under the
    window, the observers' desk and locker
  * the approach and the cavern in the brown cave set (ca) on the cave floor
  * the mould: Fallout 1's Master's growths, the floor patches thick at the
    back of the cavern and thinning toward the mouth, standing growths
    (mstr20 / mstr21) through the cavern, the spotted wall pieces on the
    observation room's east wall
  * the trial's intake pipe ends at the back of the cavern (the military
    base's own riser, mbpipe1); the survey party's last camp just inside the
    mouth: a dead fire, a skeleton and a pack to search, bones
The console (rwfroot.ssl) and the ghoul-likes are rwfac3.ssl's (foc_fac.h).

Then: copy to mod/data/maps/RWFAC3.MAP, and tools/map_edges.py and
tools/rock_field.py (with --dir on a preview first).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_rwfac2 as B  # noqa: E402
from build_rwfac2 import (BLOCK, BONES, CHAIR, COMP2, DESKMIL2, DROCK2, FOOTPRINT, GRATE, LOCKER1,  # noqa: E402,F401
                          MONITR1, PLATE, ROCK05, SCOMP1, W)
from foclib import GameIndex  # noqa: E402
from wallsets import WALLSETS  # noqa: E402

MAP_ID = 216
NAME = "RWFAC3.MAP"
WALLSET = WALLSETS["mmb"]
MAP_SCRIPT = 1633           # rwfac3.int, as the map's header has always had it
ARRIVE = B.ROOT_ARRIVE      # (96, 129): the approach, down from the annex's galleries (foc_fac.h FAC3_ARRIVE)
RWFAC2, FAC2_ROOT_ARRIVE = 215, 146 * W + 166      # back up: the galleries' far end (foc_fac.h)

LEVELS = {
    0: dict(
        rooms=[("Observation room", 108, 84, 103, 119, PLATE)],
        xgap=[], ygap=[],
        doors=[(100, 103, "x"),                                    # into the cavern
               (96, 119, "x")],                                    # onto the approach
        windows=[(103, 87, 96)],                                   # the window onto the cavern
        stripe=set(),
        caves=[("Root Chamber", [(108, 84, 89, 103), (138, 56, 57, 89), (118, 76, 35, 57)], ((84, 103), (108, 103))),
               ("Approach", [(104, 88, 119, 139)], ((104, 119), (88, 119)))],
        breaches=[], broken=set(),
    ),
}
START = (ARRIVE[0], ARRIVE[1], 0)
STAIRS = []
EXIT = dict(elev=0, hexes=[(x, y) for x in range(92, 101) for y in (135, 136, 137)], to=RWFAC2,
            tile=FAC2_ROOT_ARRIVE, dest_elev=2, rot=5)

MSTR20, MSTR21 = 0x020002CC, 0x020002CD          # standing growths
MBPIPE1 = 0x020001A6                             # the military base's pipe riser
WOODFIRE, BONE03 = 0x02000264, 0x02000054
SKELETON, BACKPACK = 0xD3, 0x5A                  # v13bones and a backpack: containers
FOOTPRINT.update({MSTR20: [(0, 0)], MSTR21: [(0, 0)], MBPIPE1: [(-1, 0), (1, 0)]})
B.CONTAINERS |= {SKELETON, BACKPACK}

STIMPAK, FLARE, CAPS, ROPE, FIRST_AID = 40, 79, 41, 127, 47
PROPS = {
    0: [
        (SCOMP1, 86, 105, None), (MONITR1, 88, 105, None),         # the station's consoles under the window
        (COMP2, 96, 105, None), (CHAIR, 92, 107, None),
        (DESKMIL2, 86, 111, []), (LOCKER1, 106, 105, [(STIMPAK, 1), (FIRST_AID, 1)]),
        (WOODFIRE, 96, 93, None), (BONE03, 92, 95, None),          # the survey party's last camp
        (SKELETON, 100, 95, [(FLARE, 2), (STIMPAK, 1)]),
        (BACKPACK, 98, 91, [(CAPS, 25), (ROPE, 1)]),
        (MSTR20, 70, 70, None), (MSTR21, 84, 62, None), (MSTR20, 100, 66, None),   # the mould standing up
        (MSTR21, 118, 74, None), (MSTR20, 126, 82, None), (MSTR21, 90, 45, None),  # through the cavern
        (MSTR20, 104, 42, None), (MSTR21, 66, 84, None),
        (MBPIPE1, 98, 37, None),                                   # the trial's intake pipe, at the back
        (DROCK2, 62, 80, None), (ROCK05, 130, 62, None),
    ],
}
MOULD = [(0, "Root Chamber", 0, 140, 7, "back"), (0, "Observation room", 2, 4, 8)]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--preview", metavar="DIR", required=True)
    a = ap.parse_args()
    gi = GameIndex(pristine=False)
    cfg = sys.modules[__name__]
    data, report = B.build(gi, cfg)
    out = Path(a.preview) / NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    for e, (nw, ng, nr, nd, npr, ns, ndec) in report.items():
        print(f"e{e}: {nw} wall pieces, {ng} gap blockers, {nr} rock pieces, {nd} doors, {npr} props, "
              f"{ns} stripes, {ndec} vents, pipes and lights")
    print("wrote", out)
    B.label(out, Path(a.preview), cfg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
