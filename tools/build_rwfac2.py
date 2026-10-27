#!/usr/bin/env python3
"""
build_rwfac2.py - lay out RWFAC2, the military annex under the Waterworks (the
Facility Below's military tier, REDWELL_DESIGN "Q1 facility" and SITE_PLANS):
floors, walls, doors, the stairs between its levels, the trial station's breach
into the natural galleries, the exit down to the Root Chamber, and the props.
The fittings, the ghoul-likes, the turrets and the sealed door's lock are
rwfac2.ssl's and rwfsec.ssl's (foc_fac.h).

    python tools/build_rwfac2.py --preview build/rwfac2      # map + labelled renders, nothing installed

A dungeon in Fallout 2's military base style, measured from the maps that use
it (the Sierra Army Depot, the EPA, Fallout 1's Mariposa and the Master's
lair):
  * walls: the military set mmb by the originals' grammar (tools/wallsets.py,
    measured by wall_junctions.py, wall_sequences.py, door_frames.py); doors
    are its vault doors, vdoorf in an x-run and vdoors in a y-run, framed as
    every one of theirs is
  * floors: Fallout 2's steel plate checker (plt2000 / plt1000) inside the
    vtgsl strips along the walls (floor_borders.py vtgsl plt), grating in the
    tunnel and the power room; the natural galleries on the cave floor
    (cav4009, cav4010 on even-row odd-column squares), walled in the brown
    cave set ca, lit face or dark back as in RWFAC1
  * the back walls (a room's north x-run and east y-run): in corridors,
    quarters and stores a hazard stripe along the whole wall, as the
    originals paint theirs (x-run: strp06, then strp03 / strp02 pairs, strp04;
    y-run: strp07, strp09 / strp08 pairs, strp11), and a light; in offices,
    labs and machine rooms vents (vltvent3 on an x-run, vent002 on a y-run)
    with a pipe beside them (encl36 / encl35) and a light (stripes and vents
    never share a hex in theirs); one light per room, mblight1 on the gap
    where the east wall hangs below the north wall, else mblight2 on the east
    wall
  * the stairs as Fallout 2 joins floors: stair00 on the lower floor, two
    rows under the north wall and six hexes in from the east wall, and stway
    on the floor above, four hexes east and a row north of it, each landing
    beside the other (the Den's business, denbus1)
  * the mould (REDWELL_DESIGN 1.3): Fallout 1's Master's growths, the spotted
    wall pieces (mstr22, mstr24-27) on east walls and the floor patches
    (mstr44-50), from a few in the barracks to thick in the galleries; no
    radioactive goop, since the mould reads almost no radiation

Elevation 0, the Security System: the lift lobby (the way in from RWFAC1's
service lift) with a wash room off it, the checkpoint hall with the guards'
crate barricade and the guard post behind its window, and the sealed door
in the checkpoint's west wall (rwfsec.ssl): beyond it a tunnel and the stair
room, with the stairwell down.

Elevation 1, the annex: the stair foot, then one long corridor; barracks,
mess, command office and power room on the north side, with a service
passage behind the mess, the command office and the power room, so the
level loops; officers' quarters, armory, stores, the decontamination room
and the latrine on the south side; the stair room at the far end, with the
stairwell down.

Elevation 2, the trial station: the stair foot and the lab corridor; the
alga tank lab, the sample lab and the aquifer monitoring post to the north,
the trial log room and the cold store to the south; the corridor's west
wall broken through into the natural galleries, which wind north, south and
west to a side cave where the survey team left its cache and on to the way
down to the Root Chamber (RWFAC3), the mould thickening the further they go.

Objects are written in hex order on each level, as the originals write them.
Then: copy to mod/data/maps/RWFAC2.MAP, and tools/map_edges.py and
tools/rock_field.py (with --dir on a preview first).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_rwfac1 import (CA_GRAMMAR, inside, rock_cells, rock_pieces, room_squares,  # noqa: E402
                          runs_from_rooms, screen)
from foclib import GameIndex, parse_lst  # noqa: E402
from foclib.formats import MapFile  # noqa: E402
from mapbuild import MapBuilder, MapObjectSpec, extras_for  # noqa: E402
from wallsets import WALLSETS, build as build_walls  # noqa: E402

W = 200
MAP_ID = 215
NAME = "RWFAC2.MAP"
WALLSET = WALLSETS["mmb"]
MAP_SCRIPT = 1632           # rwfac2.int, as the map's header has always had it
RWFAC3, ROOT_ARRIVE = 216, (96, 129)     # the way down: RWFAC3's arrival (build_rwfac3.py ARRIVE)

PLATE, GRATE, CAVE = "plate", "grate", "cave"

# ------------------------------------------------------------------ the levels
# rooms: (name, x_high, x_low, y_top, y_bottom, floor) - x even, y odd; walls run round every room
# xgap / ygap: wall hexes taken out where two rooms open into each other: (y, x_lo, x_hi) / (x, y_lo, y_hi)
# doors: (x, y, "x" | "y") - a vault door: in an x-run at even x (odd y), in a y-run at even y
# windows: (y, x_from, x_to) on an x-run; stripe: the rooms whose back walls are striped
# caves: (name, rectangles (x_high, x_low, y_top, y_bottom), (start, end) on the concrete) - the
#   natural rock: the outline round the rectangles' union from start to end, the concrete between
#   them closes it; breaches (x, y_lo, y_hi) open a y-run onto it
LEVELS = {
    0: dict(
        rooms=[("Lift lobby", 100, 80, 93, 109, PLATE),
               ("Wash room", 96, 80, 109, 119, PLATE),
               ("Checkpoint", 130, 100, 87, 117, PLATE),
               ("Guard post", 124, 106, 79, 87, PLATE),
               ("Tunnel", 150, 130, 97, 107, GRATE),
               ("Stair room", 166, 150, 87, 113, PLATE)],
        xgap=[], ygap=[(150, 98, 106)],                            # the tunnel opens into the stair room
        doors=[(100, 100, "y"), (88, 109, "x"), (120, 87, "x"),
               (130, 102, "y")],                                   # the sealed door (foc_fac.h FAC2_SEAL_DOOR)
        windows=[(87, 109, 116)],                                  # the guard post's window onto the checkpoint
        stripe={"Lift lobby", "Checkpoint", "Tunnel", "Stair room"},
        caves=[], breaches=[],
    ),
    1: dict(
        rooms=[("Stair foot", 166, 150, 87, 113, PLATE),
               ("Corridor", 150, 46, 97, 105, PLATE),
               ("Barracks", 150, 118, 73, 97, PLATE),
               ("Mess", 118, 96, 73, 97, PLATE),
               ("Command office", 96, 74, 73, 97, PLATE),
               ("Power room", 74, 46, 73, 97, GRATE),
               ("Service passage", 118, 46, 67, 73, PLATE),
               ("Officers' quarters", 150, 126, 105, 121, PLATE),
               ("Armory", 126, 106, 105, 121, PLATE),
               ("Stores", 106, 86, 105, 121, PLATE),
               ("Decontamination", 86, 66, 105, 121, PLATE),
               ("Latrine", 66, 46, 105, 121, PLATE),
               ("Stair room", 46, 30, 91, 111, PLATE)],
        xgap=[], ygap=[(150, 98, 104),                             # the stair foot opens onto the corridor
                       (46, 98, 104)],                             # and the corridor onto the far stair room
        doors=[(134, 97, "x"), (106, 97, "x"), (86, 97, "x"), (60, 97, "x"),
               (108, 73, "x"), (66, 73, "x"),                      # the mess and the power room onto the passage
               (138, 105, "x"), (116, 105, "x"),                   # (116, 105): the armory, locked (foc_fac.h)
               (96, 105, "x"), (76, 105, "x"), (56, 105, "x")],
        windows=[],
        stripe={"Corridor", "Barracks", "Officers' quarters", "Armory", "Stores", "Stair foot", "Stair room"},
        caves=[], breaches=[],
    ),
    2: dict(
        rooms=[("Stair foot", 46, 30, 91, 111, PLATE),
               ("Lab corridor", 120, 46, 97, 105, PLATE),
               ("Alga tank lab", 120, 84, 73, 97, PLATE),
               ("Sample lab", 84, 62, 79, 97, PLATE),
               ("Monitoring post", 62, 46, 83, 97, PLATE),
               ("Trial log room", 120, 98, 105, 119, PLATE),
               ("Cold store", 98, 76, 105, 119, PLATE)],
        xgap=[], ygap=[(46, 98, 104)],                             # the stair foot opens onto the corridor
        doors=[(102, 97, "x"), (74, 97, "x"), (54, 97, "x"), (110, 105, "x"), (86, 105, "x")],
        windows=[(97, 87, 94)],                                    # the tank lab's window onto the corridor
        stripe={"Lab corridor", "Stair foot", "Cold store"},
        caves=[("Galleries", [(134, 120, 89, 113), (156, 134, 75, 101), (156, 142, 101, 137),
                              (176, 142, 137, 155), (142, 124, 125, 145)], ((120, 89), (120, 113)))],
        breaches=[(120, 100, 104)],                                # the corridor's west wall, broken through
        broken={(120, 99)},
    ),
}
START = (90, 101, 0)        # the lift lobby (foc_fac.h FAC2_LOBBY_ARRIVE)

# the stairs: (lower elevation, stair00 hex) - the stway is on the elevation above, (x-4, y-1)
STAIRS = [(1, (156, 89)), (2, (36, 93))]
# the way down to the Root Chamber: exit grid hexes on elev 2, at the galleries' far end
EXIT = dict(elev=2, hexes=[(x, y) for x in (172, 173, 174) for y in range(143, 151)], to=RWFAC3,
            tile=ROOT_ARRIVE[1] * W + ROOT_ARRIVE[0], dest_elev=0, rot=2)

# ------------------------------------------------------------------ pieces
LADDER, BLOCK = 0x0200008B, 0x02000158
STAIR, STAIRWELL = 0x0200015C, 0x02000164
EXIT_GRID = 0x05000010
STRP = {n: 0x02000344 + n for n in range(1, 12)}                    # strp01-11
VLTVENT3, VENT002, ENCL35, ENCL36 = 0x0200091D, 0x020007AF, 0x020005F7, 0x020005F8
MBLIGHT1, MBLIGHT2 = 0x0200033B, 0x0200033C
BEDX, BEDY = 0x02000275, 0x02000276                                 # bedmilt1 (along x), bedmilt2 (along y)
TABLE, CHAIR = 0x0200025D, 0x02000035                               # tblmetl2, chr7000
COMP1, COMP2, MONITR1, MONITR2, MONITR3 = 0x0200000B, 0x0200000C, 0x0200002B, 0x0200002C, 0x0200002D
SCOMP1, SCOMP2, SCREENS4, STCOMP3 = 0x02000343, 0x02000344, 0x02000338, 0x020000A0
ROBCOMP1, ROBCOMP2, ROBCOMP3 = 0x0200033E, 0x0200033F, 0x02000340
TANK, TANK_BROKEN = 0x0200022B, 0x0200022C                          # gtank01 / gtank02, suspension tanks
SINK, TOILET, SHOWER = 0x02000267, 0x02000268, 0x0200026E           # bath03, bath04, bath10
BARREL3, BARREL4, CRATE1, CRATE2, BOXES2 = 0x0200018D, 0x0200018E, 0x02000191, 0x02000192, 0x020000DD
BONES = 0x02000055
POWER003 = 0x02000795
DROCK2, DROCK4, ROCK05 = 0x020001AD, 0x020001AF, 0x02000050
MSTR_WALL = [0x020002CE, 0x020002D0, 0x020002D1, 0x020002D2, 0x020002D3]   # mstr22, 24, 25, 26, 27
MSTR_FLOOR = [0x020002E4 + i for i in range(7)]                     # mstr44-50
FOOTLOCKER, LOCKER1, LOCKER2, DESKMIL1, DESKMIL2 = 0x80, 0x84, 0x85, 0xB9, 0xBA
CONTAINERS = {FOOTLOCKER, LOCKER1, LOCKER2, DESKMIL1, DESKMIL2}
ONWALL = {SINK, SCREENS4, ROBCOMP1, ROBCOMP2, ROBCOMP3} | set(MSTR_WALL)
# blockers round a piece, as the military maps put them (tools/prop_footprints.py)
FOOTPRINT = {BEDX: [(-2, 0), (-2, 1), (-1, 1), (0, 1), (1, 1), (2, 0), (2, 1)],
             BEDY: [(1, -2), (1, -1), (1, 0), (1, 1)],
             TABLE: [(-2, -1), (-2, 0), (-1, 0), (0, -1), (1, 0)], CHAIR: [(-1, -1)],
             COMP1: [(-1, -1), (1, -1)], COMP2: [(-1, -1), (1, -1)], MONITR1: [(-1, -1), (1, -1)],
             MONITR2: [(-1, -1), (1, -1)], MONITR3: [(-1, -1), (1, -1)],
             TANK: [(-1, 0), (1, 0), (0, -1), (-1, -1)], TANK_BROKEN: [(-1, 0), (1, 0), (0, -1), (-1, -1)],
             POWER003: [(-1, 0), (1, 0), (0, -1)],
             STAIR: [(-4, 0), (-3, 1), (-2, -1), (-2, 0), (-1, 1), (0, -1)], STAIRWELL: [(0, 0), (2, 1), (4, 0)]}

# items, for containers' contents
STIMPAK, FLARE, ROPE, CAPS, GEIGER, MM10_JHP, COMBAT_ARMOR, ASSAULT_RIFLE, MM5_JHP = 40, 79, 127, 41, 52, 29, 17, 23, 35
DOCTORS_BAG, FIRST_AID = 91, 47

# (pid, x, y, contents) - contents [(pid, count)] for a container. Against a back wall = y_top + 2
# (north) or x_low + 2 (east); a back corner = both. ONWALL pieces sit on the wall hex itself.
PROPS = {
    0: [
        (CRATE1, 82, 95, None), (BOXES2, 84, 95, None),            # lobby: freight left by the lift
        (SINK, 80, 112, None), (SINK, 80, 116, None),              # wash room: sinks on the east wall,
        (TOILET, 86, 111, None), (SHOWER, 94, 113, None),          # a toilet and a shower
        (LOCKER2, 92, 111, [(FLARE, 2)]),
        (CRATE1, 112, 89, None), (CRATE2, 112, 91, None), (BOXES2, 112, 93, None),    # checkpoint: the guards'
        (CRATE1, 112, 95, None), (BARREL4, 112, 97, None), (CRATE2, 112, 99, None),   # barricade across the hall,
        (CRATE1, 112, 107, None), (BARREL3, 112, 109, None), (CRATE2, 112, 111, None),  # a lane left open at
        (BOXES2, 112, 113, None), (CRATE1, 112, 115, None),                           # the middle
        (BONES, 117, 103, None),                                   # someone who tried the door
        (DESKMIL1, 108, 81, [(CAPS, 12)]), (CHAIR, 110, 83, None), # guard post: the desk in the back corner,
        (MONITR1, 114, 81, None), (LOCKER1, 118, 81, [(STIMPAK, 1), (MM10_JHP, 1)]),
        (BONES, 140, 104, None),                                   # the tunnel: the last of the garrison
        (CRATE2, 162, 109, None),
    ],
    1: [
        (CRATE1, 164, 109, None), (CRATE2, 162, 111, None),        # stair foot
        (BEDX, 124, 75, None), (BEDX, 132, 75, None), (BEDX, 140, 75, None),   # barracks: bunks on the back wall
        (FOOTLOCKER, 128, 79, [(CAPS, 8)]), (FOOTLOCKER, 136, 79, [(FLARE, 1)]),
        (LOCKER1, 120, 85, []), (LOCKER2, 120, 89, [(STIMPAK, 1)]),            # lockers on the east wall
        (TABLE, 104, 81, None), (CHAIR, 102, 83, None), (CHAIR, 106, 79, None),  # mess: tables and chairs
        (TABLE, 112, 89, None), (CHAIR, 110, 91, None), (CHAIR, 114, 87, None),
        (MONITR1, 78, 75, None), (MONITR2, 82, 75, None),          # command office: monitors on the back wall,
        (SCREENS4, 74, 82, None),                                  # the screens on the east wall
        (DESKMIL2, 90, 87, [(CAPS, 20)]), (CHAIR, 88, 89, None),
        (SCOMP1, 48, 75, None), (SCOMP2, 52, 75, None),            # power room: machines in the back corner,
        (POWER003, 56, 87, None), (POWER003, 64, 87, None),        # the generators in the open
        (ROBCOMP1, 60, 73, None),                                  # and a receptacle on the back wall
        (ROBCOMP2, 46, 83, None), (ROBCOMP3, 46, 84, None),
        (BEDY, 128, 109, None), (BEDY, 128, 115, None),            # officers' quarters: beds on the east wall,
        (DESKMIL1, 136, 107, [(CAPS, 15)]), (CHAIR, 136, 109, None),            # a desk on the back wall
        (LOCKER1, 144, 107, [(FIRST_AID, 1)]), (FOOTLOCKER, 140, 117, []),
        (LOCKER1, 110, 107, [(COMBAT_ARMOR, 1)]),                  # armory: the kit in its lockers
        (LOCKER2, 108, 107, [(ASSAULT_RIFLE, 1), (MM5_JHP, 2)]),
        (LOCKER1, 112, 107, [(STIMPAK, 1)]), (CRATE1, 124, 117, None),
        (BARREL4, 88, 107, None), (BARREL3, 90, 107, None),        # stores: drums in the corner,
        (CRATE1, 96, 107, None), (CRATE2, 100, 107, None),         # crates on the back wall
        (LOCKER2, 102, 117, [(FLARE, 2), (ROPE, 1)]),
        (SHOWER, 70, 109, None), (SHOWER, 74, 109, None),          # decontamination: showers on the back wall
        (SINK, 66, 112, None), (COMP1, 80, 107, None),             # and its panel
        (TOILET, 50, 107, None), (TOILET, 54, 107, None), (SINK, 46, 114, None),   # latrine
        (CRATE1, 34, 109, None),                                   # far stair room
    ],
    2: [
        (CRATE2, 42, 109, None),
        (TANK, 90, 83, None), (TANK, 100, 83, None), (TANK_BROKEN, 110, 83, None),   # the alga tanks, in rows
        (TANK, 95, 91, None), (TANK_BROKEN, 105, 91, None),
        (SCOMP1, 86, 75, None), (SCOMP2, 90, 75, None),            # and their controls on the back wall
        (COMP1, 66, 81, None), (COMP2, 70, 81, None),              # sample lab
        (TABLE, 76, 89, None), (CHAIR, 74, 91, None),
        (LOCKER1, 82, 81, [(FIRST_AID, 1), (STIMPAK, 1)]),
        (MONITR2, 50, 85, None), (MONITR3, 54, 85, None), (SCREENS4, 46, 90, None),   # monitoring post
        (DESKMIL2, 114, 107, []), (CHAIR, 114, 109, None),         # trial log room
        (MONITR1, 108, 107, None),
        (SCOMP1, 80, 107, None), (SCOMP2, 84, 107, None),          # cold store: the refrigeration units
        (LOCKER1, 94, 107, [(STIMPAK, 1)]), (CRATE1, 96, 117, None),
        (DROCK2, 140, 92, None), (ROCK05, 150, 117, None),         # galleries: rock come down from the roof
        (DROCK4, 160, 140, None),
        (BONES, 128, 133, None),                                   # the survey team's cache, in the side cave
        (FOOTLOCKER, 130, 129, [(GEIGER, 1), (STIMPAK, 2), (CAPS, 40)]),
    ],
}
# the mould: (elevation, room or cave name, wall growths, floor patches, seed)
MOULD = [(1, "Barracks", 2, 4, 1),
         (2, "Alga tank lab", 3, 6, 2), (2, "Lab corridor", 1, 6, 3), (2, "Trial log room", 2, 3, 4),
         (2, "Galleries", 0, 60, 5)]

# floors
FRAME = {("N", "W"): "vtgsl003", ("N", "E"): "vtgsl004", ("S", "W"): "vtgsl002", ("S", "E"): "vtgsl001",
         "N": ("vtgsl012", "vtgsl011"), "S": ("vtgsl015", "vtgsl016"),
         "W": ("vtgsl013", "vtgsl014"), "E": ("vtgsl010", "vtgsl009")}
PLATE_CHECKER = ("plt2000", "plt1000")      # (c + r) even, odd
CAVE_FIELD = ("cav4009", "cav4010")


def paint(style, squares, walls, tid):
    out = {}
    for c, r in squares:
        if style == GRATE:
            out[(c, r)] = tid("grt2000")
            continue
        if style == CAVE:
            out[(c, r)] = tid(CAVE_FIELD[1 if (r % 2 == 0 and c % 2 == 1) else 0])
            continue
        sides = [k for k, hexes in (("N", [(2 * c, 2 * r - 1), (2 * c + 1, 2 * r - 1)]),
                                    ("S", [(2 * c, 2 * r + 1), (2 * c + 1, 2 * r + 1)]),
                                    ("W", [(2 * c + 2, 2 * r), (2 * c + 2, 2 * r + 1)]),
                                    ("E", [(2 * c, 2 * r), (2 * c, 2 * r + 1)]))
                 if any(h in walls for h in hexes)]
        ns = [s for s in sides if s in "NS"][:1]
        we = [s for s in sides if s in "WE"][:1]
        if ns and we:
            out[(c, r)] = tid(FRAME[(ns[0], we[0])])
        elif ns or we:
            out[(c, r)] = tid(FRAME[(ns or we)[0]][(c + r) % 2])
        else:
            out[(c, r)] = tid(PLATE_CHECKER[(c + r) % 2])
    return out


def outline(rects, start, end):
    """The boundary of a union of rectangles (x_high, x_low, y_top, y_bottom) as corner points, from
    start round to end the long way (not along the side the two share)."""
    cells = set()
    for xh, xl, yt, yb in rects:
        cells |= {(x, y) for x in range(xl, xh) for y in range(yt, yb)}
    edges = {}
    for (x, y) in cells:
        for (ax, ay), (bx, by), (nx, ny) in (((x, y), (x + 1, y), (x, y - 1)), ((x + 1, y), (x + 1, y + 1), (x + 1, y)),
                                             ((x + 1, y + 1), (x, y + 1), (x, y + 1)), ((x, y + 1), (x, y), (x - 1, y))):
            if (nx, ny) not in cells:
                edges[(ax, ay)] = (bx, by)
    # walk the boundary from start; the concrete side runs from end back to start
    pts = [start]
    p = start
    for _ in range(len(edges) + 1):
        p = edges[p]
        pts.append(p)
        if p == end:
            break
    else:
        raise SystemExit("cave outline: end not on the boundary")
    if any(p[0] == start[0] for p in pts[1:-1]) and all(p[0] == start[0] for p in pts):
        raise SystemExit("cave outline walked the concrete side")
    corners = [pts[0]]
    for a, b, c in zip(pts, pts[1:], pts[2:]):
        if (b[0] - a[0], b[1] - a[1]) != (c[0] - b[0], c[1] - b[1]):
            corners.append(b)
    corners.append(pts[-1])
    return corners


def stripes(lv, cells, frames):
    """The hazard stripe along a striped room's north and east walls, as the originals paint it."""
    out = []
    for name, xh, xl, yt, yb, _ in lv["rooms"]:
        if name not in lv["stripe"]:
            continue
        north = [x for x in range(xl + 1, xh) if (x, yt) in cells and (x, yt) not in frames]
        east = [y for y in range(yt + 2, yb) if (xl, y) in cells and (xl, y) not in frames]
        for seq, along in ((north, "x"), (east, "y")):
            runs, run = [], []
            for v in seq + [None]:
                if v is not None and (not run or run[-1] == v - 1):
                    run.append(v)
                    continue
                if run:
                    runs.append(run)
                run = [v] if v is not None else []
            for run in runs:
                while run and run[0] % 2 == 0:
                    run = run[1:]
                while run and run[-1] % 2 == 1:
                    run = run[:-1]
                if len(run) < 2:
                    continue
                for i, v in enumerate(run):
                    if along == "x":
                        n = 6 if i == 0 else 4 if i == len(run) - 1 else (3 if v % 2 == 0 else 2)
                        out.append(((v, yt), STRP[n]))
                    else:
                        n = 7 if i == 0 else 11 if i == len(run) - 1 else (9 if v % 2 == 0 else 8)
                        out.append(((xl, v), STRP[n]))
    return out


def wall_decor(lv, cells, gaps, frames, striped_hexes):
    """Vents with a pipe beside them on the unstriped rooms' back walls, and one light per room."""
    out = []
    used = set(striped_hexes)
    plain_x = {"mmb1025", "mmb1000", "mmb1002"}
    plain_y_odd, plain_y_even = {"mmb1022", "mmb1021"}, {"mmb1020", "mmb1016"}
    for name, xh, xl, yt, yb, _ in lv["rooms"]:
        if name not in lv["stripe"]:
            north = [x for x in range(xl + 3, xh - 2) if x % 2 == 0 and cells.get((x, yt)) in plain_x
                     and (x, yt) not in frames]
            for i, x in enumerate(north):
                if (x // 2) % 7 == 3 and (x + 2, yt) in cells and cells.get((x + 2, yt)) in plain_x \
                        and not {(x, yt), (x + 2, yt)} & used:
                    out += [((x, yt), VLTVENT3), ((x + 2, yt), ENCL36)]
                    used |= {(x, yt), (x + 2, yt)}
            east = [y for y in range(yt + 3, yb - 2) if (xl, y) not in frames]
            for y in east:
                if y % 2 == 1 and (y // 2) % 6 == 2 and cells.get((xl, y)) in plain_y_odd \
                        and cells.get((xl, y + 1)) in plain_y_even and not {(xl, y), (xl, y + 1)} & used:
                    out += [((xl, y), VENT002), ((xl, y + 1), ENCL35)]
                    used |= {(xl, y), (xl, y + 1)}
        # the light: on the gap under the north-east corner, else mid east wall
        if (xl, yt + 1) in gaps and (xl, yt + 1) not in used:
            out.append(((xl, yt + 1), MBLIGHT1))
            used.add((xl, yt + 1))
        else:
            spots = [(xl, y) for y in range(yt + 3, yb - 2) if y % 2 == 1 and cells.get((xl, y)) in plain_y_odd
                     and (xl, y) not in used and (xl, y) not in frames]
            if spots:
                h = spots[len(spots) // 2]
                out.append((h, MBLIGHT2))
                used.add(h)
    return out


def lv_caves(lv):
    return {c[0] for c in lv.get("caves", [])}


def build(gi, cfg=None):
    cfg = cfg or sys.modules[__name__]
    walls_lst = parse_lst(gi.vfs.read("art\\walls\\walls.lst"))
    tiles_lst = parse_lst(gi.vfs.read("art\\tiles\\tiles.lst"))
    grammar = json.loads(CA_GRAMMAR.read_text(encoding="utf-8"))["grammar"]
    tile_id = {}
    for i, n in enumerate(tiles_lst):
        if n:
            tile_id.setdefault(n.lower().replace(".frm", ""), i)

    def tid(name):
        return tile_id[name.lower()]
    wall_pid = {}
    for i in range(1, len(gi.proto_lst(3)) + 1):
        pid = 0x03000000 | i
        pr = gi.proto(pid)
        if pr is None:
            continue
        a = pr.fid & 0xFFFFFF
        wall_pid.setdefault(walls_lst[a].lower().replace(".frm", "") if a < len(walls_lst) else "", pid)

    b = MapBuilder(cfg.NAME, elevations=tuple(cfg.LEVELS), start_tile=cfg.START[1] * W + cfg.START[0], start_elevation=cfg.START[2],
                   start_orientation=2, map_id=cfg.MAP_ID, map_script_index=cfg.MAP_SCRIPT)
    objs, report, areas = [], {}, {}
    for elev, lv in cfg.LEVELS.items():
        lv.setdefault("broken", set())
        lv["xgap"] = lv.get("xgap", [])
        xruns, yruns = runs_from_rooms(dict(lv, rock=[]))
        cells, gaps, doors, glass = build_walls(cfg.WALLSET, xruns, yruns, lv["doors"], (), lv["windows"],
                                                lv["broken"])
        frames = set()
        for x, y, k in lv["doors"]:
            spec = cfg.WALLSET["x_door"] if k == "x" else cfg.WALLSET["y_door"]
            frames |= {((x + d, y) if k == "x" else (x, y + d)) for d in spec["frame"]} | {(x, y)}
        rock, caves = {}, {}
        for name, rects, (s, e) in lv["caves"]:
            pts = outline(rects, s, e)
            rock.update(rock_pieces(rock_cells(pts), grammar, pts))
            caves[name] = pts
        for (x, y), piece in cells.items():
            if (x, y) not in rock:
                objs.append((elev, x, y, wall_pid[piece]))
        for x, y in gaps:
            if (x, y) not in rock:
                objs.append((elev, x, y, wall_pid["block"]))
        for (x, y), piece in rock.items():
            objs.append((elev, x, y, wall_pid[piece]))
        for x, y, pid in doors + glass:
            objs.append((elev, x, y, pid))
        walls = set(cells) | set(rock)
        floor = {}
        for name, xh, xl, yt, yb, style in lv["rooms"]:
            sq = room_squares(xh, xl, yt, yb)
            floor.update(paint(style, sq, walls, tid))
            areas[(elev, name)] = sq
        for name, pts in caves.items():
            xs, ys = [p[0] for p in pts], [p[1] for p in pts]
            sq = [(c, r) for r in range(min(ys) // 2, max(ys) // 2 + 1) for c in range(min(xs) // 2, max(xs) // 2 + 1)
                  if inside(pts, 2 * c + 1, 2 * r + 0.5)]       # off the outline's odd rows: the floor runs under its south side
            floor.update(paint(CAVE, [s for s in sq if s not in floor], walls, tid))
            areas[(elev, name)] = sq
        for (c, r), t in floor.items():
            b.set_floor(elev, c, r, t)
        # stripes, decor, props with their blockers
        st = stripes(lv, cells, frames)
        decor = wall_decor(lv, cells, gaps, frames, {h for h, _ in st})
        for (x, y), pid in st + decor:
            objs.append((elev, x, y, pid, None, None))
        taken = set()
        for pid, x, y, contents in cfg.PROPS[elev]:
            if pid not in ONWALL and (x, y) in walls:
                raise SystemExit(f"e{elev}: 0x{pid:08X} at ({x},{y}) is on a wall")
            if pid in ONWALL and (x, y) not in walls:
                raise SystemExit(f"e{elev}: 0x{pid:08X} at ({x},{y}) belongs on a wall hex")
            objs.append((elev, x, y, pid, None, contents))
            taken.add((x, y))
            foot = list(FOOTPRINT.get(pid, [])) + ([(0, 0)] if pid in CONTAINERS else [])
            for dx, dy in foot:
                h = (x + dx, y + dy)
                if h not in walls and h not in taken - {(x, y)}:
                    objs.append((elev, h[0], h[1], BLOCK, None, None))
        # the mould
        for e2, name, nwall, nfloor, seed, *toward in cfg.MOULD:
            if e2 != elev:
                continue
            toward = toward[0] if toward else ("far" if name in lv_caves(lv) else None)
            room = next((r for r in lv["rooms"] if r[0] == name), None)
            if room is not None and nwall:
                _, xh, xl, yt, yb, _ = room
                spots = [(xl, y) for y in range(yt + 3, yb - 1) if cells.get((xl, y)) in
                         ("mmb1020", "mmb1016", "mmb1021", "mmb1022") and (xl, y) not in frames]
                spots = [h for h in spots if not any(o[1:3] == h for o in objs if o[0] == elev and len(o) > 4)]
                for i in range(nwall):
                    if spots:
                        h = spots[(seed * 5 + i * 7) % len(spots)]
                        spots.remove(h)
                        objs.append((elev, h[0], h[1], MSTR_WALL[(seed + i) % len(MSTR_WALL)], None, None))
            sq = [s for s in areas.get((elev, name), [])]
            held = taken | {o[1:3] for o in objs if o[0] == elev}
            free = [(2 * c + 1, 2 * r) for c, r in sq if (2 * c + 1, 2 * r) not in held and (2 * c + 1, 2 * r) not in walls]
            # thicker toward the far end of a cave (high x, high y)
            if free:
                # thick toward the far end of a cave: "far" high x + y, "back" low y
                free.sort(key=(lambda h: (h[0] + h[1], h)) if toward != "back" else (lambda h: (-h[1], h)))
                for i in range(min(nfloor, len(free))):
                    u = ((i * 389 + seed * 113) % 997) / 997
                    k = len(free) - 1 - int(len(free) * u * u) if toward \
                        else (i * 53 + seed * 17) % len(free)
                    h = free[k]
                    objs.append((elev, h[0], h[1], MSTR_FLOOR[(i + seed) % len(MSTR_FLOOR)], None, None))
        report[elev] = (len(cells), len(gaps), len(rock), len(doors), len(cfg.PROPS[elev]), len(st), len(decor))
    # the stairs: stair00 below leading up, stway above leading down, each landing beside the other
    for lower, (sx, sy) in cfg.STAIRS:
        tx, ty = sx - 4, sy - 1
        objs.append((lower, sx, sy, STAIR, ((ty + 1) * W + tx | ((lower - 1) << 29), -1), None))
        objs.append((lower - 1, tx, ty, STAIRWELL, ((sy + 2) * W + sx | (lower << 29), -1), None))
        for pid, (x, y), e in ((STAIR, (sx, sy), lower), (STAIRWELL, (tx, ty), lower - 1)):
            for dx, dy in FOOTPRINT[pid]:
                objs.append((e, x + dx, y + dy, BLOCK, None, None))
    for ex in (cfg.EXIT if isinstance(cfg.EXIT, list) else [cfg.EXIT]):
        for x, y in ex["hexes"]:
            objs.append((ex["elev"], x, y, EXIT_GRID, (ex["to"], ex["tile"], ex["dest_elev"], ex["rot"]), None))
    objs = [o if len(o) == 6 else o + (None, None) for o in objs]
    objs.sort(key=lambda o: (o[0], o[2] * W + o[1]))      # by hex, as every original map writes them
    for elev, x, y, pid, extras, contents in objs:
        pr = gi.proto(pid)
        if pr is None:
            raise SystemExit(f"no proto 0x{pid:08X}")
        flags = pr.flags - (1 << 32) if pr.flags >= 1 << 31 else pr.flags
        inv = []
        for ipid, n in contents or []:
            ip = gi.proto(ipid)
            iflags = ip.flags - (1 << 32) if ip.flags >= 1 << 31 else ip.flags
            ext = extras_for(0, ipid, ip.subtype)
            if ip.subtype in (4, 5, 6):              # ammo, misc, key: one stack of n
                inv.append(MapObjectSpec(pid=ipid, fid=ip.fid, tile=-1, elevation=elev, flags=iflags, extras=ext, count=n))
            else:
                inv += [MapObjectSpec(pid=ipid, fid=ip.fid, tile=-1, elevation=elev, flags=iflags, extras=ext)
                        for _ in range(n)]
        b.add(MapObjectSpec(pid=pid, fid=pr.fid, tile=y * W + x, elevation=elev, flags=flags,
                            extras=extras if extras is not None else extras_for(pid >> 24, pid, pr.subtype),
                            inventory=inv))
    data = b.to_bytes()
    MapFile.parse(data, gi.proto)
    return data, report


def label(path, out_dir, cfg=None):
    cfg = cfg or sys.modules[__name__]
    import map_edges as me
    out_dir.mkdir(parents=True, exist_ok=True)
    for elev, lv in cfg.LEVELS.items():
        stem = cfg.NAME.split(".")[0].lower()
        png = out_dir / f"{stem}_e{elev}.png"
        ox, oy, s = me.render(path, elev, png, 2600)
        im = Image.open(png).convert("RGB")
        d = ImageDraw.Draw(im)
        marks = [(n, (xh + xl) // 2, (yt + yb) // 2) for n, xh, xl, yt, yb, _ in lv["rooms"] if n]
        for name, rects, _ in lv["caves"]:
            xh, xl, yt, yb = rects[len(rects) // 2]
            marks.append((name, (xh + xl) // 2, (yt + yb) // 2))
        for name, cx, cy in marks:
            px, py = screen(cx, cy)
            px, py = (px + me.GECKO_OFFSET[0] - ox) * s, (py + me.GECKO_OFFSET[1] - oy) * s
            w = d.textlength(name)
            d.rectangle([px - w / 2 - 3, py - 7, px + w / 2 + 3, py + 7], fill=(0, 0, 0))
            d.text((px - w / 2, py - 6), name, fill=(255, 220, 120))
        bbox = Image.open(png).convert("L").point(lambda v: 255 if v > 12 else 0).getbbox()
        if bbox:
            im = im.crop((max(0, bbox[0] - 30), max(0, bbox[1] - 30), min(im.width, bbox[2] + 30), min(im.height, bbox[3] + 30)))
        im.save(out_dir / f"{stem}_e{elev}_labelled.png")
        print("  wrote", out_dir / f"{stem}_e{elev}_labelled.png")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--preview", metavar="DIR", required=True)
    a = ap.parse_args()
    gi = GameIndex(pristine=False)
    data, report = build(gi)
    out = Path(a.preview) / NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    for e, (nw, ng, nr, nd, npr, ns, ndec) in report.items():
        print(f"e{e}: {nw} wall pieces, {ng} gap blockers, {nr} rock pieces, {nd} doors, {npr} props, "
              f"{ns} stripes, {ndec} vents, pipes and lights")
    print("wrote", out)
    label(out, Path(a.preview))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
