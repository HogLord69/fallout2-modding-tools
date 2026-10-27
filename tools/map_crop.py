#!/usr/bin/env python3
"""
map_crop.py - cut a map back down to the vanilla city-encounter footprint,
losslessly, without touching the source map.

    python tools/map_crop.py                                   # REDWELL.MAP -> RWCORE.MAP
    python tools/map_crop.py --dry-run --render build/rwcore.png
    python tools/map_crop.py --src base/mods/foc/maps/REDWELL.MAP --out RWCORE.MAP
    python tools/map_crop.py --floor original                  # the old 7,455-square desert margin
    python tools/map_crop.py --dump-mask mod/data/maps/REDWELL.MAP.bak   # refresh the mask file

WHY
    REDWELL.MAP grew to the whole 200x200 hex grid (all 10,000 floor squares
    painted, exit grids along the outer edge, ~3,000 objects) while the town's
    growth tiers were being laid out on one map. The design has since moved to
    a permanent core map plus district maps that unlock as the colony grows, so
    the starting town needs to be the size it used to be again: the vanilla
    city-encounter frame. The original Redwell was generated on that template
    (city2.map - 430 exit grids on a rotated quad, hex x31..169 / y29..163, and
    433 scroll blockers); city1-8 all share it.

    This is a byte-level splice, NOT a MapBuilder round-trip. MapBuilder
    rewrites every object from a spec and zeroes flags / light / inventories /
    door states, which is fine for the fauna pass but wrong for "keep exactly
    what the editor did". Here every kept object is copied verbatim; only the
    tile block, the object counts, the frame objects and the header name change.

WHAT IT DOES
    floor    void (tile 1) every square outside the chosen footprint:
               --floor encounter  city2.map's own 2,969 painted squares - the
                                  exit ring plus a thin margin, exactly what a
                                  city encounter looks like          (default)
               --floor original   the pre-expansion Redwell footprint, a 7,455-
                                  square shape snapshotted in
                                  tools/redwell_orig_floor.txt. Bigger desert
                                  margin, but it also keeps any floor the
                                  expanded map painted out there (roads and
                                  building floors with their walls gone).
               --floor keep       leave the floor alone (objects still cropped)
             Squares inside the footprint keep whatever the source paints.
    roof     void every roof square whose centre is outside the exit-grid hull.
    objects  keep every object whose hex is inside the convex hull of the
             template's exit grids; drop the rest. Drop ALL of the source's exit
             grids and scroll blockers, then append the template's 430 exit
             grids + 433 scroll blockers byte-for-byte (vanilla flags, exit to
             worldmap).
    header   name -> the output filename. The engine matches the header name
             against maps.txt map_name (map.cc: wmMapMatchNameToIdx), so the
             GAME needs a maps.txt entry before it can load the result; gecko
             does not care and opens it by filename.
    well     re-bind rwwell to the town well. The Modoc well (modwell1) that
             carried the script was deleted in gecko and a different well
             placed (proto 5397, otower3.frm); gecko cannot write script ids,
             so the script fell off and the whole day-1 sequence with it. The
             source map still carries the now-orphaned script-table entry, so
             the fix is two int32s on the well object (WELL_PID). --no-well
             skips.

    flags    give every object whose stored flags are 0 the flags its proto
             says a fresh placement gets (object.cc::objectCreateWithPid: FLAT,
             NO_BLOCK, MULTIHEX, the TRANS_* family, LIGHT_THRU, SHOOT_THRU,
             WALL_TRANS_END, NO_HIGHLIGHT) plus the proto's light. The engine
             reads object flags from the .map and never re-derives them, and
             this project's editor and MapBuilder both write 0 - so every
             weed, dirt patch and shrub on the map was a solid, non-flat
             obstacle, which is what walled the well in ("I cannot get
             there"). Vanilla's mapper writes the proto flags; this restores
             that. --no-flags skips.

    Objects with a script are never dropped silently - the tool refuses if one
    falls outside the hull, because losing a scripted NPC is never what you
    meant. Move it inside in gecko first, or pass --drop-scripted.

OUTPUT
    Written to BOTH trees, identical: mod\\data\\maps\\<OUT> (authored source of
    truth) and base\\mods\\foc\\maps\\<OUT> (the mounted copy gecko edits). The
    source map is never modified.

    NEVER OVERWRITES SILENTLY. base\\mods\\foc\\maps\\<OUT> is the very file
    gecko saves to, so an output name that already exists may be someone's
    hand-edited map. If either destination exists the tool refuses; --force
    replaces it, but only after moving the old file to
    mod\\data\\maps\\_replaced\\<OUT>.<timestamp>. (2026-09-19: three re-runs of
    `--out RWCORE2.MAP` wiped out 40 minutes of gecko work on a RWCORE2 the
    owner had already made. This guard exists so that cannot happen again.)
"""

from __future__ import annotations

import argparse
import shutil
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foclib import GameIndex, MapFile, hex_xy, pid_type  # noqa: E402
from redwell_fauna import _convex_hull, _in_poly  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
AUTHORED = ROOT / "mod" / "data" / "maps"
DEPLOYED = ROOT / "base" / "mods" / "foc" / "maps"
REPLACED = AUTHORED / "_replaced"


def stash_existing(path: Path) -> Path | None:
    """Move a file we are about to replace into mod/data/maps/_replaced, dated."""
    if not path.is_file():
        return None
    REPLACED.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(path.stat().st_mtime))
    dst = REPLACED / f"{path.name}.{stamp}.{path.parent.parent.name}"
    shutil.move(str(path), str(dst))
    return dst
MASK_FILE = Path(__file__).resolve().parent / "redwell_orig_floor.txt"

TEMPLATE = "maps\\city2.map"          # the frame the original Redwell was built on
EXIT_GRID_PIDS = range(0x05000010, 0x05000018)
SCROLL_BLOCKER_PID = 0x0500000C
VOID_TILE = 1                         # art\tiles\edge (black); FO2 "no floor here"
SQUARES = 10000
HEADER_NAME_OFF, HEADER_NAME_LEN = 4, 16

# object flag bits (object.h) - the subset objectCreateWithPid derives from a proto
F_FLAT, F_NO_BLOCK, F_MULTIHEX, F_NO_HIGHLIGHT = 0x08, 0x10, 0x800, 0x1000
F_TRANS_RED, F_TRANS_NONE, F_TRANS_WALL = 0x4000, 0x8000, 0x10000
F_TRANS_GLASS, F_TRANS_STEAM, F_TRANS_ENERGY = 0x20000, 0x40000, 0x80000
F_WALL_TRANS_END, F_LIGHT_THRU, F_SHOOT_THRU = 0x10000000, 0x20000000, 0x80000000
OBJ_FLAGS_OFF, OBJ_LIGHT_OFF = 36, 52     # int32 offsets inside an object record
# critter data block, in ON-DISK order (proto.cc::objectDataRead +
# objectCritterCombatDataRead - NOT the CritterCombatData struct order):
# 72-byte header, 12-byte inventory header, then
#   84 field_0   88 damageLastTurn   92 maneuver   96 ap   100 results
#  104 aiPacket  108 team           112 whoHitMeCid   116 hp   120 rad   124 poison
# Getting this wrong once (ai at 100, team at 104) wrote every colonist's AI
# packet number into `results` - the DAM_* flag word - so they all loaded
# KNOCKED_OUT: no Talk verb, USE opened their (empty) inventory like a corpse.
OBJ_CRIT_RESULTS_OFF, OBJ_CRIT_AI_OFF, OBJ_CRIT_TEAM_OFF = 100, 104, 108
OBJ_CRIT_WHOHIT_OFF, OBJ_CRIT_HP_OFF = 112, 116

WELL_PID = 0x02001515                 # proto 5397 / otower3.frm, "a well", at hex
                                      # (100,94). NOT 0x02001AE9 - that is one of the
                                      # four oolymp7x shrubs planted around it, one of
                                      # which sits on the old modwell1 hex (101,96).
WELL_SCRIPT = "rwwell"
SCRIPT_TYPE_SCENERY = 3               # script-table block / sid high byte
OBJ_SID_OFF, OBJ_SIDX_OFF = 64, 68    # int32 offsets inside an object record


# ----------------------------------------------------------------- map bytes

def object_spans(raw: bytes, m: MapFile, proto):
    """
    [(obj, start, end)] for every TOP-LEVEL object, in file order, plus the
    offset of the object section and the byte tail after the last object.
    Inventory children live inside their owner's span, so a span is exactly
    what has to move as a unit.
    """
    if not m.objects:
        sys.exit("source map has no objects - nothing to crop")
    if m.elevations != [0]:
        sys.exit(f"expected a single-elevation map on level 0, got {m.elevations}")
    sec = m.objects[0].off - 8                       # total count + elev-0 count
    total, n0 = struct.unpack_from(">2i", raw, sec)
    if total != len(m.objects) or n0 != total:
        sys.exit(f"object section at 0x{sec:X} disagrees with the parse "
                 f"(total={total}, elev0={n0}, parsed={len(m.objects)})")
    spans = []
    p = sec + 8
    for _ in range(n0):
        obj, end = MapFile._read_object(raw, p, proto)
        spans.append((obj, p, end))
        p = end
    tail = raw[p:]
    if tail != b"\0" * 8:                            # elev 1 + elev 2 counts
        sys.exit(f"unexpected {len(tail)} byte tail after the last object: {tail[:16]!r}")
    return sec, spans, tail


def read_tiles(raw: bytes, m: MapFile):
    pairs = struct.unpack_from(">20000H", raw, m.tiles_offset)
    return list(pairs[0::2]), list(pairs[1::2])      # roofs, floors


def pack_tiles(roofs, floors) -> bytes:
    return struct.pack(">20000H", *[v for pair in zip(roofs, floors) for v in pair])


# --------------------------------------------------------------------- masks

def load_mask_file(path: Path) -> list[bool]:
    rows = [ln.rstrip("\n") for ln in path.read_text(encoding="ascii").splitlines()
            if ln and not ln.startswith("#")]
    if len(rows) != 100 or any(len(r) != 100 for r in rows):
        sys.exit(f"{path.name}: expected 100 rows x 100 columns of '#'/'.'")
    return [c == "#" for r in rows for c in r]


def mask_from_map(m: MapFile) -> list[bool]:
    return [t > 1 for t in m.floors[0]]


def dump_mask(m: MapFile, src: Path) -> None:
    mask = mask_from_map(m)
    painted = sum(mask)
    if painted > 0.9 * SQUARES:
        sys.exit(f"{src.name} paints {painted}/{SQUARES} squares - that is the "
                 f"expanded map, not the original footprint; refusing to overwrite "
                 f"{MASK_FILE.name} with it")
    lines = [
        "# Painted-floor footprint of the ORIGINAL (pre-expansion) REDWELL.MAP,",
        "# one row of 100 squares per line, row 0 first: '#' = floor painted, '.' = void (tile 1).",
        f"# Snapshot of {src.as_posix()} by tools/map_crop.py --dump-mask;",
        f"# {painted} painted squares. map_crop.py --floor original crops to this shape.",
    ]
    for y in range(100):
        lines.append("".join("#" if mask[y * 100 + x] else "." for x in range(100)))
    MASK_FILE.write_text("\n".join(lines) + "\n", encoding="ascii")
    print(f"wrote {MASK_FILE.relative_to(ROOT)} ({painted} painted squares)")


def square_in_hull(sq: int, hull) -> bool:
    # floor squares and object hexes share the .map's mirrored raw convention;
    # a square column ~= 2 hex columns (same mapping redwell_fauna uses).
    return _in_poly((sq % 100) * 2, (sq // 100) * 2, hull)


# ---------------------------------------------------------------------- crop

def crop(raw: bytes, m: MapFile, tpl_raw: bytes, tpl: MapFile, gi: GameIndex,
         out_name: str, floor_mode: str, drop_scripted: bool):
    sec, spans, tail = object_spans(raw, m, gi.proto)
    _tsec, tspans, _ttail = object_spans(tpl_raw, tpl, gi.proto)

    exits = [hex_xy(o.tile) for o in tpl.objects if o.pid in EXIT_GRID_PIDS]
    hull = _convex_hull(exits)
    exit_tiles = {o.tile for o in tpl.objects if o.pid in EXIT_GRID_PIDS}

    # --- objects ------------------------------------------------------------
    kept, dropped = [], []
    for obj, s, e in spans:
        if obj.pid in EXIT_GRID_PIDS or obj.pid == SCROLL_BLOCKER_PID:
            dropped.append(obj)                       # frame is rebuilt below
            continue
        hx, hy = hex_xy(obj.tile) if 0 <= obj.tile < 40000 else (-1, -1)
        if 0 <= obj.tile < 40000 and not _in_poly(hx, hy, hull):
            dropped.append(obj)
            continue
        kept.append((obj, raw[s:e]))

    scripted_lost = [o for o in dropped
                     if o.script_index not in (-1, 0xFFFFFFFF)
                     and o.pid not in EXIT_GRID_PIDS and o.pid != SCROLL_BLOCKER_PID]
    if scripted_lost and not drop_scripted:
        for o in scripted_lost:
            hx, hy = hex_xy(o.tile)
            print(f"  scripted object outside the frame: pid=0x{o.pid:08X} "
                  f"script_index={o.script_index} at hex ({hx},{hy})")
        sys.exit("refusing to drop scripted objects - move them inside the exit "
                 "ring in gecko, or pass --drop-scripted")

    frame = [(obj, tpl_raw[s:e]) for obj, s, e in tspans
             if obj.pid in EXIT_GRID_PIDS or obj.pid == SCROLL_BLOCKER_PID]

    # --- tiles ----------------------------------------------------------------
    roofs, floors = read_tiles(raw, m)
    if floor_mode == "original":
        keep_floor = load_mask_file(MASK_FILE)
    elif floor_mode == "encounter":
        keep_floor = mask_from_map(tpl)
    else:
        keep_floor = [True] * SQUARES
    floor_voided = roof_voided = 0
    for sq in range(SQUARES):
        if floors[sq] > 1 and not keep_floor[sq]:
            floors[sq] = VOID_TILE
            floor_voided += 1
        if roofs[sq] > 1 and not square_in_hull(sq, hull):
            roofs[sq] = VOID_TILE
            roof_voided += 1

    # --- assemble ---------------------------------------------------------------
    head = bytearray(raw[:sec])
    name = out_name.upper().encode("cp1252", "replace")[:HEADER_NAME_LEN - 1]
    head[HEADER_NAME_OFF:HEADER_NAME_OFF + HEADER_NAME_LEN] = (
        name + b"\0" * (HEADER_NAME_LEN - len(name)))
    head[m.tiles_offset:m.tiles_offset + 40000] = pack_tiles(roofs, floors)

    body = bytearray()
    n = len(kept) + len(frame)
    body += struct.pack(">2i", n, n)
    for _obj, b in kept:
        body += b
    for _obj, b in frame:
        body += b
    body += tail
    out = bytes(head) + bytes(body)

    # --- report ------------------------------------------------------------------
    on_exit = [o for o, _ in kept if o.tile in exit_tiles]
    # objects hugging the cut: inside the hull, but a hex 2 steps out is not
    edge = []
    for o, _ in kept:
        if not (0 <= o.tile < 40000):
            continue
        hx, hy = hex_xy(o.tile)
        if any(not _in_poly(hx + dx, hy + dy, hull)
               for dx, dy in ((2, 0), (-2, 0), (0, 2), (0, -2))):
            edge.append((hx, hy, o.pid))
    by_type = {}
    for o in dropped:
        if o.pid in EXIT_GRID_PIDS or o.pid == SCROLL_BLOCKER_PID:
            continue
        by_type[pid_type(o.pid)] = by_type.get(pid_type(o.pid), 0) + 1
    return out, dict(
        hull=hull, kept=len(kept), frame=len(frame),
        dropped_by_type=by_type, dropped_critters=[
            (hex_xy(o.tile), o.pid) for o in dropped if pid_type(o.pid) == 1],
        floor_voided=floor_voided, roof_voided=roof_voided,
        on_exit=on_exit, edge=edge,
    )


# ----------------------------------------------------------------- well script

def bind_well(out: bytes, gi: GameIndex) -> tuple[bytes, str]:
    """
    Give the well its script back if it lost it. Reuses the orphaned rwwell
    entry in the map's script table (a table entry is what makes a binding
    live - object.cc looks the script up by sid and then overwrites the
    object's script index from it), so no table rewrite is needed.
    """
    m = MapFile.parse(out, gi.proto)
    line = gi.script_line(WELL_SCRIPT)
    if line is None:
        return out, f"{WELL_SCRIPT}.int is not in scripts.lst - well left unbound"
    sidx = line - 1                                   # map stores 0-based
    wells = [o for o in m.objects if o.pid == WELL_PID]
    if not wells:
        return out, f"no well (pid 0x{WELL_PID:08X}) on the map - nothing to bind"
    well = wells[0]
    if well.script_index == sidx:
        return out, f"well at {hex_xy(well.tile)} already runs {WELL_SCRIPT} (index {sidx})"
    used = {o.sid for o in m.objects if o.sid != -1}
    orphan = next((pid for pid, si in m.script_pids
                   if (pid >> 24) == SCRIPT_TYPE_SCENERY and si == sidx and pid not in used), None)
    if orphan is None:
        return out, (f"well is unbound and the script table has no spare {WELL_SCRIPT} "
                     f"entry - run tools/redwell_fauna.py on the source first")
    buf = bytearray(out)
    struct.pack_into(">2i", buf, well.off + OBJ_SID_OFF, orphan, sidx)
    return bytes(buf), (f"well at {hex_xy(well.tile)} re-bound to {WELL_SCRIPT} "
                        f"(sid 0x{orphan:08X}, index {sidx})")


# ---------------------------------------------------------------- object flags

def flags_from_proto(pflags: int) -> int:
    """object.cc::objectCreateWithPid, bit for bit."""
    f = 0
    if pflags & F_FLAT:
        f |= F_FLAT
    if pflags & F_NO_BLOCK:
        f |= F_NO_BLOCK
    if pflags & F_MULTIHEX:
        f |= F_MULTIHEX
    if pflags & F_TRANS_NONE:
        f |= F_TRANS_NONE
    elif pflags & F_TRANS_WALL:
        f |= F_TRANS_WALL
    elif pflags & F_TRANS_GLASS:
        f |= F_TRANS_GLASS
    elif pflags & F_TRANS_STEAM:
        f |= F_TRANS_STEAM
    elif pflags & F_TRANS_ENERGY:
        f |= F_TRANS_ENERGY
    elif pflags & F_TRANS_RED:
        f |= F_TRANS_RED
    if pflags & F_LIGHT_THRU:
        f |= F_LIGHT_THRU
    if pflags & F_SHOOT_THRU:
        f |= F_SHOOT_THRU
    if pflags & F_WALL_TRANS_END:
        f |= F_WALL_TRANS_END
    if pflags & F_NO_HIGHLIGHT:
        f |= F_NO_HIGHLIGHT
    return f


def normalize_flags(out: bytes, gi: GameIndex) -> tuple[bytes, dict]:
    """
    Objects stored with flags == 0 get their proto's placement flags and light,
    exactly as if the vanilla mapper had placed them. Objects that already carry
    flags (the city2 frame, anything hand-set) are left alone.

    Critters stored with hp == 0 get their proto's max hp, an AI packet of 0
    ("Addict - Wimpy") gets the proto's packet, team 0 gets the proto's team
    and whoHitMeCid 0 becomes -1 (nobody) - the values a vanilla mapper writes.
    The engine reads all of these from the .map and never refills them.

    Also REPAIRS the damage this function itself did between 2026-09-19 and
    09-21, when the AI packet was written to offset 100 = `results` (the DAM_*
    flags): a fresh map stores results 0, so a results word that equals the
    proto's AI packet is that bug's signature and gets cleared.
    """
    m = MapFile.parse(out, gi.proto)
    buf = bytearray(out)
    stats = {"seen": 0, "flagged": 0, "walkable": 0, "flat": 0, "lit": 0, "no_proto": 0,
             "healed": 0, "ai": 0, "team": 0, "whohit": 0, "results_repaired": 0,
             "results_other": []}
    for o in m.objects:
        stats["seen"] += 1
        pr = gi.proto(o.pid)
        if pr is None:
            stats["no_proto"] += 1
            continue
        cur = struct.unpack_from(">I", buf, o.off + OBJ_FLAGS_OFF)[0]
        if cur == 0:
            nf = flags_from_proto(pr.flags)
            if nf:
                struct.pack_into(">I", buf, o.off + OBJ_FLAGS_OFF, nf)
                stats["flagged"] += 1
                if nf & F_NO_BLOCK:
                    stats["walkable"] += 1
                if nf & F_FLAT:
                    stats["flat"] += 1
        ld, li = struct.unpack_from(">2i", buf, o.off + OBJ_LIGHT_OFF)
        if ld == 0 and li == 0 and (pr.light_distance or pr.light_intensity):
            struct.pack_into(">2i", buf, o.off + OBJ_LIGHT_OFF, pr.light_distance, pr.light_intensity)
            stats["lit"] += 1
        if (o.pid >> 24) == 1 and pr.max_hp is not None:
            def rd(off):
                return struct.unpack_from(">i", buf, o.off + off)[0]

            def wr(off, v):
                struct.pack_into(">i", buf, o.off + off, v)

            results, ai = rd(OBJ_CRIT_RESULTS_OFF), rd(OBJ_CRIT_AI_OFF)
            if results != 0 and results == pr.ai_packet:
                wr(OBJ_CRIT_RESULTS_OFF, 0)          # the 09-19 mis-write, undone
                results = 0
                stats["results_repaired"] += 1
            elif results != 0:
                stats["results_other"].append((o.pid, o.tile, results))
            if rd(OBJ_CRIT_HP_OFF) == 0 and pr.max_hp > 0:
                wr(OBJ_CRIT_HP_OFF, pr.max_hp)
                stats["healed"] += 1
            if ai == 0 and pr.ai_packet:
                wr(OBJ_CRIT_AI_OFF, pr.ai_packet)
                stats["ai"] += 1
            if rd(OBJ_CRIT_TEAM_OFF) == 0 and pr.team:
                wr(OBJ_CRIT_TEAM_OFF, pr.team)
                stats["team"] += 1
            if rd(OBJ_CRIT_WHOHIT_OFF) == 0:
                wr(OBJ_CRIT_WHOHIT_OFF, -1)
                stats["whohit"] += 1
    return bytes(buf), stats


def critter_note(s: dict) -> str:
    """One report line for normalize_flags' critter half."""
    note = (f"critters: {s['healed']} given max hp (were 0), {s['ai']} given AI packet, "
            f"{s['team']} given team, {s['whohit']} whoHitMe -> -1, "
            f"{s['results_repaired']} KNOCKED_OUT results words repaired")
    if s["results_other"]:
        note += "\n  WARNING: non-zero damage flags left on: " + ", ".join(
            f"0x{pid:08X}@({t % 200},{t // 200}) results=0x{r:X}" for pid, t, r in s["results_other"])
    return note


# -------------------------------------------------------------------- render

def render(gi: GameIndex, m: MapFile, out: Path) -> None:
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "focrender", str(Path(__file__).resolve().parent / "render.py"))
    r = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(r)
    out.parent.mkdir(parents=True, exist_ok=True)
    r.render_map(gi, m, 0, True).save(out)
    print(f"rendered {out.relative_to(ROOT) if out.is_relative_to(ROOT) else out}")


def clusters(pts, reach: int = 4):
    """Group (hx, hy, pid) points closer than `reach` hexes; -> [(bbox, count)]."""
    parent = list(range(len(pts)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(pts)):
        for j in range(i + 1, len(pts)):
            if abs(pts[i][0] - pts[j][0]) <= reach and abs(pts[i][1] - pts[j][1]) <= reach:
                parent[find(i)] = find(j)
    groups: dict[int, list] = {}
    for i, p in enumerate(pts):
        groups.setdefault(find(i), []).append(p)
    out = []
    for g in groups.values():
        xs = [p[0] for p in g]
        ys = [p[1] for p in g]
        out.append(((min(xs), min(ys), max(xs), max(ys)), len(g)))
    return sorted(out, key=lambda t: (t[0][1], t[0][0]))


# ---------------------------------------------------------------------- main

TYPE_NAMES = {0: "items", 1: "critters", 2: "scenery", 3: "walls", 4: "tiles", 5: "misc"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--src", default="base/mods/foc/maps/REDWELL.MAP",
                    help="map to crop (the live, gecko-edited copy by default)")
    ap.add_argument("--out", default="RWCORE.MAP",
                    help="output filename; written to mod/data/maps and base/mods/foc/maps")
    ap.add_argument("--floor", choices=("encounter", "original", "keep"), default="encounter")
    ap.add_argument("--drop-scripted", action="store_true")
    ap.add_argument("--no-well", action="store_true", help="do not re-bind rwwell to the well")
    ap.add_argument("--no-flags", action="store_true",
                    help="leave zeroed object flags alone (do not apply proto flags)")
    ap.add_argument("--force", action="store_true",
                    help="replace an existing output (the old file is stashed in mod/data/maps/_replaced)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--render", metavar="PNG")
    ap.add_argument("--dump-mask", metavar="MAP",
                    help="rewrite tools/redwell_orig_floor.txt from this map's floor and exit")
    args = ap.parse_args()

    gi = GameIndex(pristine=False)      # the map uses this mod's own protos

    if args.dump_mask:
        p = ROOT / args.dump_mask
        dump_mask(MapFile.parse(p.read_bytes(), gi.proto), p.relative_to(ROOT))
        return 0

    src = ROOT / args.src
    raw = src.read_bytes()
    m = MapFile.parse(raw, gi.proto)
    tpl_raw = gi.vfs.read(TEMPLATE)
    tpl = MapFile.parse(tpl_raw, gi.proto)

    out_name = args.out.upper()
    if not out_name.endswith(".MAP"):
        out_name += ".MAP"
    if len(out_name) > HEADER_NAME_LEN - 1:
        sys.exit(f"{out_name}: the .map header holds {HEADER_NAME_LEN - 1} chars of name")

    out, rep = crop(raw, m, tpl_raw, tpl, gi, out_name, args.floor, args.drop_scripted)
    well_note = "skipped (--no-well)"
    if not args.no_well:
        out, well_note = bind_well(out, gi)
    flag_stats = None
    if not args.no_flags:
        out, flag_stats = normalize_flags(out, gi)

    check = MapFile.parse(out, gi.proto)
    assert len(check.objects) == rep["kept"] + rep["frame"], len(check.objects)
    assert check.name == out_name, check.name
    assert check.default_tile == m.default_tile
    n_scripted = lambda mm: len([o for o in mm.objects if o.script_index not in (-1, 0xFFFFFFFF)])
    assert n_scripted(check) >= n_scripted(m), "lost a script"
    painted = sum(1 for t in check.floors[0] if t > 1)

    hx0 = min(x for x, _ in rep["hull"]); hx1 = max(x for x, _ in rep["hull"])
    hy0 = min(y for _, y in rep["hull"]); hy1 = max(y for _, y in rep["hull"])
    print(f"{src.name} -> {out_name}  ({len(raw)} -> {len(out)} bytes)")
    print(f"  frame: {TEMPLATE} exit ring hex x{hx0}..{hx1} y{hy0}..{hy1}, "
          f"{rep['frame']} exit grids + scroll blockers copied verbatim")
    print(f"  objects: {len(m.objects)} -> {len(check.objects)}  "
          f"({rep['kept']} kept inside the ring, "
          + ", ".join(f"{n} {TYPE_NAMES.get(t, t)}" for t, n in sorted(rep["dropped_by_type"].items()))
          + " dropped outside it)")
    if rep["dropped_critters"]:
        print(f"  dropped critters: " + ", ".join(
            f"0x{pid:08X}@({x},{y})" for (x, y), pid in rep["dropped_critters"]))
    print(f"  floor: --floor {args.floor}, {rep['floor_voided']} squares voided, "
          f"{painted} painted remain;  roofs: {rep['roof_voided']} squares voided outside the ring")
    print(f"  well: {well_note}")
    if flag_stats:
        print(f"  flags: {flag_stats['flagged']} objects with stored flags 0 given their proto's "
              f"({flag_stats['walkable']} now walkable, {flag_stats['flat']} flat); "
              f"{flag_stats['lit']} given proto light; {flag_stats['no_proto']} without a proto")
        print("  " + critter_note(flag_stats))
    if rep["on_exit"]:
        print(f"  NOTE: {len(rep['on_exit'])} kept objects sit ON exit-grid hexes: "
              + ", ".join(f"0x{o.pid:08X}@{hex_xy(o.tile)}" for o in rep["on_exit"][:8]))
    if rep["edge"]:
        print(f"  {len(rep['edge'])} kept objects hug the cut line - structures the ring "
              f"slices through; tidy these in gecko (hex boxes x0-x1,y0-y1: count):")
        for (x0, y0, x1, y1), n in clusters(rep["edge"]):
            print(f"      x{x0}-{x1}, y{y0}-{y1}: {n}")

    if args.render:
        render(gi, check, ROOT / args.render)
    if args.dry_run:
        print("dry run: nothing written")
        return 0

    existing = [d / out_name for d in (AUTHORED, DEPLOYED) if (d / out_name).is_file()]
    if existing and not args.force:
        for e in existing:
            st = e.stat()
            print(f"  exists: {e.relative_to(ROOT)}  ({st.st_size} bytes, "
                  f"{time.strftime('%Y-%m-%d %H:%M', time.localtime(st.st_mtime))})")
        sys.exit(f"refusing to overwrite {out_name} - it may be a gecko-edited map. "
                 f"Re-run with --force to replace it (the old file is kept in "
                 f"{REPLACED.relative_to(ROOT)}), or pick another --out name.")

    for d in (AUTHORED, DEPLOYED):
        d.mkdir(parents=True, exist_ok=True)
        stashed = stash_existing(d / out_name)
        if stashed:
            print(f"stashed old {(d / out_name).relative_to(ROOT)} -> {stashed.relative_to(ROOT)}")
        (d / out_name).write_bytes(out)
        print(f"wrote {(d / out_name).relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
