#!/usr/bin/env python3
"""
rework_clcourt.py - rebuild the owner's courthouse map (CLCOURT.MAP) after the
1947 first floor plan of the Coke County Court House, Robert Lee, Texas
(David S. Castle Co., sheet 2 of 7), with a second floor for the courtroom
in the pattern of Castle's courthouses (Reagan County, Big Lake). Built from
the owner's own map, kept at mod/maps_src/CLCOURT.owner.MAP, with what is on
it. Owner's request and approval: 2026-10-13.

    python tools/rework_clcourt.py --preview build/clcourt_rework   # renders, no write
    python tools/rework_clcourt.py --write

Ground floor (elevation 0): a corridor the width of the building with a door
out at each end. Back row: the stair hall up, the County Clerk, an office
with its waiting room, the County Library, the stairs down with storage off
a service hall, two toilets. Front row: a waiting room into the Treasurer
and the Commissioners' Court, a waiting room into the County Judge, the
lobby and porch, a waiting room into the County Attorney and the Tax
Assessor, the vault and the tax lobby with its counter into the Tax
Assessor & Collector. The blueprint's living quarters and Sheriff's office
are left out (owner).

Second floor (elevation 2): a hall across the front with the stair hall off
it; the District Courtroom, the judge's chambers, the court reporter, the
toilets; the jury room, a witness room, the law library and the District
Attorney.

Walls follow Fallout 1 and 2's nec grammar, measured over every map of both
games (tools/nec_corners.py, and the junction counts in this file's
JUNCTION table): x-runs on odd hex rows, y-runs on even hex columns; a y-run
that hangs below an x-run starts two rows down, with a blocker in the gap
hex; a y-run that ends at an x-run touches it; every corner, T and crossing
takes the piece the originals use for its neighbours, brick or grey. Brick
shows where the owner's map shows it: the front, the west face and the
porch.

Furniture follows tools/furniture_walls.py (where the originals put each
piece against walls): against the back walls only (the x-run above, or the
y-run at lower x), never the front ones; sinks, mirrors, pictures, wall
lamps and bars on the wall hex. check() enforces this.

Stairs as Fallout and its total conversions do them (tools/stairs_survey.py):
the staircase (stair00) on the lower floor leads up, the stairwell (stway)
on the floor above leads down, each carrying its destination (map -1, tile
| elevation << 29). The owner's basement pair is wired the same way.

The owner's objects are moved with their bytes kept (tile and elevation
patched). The top of the owner's black frame moves back to fit the deeper
building; run tools/map_edge_blockers.py CLCOURT.MAP after writing.

--write refuses if gecko or the game is running, and moves the current map to
mod/data/maps/_replaced.
"""

from __future__ import annotations

import argparse
import random
import struct
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foclib import GameIndex, parse_lst  # noqa: E402
from foclib.formats import MapFile  # noqa: E402
from map_crop import AUTHORED, DEPLOYED, stash_existing  # noqa: E402
from mapbuild import MapBuilder, MapObjectSpec, extras_for  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
NAME = "CLCOURT.MAP"
SOURCE = ROOT / "mod" / "maps_src" / "CLCOURT.owner.MAP"
MAP_ID = 212
W = 200
EAST_X, WEST_X, N_Y, FRONT_Y = 64, 130, 111, 153

# ------------------------------------------------------------------ layouts
# x-runs (x_high, x_low, y): both ends on a y-run column. y-runs (x, y_top, y_bottom):
# from one x-run row to another. Openings and doors are cut out afterwards.
FLOORS = {
    0: dict(
        xruns=[(130, 64, 111), (130, 64, 127), (130, 64, 133), (130, 64, 153),
               (108, 102, 119), (82, 76, 119), (72, 64, 119),
               (130, 108, 139), (96, 74, 139), (108, 96, 145)],
        yruns=[(130, 111, 153), (64, 111, 153),
               (120, 111, 127), (108, 111, 127), (102, 111, 127), (82, 111, 127), (76, 111, 127), (72, 111, 127),
               (114, 133, 153), (108, 133, 145), (108, 145, 153), (96, 133, 145), (96, 145, 153),
               (122, 139, 153), (88, 139, 153), (80, 139, 153), (82, 133, 139), (74, 133, 139)],
        open={(x, 127) for x in range(121, 130)} | {(x, 127) for x in range(73, 76)} |
             {(x, 133) for x in range(97, 108)} | {(x, 139) for x in range(65, 74)} |
             {(x, 153) for x in range(97, 108)},
        doors=[(114, 127, "x"), (104, 127, "x"), (92, 127, "x"), (78, 127, "x"),
               (108, 116, "yo"), (104, 119, "x"), (76, 116, "y"), (72, 116, "y"), (72, 124, "y"),
               (122, 133, "x"), (110, 133, "x"), (90, 133, "x"), (70, 133, "x"),
               (126, 139, "x"), (118, 139, "x"), (110, 139, "x"), (92, 139, "x"), (84, 139, "x"), (78, 139, "x"),
               (64, 130, "y"), (130, 130, "yb"), (102, 145, "x"), (80, 146, "y")],
        brick=lambda x, y, kind: (kind == "x" and y in (153, 145)) or (kind == "y" and (x == 130 or (x == 96 and y > 145))),
    ),
    2: dict(
        xruns=[(130, 64, 111), (130, 64, 133), (130, 64, 139), (130, 108, 153), (96, 64, 153), (108, 96, 145)],
        yruns=[(130, 111, 153), (64, 111, 153),
               (120, 111, 133), (88, 111, 133), (76, 111, 133), (70, 111, 133),
               (108, 139, 145), (108, 145, 153), (96, 139, 145), (96, 145, 153), (80, 139, 153)],
        open={(x, 133) for x in range(121, 130)},
        doors=[(102, 133, "xo"), (112, 133, "x"), (82, 133, "x"), (74, 133, "x"), (66, 133, "x"),
               (88, 118, "y"), (118, 139, "x"), (102, 139, "x"), (88, 139, "x"), (72, 139, "x")],
        brick=lambda x, y, kind: (kind == "x" and y in (153, 145)) or (kind == "y" and (x == 130 or (x == 96 and y > 145))),
    ),
}

# Junction pieces: (lo, hi, up, down) -> piece, from every nec junction in Fallout 1 and 2.
# lo = the x-run continues to x-1, hi = to x+1, up = a y-run touches from above,
# down = a y-run hangs below a one-hex gap; each "g" grey or "B" brick.
JUNCTION = {
    (None, "g", None, "g"): "101", ("g", "g", None, "g"): "117", (None, "g", "g", None): "118",
    ("g", None, "g", None): "123", (None, "g", "g", "g"): "121", ("g", "g", "g", None): "122",
    ("g", None, "g", "g"): "119", ("g", None, None, "g"): "120", (None, "B", "g", None): "067",
    ("B", None, "B", None): "050", ("g", None, None, "B"): "068", ("B", "B", "g", None): "156",
    ("g", None, "B", "B"): "155", ("g", "g", "g", "g"): "124", (None, "B", None, "B"): "152",
    (None, "g", "B", None): "118", ("B", None, "g", "g"): "119", ("B", None, None, "g"): "120",
    (None, "B", "g", "B"): "154", (None, "B", "B", "B"): "154", ("B", "B", None, "B"): "153",
    ("B", None, "B", "B"): "155", (None, "g", "B", "g"): "121", ("g", "g", "B", None): "122",
    ("B", None, "g", "B"): "119", ("g", "B", "g", "B"): "157", ("B", "g", None, "g"): "117",
    ("B", "g", "g", "g"): "124", ("g", "B", None, "B"): "153", ("B", "B", "B", None): "156",
    ("B", None, "B", "g"): "050", ("B", None, None, "B"): "120", ("B", "B", "g", "g"): "124",
}
GREY_X = {0: ["094", "095", "097", "100"], 1: ["096", "098", "099"]}
BRICK_X = {0: ["052", "058", "052", "162"], 1: ["053", "059"]}
GREY_Y = ["103", "106", "109"]
BRICK_Y = ["061", "163", "060"]

# ------------------------------------------------------------------ the owner's objects
# (old x, old y) -> (x, y) or (x, y, elevation); None removes it.
CT = (32, -18)                       # the owner's courtroom set, to the second floor courtroom


def ct(x, y, dy=0):
    return (x + CT[0], y + CT[1] + dy, 2)


MOVE = {
    # District Courtroom, second floor: the owner's bench group as the owner set it out
    **{p: ct(*p) for p in [(65, 131), (74, 133), (74, 131), (74, 135), (66, 133), (66, 135),
                            (65, 132), (65, 133), (65, 135), (74, 130)]},
    (69, 129): (101, 111, 2),                                   # the picture, on the back wall
    # counsel tables, chairs, papers, briefcase
    **{p: ct(*p, 1) for p in [(69, 140), (79, 140), (78, 140), (80, 140), (69, 141), (73, 140), (77, 138)]},
    # the twelve pews
    **{p: ct(*p, 1) for p in [(77, 143), (81, 143), (67, 144), (71, 144), (78, 145), (82, 145),
                               (68, 146), (72, 146), (78, 148), (82, 148), (69, 149), (73, 149)]},
    # judge's chambers: the owner's office behind the old courtroom, against the back wall
    (84, 118): (84, 112, 2), (79, 118): (79, 112, 2), (82, 119): (82, 114, 2), (81, 120): (81, 115, 2),
    (83, 122): (83, 117, 2), (82, 124): (82, 119, 2), (84, 124): (84, 119, 2),
    (89, 124): (77, 124, 2), (89, 125): (77, 125, 2),            # dressers, against the right wall
    # jury room: the long tables and chairs, the two fridges against the back wall
    (118, 126): (118, 142, 2), (118, 128): (118, 145, 2), (119, 127): (120, 143, 2), (119, 129): (120, 146, 2),
    (129, 127): (116, 143, 2), (129, 129): (116, 146, 2), (129, 131): (122, 144, 2),
    (128, 134): (126, 140, 2), (127, 140): (123, 140, 2),
    # court reporter: monitors two hexes off the back wall, chair, table, chair
    (118, 139): (71, 113, 2), (120, 139): (69, 141, 2), (122, 139): (72, 118, 2), (122, 140): (71, 121, 2),
    (123, 143): (72, 123, 2),
    (119, 135): (100, 140, 2),                                  # witness room table
    # law library: the shelves of books and parts on their big shelf, two big shelves
    (94, 120): (92, 141, 2), (106, 125): (84, 141, 2), (112, 125): (82, 141, 2),
    # ground floor: County Library bookcases, against the back wall
    (97, 118): (85, 112), (103, 118): (89, 112), (111, 118): (93, 112), (122, 118): (97, 112),
    (108, 118): (114, 112),                                     # County Clerk: workbench and tool board
    (100, 125): (77, 134),                                      # footlocker in the vault
    # corridor: posters on the wall, chairs, Nuka-Cola machine against the wall, debris
    (96, 128): (96, 128), (99, 128): (99, 128), (103, 129): (87, 128), (111, 127): (111, 127),
    (107, 129): (107, 128), (109, 129): (109, 128), (111, 129): (101, 129), (89, 119): (85, 128),
    (90, 129): (90, 130), (94, 131): (94, 131), (95, 137): (95, 131), (93, 133): (93, 131),
    (108, 134): (108, 131), (94, 136): (94, 130), (110, 139): (110, 130), (105, 137): (104, 140),
    (109, 137): (127, 131), (95, 133): (100, 131), (110, 134): (120, 131), (91, 145): (99, 140),
    (92, 133): (92, 131),
    # waiting chairs against the right walls of the waiting rooms
    (89, 132): (115, 134), (89, 133): (117, 134), (89, 134): (125, 134), (89, 135): (127, 134),
    (89, 137): (86, 134), (89, 136): (89, 146),
    # toilets: urinal and toilet against the back wall, sink and mirror on the east wall
    (117, 146): (68, 112), (121, 146): (70, 112), (116, 152): (64, 115),
    # broken boards: in the corridor's ends and the stair hall
    (114, 135): (67, 130), (117, 137): (66, 131), (86, 141): (128, 124), (89, 143): (127, 125),
    # rubble
    (90, 141): (91, 143), (89, 144): (93, 150), (109, 143): (111, 149), (111, 137): (112, 136),
    (117, 136): (117, 136), (117, 139): (119, 150),
    # front rooms: tables
    (92, 149): (90, 141), (112, 149): (82, 142),
    # outside: the porch and the west side, as the owner had them
    (119, 123): (119, 123), (131, 122): (131, 122), (131, 123): (131, 123), (131, 124): (131, 124),
    (131, 125): (131, 125), (132, 126): (132, 126), (117, 153): (126, 150), (104, 145): (104, 145),
    (110, 153): (110, 153), (103, 150): (103, 150), (103, 153): (103, 153),
    # vermin
    (121, 127): (121, 129), (121, 131): (110, 136, 2), (92, 137): (90, 136, 2), (104, 137): (102, 137),
    (108, 139): (70, 136), (93, 130): (93, 130), (109, 133): (109, 131),
    (92, 118): (79, 114),                                       # the stairwell down
}
RAIL = dict(dx=2, dy=-11, elev=2)            # the owner's railing: the bar in the courtroom
RAIL_ENDS = {(96, 136), (107, 135), (108, 135), (108, 136), (107, 136)}
COUNTER = dict(dx=-32, dy=7)                 # the owner's counter: the tax lobby's counter line
DOOR_REUSE = {"xo": 0x0200174E, "yo": 0x0200174F}   # the owner's Olympus doors

STAIR_UP = (126, 121)                        # stair00, ground floor
STAIR_UP_TOP = (122, 120)                    # stway, second floor
STAIRWELL_DOWN = (79, 114)                   # the owner's stway, ground floor
BASEMENT_STAIR = (94, 109)                   # the owner's stair00, basement
BASEMENT_LANDING = (92, 108)
BASEMENT_LANDING_UP = (79, 117)

CHAIR, TABLE, DESK, DESK2, LTABLE3, LTABLE4 = 0x0200029E, 0x02000004, 0x02000194, 0x02000195, 0x020001EF, 0x020001F0
TOILET, URINAL, SINK, BOOKCASE, FOOTLOCKER, CRATE1, CRATE3 = (0x02000134, 0x02000147, 0x0200011D, 0x0000003D,
                                                             0x00000081, 0x02000191, 0x02000193)
ADDS = [
    # ground floor
    (DESK, 116, 117, 0), (CHAIR, 116, 119, 0), (DESK2, 111, 116, 0), (CHAIR, 113, 121, 0),     # Clerk
    (DESK, 105, 112, 0), (CHAIR, 103, 112, 0), (CHAIR, 103, 122, 0), (CHAIR, 103, 124, 0),     # office, waiting
    (TABLE, 92, 119, 0), (CHAIR, 90, 120, 0), (CHAIR, 94, 120, 0),                              # library
    (CRATE3, 79, 121, 0), (CRATE1, 77, 124, 0),                                                  # storage
    (TOILET, 68, 120, 0), (SINK, 64, 123, 0),                                                    # ladies'
    (DESK2, 127, 144, 0), (CHAIR, 127, 146, 0), (FOOTLOCKER, 124, 140, 0),                      # Treasurer
    (LTABLE3, 117, 142, 0), (LTABLE4, 117, 145, 0), (CHAIR, 119, 143, 0), (CHAIR, 119, 146, 0),
    (CHAIR, 115, 143, 0), (CHAIR, 115, 146, 0),                                                  # Commissioners'
    (CHAIR, 112, 134, 0), (DESK, 111, 144, 0), (CHAIR, 111, 146, 0),                            # County Judge
    (BOOKCASE, 94, 140, 0), (DESK, 92, 144, 0), (CHAIR, 92, 146, 0),                            # County Attorney
    (DESK, 85, 143, 0), (CHAIR, 85, 145, 0),                                                     # Tax Assessor
    (DESK2, 70, 143, 0), (CHAIR, 70, 145, 0), (DESK, 75, 143, 0), (CHAIR, 75, 145, 0),          # Collector
    (FOOTLOCKER, 79, 134, 0), (0x0200047A, 69, 139, 0),                                          # vault, counter bars
    # second floor
    *[(CHAIR, x, y, 2) for x in (89, 91) for y in range(121, 127)],                             # jury box
    (CHAIR, 111, 117, 2),                                                                        # witness chair
    (CHAIR, 98, 140, 2), (CHAIR, 104, 140, 2),                                                   # witness room
    (TABLE, 86, 144, 2), (CHAIR, 86, 146, 2),                                                    # law library
    (DESK, 72, 145, 2), (CHAIR, 72, 147, 2), (BOOKCASE, 67, 140, 2), (BOOKCASE, 76, 140, 2),   # District Attorney
    (TOILET, 66, 112, 2), (URINAL, 68, 112, 2), (SINK, 64, 118, 2),                            # toilets
]

# furniture rules, from tools/furniture_walls.py
ON_WALL = ("sink", "szerkal", "walllkr", "stelbar", "encpic", "nsign", "wlamp", "oolymp4", "oolympcw", "bar0", "rustb")
BACK_WALL_1 = ("bokcas2", "bokcas3", "bkshlf", "locker5", "cola", "sttable", "sttools", "toilet", "urinal", "fridge",
               "svault00", "svilla08")
BACK_WALL_2 = ("monitr", "bigshlf", "shelf00")
RIGHT_WALL_1 = ("bokcas6", "bokcas7", "dresr2", "char05")


def build_walls(fl):
    """Cells of one floor: {(x, y): (piece, style)}, gap hexes, doors."""
    door_at = {(x, y): k for x, y, k in fl["doors"]}
    xs, ys = {}, {}
    for xh, xl, y in fl["xruns"]:
        for x in range(xl, xh + 1):
            if (x, y) not in fl["open"] and (x, y) not in door_at:
                xs[(x, y)] = "B" if fl["brick"](x, y, "x") else "g"
    for x, y0, y1 in fl["yruns"]:
        for y in range(y0, y1 + 1):
            if (x, y) not in door_at:
                ys.setdefault((x, y), "B" if fl["brick"](x, y, "y") else "g")
    # an x-run hex with no x-run neighbour is only a y-run passing
    for c in list(xs):
        x, y = c
        if (x - 1, y) not in xs and (x + 1, y) not in xs and (x - 1, y) not in door_at and (x + 1, y) not in door_at:
            if c in ys:
                del xs[c]
    # junctions: the y-run's hex on an x-run row belongs to the x-run; below it, a gap
    gaps = set()
    for (x, y) in xs:
        ys.pop((x, y), None)
        if (x, y + 1) in ys and (x, y + 2) in ys:
            del ys[(x, y + 1)]
            gaps.add((x, y + 1))
    cells = {}
    for (x, y), st in xs.items():
        lo = xs.get((x - 1, y)) or ("door" if (x - 1, y) in door_at else None)
        hi = xs.get((x + 1, y)) or ("door" if (x + 1, y) in door_at else None)
        up = ys.get((x, y - 1))
        dn = ys.get((x, y + 2)) if (x, y + 1) in gaps else None
        if lo == "door":
            piece = "158" if st == "B" else "099"
        elif hi == "door":
            piece = "159" if st == "B" else "091"
        elif up or dn:
            key = (lo, hi, up, dn)
            piece = JUNCTION.get(key)
            if piece is None:
                raise SystemExit(f"no junction piece for {key} at ({x},{y})")
        elif lo and hi:
            piece = (BRICK_X if st == "B" else GREY_X)[x % 2][(x // 2) % len((BRICK_X if st == "B" else GREY_X)[x % 2])]
        else:
            raise SystemExit(f"free end of an x-run at ({x},{y})")
        cells[(x, y)] = (piece, st)
    for (x, y), st in ys.items():
        if door_at.get((x, y - 1), "").startswith("y"):
            piece = "161" if st == "B" else "108"
        elif door_at.get((x, y + 1), "").startswith("y"):
            piece = "160" if st == "B" else "107"
        elif (x, y - 1) not in ys and (x, y - 1) not in xs:
            piece = "062" if st == "B" else "102"
        else:
            piece = (BRICK_Y if st == "B" else GREY_Y)[y % 3]
        cells[(x, y)] = (piece, st)
    # the stub under a grey door's high-side jamb, as the owner's map and Fallout 2 have it
    for (x, y), k in door_at.items():
        if k.startswith("x") and (x + 1, y) in cells and cells[(x + 1, y)][0] == "099" and \
                (x + 1, y + 1) not in cells and (x + 1, y + 1) not in gaps:
            cells[(x + 1, y + 1)] = ("090", "g")
    return cells, gaps, door_at


def run():
    gi = GameIndex(pristine=False)
    raw = SOURCE.read_bytes()
    m = MapFile.parse(raw, gi.proto)
    walls_lst = parse_lst(gi.vfs.read("art\\walls\\walls.lst"))
    scen_lst = parse_lst(gi.vfs.read("art\\scenery\\scenery.lst"))
    tiles_lst = parse_lst(gi.vfs.read("art\\tiles\\tiles.lst"))
    tile_id = {}
    for i, n in enumerate(tiles_lst):
        tile_id.setdefault(n.lower().replace(".frm", ""), i)
    for layer in m.floors + m.roofs:
        for v in set(layer):
            if (v & 0xFFF) > 1:
                tile_id[tiles_lst[v & 0xFFF].lower().replace(".frm", "")] = v & 0xFFF

    spans = []
    for o in m.objects:
        _, end = MapFile._read_object(raw, o.off, gi.proto)
        spans.append((o, o.off, end))

    def art_of(o):
        t = o.pid >> 24
        lst = walls_lst if t == 3 else scen_lst if t == 2 else None
        if lst is None:
            return ""
        i = o.fid & 0xFFF
        return lst[i].lower().replace(".frm", "") if i < len(lst) else ""

    # wall pids for nec pieces: the owner's where the map has them, else by art name
    wall_pid = {}
    for o in m.objects:
        if (o.pid >> 24) == 3:
            wall_pid.setdefault(art_of(o), o.pid)
    for i in range(1, len(gi.proto_lst(3)) + 1):
        pid = 0x03000000 | i
        pr = gi.proto(pid)
        if pr is None:
            continue
        a = walls_lst[pr.fid & 0xFFF].lower().replace(".frm", "") if (pr.fid & 0xFFF) < len(walls_lst) else ""
        wall_pid.setdefault(a, pid)
    block_pid = wall_pid["block"]

    def in_zone(x, y):
        return EAST_X - 2 <= x <= WEST_X + 1 and N_Y - 4 <= y <= FRONT_Y

    floors_walls = {e: build_walls(fl) for e, fl in FLOORS.items()}

    SECRET_BLOCK, LIGHT, AUTO_BLOCK = 0x02000043, 0x0200008D, 0x02000158
    FRAME_TOP = {(118, 94), (113, 98), (103, 103), (93, 108), (83, 113), (73, 118), (63, 123),
                 (53, 128), (43, 133), (33, 138), (29, 140)}
    FRAME_DX, FRAME_DY = -10, -15

    out_objs = []             # (elev, bytes)
    removed, unmapped = [], []

    def place(data, x, y, elev=None):
        struct.pack_into(">i", data, 4, y * W + x)
        if elev is not None:
            struct.pack_into(">i", data, 0x28, elev)

    for o, a, b in spans:
        x, y = o.tile % W, o.tile // W
        t = o.pid >> 24
        data = bytearray(raw[a:b])
        if o.elevation == 0 and o.pid == SECRET_BLOCK and y < 155:
            continue
        if o.elevation == 0 and (x, y) in FRAME_TOP and o.pid in (0x020008F8, 0x020008F9):
            place(data, x + FRAME_DX, y + FRAME_DY)
            out_objs.append((0, data))
            continue
        if o.elevation == 1 and o.pid == 0x0200015C and (x, y) == BASEMENT_STAIR:
            struct.pack_into(">2i", data, 88, BASEMENT_LANDING_UP[1] * W + BASEMENT_LANDING_UP[0], -1)
            out_objs.append((1, data))
            continue
        if o.elevation != 0 or not in_zone(x, y):
            out_objs.append((o.elevation, data))
            continue
        art = art_of(o) if t in (2, 3) else ""
        if t == 3:
            if art.startswith("rustb"):
                place(data, x + RAIL["dx"], y + RAIL["dy"], RAIL["elev"])
                out_objs.append((2, data))
            elif art.startswith("bar"):
                if x == 106:
                    removed.append((x, y, art))
                else:
                    place(data, x + COUNTER["dx"], y + COUNTER["dy"])
                    out_objs.append((0, data))
            elif art == "block" and (x, y) in RAIL_ENDS:
                place(data, x + RAIL["dx"], y + RAIL["dy"], RAIL["elev"])
                out_objs.append((2, data))
            continue                                        # every other wall is rebuilt
        if t == 2 and gi.proto(o.pid) is not None and gi.proto(o.pid).subtype == 0:
            if (x, y) == (102, 145):
                out_objs.append((0, data))                  # the owner's front door
            continue
        if o.pid == LIGHT:
            out_objs.append((0, data))
            continue
        if o.pid == AUTO_BLOCK:
            if (x, y) in RAIL_ENDS:
                place(data, x + RAIL["dx"], y + RAIL["dy"], RAIL["elev"])
                out_objs.append((2, data))
            continue
        if t in (0, 1, 2):
            if (x, y) not in MOVE:
                unmapped.append((x, y, hex(o.pid), art))
                continue
            dst = MOVE[(x, y)]
            if dst is None:
                removed.append((x, y, art))
                continue
            elev = dst[2] if len(dst) > 2 else 0
            place(data, dst[0], dst[1], elev)
            if o.pid == 0x02000164 and (x, y) == (92, 118):
                struct.pack_into(">2i", data, 88, BASEMENT_LANDING[1] * W + BASEMENT_LANDING[0] | (1 << 29), -1)
            out_objs.append((elev, data))
            continue
        out_objs.append((o.elevation, data))
    if unmapped:
        for u in unmapped:
            print("unmapped:", u)
        sys.exit("objects in the rework zone without a place; add them to MOVE")

    builder = MapBuilder(NAME, elevations=tuple(m.elevations), map_id=MAP_ID)

    def new(pid, x, y, elev=0, extras=None):
        pr = gi.proto(pid)
        if pr is None:
            sys.exit(f"no proto for 0x{pid:08X}")
        spec = MapObjectSpec(pid=pid, fid=pr.fid, tile=y * W + x, elevation=elev,
                             flags=pr.flags - (1 << 32) if pr.flags >= 1 << 31 else pr.flags,
                             extras=extras if extras is not None else extras_for(pid >> 24, pid, pr.subtype))
        out = bytearray()
        builder._write_object(out, spec)
        out_objs.append((elev, out))

    n_walls = 0
    for elev, (cells, gaps, door_at) in floors_walls.items():
        for (x, y), (piece, _) in sorted(cells.items()):
            art = "nec" + piece
            if art not in wall_pid:
                sys.exit(f"no wall pid for {art} at ({x},{y})")
            new(wall_pid[art], x, y, elev)
            n_walls += 1
        for x, y in sorted(gaps):
            new(block_pid, x, y, elev)
        for (x, y), k in door_at.items():
            if elev == 0 and (x, y) == (102, 145):
                continue
            pid = DOOR_REUSE.get(k) or (0x020003BE if k.startswith("x") else 0x020003BF)
            new(pid, x, y, elev)
    for pid, x, y, elev in ADDS:
        new(pid, x, y, elev)
    for pid, x, y in ((0x020008F8, 114, 88), (0x020008F8, 121, 99), (0x020008F8, 22, 134)):
        new(pid, x, y, 0)
    sx, sy = STAIR_UP
    tx, ty = STAIR_UP_TOP
    new(0x0200015C, sx, sy, 0, extras=((ty + 2) * W + tx | (2 << 29), -1))
    new(0x02000164, tx, ty, 2, extras=(sy * W + sx + 1, -1))

    # ------------------------------------------------------------ floors
    floors = [list(f) for f in m.floors]
    roofs = [list(r) for r in m.roofs]
    e0, e2 = m.elevations.index(0), m.elevations.index(2)
    f0, f2, r0 = floors[e0], floors[e2], roofs[e0]
    old_floor = list(f0)
    rng = random.Random(1947)

    def fill(fl, xh, xl, yt, yb, names):
        for y in range(yt, yb + 1):
            for x in range(xl, xh + 1):
                fl[(y // 2) * 100 + x // 2] = tile_id[names[(x // 2 + y // 2) % len(names)]]

    desert = Counter(tiles_lst[v & 0xFFF].lower().replace(".frm", "") for v in old_floor
                     if (v & 0xFFF) > 1 and tiles_lst[v & 0xFFF].lower().startswith("edg5"))
    dnames = [n for n, c in desert.items() for _ in range(c)]
    for sqy in range(25, 66):
        for sqx in range(2, 80):
            if (f0[sqy * 100 + sqx] & 0xFFF) > 1:
                continue
            hx, hy = sqx * 2, sqy * 2
            if not (3420 < 24 * (199 - hx) + 16 * hy < 6420) or hy < 79 + (108 - hx) / 2 - 4:
                continue
            f0[sqy * 100 + sqx] = tile_id[rng.choice(dnames)]

    BACK, CORR, OFFICE = ["crbm004", "crbm007"], ["curb16"], ["tp154", "tp154", "tp166"]
    CMT = ["cmt1000", "cmt2000", "cmt3000", "cmt4000"]
    fill(f0, WEST_X, EAST_X, N_Y, 127, BACK)
    fill(f0, WEST_X, EAST_X, 127, 133, CORR)
    fill(f0, WEST_X, EAST_X, 134, FRONT_Y - 1, OFFICE)
    fill(f0, 129, 121, N_Y + 1, 127, CORR)                    # stair hall
    fill(f0, 101, 83, N_Y + 1, 126, OFFICE)                   # library
    fill(f0, 75, 73, N_Y + 1, 127, CORR)                      # service hall
    fill(f0, 71, 65, N_Y + 1, 126, CMT)                       # toilets
    fill(f0, 81, 75, 134, 138, CMT)                           # vault
    fill(f0, 73, 65, 134, 139, CORR)                          # tax lobby
    for sqy in range(67, 77):                                 # the owner's brick entry and porch
        for sqx in range(48, 55):
            f0[sqy * 100 + sqx] = old_floor[sqy * 100 + sqx]
    for sqy in range(N_Y // 2, FRONT_Y // 2 + 1):             # the owner's brick plinth on the west
        v = old_floor[sqy * 100 + 65]
        ok = (v & 0xFFF) > 1 and tiles_lst[v & 0xFFF].lower().startswith("brick")
        f0[sqy * 100 + 65] = v if ok else tile_id["brick08"]
    fill(f2, WEST_X - 1, EAST_X, N_Y + 1, FRONT_Y, OFFICE)
    fill(f2, WEST_X - 1, EAST_X, 133, 139, CORR)
    fill(f2, 129, 121, N_Y + 1, 133, CORR)                    # stair hall
    fill(f2, 129, 109, 140, FRONT_Y, BACK)                    # jury room
    fill(f2, 69, 65, N_Y + 1, 132, CMT)                       # toilets
    for sqy in range(73, 77):                                 # nothing over the porch
        for sqx in range(48, 54):
            f2[sqy * 100 + sqx] = 1
    for sqy in range(56, 67):                                 # courtroom: the owner's steel floor and carpet
        for sqx in range(45, 60):
            v = old_floor[(sqy + 9) * 100 + (sqx - 16)]
            name = tiles_lst[v & 0xFFF].lower() if (v & 0xFFF) > 1 else ""
            f2[sqy * 100 + sqx] = v if name.startswith(("stlflr", "carpet")) else tile_id["stlflr06"]

    # ------------------------------------------------------------ roof (ground floor)
    foot = {(sqx, sqy) for sqy in range(N_Y // 2, FRONT_Y // 2 + 1) for sqx in range(EAST_X // 2 - 1, WEST_X // 2)}
    for sqy in range(73, 77):
        for sqx in range(48, 53):
            foot.discard((sqx, sqy))
    for sqy in range(40, 80):
        for sqx in range(25, 70):
            if (sqx, sqy) not in foot and r0[sqy * 100 + sqx] & 0xFFF > 1:
                r0[sqy * 100 + sqx] = 1
    fillers = ["tp153", "tp154", "tp155", "tp156"]
    WEST_CYCLE = ["redbrk14", "redbrk12", "redbrk13"]
    for sqx, sqy in foot:
        outside = lambda dx, dy: (sqx + dx, sqy + dy) not in foot  # noqa: E731
        n, s_, w, e = outside(0, -1), outside(0, 1), outside(1, 0), outside(-1, 0)
        if n and w:
            name = "redbrk01"
        elif n and e:
            name = "redbrk04"
        elif s_ and w:
            name = "redbrk11"
        elif s_ and e:
            name = "redbrk08"
        elif n:
            name = "redbrk03"
        elif s_:
            name = "redbrk09" if sqx % 3 else "redbrk10"
        elif w:
            name = WEST_CYCLE[sqy % 3]
        elif e:
            name = "redbrk06"
        elif outside(-1, -1) or outside(1, -1):
            name = "redbrk11"
        elif outside(-1, 1) or outside(1, 1):
            name = "epagh093"
        else:
            inner = lambda dx, dy: not outside(dx, dy) and all(  # noqa: E731
                not outside(dx + a, dy + b) for a in (-1, 0, 1) for b in (-1, 0, 1))
            ne, se, ee = not inner(0, -1), not inner(0, 1), not inner(-1, 0)
            name = ("tp161" if ne and ee else "tp162" if se and ee else "tp157" if ne else
                    "tp159" if se else "tp158" if ee else fillers[sqx % 4])
        r0[sqy * 100 + sqx] = tile_id[name]
    for sqy in (64, 66):
        for row in (range(63, 58, -1), range(44, 39, -1)):
            for sqx, name in zip(row, ["extra005", "extra006", "extra006", "extra006", "extra007"]):
                r0[sqy * 100 + sqx] = tile_id[name]

    # ------------------------------------------------------------ write
    out = bytearray(raw[:m.tiles_offset])
    for ri, rf in zip(roofs, floors):
        out += struct.pack(">20000H", *[v for pair in zip(ri, rf) for v in pair])
    first = spans[0][1]
    out += raw[m.tiles_offset + 40000 * len(m.elevations):first - 8]
    groups = {0: [], 1: [], 2: []}
    for e, d in out_objs:
        groups[e].append(d)

    # Back to front, as the owner's Bring Forward / Send Backward does by hand.
    # Flat objects first. Then row by row (hex y): a wall comes before everything
    # in the rows in front of it, and after everything in the rows behind it; on
    # its own row, walls first, then what hangs on or stands by them. Beside a
    # side wall (a y-run), an object in front of it (at higher x) waits for the
    # wall's next three rows, whose tall sprites rise over it; an object behind
    # it (at lower x) goes before the wall's three rows above it.
    def depth(d, elev):
        tile, flags = struct.unpack_from(">i", d, 4)[0], struct.unpack_from(">I", d, 0x24)[0]
        pid = struct.unpack_from(">i", d, 0x2C)[0]
        if not 0 <= tile < 40000:
            return (0, -10**9, 0)
        if flags & 0x08:
            return (0, tile // W, tile % W)
        x, y = tile % W, tile // W
        if (pid >> 24) == 3:
            return (1, y, -x)
        k = y + 0.5
        cells = floors_walls[elev][0] if elev in floors_walls else {}
        yrun = lambda cx, cy: (cx, cy) in cells and cx % 2 == 0 and (  # noqa: E731
            (cx, cy - 1) in cells or (cx, cy + 1) in cells)
        front_of = [r for cx in range(x - 3, x) for r in range(y + 1, y + 4) if yrun(cx, r)]
        behind = [r for cx in range(x + 1, x + 4) for r in range(y - 3, y) if yrun(cx, r)]
        if front_of:
            k = max(k, max(front_of) + 0.5)
        elif behind:
            k = min(k, min(behind) - 0.5)
        # but never after the next wall row in front of it (a room's front wall)
        ahead = [r for r in range(y + 1, y + 16) if (x, r) in cells or (x + 1, r) in cells]
        if ahead:
            k = min(k, min(ahead) - 0.25)
        return (1, k, -x)
    for e in groups:
        groups[e].sort(key=lambda d, e=e: depth(d, e))
    out += struct.pack(">i", sum(len(g) for g in groups.values()))
    for e in (0, 1, 2):
        out += struct.pack(">i", len(groups[e]))
        for d in groups[e]:
            out += d
    result = bytes(out)
    MapFile.parse(result, gi.proto)
    return result, n_walls, floors_walls, removed


def check(result, floors_walls):
    """Furniture rules (tools/furniture_walls.py) and doorways, on both floors."""
    gi = GameIndex(pristine=False)
    m = MapFile.parse(result, gi.proto)
    scen = parse_lst(gi.vfs.read("art\\scenery\\scenery.lst"))
    items = parse_lst(gi.vfs.read("art\\items\\items.lst"))
    problems = []
    for elev, (cells, gaps, door_at) in floors_walls.items():
        wall = set(cells) | gaps
        for o in m.objects:
            if o.elevation != elev or not (0 <= o.tile < 40000):
                continue
            t = o.pid >> 24
            if t not in (0, 1, 2):
                continue
            x, y = o.tile % W, o.tile // W
            if not (EAST_X <= x <= WEST_X and N_Y <= y <= FRONT_Y):
                continue
            lst = scen if t == 2 else items if t == 0 else None
            art = lst[o.fid & 0xFFF].lower().replace(".frm", "") if lst and (o.fid & 0xFFF) < len(lst) else "critter"
            pr = gi.proto(o.pid)
            if t == 2 and pr is not None and pr.subtype in (0, 1):
                continue                                    # doors and stairs
            if art.startswith(("block", "light")) or o.pid in (0x02000043, 0x0200008D, 0x02000158):
                continue
            where = f"e{elev} ({x},{y}) {art}"
            if art.startswith(ON_WALL):
                if (x, y) not in cells and not art.startswith(("oolymp4", "oolympcw", "nsign")) and \
                        not art.startswith(("bar0", "rustb", "stelbar")):
                    problems.append(f"{where}: belongs on a wall hex")
                continue
            if (x, y) in wall:
                problems.append(f"{where}: on a wall")
                continue
            if (x, y) in door_at:
                problems.append(f"{where}: in a doorway")
            dirs = (-1, W - 1, W, W + 1, 1, -W) if x % 2 == 0 else (-W - 1, -1, W, 1, 1 - W, -W)
            if t != 1 and any((o.tile + d) in {yy * W + xx for xx, yy in door_at} for d in dirs):
                problems.append(f"{where}: next to a door")
            if art.startswith(BACK_WALL_1) and (x, y - 1) not in cells and (x - 1, y) not in cells:
                problems.append(f"{where}: should stand one hex below a back wall")
            if art.startswith(BACK_WALL_2) and (x, y - 2) not in cells and (x, y - 1) not in cells:
                problems.append(f"{where}: should stand two hexes below a back wall")
            if art.startswith(RIGHT_WALL_1) and (x - 1, y) not in cells:
                problems.append(f"{where}: should stand against the right-hand wall")
            if t in (0, 2) and not art.startswith(("pue", "sbone", "bone", "mstr", "roks",
                                              "drock", "rockmb", "nroks", "svilla0p", "svilla0q", "trash", "otbl",
                                              "ndeadtr", "sbibl", "arcanm", "encl41")) and \
                    (((x, y - 1) not in cells and (x - 1, y) not in cells and
                      any((x, y + d) in cells or (x + 1, y + d) in cells for d in (1, 2, 3, 4, 5)))
                     or any((x + d, y) in cells for d in (1, 2))):
                problems.append(f"{where}: within five hexes behind a front wall (draws on top of it)")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--preview", type=Path, help="render prefix, e.g. build/clcourt_rework")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--out", type=Path, default=ROOT / "build" / "CLCOURT_rework.MAP")
    args = ap.parse_args()
    result, n_walls, floors_walls, removed = run()
    args.out.write_bytes(result)
    print(f"wrote {args.out} ({len(result)} bytes); {n_walls} wall pieces; removed {len(removed)}")
    for r in removed:
        print("  removed", r)
    used = Counter(p for cells, _, _ in floors_walls.values() for p, _ in cells.values())
    print("pieces:", ", ".join(f"{p}x{n}" for p, n in sorted(used.items())))
    problems = check(result, floors_walls)
    for p in problems:
        print("  CHECK:", p)
    if args.preview:
        D = []
        order = (ROOT / "base" / "mods" / "mods_order.txt").read_text().split()
        for d in ["base/master.dat", "base/critter.dat"] + [f"base/mods/{n}" for n in order] + ["base/mods/foc"]:
            if (ROOT / d).exists():
                D += ["--data", str(ROOT / d)]
        g = str(ROOT / "reference" / "gecko" / "build" / "gecko-cli.exe")
        for elev in (0, 2):
            subprocess.run([g, "map", "render", "--map", str(args.out), "--elevation", str(elev),
                            "--out", f"{args.preview}_e{elev}.png", "--max-dim", "2400",
                            "--crop-hex", str(132 * W + 97), "--crop-extent", "800"] + D, check=False)
    if args.write:
        if problems:
            sys.exit("not writing: fix the CHECK problems first")
        running = subprocess.run(["tasklist"], capture_output=True, text=True).stdout.lower()
        for exe in ("fallout2", "gecko"):
            if exe in running:
                sys.exit(f"{exe} is running; close it before writing the map")
        src, dep = AUTHORED / NAME, DEPLOYED / NAME
        old = stash_existing(src)
        src.write_bytes(result)
        dep.write_bytes(result)
        print(f"wrote {src.relative_to(ROOT)} and the deployed copy (old copy: {old.relative_to(ROOT) if old else 'none'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
