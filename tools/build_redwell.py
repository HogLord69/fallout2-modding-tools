#!/usr/bin/env python3
"""
build_redwell.py - Redwell, tier 0.

    python tools/build_redwell.py

DERIVED FROM ARROYO, NOT GENERATED
----------------------------------
The first attempt placed 449 objects by hand and measured like this against
real town maps (tools/compare_map.py):

    objects per floored square   mine 0.15   human average 1.28
    wall:scenery ratio           mine 2.05   human average 0.39
    stacked hexes                mine 4.7%   human average 20.5%

A real Fallout 2 town carries about 1.3 objects per floored square and is
overwhelmingly SCENERY - pots, bedding, brush, tools - with walls a small
minority. Arroyo puts 4001 objects on the same 3002 floored squares this map
has. Hand-placing three and a half thousand props with any spatial judgement is
exactly the thing that does not survive being generated, so this does not try.

Instead Redwell is Arroyo's composition, edited:

  strip    the landmarks that belong to Arroyo's story and were never asked
           for - the stone face (head1.frm), the cliff and cave (mount*),
           the canyon walls - plus every script, so nothing inherited talks
           about the Temple of Trials
  keep     tents with their bedding and pots, the brahmin pen with brahmin,
           the crop rows, the well, the trees and scrub, the handcart
  add      two adobe buildings from Modoc, five heaps of dung, a shovel,
           and Mose

Everything is vanilla art. The debt is recorded in ASSETS.md: this map is a
derivative of ARVILLAG.MAP and credit is owed accordingly.
"""

from __future__ import annotations

import json
import random
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foclib import (  # noqa: E402
    OBJ_TYPE_CRITTER,
    GameIndex,
    MapFile,
    hex_xy,
    parse_lst,
    pid_type,
)
from mapbuild import HEX_W, MapBuilder, MapObjectSpec, extras_for  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
STAMPS = ROOT / "corpus" / "stamps.json"
OUT = ROOT / "mod" / "data" / "maps" / "REDWELL.MAP"

# Two donors informed this map.
#
#   ARVILLAG.MAP (vanilla)  supplies the composition and is what gets copied:
#       a village at 1.34 objects per floored square, tents with bedding and
#       pots inside them, a fenced pen with brahmin and feed, crop rows.
#       Every proto is native, so nothing is lost in translation.
#
#   NH_VILL.MAP (Resurrection) supplies the READ: a desert settlement built
#       around one substantial adobe with a real interior, tents clustered
#       loosely around it, pen and crops off to one side, open ground between.
#       It is not copied - carrying it across dropped 1966 of its 3942 objects,
#       because our base has the ART but no PROTO using it, and porting all of
#       that is a separate job.
#
# So: Arroyo's material, arranged the way Resurrection arranges a desert
# village, with adobe taken from vanilla's own (NCR and the Redding mine).
DONOR_SOURCE = "fo2"
DONOR = "maps/ARVILLAG.MAP"

# Names mean different things in different installs: a PID is an index, not an
# identity. Everything crossing from the donor is remapped by ART NAME, which
# is the only portable handle. See CLAUDE.md 4f and tools/port.py.

# Art that is unmistakably Arroyo's and has no place in Redwell.
STRIP_ART = (
    "head",            # stone faces / idols
    "arcanm",          # Arroyo canyon walls
    "arwlsc",
    "artemp",          # temple pieces
)

PID_SHOVEL = 0x00000121
PID_FARMER = 0x010000D6           # 'Farmer' - Mose

SCRIPT_RWFARMER = 1601 - 1        # 0-based; the SCRIPT_* defines are 1-based
SCRIPT_RWDUNG = 1602 - 1
SCRIPT_TYPE_ITEM = 3
SCRIPT_TYPE_CRITTER = 4

DUNG_TOTAL = 5

# A critter written with hp=0 renders and reads as a CORPSE. Real maps store
# the proto's hit points; a villager in Arroyo carries hp=50, ap=9, team=1.
CRITTER_AP = 8
CRITTER_AI = 1
CRITTER_TEAM = 1
CRITTER_HP = 50


def critter_extras_live(hp=CRITTER_HP):
    """7 combat words then hp / radiation / poison, matching real maps."""
    return (0, 0, CRITTER_AP, 0, CRITTER_AI, CRITTER_TEAM, -1, hp, 0, 0)


def read_critter_extras(data: bytes, off: int):
    """Copy a donor critter's own combat block so it stays alive and sane."""
    base = off + 72 + 12          # past header, past the inventory triple
    return struct.unpack_from(">10i", data, base + 4)


def art_name(gi, lists, obj_type, fid):
    lst = lists.get(obj_type)
    if not lst:
        return ""
    i = fid & 0xFFF
    return lst[i] if 0 <= i < len(lst) else ""


def find_proto_by_art(gi: GameIndex, obj_type: int, art: str) -> int | None:
    d = {0: "items", 1: "critters", 2: "scenery", 3: "walls", 5: "misc"}[obj_type]
    lst = parse_lst(gi.vfs.read(f"art/{d}/{d}.lst"))
    low = art.lower()
    idx = next((i for i, n in enumerate(lst) if n and n.lower() == low), None)
    if idx is None:
        return None
    for i, fn in enumerate(gi.proto_lst(obj_type)):
        if not fn:
            continue
        pid = (obj_type << 24) | (i + 1)
        pr = gi.proto(pid)
        if pr is not None and (pr.fid & 0xFFF) == idx:
            return pid
    return None


def place(mb, gi, pid, hx, hy, rot=0, sid=-1, script_index=-1, extras=None):
    pr = gi.proto(pid)
    if pr is None or not (0 <= hx < HEX_W and 0 <= hy < 200):
        return None
    if extras is None:
        extras = (critter_extras_live() if pid_type(pid) == OBJ_TYPE_CRITTER
                  else extras_for(pid_type(pid), pid, pr.subtype))
    return mb.add(MapObjectSpec(
        pid=pid, fid=pr.fid, tile=hy * HEX_W + hx, elevation=0,
        rotation=rot, sid=sid, script_index=script_index, extras=extras))


def main() -> int:
    gi = GameIndex()
    rnd = random.Random(20260827)

    lists = {t: parse_lst(gi.vfs.read(f"art/{d}/{d}.lst"))
             for t, d in ((0, "items"), (1, "critters"), (2, "scenery"),
                          (3, "walls"), (5, "misc"))}

    from port import load_sources
    src_path = Path(load_sources()[DONOR_SOURCE]["path"])
    dgi = GameIndex(src_path, pristine=False)
    dlists = {t_: parse_lst(dgi.vfs.read(f"art/{d}/{d}.lst"))
              for t_, d in ((0, "items"), (1, "critters"), (2, "scenery"),
                            (3, "walls"), (5, "misc"))}
    dtiles = parse_lst(dgi.vfs.read("art/tiles/tiles.lst"))

    # our art name -> our pid, and our art name -> our tile id
    our_pid = {}
    for ot in (0, 1, 2, 3, 5):
        d = {0: "items", 1: "critters", 2: "scenery", 3: "walls", 5: "misc"}[ot]
        alist = parse_lst(gi.vfs.read(f"art/{d}/{d}.lst"))
        for i, fn in enumerate(gi.proto_lst(ot)):
            if not fn:
                continue
            pid = (ot << 24) | (i + 1)
            pr = gi.proto(pid)
            if pr is None:
                continue
            ai = pr.fid & 0xFFF
            if 0 <= ai < len(alist) and alist[ai]:
                our_pid.setdefault((ot, alist[ai].lower()), pid)

    donor_bytes = dgi.vfs.read(DONOR)
    donor = MapFile.parse(donor_bytes, dgi.proto)
    di = donor.elevations.index(0) if 0 in donor.elevations else 0

    mb = MapBuilder("REDWELL.MAP", elevations=(0,), map_id=200)
    # remap the donor's tile ids through names into ours
    our_tiles = parse_lst(gi.vfs.read("art/tiles/tiles.lst"))
    our_tile_id = {}
    for i, n in enumerate(our_tiles):
        if n:
            our_tile_id.setdefault(n.lower(), i)

    def remap_tile(tid):
        if tid <= 1 or tid >= len(dtiles) or not dtiles[tid]:
            return 1
        return our_tile_id.get(dtiles[tid].lower(), 1)

    mb.floors[0] = [remap_tile(v) for v in donor.floors[di]]
    mb.roofs[0] = [remap_tile(v) for v in donor.roofs[di]]

    # The cave mouth is in the TILE layer, which is why stripping objects never
    # removed it. cav*/cavb* tiles form it; swap them for the ground tile the
    # map already uses most, so the patch blends instead of showing a hole.
    tile_names = parse_lst(gi.vfs.read("art/tiles/tiles.lst"))
    from collections import Counter
    ground = Counter(v for v in mb.floors[0]
                     if v > 1 and v < len(tile_names)
                     and tile_names[v].lower().startswith("edg5")).most_common(1)
    fill = ground[0][0] if ground else 2
    caved = 0
    for sq, tid in enumerate(mb.floors[0]):
        if tid <= 1 or tid >= len(tile_names):
            continue
        n = tile_names[tid].lower()
        if n.startswith("cav"):
            mb.floors[0][sq] = fill
            caved += 1
    print(f"cave: {caved} cav* floor tiles replaced with {tile_names[fill]}")

    # ---- carry Arroyo's composition across, minus its landmarks ----------
    kept = stripped = 0
    strip_counts: dict[str, int] = {}
    for o in donor.objects:
        if o.elevation != 0 or not (0 <= o.tile < 40000):
            continue
        t = pid_type(o.pid)
        if t not in (0, 1, 2, 3, 5):
            continue
        a = art_name(dgi, dlists, t, o.fid).lower()
        if any(a.startswith(s) for s in STRIP_ART):
            stripped += 1
            key = next(s for s in STRIP_ART if a.startswith(s))
            strip_counts[key] = strip_counts.get(key, 0) + 1
            continue

        pid = our_pid.get((t, a))          # remap by art name, not by index
        if pid is None:
            continue
        pr = gi.proto(pid)
        if pr is None:
            continue
        if t == OBJ_TYPE_CRITTER:
            extras = read_critter_extras(donor_bytes, o.off)
        else:
            extras = extras_for(t, pid, pr.subtype)

        # Scripts are dropped: inherited ones would have Arroyo's villagers
        # discussing the Temple of Trials.
        mb.add(MapObjectSpec(
            pid=pid, fid=pr.fid, tile=o.tile, elevation=0,
            rotation=o.rotation, frame=o.frame, sid=-1, script_index=-1,
            extras=extras))
        kept += 1

    print(f"from {DONOR}: kept {kept} objects, stripped {stripped}")
    for k, n in sorted(strip_counts.items()):
        print(f"    removed {k}*  x{n}")

    # ---- two adobe buildings ---------------------------------------------
    # A wall-only stamp gave roofless shells with nothing inside. A building is
    # its floor, roof, doors and furniture as much as its walls, so take whole
    # 14x14 FRAGMENTS out of Modoc instead - tiles and objects together.
    built = 0
    # Real adobe (adb* art), two visibly different buildings. The Modoc
    # fragments used first were wooden - picked by map rather than by art.
    frag_ids = ["fo2:ncr2:e0:15_42", "fo2:redment:e0:36_38"]
    frags = []
    corpus = ROOT / "corpus" / "fragments.jsonl"
    if corpus.is_file():
        wanted = set(frag_ids)
        with corpus.open(encoding="utf-8") as f:
            for line in f:
                for fid in list(wanted):
                    if f'"{fid}"' in line:
                        fr = json.loads(line)
                        if fr["id"] == fid:
                            frags.append(fr)
                            wanted.discard(fid)
                if not wanted:
                    break

    tile_id = {}
    for i, n in enumerate(tile_names):
        if n:
            tile_id.setdefault(n.lower(), i)
    proto_pid = {}
    for ot in (0, 1, 2, 3, 5):
        for i, fn in enumerate(gi.proto_lst(ot)):
            if fn:
                proto_pid.setdefault((ot, fn.lower()), (ot << 24) | (i + 1))

    # Least-crowded floor that fits, so a building never lands off the map.
    occupied = {}
    for o in mb.objects:
        hx, hy = hex_xy(o.tile)
        occupied[(hy // 2) * 100 + (hx // 2)] =             occupied.get((hy // 2) * 100 + (hx // 2), 0) + 1

    chosen = []
    for fr in frags:
        fw, fh = fr["size_sq"]
        best = None
        for sy in range(8, 92 - fh):
            for sx in range(8, 92 - fw):
                if any(abs(sx - ox) < fw + 3 and abs(sy - oy) < fh + 3
                       for ox, oy in chosen):
                    continue
                total = 0
                ok = True
                for dy in range(fh):
                    for dx in range(fw):
                        sq = (sy + dy) * 100 + (sx + dx)
                        if not (0 <= sq < 10000) or mb.floors[0][sq] <= 1:
                            ok = False
                            break
                        total += occupied.get(sq, 0)
                    if not ok:
                        break
                if ok and (best is None or total < best[0]):
                    best = (total, sx, sy)
        if best is None:
            print(f"    no room for {fr['id']}")
            continue
        cost, sx, sy = best
        chosen.append((sx, sy))

        # displace whatever Arroyo had on that footprint
        keep = []
        for o in mb.objects:
            hx, hy = hex_xy(o.tile)
            ssx, ssy = hx // 2, hy // 2
            if sx <= ssx < sx + fw and sy <= ssy < sy + fh:
                continue
            keep.append(o)
        removed = len(mb.objects) - len(keep)
        mb.objects = keep

        for ry, row in enumerate(fr["floor"]):
            for rx, c in enumerate(row):
                if c < 0:
                    continue
                tid = tile_id.get(fr["palette"][c].lower())
                if tid:
                    mb.set_floor(0, sx + rx, sy + ry, tid)
        for ry, row in enumerate(fr["roof"]):
            for rx, c in enumerate(row):
                if c < 0:
                    continue
                tid = tile_id.get(fr["palette"][c].lower())
                if tid:
                    mb.set_roof(0, sx + rx, sy + ry, tid)

        for o in fr["objects"]:
            pid = proto_pid.get((o["t"], (o["proto"] or "").lower()))
            if pid is None:
                continue
            if place(mb, gi, pid, sx * 2 + o["dx"], sy * 2 + o["dy"],
                     o.get("rot") or 0):
                built += 1
        print(f"    {fr['id']} at square({sx},{sy}), {fw}x{fh}, "
              f"displaced {removed} Arroyo objects")
    print(f"adobe buildings: {built} objects with floors, roofs and interiors")

    # ---- the pen: find it, so the dung lands inside it --------------------
    brahmin = [o for o in donor.objects
               if pid_type(o.pid) == OBJ_TYPE_CRITTER
               and art_name(dgi, dlists, 1, o.fid).lower().startswith("mabrom")]
    if brahmin:
        bx = sum(hex_xy(o.tile)[0] for o in brahmin) // len(brahmin)
        by = sum(hex_xy(o.tile)[1] for o in brahmin) // len(brahmin)
    else:
        bx, by = 150, 60
    print(f"brahmin pen centre: hex({bx},{by}), {len(brahmin)} brahmin kept")

    # ---- biological goo, not the radioactive kind -------------------------
    goo_pids = []
    # mstr01-05 are large pools (mstr03 is 79x132px). Dung wants the small
    # ones: 13-22px.
    for n in ("mstr36.frm", "mstr38.frm", "mstr52.frm", "mstr32.frm", "mstr51.frm"):
        p = find_proto_by_art(gi, 2, n)
        if p:
            goo_pids.append(p)
    if not goo_pids:
        sys.exit("no biological goo proto found")

    spots = [(-6, -2), (-2, 2), (3, -1), (1, 5), (6, 3)]
    for i, (dx, dy) in enumerate(spots[:DUNG_TOTAL]):
        sid = mb.add_script(SCRIPT_TYPE_ITEM, SCRIPT_RWDUNG)
        place(mb, gi, goo_pids[i % len(goo_pids)], bx + dx, by + dy,
              sid=sid, script_index=SCRIPT_RWDUNG)
    print(f"dung: {DUNG_TOTAL} heaps of biological goo inside the pen")

    # ---- the well, so the shovel can sit by it ---------------------------
    well = next((o for o in donor.objects
                 if art_name(dgi, dlists, pid_type(o.pid), o.fid).lower()
                 .startswith("well")), None)
    if well:
        wx, wy = hex_xy(well.tile)
    else:
        wx, wy = 100, 100
    place(mb, gi, PID_SHOVEL, wx + 2, wy + 2)
    print(f"shovel: beside the well at hex({wx},{wy})")

    # ---- Mose, by the pen -------------------------------------------------
    mose_sid = mb.add_script(SCRIPT_TYPE_CRITTER, SCRIPT_RWFARMER)
    place(mb, gi, PID_FARMER, bx - 8, by + 6, rot=1,
          sid=mose_sid, script_index=SCRIPT_RWFARMER)
    print(f"Mose: hex({bx-8},{by+6}), hp={CRITTER_HP} (hp=0 reads as a corpse)")

    mb.start_tile = (wy + 4) * HEX_W + (wx - 4)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(mb.to_bytes())

    m = MapFile.parse(OUT.read_bytes(), gi.proto)
    floored = sum(1 for f in m.floors[0] if f > 1)
    print(f"\nwrote {OUT.relative_to(ROOT)} ({OUT.stat().st_size} bytes)")
    print(f"  {len(m.objects)} objects on {floored} floored squares "
          f"= {len(m.objects)/max(1,floored):.2f} per square")
    print(f"  script table: {len(m.script_pids)} entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
