#!/usr/bin/env python3
"""
build_clcourt.py - build CLCOURT.MAP, the Clairemont courthouse (its own map,
area_of Clairemont like the drive-in; docs/CLAIREMONT_DESIGN.md §7).

    python tools/build_clcourt.py --preview build/clcourt.png   # render only
    python tools/build_clcourt.py --write                        # write mod/data/maps/CLCOURT.MAP
    python tools/build_clcourt.py --write --force                # replace it (old copy to _replaced/)

The layout follows docs/MAP_LAYOUT_GUIDE.md (measured from every town map in
Fallout 1, Fallout 2 and the total conversions by tools/map_survey.py):

  * a play area of about 50 x 48 squares in the middle of a floored apron
    that fills almost the whole 100 x 100 grid, so scrolling never shows void
  * a double scroll-blocker ring just outside the play area, and a band of
    exit grids along its edge: world map all round, Clairemont where the road
    leaves toward it
  * the road carries on from Clairemont at the same rows (road02 x4, road11
    edge, a curb16 sidewalk on the building side) straight through the play
    area and off its far side (the riders' road)
  * buildings a few squares apart, fronting the road; clutter gathered
    around buildings and road, open desert left mostly bare

What goes on it. The buildings are in Clairemont's own style: grey
concrete-block walls (the 'nec' wall family, Clairemont's commonest) under
tar-paper roofs (tp), found with tools/find_buildings.py:
  * the courtroom: Fallout 1's Hub hall (hubwater.map) - rows of pews and a
    podium - without the Cathedral's altars and banners and the Hub's signs
  * the judge's offices: a Fallout 1 Hub building (hubdwntn.map) with
    bookcases and desks
  * the county office: Fallout 2's Klamath brick-and-block building
    (kladwtwn.map), several rooms
  * the undertaker's shed: Redding's wooden shack (corpus), beside Boot Hill
  * the gallows in a paved square across the road: Fallout: Nevada's (SL
    Center); the platform is floor tiles mbrf054-082 (Nevada's art in the
    same FOC slots, which no map FOC can reach uses), the beam is scenery
  * Boot Hill at the west end: Nevada's graveyard from SL Mormones, without
    that map's scroll blockers and exit grids

Nevada objects go through port_stamp.Converter, so anything FOC lacks is
ported with port.py and ledgered. Ported art lands above the 4096 cap: run
tools/repack_art.py after --write (back the maps up first).

This is a generator for the first layout. Once the owner edits CLCOURT.MAP
in gecko, do not re-run --write --force over it.
"""

from __future__ import annotations

import argparse
import json
import random
import re
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import port  # noqa: E402
import render  # noqa: E402
from foclib import GameIndex, MapFile, parse_lst  # noqa: E402
from foclib.formats import hex_xy, pid_type  # noqa: E402
from mapbuild import HEX_W, MapBuilder, MapObjectSpec, extras_for  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MAPS = ROOT / "mod" / "data" / "maps"
DEPLOYED = ROOT / "base" / "mods" / "foc" / "maps"
NAME = "CLCOURT.MAP"
MAP_ID = 212
CLAIREMONT_ID = 210
CLAIREMONT_ARRIVAL = 20761      # just inside Clairemont's west road end
WORLDMAP = -2

# --- layout, in squares (sx, sy). Small sx is the Clairemont (east) end.
APRON = (3, 3, 97, 97)                  # floored: nearly the whole grid
PLAY = (27, 28, 83, 80)                 # play area x0, y0, x1, y1 (exclusive)
ROAD_ROWS = (55, 56, 57, 58)            # road02, as in Clairemont's west end
ROAD_EDGE_ROW = 59                      # road11
SIDEWALK = (48, 54)                     # curb16 rows in front of the buildings, curb02 at 54
# (source, map, elevation, box x0, y0, w, h in the source) -> placed at (sx, sy);
# each box's bottom edge meets the sidewalk, 4 squares apart (towns: ~4)
LIFTS = [
    ("offices", ("fo1", "hubdwntn.map", 0, 25, 32, 13, 17), (29, 38)),
    ("courtroom", ("fo1", "hubwater.map", 0, 37, 21, 17, 19), (46, 36)),
    ("county office", ("fo2", "kladwtwn.map", 0, 32, 50, 15, 13), (67, 42)),
]
UNDERTAKER = ("bld:reddown:e0:51_61", (54, 62))   # Redding's wooden shack, beside Boot Hill
SQUARE = (33, 62, 50, 72)               # paved square across the road
GALLOWS_AT = (38, 64)
BOOTHILL_AT = (68, 62)                  # the graveyard box's top-left square
START = (37, 57)                        # on the road, ten squares in from the Clairemont end
LAMPS = []                              # the lifted buildings bring their own street lights

GROUND = [191, 192, 193, 194, 195, 196, 197, 198]   # edg5000-5007
GROUND_W = [30, 18, 18, 16, 16, 6, 7, 4]
ROAD02, ROAD11, CURB16, CURB02 = 237, 246, 132, 118

SCROLL_BLOCKER = 0x0500000C
EXIT_GRID = 0x05000010

# people, the NCR flag, pictures and sign, the chapel's emblems, altar and plants
DROP_ART = {"flag.frm", "ncrpic01.frm", "ncrpic03.frm", "ncrsign2.frm", "encl47.frm",
            "flwrlogo.frm", "altar2.frm", "maryj01.frm", "maryj02.frm"}
DEAD_TREES = [0x20003B1, 0x20003B2, 0x20003B3]                 # TREE7-9, Clairemont's
GREEN = {"tree10.frm": DEAD_TREES, "tree11.frm": DEAD_TREES,
         "bush3.frm": [0x200007D, 0x200007E, 0x200007F]}      # -> weed24-26
LAWN = re.compile(r"^gras", re.I)
# lifted buildings: the Cathedral's altars and banners, the Hub's street signs
LIFT_DROP = re.compile(r"^(ccaltar|chdflag|ss1\d\d)", re.I)

# clutter vocabulary (Clairemont's own), gathered near buildings and road
NEAR = [(0x2000066, 6), (0x2000067, 8), (0x2000068, 6), (0x2000069, 4),
        (0x200007D, 4), (0x200007E, 5), (0x200007F, 4),
        (0x20003B1, 1), (0x20003B2, 2), (0x20003B3, 1),
        (0x20000DD, 2), (0x20000DE, 2), (0x2000191, 2), (0x2000192, 1),
        (0x200018C, 2), (0x2000113, 1), (0x2000114, 1), (0x2000138, 2)]
FAR = [(0x2000066, 3), (0x2000067, 4), (0x200007D, 4), (0x200007E, 5), (0x200007F, 4),
       (0x20003B1, 2), (0x20003B2, 3), (0x20003B3, 2)]
NEAR_DENSITY = 0.30         # per square within NEAR_REACH of a building or the road (towns: ~0.3)
FAR_DENSITY = 0.05          # open ground (towns: ~0.05, and about half of it bare)
NEAR_REACH = 3

NV = "nevada"
GALLOWS_MAP, GALLOWS_BEAM_TILE = "sfchina", 19703
GALLOWS_TILE_NAMES = [f"mbrf{i:03d}.frm" for i in range(54, 83)]
BOOTHILL_MAP = "SFSHUTL2"


def corpus_building(bid: str) -> dict:
    with (ROOT / "corpus" / "buildings.jsonl").open(encoding="utf-8") as f:
        for line in f:
            if bid in line:
                r = json.loads(line)
                if r["id"] == bid:
                    return r
    sys.exit(f"no building {bid} in corpus/buildings.jsonl")


class Builder:
    def __init__(self, gi: GameIndex, seed: int = 212):
        self.gi = gi
        self.rng = random.Random(seed)
        self.mb = MapBuilder(NAME, elevations=(0,), map_id=MAP_ID)
        self.tiles = parse_lst(gi.vfs.read("art\\tiles\\tiles.lst"))
        self.tile_id = {}
        for i, n in enumerate(self.tiles):
            if n:
                self.tile_id.setdefault(n.lower(), i)
        self.footprints: list[tuple[int, int, int, int]] = []    # squares, for clutter

    def art_names(self, t: int) -> list[str]:
        d = {0: "items", 2: "scenery", 3: "walls"}[t]
        return [n.lower() for n in parse_lst(self.gi.vfs.read(f"art\\{d}\\{d}.lst"))]

    def ground_tile(self) -> int:
        return self.rng.choices(GROUND, GROUND_W)[0]

    def ground(self):
        self.mb.floors[0] = [1] * 10000
        self.mb.roofs[0] = [1] * 10000
        x0, y0, x1, y1 = APRON
        for sy in range(y0, y1):
            for sx in range(x0, x1):
                self.mb.set_floor(0, sx, sy, self.ground_tile())
        for sx in range(APRON[0], APRON[2]):
            for sy in ROAD_ROWS:
                self.mb.set_floor(0, sx, sy, ROAD02)
            self.mb.set_floor(0, sx, ROAD_EDGE_ROW, ROAD11)
        # sidewalk only in front of the town
        for sx in range(PLAY[0], PLAY[2]):
            for sy in range(SIDEWALK[0], SIDEWALK[1]):
                self.mb.set_floor(0, sx, sy, CURB16)
            self.mb.set_floor(0, sx, SIDEWALK[1], CURB02)
        x0, y0, x1, y1 = SQUARE
        for sy in range(y0, y1):
            for sx in range(x0, x1):
                self.mb.set_floor(0, sx, sy, CURB16)
        # a ragged edge on the square: ground bites into the outer ring
        for sy in range(y0, y1):
            for sx in range(x0, x1):
                edge = sx in (x0, x1 - 1) or sy in (y0, y1 - 1)
                if edge and self.rng.random() < 0.35:
                    self.mb.set_floor(0, sx, sy, self.ground_tile())

    def building(self, bid: str, at: tuple[int, int]) -> int:
        b = corpus_building(bid)
        sx0, sy0 = at
        w, h = b["size_sq"]
        self.footprints.append((sx0, sy0, sx0 + w, sy0 + h))
        for ry, row in enumerate(b.get("floor", [])):
            for rx, c in enumerate(row):
                if c >= 0:
                    name = b["palette"][c]
                    tid = self.ground_tile() if LAWN.match(name) else self.tile_id.get(name.lower())
                    if tid:
                        self.mb.set_floor(0, sx0 + rx, sy0 + ry, tid)
        for ry, row in enumerate(b.get("roof", [])):
            for rx, c in enumerate(row):
                if c >= 0:
                    tid = self.tile_id.get(b["palette"][c].lower())
                    if tid:
                        self.mb.set_roof(0, sx0 + rx, sy0 + ry, tid)
        hx0, hy0 = sx0 * 2, sy0 * 2
        n = 0
        for o in b["objects"]:
            t = o.get("t", 2)
            art = (o.get("art") or "").lower()
            # no people, and no misc: a building lifted from a town map brings
            # that town's scroll blockers and exit grids with it
            if t in (1, 5) or art in DROP_ART:
                continue
            pid = o.get("pid")
            fid = o.get("fid")
            if art in GREEN:
                pid, fid = self.rng.choice(GREEN[art]), None
            pr = self.gi.proto(pid) if pid else None
            if pr is None:
                continue
            self.add(pid, fid or pr.fid, (hy0 + o["dy"]) * HEX_W + hx0 + o["dx"], o.get("rot") or 0, o.get("frm") or 0)
            n += 1
        return n

    def add(self, pid, fid, tile, rot=0, frame=0, extras=None):
        pr = self.gi.proto(pid)
        if extras is None:
            extras = extras_for(pid_type(pid), pid, pr.subtype if pr else None)
        self.mb.add(MapObjectSpec(pid=pid, fid=fid, tile=tile, elevation=0,
                                  rotation=rot, frame=frame, extras=extras))


# ------------------------------------------------------------ Nevada pieces

def nevada_pieces(b: Builder, dry_run: bool):
    """The gallows and Boot Hill, converted into FOC ids."""
    from port_stamp import Converter, Foc  # heavy import, only when needed
    src = port.open_source(NV)
    conv = Converter(Foc(), NV, src, dry_run, "clcourt")

    gm = MapFile.parse(src.vfs.read(f"maps\\{GALLOWS_MAP}.map"), src.proto)
    src_tiles = parse_lst(src.vfs.read("art\\tiles\\tiles.lst"))
    names = set(GALLOWS_TILE_NAMES)
    cells = [(i % 100, i // 100, v) for i, v in enumerate(gm.floors[0])
             if (v & 0xFFF) < len(src_tiles) and src_tiles[v & 0xFFF].lower() in names]
    ax, ay = min(c[0] for c in cells), min(c[1] for c in cells)
    gx, gy = GALLOWS_AT
    for x, y, v in cells:
        b.mb.set_floor(0, gx + x - ax, gy + y - ay, b.tile_id[src_tiles[v & 0xFFF].lower()])
    hax, hay = ax * 2, ay * 2
    placed = 0
    for o in gm.objects:
        x, y = hex_xy(o.tile)
        if o.elevation != gm.elevations[0] or pid_type(o.pid) in (1, 5):
            continue
        on_platform = (ax <= x // 2 < ax + 8) and (ay <= y // 2 < ay + 8)
        if o.tile != GALLOWS_BEAM_TILE and not (on_platform and o.pid in (0x300026E, 0x2000043, 0x200008D)):
            continue
        pid = conv.map_pid(o.pid)
        fid = conv.map_frm(o.pid, o.fid, pid)
        if pid is None or fid is None:
            continue
        b.add(pid, fid, (gy * 2 + y - hay) * HEX_W + gx * 2 + x - hax, o.rotation, o.frame)
        placed += 1
    b.footprints.append((gx, gy, gx + 7, gy + 7))
    print(f"  gallows: {len(cells)} platform tiles, {placed} objects")

    cm = MapFile.parse(src.vfs.read(f"maps\\{BOOTHILL_MAP}.map"), src.proto)
    sc = parse_lst(src.vfs.read("art\\scenery\\scenery.lst"))
    stones = [o for o in cm.objects if pid_type(o.pid) == 2
              and sc[o.fid & 0xFFF].lower().startswith("gravstn")]
    xs = [hex_xy(o.tile)[0] for o in stones]
    ys = [hex_xy(o.tile)[1] for o in stones]
    x0, x1, y0, y1 = min(xs) - 4, max(xs) + 4, min(ys) - 4, max(ys) + 4
    ox, oy = BOOTHILL_AT[0] * 2 - x0, BOOTHILL_AT[1] * 2 - y0
    placed = 0
    for o in cm.objects:
        x, y = hex_xy(o.tile)
        # no critters, and no misc: that corner of the Nevada map carries its
        # scroll blockers and exit grids
        if o.elevation != cm.elevations[0] or not (x0 <= x <= x1 and y0 <= y <= y1):
            continue
        if pid_type(o.pid) in (1, 5):
            continue
        pid = conv.map_pid(o.pid)
        fid = conv.map_frm(o.pid, o.fid, pid)
        if pid is None or fid is None:
            continue
        b.add(pid, fid, (y + oy) * HEX_W + x + ox, o.rotation, o.frame)
        placed += 1
    b.footprints.append((BOOTHILL_AT[0], BOOTHILL_AT[1],
                         BOOTHILL_AT[0] + (x1 - x0) // 2, BOOTHILL_AT[1] + (y1 - y0) // 2))
    print(f"  Boot Hill: {placed} objects")
    s = conv.stats
    print(f"  converter: kept {s['kept']}, ledger {s['ledger']}, art match {s['artmatch']}, "
          f"ported {s['ported']}, unresolved {s['unresolved']}")


def lift(b: Builder, spec, at, dry_run: bool) -> int:
    """Copy a box of a source map (floor, roof and objects, no critters or
    misc) to square `at`, converting ids through port_stamp.Converter. A
    piece whose FOC proto at the same pid draws art of the same name keeps
    that pid (Fallout 1's doors and podium: same pids and art as Fallout 2,
    different proto bytes, so no port is needed)."""
    from port_stamp import Converter, Foc
    src_name, mp, elev, x0, y0, w, h = spec
    src = port.open_source(src_name)
    conv = Converter(Foc(), src_name, src, dry_run, "clcourt")
    m = MapFile.parse(src.vfs.read(f"maps\\{mp}"), src.proto)
    ei = m.elevations.index(elev)
    sx0, sy0 = at
    b.footprints.append((sx0, sy0, sx0 + w, sy0 + h))
    # The building is its largest roof in the box, with its walls: the
    # largest connected chain of wall hexes on or next to that roof (whether
    # a mapper put a wall under the roof edge or just outside it varies from
    # map to map). A wall separated from that chain by an empty hex - an
    # alley wall, the next building's wall line - stays behind, and so do
    # sidewalk, lamps and signs away from the building.
    from buildings import roof_components
    comps = [c for c in roof_components(m, ei)
             if any(x0 <= q % 100 < x0 + w and y0 <= q // 100 < y0 + h for q in c)]
    roof = {(q % 100, q // 100) for q in max(comps, key=len)}
    keep = {(x + dx, y + dy) for x, y in roof for dx in (-1, 0, 1) for dy in (-1, 0, 1)}
    wall_hexes = {hex_xy(o.tile) for o in m.objects
                  if o.elevation == elev and pid_type(o.pid) == 3 and 0 <= o.tile < 40000
                  and (hex_xy(o.tile)[0] // 2, hex_xy(o.tile)[1] // 2) in keep}
    chains, seen = [], set()
    for start in wall_hexes:
        if start in seen:
            continue
        stack, chain = [start], set()
        seen.add(start)
        while stack:
            hx, hy = stack.pop()
            chain.add((hx, hy))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    q = (hx + dx, hy + dy)
                    if q in wall_hexes and q not in seen:
                        seen.add(q)
                        stack.append(q)
        chains.append(chain)
    building_walls = max(chains, key=len) if chains else set()
    for x, y in keep:
        k = y * 100 + x
        v = m.floors[ei][k] & 0xFFF
        if v > 1:
            b.mb.set_floor(0, sx0 + x - x0, sy0 + y - y0, conv.map_tile(v, lambda: None))
        if (x, y) in roof:
            v = m.roofs[ei][k] & 0xFFF
            if v > 1:
                b.mb.set_roof(0, sx0 + x - x0, sy0 + y - y0, conv.map_tile(v, lambda: None))
    art = parse_lst(src.vfs.read("art\\scenery\\scenery.lst"))
    foc_sc = b.art_names(2)
    n = 0
    for o in m.objects:
        if o.elevation != elev or pid_type(o.pid) in (1, 5) or not (0 <= o.tile < 40000):
            continue
        x, y = hex_xy(o.tile)
        if not (x0 <= x // 2 < x0 + w and y0 <= y // 2 < y0 + h):
            continue
        if (x // 2, y // 2) not in keep:
            continue
        if pid_type(o.pid) == 3 and (x, y) not in building_walls:
            continue
        name = art[o.fid & 0xFFF].lower() if pid_type(o.pid) == 2 and (o.fid & 0xFFF) < len(art) else ""
        if name and LIFT_DROP.match(name):
            continue
        same = b.gi.proto(o.pid)
        if name and same is not None and foc_sc[same.fid & 0xFFF] == name:
            pid, fid = o.pid, (o.fid & ~0xFFF) | (same.fid & 0xFFF)
        else:
            pid = conv.map_pid(o.pid)
            fid = conv.map_frm(o.pid, o.fid, pid) if pid else None
        if pid is None or fid is None:
            continue
        hx, hy = sx0 * 2 + x - x0 * 2, sy0 * 2 + y - y0 * 2
        b.add(pid, fid, hy * HEX_W + hx, o.rotation, o.frame)
        n += 1
    return n


def gallows_tiles_art(dry_run: bool) -> int:
    """Nevada's platform art into FOC's same-named tile slots (FOC layer)."""
    src = port.open_source(NV)
    out = ROOT / "mod" / "data" / "art" / "tiles"
    n, rows = 0, []
    for name in GALLOWS_TILE_NAMES:
        data = src.vfs.read(f"art\\tiles\\{name}")
        dest = out / name
        if dest.is_file() and dest.read_bytes() == data:
            continue
        n += 1
        if not dry_run:
            out.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            rows.append(port.ledger_row(NV, "art", f"art\\tiles\\{name}", name,
                                        f"mod/data/art/tiles/{name}", name,
                                        "gallows platform (SL Center); replaces the unused vanilla tile in the same slot"))
    if rows:
        port.append_ledger(rows)
        port.regen_ledger_md()
    return n


# ------------------------------------------------------------ the edges

def rect_loop(x0: int, y0: int, x1: int, y1: int) -> list[tuple[int, int]]:
    """Hexes on the border of a hex rectangle: a closed loop under hex
    adjacency ((x+1, y) and (x, y+1) are always neighbours)."""
    pts = [(x, y0) for x in range(x0, x1 + 1)] + [(x, y1) for x in range(x0, x1 + 1)]
    pts += [(x0, y) for y in range(y0 + 1, y1)] + [(x1, y) for y in range(y0 + 1, y1)]
    return pts


def edges(b: Builder) -> tuple[int, int]:
    """Two scroll-blocker loops outside the play area, and exits only where
    the road leaves it (towns: ~64 exit hexes on 2 sides): Clairemont at the
    east end, the world map at the west (the riders' road)."""
    hx0, hy0, hx1, hy1 = PLAY[0] * 2, PLAY[1] * 2, PLAY[2] * 2 - 1, PLAY[3] * 2 - 1
    blockers = set(rect_loop(hx0 - 3, hy0 - 3, hx1 + 3, hy1 + 3)) | set(rect_loop(hx0 - 6, hy0 - 6, hx1 + 6, hy1 + 6))
    sb = b.gi.proto(SCROLL_BLOCKER)
    for x, y in blockers:
        b.add(SCROLL_BLOCKER, sb.fid, y * HEX_W + x)
    eg = b.gi.proto(EXIT_GRID)
    road_hexes = range(ROAD_ROWS[0] * 2 - 4, ROAD_EDGE_ROW * 2 + 6)
    to_cl = 0
    for y in road_hexes:
        for x in (hx0, hx0 + 1):
            b.add(EXIT_GRID, eg.fid, y * HEX_W + x, extras=(CLAIREMONT_ID, CLAIREMONT_ARRIVAL, 0, 2))
            to_cl += 1
        for x in (hx1 - 1, hx1):
            b.add(EXIT_GRID, eg.fid, y * HEX_W + x, extras=(WORLDMAP, -1, 0, 0))
    return len(blockers), to_cl


# ------------------------------------------------------------ clutter

def clutter(b: Builder) -> tuple[int, int]:
    """Clutter gathered within NEAR_REACH squares of a building or the road,
    sparse beyond; nothing on or next to another object."""
    taken = set()
    for o in b.mb.objects:
        x, y = hex_xy(o.tile)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                taken.add((x + dx, y + dy))

    def near(sx, sy):
        for x0, y0, x1, y1 in b.footprints:
            if x0 - NEAR_REACH <= sx < x1 + NEAR_REACH and y0 - NEAR_REACH <= sy < y1 + NEAR_REACH:
                return True
        return abs(sy - (ROAD_ROWS[0] + ROAD_EDGE_ROW) / 2) <= 3 + NEAR_REACH

    ground = set(GROUND)
    n_near = n_far = 0
    x0, y0, x1, y1 = PLAY
    for sy in range(y0 + 2, y1 - 2):
        for sx in range(x0 + 2, x1 - 2):
            if (b.mb.floors[0][sy * 100 + sx] & 0xFFF) not in ground:
                continue
            is_near = near(sx, sy)
            if b.rng.random() > (NEAR_DENSITY if is_near else FAR_DENSITY):
                continue
            hx, hy = sx * 2 + b.rng.randint(0, 1), sy * 2 + b.rng.randint(0, 1)
            if (hx, hy) in taken:
                continue
            pool = NEAR if is_near else FAR
            pid = b.rng.choices([p for p, _ in pool], [w for _, w in pool])[0]
            b.add(pid, b.gi.proto(pid).fid, hy * HEX_W + hx)
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    taken.add((hx + dx, hy + dy))
            n_near += is_near
            n_far += not is_near
    lamp = b.gi.proto(0x2000126)
    for sx, sy in LAMPS:
        b.add(0x2000126, lamp.fid, sy * 2 * HEX_W + sx * 2)
    return n_near, n_far


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--preview", type=Path, help="render to this PNG; writes nothing")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if not (args.preview or args.write):
        ap.error("--preview or --write")

    gi = GameIndex(pristine=False)
    if args.write:
        print(f"  gallows platform tiles written: {gallows_tiles_art(False)}")
        gi = GameIndex(pristine=False)
    b = Builder(gi)
    b.ground()
    for label, spec, at in LIFTS:
        print(f"  {label}: {lift(b, spec, at, not args.write)} objects")
    print(f"  undertaker's shed: {b.building(*UNDERTAKER)} objects")
    nevada_pieces(b, not args.write)
    near, far = clutter(b)
    print(f"  clutter: {near} near buildings and road, {far} on open ground, {len(LAMPS)} lamps")
    blockers, to_cl = edges(b)
    print(f"  edges: {blockers} scroll blockers, {to_cl} exits to Clairemont, {to_cl} to the world map")
    b.mb.start_tile = START[1] * 2 * HEX_W + START[0] * 2
    data = b.mb.to_bytes()

    if args.preview:
        m = MapFile.parse(data, gi.proto)
        render.render_map(gi, m, 0, True).save(args.preview)
        args.preview.with_suffix(".map").write_bytes(data)    # for map_survey_one.py
        print(f"preview: {args.preview} (+ .map)")
        return 0

    out = MAPS / NAME
    for p in (out, DEPLOYED / NAME):
        if p.is_file() and not args.force:
            sys.exit(f"{p} exists - it may hold gecko edits. Pass --force to replace it "
                     f"(the old one goes to mod/data/maps/_replaced/).")
    if out.is_file():
        keep = MAPS / "_replaced"
        keep.mkdir(exist_ok=True)
        shutil.copy2(out, keep / f"{NAME}.{time.strftime('%Y%m%d_%H%M%S')}")
    out.write_bytes(data)
    print(f"wrote {out} ({len(data)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
