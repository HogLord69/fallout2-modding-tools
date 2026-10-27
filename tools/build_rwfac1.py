#!/usr/bin/env python3
"""
build_rwfac1.py - lay out RWFAC1, the Waterworks (the Facility Below's civilian
tier), from the owner's design doc (docs/RWFAC1_DESIGN.md): floors, walls,
doors, the flooded hall's water and the props. The fittings, vermin and locks
are rwfac1.ssl's (foc_fac.h).

    python tools/build_rwfac1.py --preview build/rwfac1      # layout map + labelled renders, nothing installed

A dungeon first (owner: "the real world layouts are just a guide. I want them
to be fun"), laid out the way the originals and the total conversions lay out
theirs (FO2's Gecko tunnels and power plant, Toxic Caves, military base,
Sierra Army Depot, the EPA; FO1's Mariposa and the Glow; Nevada's and
Sonora's bunkers): corridors that loop round blocks of rooms so there is a
second way round, rooms from halls to closets, dead-end side rooms, turns
that hide what is ahead, and rock where the building broke into the ground.

Elevation 0, the Well-Head Level: the stair landing (the way in from the
colonists' dig) opens onto a corridor with the stores off one side and the
well-head room off the other. The motor room is behind the well-head room,
and a back passage from it comes round to the stores, so the level loops.
The intake shaft, an open pit with a ledge round it, is off the far side of
the well-head room.

Elevation 1, the Treatment Level: the shaft foot opens onto the filter
gallery, the hub, with filter-bed bays along its south side. North of it the
chlorine store behind a two-door airlock, the maintenance office with a
supply closet, and the control room. South, a short stair down into the
flooded pump hall; the breaker room and the service lift hall behind it. The
dead east wing has fallen in: rock walls, reached by a breach from the lift
hall or a squeeze through the gallery's east wall. The pipe tunnel is the
doc's long way round, from the flooded hall up the west side and along the
back to the control room's back door, with a dead-end alcove on the way.

Walls are Fallout 2's industrial panel set (dv) by the originals' grammar
(tools/wallsets.py, measured by tools/wall_junctions.py), the set the
originals use underground for Gecko's plant and tunnels, the EPA, the Glow
(the town's concrete block, nec, is a surface set). Doors are Gecko's round
hatches in their frames; arches are the one-hex lintel openings. The rock is
Fallout 2's dark brown cave set (ca), lit face or dark back by which side the
cave is on, from build/ca_corners/grammar.json.

Floors as Gecko's tunnels and plant lay them (tools/floor_borders.py): a
checker of brn1000 / brn1001 inside a frame of the vtgst strips along every
wall, with its corner pieces; the floor starts on the square inside a room's
north and west walls and runs under its south and east walls, as theirs do.
Grating (grt2000) on the shaft foot and the filter bays, Fallout 2's steel
plate checker (plt2000 / plt1000) in the motor room and the control room, the
brn checker on the fallen-in wing. The flooded hall gets its water as scenery
in the objects pass, the way New Reno lays its pool (Newr2 elevation 2): one
water01 on each floor square, on the square's (odd x, odd y) hex, flat and not
blocking, with invisible blockers on the square's four hexes so the water
can't be walked. A grating walkway runs along the pumps on the back wall and
down the west side to the door, the long way round to the control room
(Fallout 2's cave water tiles laid flat read as ridges). The intake shaft's pit is
left open; its squares go in <stem>.voids.json beside the map so
tools/rock_field.py leaves them.

Objects are written in hex order on each level, as the originals write them. Once the owner has seen it: copy to
mod/data/maps/RWFAC1.MAP (and the voids file), then tools/map_edges.py and
tools/rock_field.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foclib import GameIndex, parse_lst  # noqa: E402
from foclib.formats import MapFile  # noqa: E402
from mapbuild import MapBuilder, MapObjectSpec, extras_for  # noqa: E402
from wallsets import WALLSETS, build as build_walls  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
W = 200
MAP_ID = 214
NAME = "RWFAC1.MAP"
CA_GRAMMAR = ROOT / "build" / "ca_corners" / "grammar.json"
WALLSET = WALLSETS["dv"]

# floor styles
BRN, GRATE, PLATE, PIT = "brn", "grate", "plate", "pit"

# ------------------------------------------------------------------ the levels
# rooms: (name, x_high, x_low, y_top, y_bottom, floor style) - x even, y odd; walls run round every room
# xgap / ygap: wall hexes taken out where two rooms open into each other: (y, x_lo, x_hi) / (x, y_lo, y_hi)
# doors: (x, y, "x" | "y") - a hatch, five hexes along the run; arches: framed one-hex openings
# rock: fallen-in ground: (name, outline, closure). The outline runs from a point on a concrete wall
#   round to another (each step along x or y); its two end hexes stay concrete. The closure points
#   (along the concrete) close the floor's outline. breaches (x, y_lo, y_hi) open a y-run onto it.
# extra: (x_high, x_low, y_top, y_bottom, style) floor laid over a room's (the pump hall's walkway)
LEVELS = {
    0: dict(
        rooms=[("Stair landing", 124, 110, 111, 123, BRN),
               ("", 120, 110, 89, 111, BRN),                       # the corridor up from the landing
               ("Stores", 140, 120, 77, 101, BRN),
               ("", 134, 110, 71, 77, BRN),                        # the back passage
               ("Motor room", 110, 86, 71, 83, PLATE),
               ("Well-head room", 110, 78, 83, 107, BRN),
               ("Intake shaft", 78, 62, 87, 103, PIT)],
        xgap=[], ygap=[], breaches=[],
        doors=[(116, 111, "x"), (120, 95, "y"), (126, 77, "x"), (110, 73, "y"), (98, 83, "x"),
               (110, 97, "y"), (78, 95, "y")],
        arches={(116, 111)},
        rock=[],
        extra=[],
    ),
    1: dict(
        rooms=[("Shaft foot", 152, 138, 95, 111, GRATE),
               ("Filter gallery", 138, 74, 91, 111, BRN),
               ("", 124, 112, 111, 117, GRATE),                    # filter-bed bays
               ("", 108, 98, 111, 117, GRATE),
               ("", 134, 128, 111, 117, BRN),                      # the stair down to the pump hall
               ("Flooded pump hall", 152, 98, 117, 139, BRN),
               ("", 130, 122, 85, 91, BRN),                        # the chlorine airlock
               ("Chlorine store", 138, 114, 71, 85, BRN),
               ("Maintenance office", 110, 94, 73, 91, BRN),
               ("", 110, 104, 73, 81, BRN),                        # its supply closet
               ("Control room", 90, 74, 71, 91, PLATE),
               ("Breaker room", 94, 78, 111, 123, BRN),
               ("Service lift", 94, 78, 123, 139, BRN),
               ("", 158, 152, 65, 139, BRN),                       # the pipe tunnel: west side
               ("Pipe tunnel", 152, 74, 65, 71, BRN),              # and along the back
               ("", 100, 94, 59, 65, BRN)],                        # a dead-end alcove off it
        xgap=[(111, 113, 123), (111, 99, 107),                     # the bays open onto the gallery
              (117, 129, 133),                                     # the stair opens into the pump hall
              (65, 95, 99)],                                       # the alcove opens off the tunnel
        ygap=[(138, 99, 107),                                      # the shaft foot opens onto the gallery
              (152, 65, 70)],                                      # the tunnel turns the corner
        breaches=[(74, 103, 105), (78, 131, 133)],                 # the squeeze from the gallery, the breach from the lift hall
        doors=[(130, 111, "x"), (126, 91, "x"), (126, 85, "x"), (102, 91, "x"), (106, 81, "x"),
               (86, 91, "x"), (82, 71, "x"), (86, 111, "x"), (86, 123, "x"), (152, 131, "y")],
        # (86, 91): the control room's hatch, beside its window (foc_fac.h FAC1_CONTROL_DOOR)
        arches={(130, 111), (106, 81)},
        windows=[(91, 75, 80)],                                    # the control room's window onto the gallery
        broken={(74, 102), (74, 106), (78, 130), (78, 134)},       # the wall ends at the two breaches
        rock=[("Dead east wing", [(74, 97), (68, 97), (68, 95), (60, 95), (60, 101), (54, 101), (54, 113),
                                  (58, 113), (58, 121), (52, 121), (52, 133), (58, 133), (58, 139), (78, 139)],
               [(78, 111), (74, 111)])],
        extra=[(152, 98, 117, 121, GRATE),                         # the pump hall's walkway: along the pumps
               (152, 148, 121, 133, GRATE)],                       # and down the west side to the door
        # flood: (room, dry boxes as (x_high, x_low, y_top, y_bottom)) - the rest of the room is water
        flood=[("Flooded pump hall", [(152, 98, 117, 121), (152, 148, 121, 133)])],
    ),
}
START = (116, 118)          # on the stair landing, at the foot of the colonists' ladder (foc_fac.h FAC1_STAIR_ARRIVE)
MAP_SCRIPT = 1631           # rwfac1.int, as the map's header has always had it
RWCORE2, DIG_ARRIVE = 201, 16506     # the ladder up: RWCORE2 (106, 82), beside the dig (foc_fac.h FAC_DIG_ARRIVE)

# The props, furnished the way Gecko's power plant and tunnels furnish theirs (the set these walls
# come from), measured by tools/room_props.py, tools/wall_decor.py and tools/prop_footprints.py:
#   * every room's back walls (its north x-run and its east y-run, the ones the camera sees) carry
#     vents in pairs, two hexes apart, on the plain panels (luvers1 on an x-run, luvers2 on a y-run),
#     about one per twelve back-wall hexes, and one light (mblight), on the east wall where there is
#     one; never the front walls
#   * machine rooms: tanks and machinery against the back walls and in the back (north-east)
#     corner, one machine set into the east wall (geckm07, in place of a wall piece, with a blocker
#     either side); a tank stands in the open only as the room's centrepiece
#   * control rooms: consoles in a row along the east wall, a monitor on it, the sign
#   * stores: boxes in the corner and on the back walls, lockers in pairs
#   * offices: a desk in the back corner with its chair
#   * each piece's blockers as the originals put them; a container (an item) gets one on its hex
# (pid, x, y, contents) - contents [(pid, count)] for a container; INWALL pieces replace the wall hex.
LADDER, BLOCK = 0x0200008B, 0x02000158
GECKM07, GECKM08, GECKM06 = 0x0200048F, 0x02000490, 0x020003EF
POWER003 = 0x02000795
GEKTANK1, GEKTANK2, GEKTANK3, GEKTANK5 = 0x02000494, 0x02000495, 0x02000496, 0x020004A6
BVS48, BVS31, CONSIGN2 = 0x02000333, 0x02000322, 0x0200048B
BOXES2, BOXES4, NJUNK5, NJUNK6 = 0x020000DD, 0x020000DF, 0x02000113, 0x02000114
BARREL2, BARREL4, BARREL5, STEAM = 0x0200018C, 0x0200018E, 0x0200018F, 0x020004A4
DROCK2, DROCK4, ROCK05 = 0x020001AD, 0x020001AF, 0x02000050
SS108 = 0x0200029A
LOCKER1, LOCKER3, SHELVES, DESK2, DESK3 = 0x84, 0x86, 0x99, 0xB6, 0xB7
WORKBENCH = 0x02001331
LUVERS = {"x": 0x0200049E, "y": 0x0200049F}
LIGHT = 0x0200033C
WATER = 0x020003FB                    # water01, New Reno's pool water
INWALL = {GECKM07}
ONWALL = {BVS31, CONSIGN2}            # hung on a wall hex, over the panel
FOOTPRINT = {GEKTANK2: [(1, -1)], GEKTANK3: [(-1, 0)], GECKM08: [(0, -1)], GECKM06: [(0, -1)],
             GECKM07: [(-1, 0), (1, 0)], NJUNK6: [(0, 1), (1, -1), (1, 0)], BOXES4: [(-1, 1), (0, 1)],
             BVS48: [(0, -1)], POWER003: [(-1, 0), (1, 0), (0, -1)]}
PROPS = {
    0: [
        (DROCK2, 112, 113, None), (ROCK05, 121, 113, None),        # stair landing: the dig's spill
        (BOXES2, 122, 79, None), (NJUNK5, 132, 79, None),          # stores: boxes in the corner and on the back wall
        (BOXES4, 122, 86, None),
        (LOCKER1, 136, 79, [(127, 1), (40, 1), (79, 2)]),          # lockers in a pair: the rope, a stimpak, flares
        (LOCKER3, 138, 79, []),
        (GECKM08, 88, 73, None), (POWER003, 96, 73, None),         # motor room: machinery on the back wall
        (GEKTANK5, 104, 73, None), (GECKM07, 86, 78, None),        # and one set into the east wall
        (WORKBENCH, 88, 80, None),
        (GEKTANK1, 94, 96, None),                                  # well-head room: the well's casing, in the open
        (GEKTANK3, 80, 85, None), (GECKM06, 102, 85, None),        # the pump control on the back wall
        (GECKM07, 78, 88, None),
    ],
    1: [
        (GEKTANK5, 114, 114, None), (GEKTANK5, 100, 114, None),    # the filter beds' tanks, in the bays
        (GECKM08, 100, 119, None), (GEKTANK3, 112, 119, None),     # pump hall: pumps on the back wall
        (GEKTANK5, 140, 119, None), (GECKM07, 98, 128, None),
        (BARREL4, 116, 73, None), (BARREL2, 118, 73, None),        # chlorine store: drums in the corner
        (BARREL5, 116, 76, None), (BARREL2, 130, 73, None),
        (STEAM, 124, 78, None),                                    # and the gas off them
        (LOCKER3, 134, 73, [(48, 1), (49, 1)]),                    # the plant's chems
        (DESK2, 96, 75, []), (SS108, 98, 77, None),                # office: the desk in the corner, its chair
        (SHELVES, 106, 75, []), (NJUNK6, 108, 76, None),           # the closet
        (BVS48, 76, 78, None), (BVS48, 76, 82, None),              # control room: consoles along the east wall
        (BVS31, 74, 86, None), (CONSIGN2, 74, 76, None),           # a monitor and the sign on it
        (DESK3, 88, 73, [(41, 30)]),                               # the manager's desk, a little money in it
        (POWER003, 90, 113, None), (GECKM07, 78, 118, None),       # breaker room
        (DROCK2, 66, 99, None), (ROCK05, 56, 103, None),           # dead east wing: rock where the roof came in
        (DROCK4, 56, 124, None), (NJUNK6, 70, 120, None),
        (BOXES2, 96, 61, None), (LOCKER1, 98, 61, [(40, 1)]),      # a stash someone left in the alcove
    ],
}
CONTAINERS = {LOCKER1, LOCKER3, SHELVES, DESK2, DESK3}


# vtgst, the strips along the walls (tools/floor_borders.py): corners, then each side's pair by (c + r) parity
FRAME = {("N", "W"): "vtgst003", ("N", "E"): "vtgst004", ("S", "W"): "vtgst002", ("S", "E"): "vtgst001",
         "N": ("vtgst012", "vtgst011"), "S": ("vtgst016", "vtgst015"),
         "W": ("vtgst014", "vtgst013"), "E": ("vtgst010", "vtgst009")}
CHECKER = ("brn1001", "brn1000")        # (c + r) even, odd
PLATE_CHECKER = ("plt2000", "plt1000")  # steel plate, as Fallout 2 lays it (tools/floor_borders.py, floor survey)


def screen(x, y):
    v3 = W - 1 - x
    return 48 * (v3 // 2) + 32 * (v3 & 1) + 16 * y, -12 * (v3 // 2) + 12 * y


def runs_from_rooms(lv):
    """x-runs and y-runs round every room, merged, with the gaps and breaches taken out."""
    xc, yc = set(), set()
    for _, xh, xl, yt, yb, _ in lv["rooms"]:
        assert xh % 2 == 0 and xl % 2 == 0 and yt % 2 == 1 and yb % 2 == 1, (xh, xl, yt, yb)
        for x in range(xl, xh + 1):
            xc |= {(x, yt), (x, yb)}
        for y in range(yt, yb + 1):
            yc |= {(xh, y), (xl, y)}
    for y, a, b in lv["xgap"]:
        xc -= {(x, y) for x in range(a, b + 1)}
    for x, a, b in lv["ygap"] + lv["breaches"]:
        yc -= {(x, y) for y in range(a, b + 1)}

    def segments(cells, along):
        out = []
        lines = {}
        for x, y in cells:
            lines.setdefault(y if along == "x" else x, []).append(x if along == "x" else y)
        for k, vs in lines.items():
            vs.sort()
            start = prev = vs[0]
            for v in vs[1:] + [None]:
                if v is None or v != prev + 1:
                    if prev > start:
                        out.append((prev, start, k) if along == "x" else (k, start, prev))
                    start = v
                prev = v if v is not None else prev
        return out
    return segments(xc, "x"), segments(yc, "y")


def rock_cells(points):
    """The hexes along an outline of x and y steps, its two end hexes left to the concrete."""
    cells = []
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if y0 == y1:
            step = 1 if x1 > x0 else -1
            cells += [(x, y0) for x in range(x0, x1, step)]
        elif x0 == x1:
            step = 1 if y1 > y0 else -1
            cells += [(x0, y) for y in range(y0, y1, step)]
        else:
            raise SystemExit(f"rock outline step {(x0, y0)} -> {(x1, y1)} is neither along x nor along y")
    cells.append(points[-1])
    cells = list(dict.fromkeys(cells))
    return [c for c in cells if c not in (points[0], points[-1])]


# The cave set is two-sided: ca001-048 and ca071-076 are the lit rock face, seen from inside the
# cave; ca049-070 and ca077-080 the dark back. Fallout's view shows a room's north and east walls
# (low y, low x) from inside and its south and west walls from behind, so a rock wall with the
# cave below it or to its west (higher y, higher x) shows its face, and one with the cave above it
# or to its east shows its back. ca081-091 are mine timbers, not rock.
ROCK_FACE = {f"ca{n:03d}" for n in list(range(1, 49)) + list(range(71, 77))}
ROCK_BACK = {f"ca{n:03d}" for n in list(range(49, 71)) + list(range(77, 81))}


def inside(pts, x, y):
    n, c = len(pts), False
    for i in range(n):
        (x0, y0), (x1, y1) = pts[i], pts[(i + 1) % n]
        if (y0 > y) != (y1 > y) and x < (x1 - x0) * (y - y0) / (y1 - y0) + x0:
            c = not c
    return c


def rock_pieces(cells, grammar, outline):
    c = set(cells)
    out = {}
    by_s = {}
    for key, pieces in grammar.items():
        by_s.setdefault(key.split("|")[0] + "|" + key.split("|")[2], Counter()).update(dict(pieces))
    for (x, y) in cells:
        s = "".join(k if (x + dx, y + dy) in c else "." for k, dx, dy in
                    (("W", -1, 0), ("E", 1, 0), ("N", 0, -1), ("S", 0, 1)))
        diag = "".join(k if (x + dx, y + dy) in c else "." for k, dx, dy in
                       (("a", -1, -1), ("b", 1, -1), ("c", -1, 1), ("d", 1, 1)))
        key = f"{s}|{diag}|p{x % 2}"
        face = (inside(outline, x, y + 2) and not inside(outline, x, y - 2)) or \
               (inside(outline, x + 2, y) and not inside(outline, x - 2, y))
        want = ROCK_FACE if face else ROCK_BACK
        pool = list(grammar.get(key, [])) + by_s.get(f"{s}|p{x % 2}", Counter()).most_common(12)
        choices = [p for p, _ in pool if p in want] or [p for p, _ in pool if p in ROCK_FACE | ROCK_BACK]
        if not choices:
            raise SystemExit(f"no rock piece for {key} at ({x},{y})")
        top = list(dict.fromkeys(choices))[:4]
        out[(x, y)] = top[(x * 7 + y * 3) % len(top)]
    return out


def room_squares(xh, xl, yt, yb):
    """The floor squares of a room: from inside its north and west walls to under its south and east ones."""
    return [(c, r) for r in range((yt + 1) // 2, (yb - 1) // 2 + 1) for c in range(xl // 2, xh // 2)]


def paint(style, squares, walls, tid, voids):
    """{square: tile id} for one floor area in its style."""
    out = {}
    for c, r in squares:
        if style == GRATE:
            out[(c, r)] = tid("grt2000")
            continue
        if style == PLATE:
            out[(c, r)] = tid(PLATE_CHECKER[(c + r) % 2])
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
        elif style == PIT:
            voids.add((c, r))
        else:
            out[(c, r)] = tid(CHECKER[(c + r) % 2])
    return out


def wall_decor(lv, cells):
    """Vents in pairs and a light on each room's back walls (its north x-run and east y-run),
    on the plain panels only, as Gecko's plant hangs them (tools/wall_decor.py)."""
    out = []
    used = set()
    for name, xh, xl, yt, yb, style in lv["rooms"]:
        north = [(x, yt) for x in range(xl + 2, xh - 1) if cells.get((x, yt)) == "dv1000"]
        east = [(xl, y) for y in range(yt + 2, yb - 1) if cells.get((xl, y)) == "dv1019"]
        for run, kind in ((north, "x"), (east, "y")):
            hexes = set(run)
            for (x, y) in run:
                a, b2 = (x, y), ((x + 2, y) if kind == "x" else (x, y + 2))
                k = (x // 2 + y) if kind == "x" else (y // 2 + x)
                if k % 12 == 0 and b2 in hexes and not ({a, b2} & used):
                    out += [(a, LUVERS[kind]), (b2, LUVERS[kind])]
                    used |= {a, b2}
        spots = [h for h in east if h not in used] or [h for h in north if h not in used]
        if spots and (xh - xl) * (yb - yt) >= 60:
            h = spots[len(spots) // 2]
            out.append((h, LIGHT))
            used.add(h)
    return [((x, y), pid) for (x, y), pid in out]


def build(gi):
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

    b = MapBuilder(NAME, elevations=(0, 1), start_tile=START[1] * W + START[0], start_elevation=0,
                   start_orientation=2, map_id=MAP_ID, map_script_index=MAP_SCRIPT)
    objs, report, voids = [], {}, {}
    for elev, lv in LEVELS.items():
        xruns, yruns = runs_from_rooms(lv)
        cells, gaps, hatches, glass = build_walls(WALLSET, xruns, yruns, lv["doors"], lv["arches"],
                                                  lv.get("windows", ()), lv.get("broken", ()))
        rock = {}
        for name, pts, closure in lv["rock"]:
            rock.update(rock_pieces(rock_cells(pts), grammar, pts + closure))
        # a machine set into a wall takes a plain wall panel's place (the originals put it on a
        # block); if the hex given is not one, the nearest along the same run
        props = []
        for pid, x, y, contents in PROPS[elev]:
            if pid in INWALL:
                plain = ("dv1019", "dv1021", "dv1000", "dv1004")
                along = [(x, y + d) for d in (0, 1, -1, 2, -2, 3, -3, 4, -4)] if (x, y - 1) in cells or (x, y + 1) in cells                     else [(x + d, y) for d in (0, 1, -1, 2, -2, 3, -3, 4, -4)]
                spot = next((h for h in along if cells.get(h) in plain and cells.get((h[0], h[1] - 1)) in plain + ("block",)
                             and cells.get((h[0], h[1] + 1)) in plain + ("block",)), None)
                if spot is None:
                    raise SystemExit(f"e{elev}: no plain wall panel near ({x},{y}) for the machine")
                cells[spot] = "block"
                x, y = spot
            props.append((pid, x, y, contents))
        decor = wall_decor(lv, cells)
        for (x, y), piece in cells.items():
            if (x, y) not in rock:
                objs.append((elev, x, y, wall_pid[piece]))
        for x, y in gaps:
            if (x, y) not in rock:
                objs.append((elev, x, y, wall_pid["block"]))
        for (x, y), piece in rock.items():
            objs.append((elev, x, y, wall_pid[piece]))
        for x, y, pid in hatches + glass:
            objs.append((elev, x, y, pid))
        report[elev] = (len(cells), len(gaps), len(rock), len(hatches), len(lv["arches"]))
        walls = set(cells) | set(rock)
        floor = {}
        voids[elev] = set()
        for name, xh, xl, yt, yb, style in lv["rooms"]:
            floor.update(paint(style, room_squares(xh, xl, yt, yb), walls, tid, voids[elev]))
        for name, pts, closure in lv["rock"]:
            poly = pts + closure
            xs, ys = [p[0] for p in poly], [p[1] for p in poly]
            sq = [(c, r) for r in range(min(ys) // 2, max(ys) // 2 + 1) for c in range(min(xs) // 2, max(xs) // 2 + 1)
                  if inside(poly, 2 * c + 1, 2 * r + 0.5)]      # off the outline's odd rows
            floor.update({s: tid(CHECKER[(s[0] + s[1]) % 2]) for s in sq if s not in floor})
        for xh, xl, yt, yb, style in lv["extra"]:
            floor.update(paint(style, room_squares(xh, xl, yt, yb), walls, tid, voids[elev]))
        for (c, r), t in floor.items():
            b.set_floor(elev, c, r, t)
            voids[elev].discard((c, r))
        # the props with their blockers, the wall decor, and invisible blockers on the rim of an
        # open pit so nobody walks off the ledge
        taken = set()
        for pid, x, y, contents in props:
            if pid not in INWALL | ONWALL and (x, y) in walls:
                raise SystemExit(f"e{elev}: 0x{pid:08X} at ({x},{y}) is on a wall")
            objs.append((elev, x, y, pid, None, contents))
            taken.add((x, y))
            foot = list(FOOTPRINT.get(pid, [])) + ([(0, 0)] if pid in CONTAINERS else [])
            for dx, dy in foot:
                h = (x + dx, y + dy)
                if h not in walls and h not in taken - {(x, y)}:
                    objs.append((elev, h[0], h[1], BLOCK, None, None))
        for (x, y), pid in decor:
            objs.append((elev, x, y, pid, None, None))
        rooms = {r[0]: r for r in lv["rooms"]}
        for name, dry in lv.get("flood", ()):
            _, xh, xl, yt, yb, _ = rooms[name]
            dry_sq = {s for box in dry for s in room_squares(*box)}
            held = taken | {(o[1], o[2]) for o in objs if o[0] == elev and o[3] == BLOCK}
            for c, r in room_squares(xh, xl, yt, yb):
                if (c, r) in dry_sq:
                    continue
                objs.append((elev, 2 * c + 1, 2 * r + 1, WATER, None, None))
                for h in ((2 * c, 2 * r), (2 * c + 1, 2 * r), (2 * c, 2 * r + 1), (2 * c + 1, 2 * r + 1)):
                    if h not in walls and h not in held:
                        objs.append((elev, h[0], h[1], BLOCK, None, None))
        pit = {(2 * c + dx, 2 * r + dy) for c, r in voids[elev] for dx in (0, 1) for dy in (0, 1)}
        for (x, y) in sorted(pit):
            if any(((x + dx, y + dy) not in pit) for dx in (-1, 0, 1) for dy in (-1, 0, 1)):
                objs.append((elev, x, y, BLOCK, None, None))
        report[elev] += (len(PROPS[elev]), len(decor))
    # the colonists' ladder up to the dig (Fallout 2's ladder data: destination tile with its facing
    # and elevation bits, then the map)
    objs.append((0, 111, 117, LADDER, (DIG_ARRIVE | (3 << 26), RWCORE2), None))
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
    return data, report, {str(e): sorted(v) for e, v in voids.items()}


def label(path, out_dir):
    import map_edges as me
    out_dir.mkdir(parents=True, exist_ok=True)
    for elev, lv in LEVELS.items():
        png = out_dir / f"rwfac1_e{elev}.png"
        ox, oy, s = me.render(path, elev, png, 2600)
        im = Image.open(png).convert("RGB")
        d = ImageDraw.Draw(im)
        marks = [(n, (xh + xl) // 2, (yt + yb) // 2) for n, xh, xl, yt, yb, _ in lv["rooms"] if n]
        marks += [(n, sum(p[0] for p in pts) // len(pts), sum(p[1] for p in pts) // len(pts)) for n, pts, _ in lv["rock"]]
        for name, cx, cy in marks:
            px, py = screen(cx, cy)
            px, py = (px + me.GECKO_OFFSET[0] - ox) * s, (py + me.GECKO_OFFSET[1] - oy) * s
            w = d.textlength(name)
            d.rectangle([px - w / 2 - 3, py - 7, px + w / 2 + 3, py + 7], fill=(0, 0, 0))
            d.text((px - w / 2, py - 6), name, fill=(255, 220, 120))
        bbox = Image.open(png).convert("L").point(lambda v: 255 if v > 12 else 0).getbbox()
        if bbox:
            im = im.crop((max(0, bbox[0] - 30), max(0, bbox[1] - 30), min(im.width, bbox[2] + 30), min(im.height, bbox[3] + 30)))
        im.save(out_dir / f"rwfac1_e{elev}_labelled.png")
        print("  wrote", out_dir / f"rwfac1_e{elev}_labelled.png")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--preview", metavar="DIR", required=True)
    a = ap.parse_args()
    gi = GameIndex(pristine=False)
    data, report, voids = build(gi)
    out = Path(a.preview) / NAME
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    (out.parent / "RWFAC1.voids.json").write_text(json.dumps(voids), encoding="utf-8")
    for e, (nw, ng, nr, nd, na, npr, ndec) in report.items():
        print(f"e{e}: {nw} wall pieces, {ng} gap blockers, {nr} rock pieces, {nd} hatches, {na} arches, "
              f"{npr} props, {ndec} on the walls")
    print("wrote", out)
    label(out, Path(a.preview))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
