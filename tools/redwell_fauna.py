#!/usr/bin/env python3
"""
redwell_fauna.py - the Redwell "finalize" pass over a gecko-edited map.

    python tools/redwell_fauna.py [--map mod/data/maps/REDWELL.MAP] [--dry-run]
    python tools/redwell_fauna.py --render build/redwell_finalize.png

REDWELL.MAP is authored in the gecko GUI editor, which cannot write script
ids, populates critter hp with 0, and does not blocker large scenery. This
one pass fixes all of that in a single MapBuilder round-trip (the pattern
bind_scripts.py / map_finalize.py use), preserving every object and every
script already bound:

  * the four corral brahmin were placed as proto 0x010000BF ("Bess", the
    named Modoc quest brahmin) with hp 0, so they loaded as corpses. Rebind
    to the generic Brahmin proto (0x0100000A), give them a real combat block
    and the rwbrah wander script.
  * move Rem (rwwatch) to the edge of the corn rows.
  * drop invisible blocking hexes (scenery 67) on the footprint of every
    car / cart / truck, via car_blockers.blocker_specs, and on the stone rim
    of the well, so the sprites read as solid.
  * replace the camera scroll-blocker ring (misc 12) with a two-layer diamond
    sitting on the exit-grid perimeter, so the camera can't be scrolled past
    the exits into the empty painted desert / the void.

A .bak is kept beside the map.
"""

from __future__ import annotations

import argparse
import shutil
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foclib import OBJ_TYPE_CRITTER, GameIndex, MapFile, hex_xy, pid_type  # noqa: E402
from mapbuild import MapBuilder, MapObjectSpec, extras_for  # noqa: E402
from car_blockers import (  # noqa: E402
    BLOCKING_HEX_FID,
    BLOCKING_HEX_PID,
    blocker_specs,
)
from scroll_ring import (  # noqa: E402
    SCROLL_BLOCKER_FID,
    SCROLL_BLOCKER_PID,
)

ROOT = Path(__file__).resolve().parent.parent

# The flags every vanilla scroll blocker carries (read out of desert1.map etc.):
# FLAT | NO_BLOCK | LIGHT_THRU | SHOOT_THRU  ->  0xA0000018. Without NO_BLOCK the
# hex would block the DUDE, not just the camera - a 2288-hex wall around the
# settlement. Stored as a signed int32 in the .map.
SCROLL_BLOCKER_FLAGS = 0xA0000018 - (1 << 32)      # -1610612712

BESS_PID = 0x010000BF          # what gecko placed - the Modoc quest brahmin
BRAHMIN_PID = 0x0100000A       # PID_BRAHMIN - generic livestock
BRAHMIN_FID = 0x0100000F       # art\critters\critters.lst[15] = mabrom
BRAHMIN_EXTRAS = (0, 0, 7, 0, 5, 1, -1, 35, 0, 0)  # from a live Arroyo brahmin

RWBRAH_IDX = 1611 - 1          # foc_ids.h define is the 1-based scripts.lst line
RWWATCH_IDX = 1606 - 1         # Rem
RWWELL_IDX = 1601 - 1          # rwwell - drink to heal, fade to black, "damn good water"
SCRIPT_TYPE_SCENERY = 3
SCRIPT_TYPE_CRITTER = 4

# Rem moves to the west edge of the corn (rows sit at squares x48..50, y61..67).
REM_TILE = (2 * 63) * 200 + (2 * 47)      # square (47, 63)

# The well (modwell1) blocks only its anchor hex; its stone rim covers these
# hexes, offsets in (dx east, dy south) from the anchor. Pattern lifted from
# an older hand-blockered Redwell (build/_attic/REDWELL.MAP.map).
# 2026-09-19: the Modoc well was deleted in gecko and replaced by proto 5397
# (otower3.frm, "a well") one hex NW at (100,94); the oolymp7x objects around
# it are shrubs. WELL_RIM was measured on modwell1's sprite and does not fit
# otower3 - applying it would drop invisible blockers on open ground NW of the
# new well - so it is empty until someone measures the new rim. The old rim
# blockers are still baked into the map from the earlier pass. The rwwell
# binding targets the new well (map_crop.py does the same when it crops).
WELL_PID = 0x02001515              # was 0x020003E1 (modwell1)
WELL_RIM = []                      # modwell1's was [(-3,-3),(-2,-3),(-1,-2),(0,-3),(0,-2),(1,-3)]

# Owner request: the player spawns at the well. modwell1's rim sits to its
# north (WELL_RIM), so 3 hexes due south of the anchor is clear ground with
# the well filling the view. (dx east, dy south) from the well anchor.
START_AT_WELL = (0, 3)

EXIT_GRID_PIDS = range(0x05000010, 0x05000018)

# Camera scroll limit - TWO mechanisms, because this base runs the experimental
# zoom build of Mash HRP 4.1.8, which honours neither scroll-blocker objects nor
# f2_res.ini SCROLL_DIST (sfall's own readme calls the combo incompatible).
#
#  1. PAINTED-FLOOR TRIM. REDWELL.MAP had 7455 painted floor squares (~75% of
#     the 100x100 grid); a normal FO2 town paints ~3000 (vctyctyd 3072, modmain
#     3484). The camera roams the whole painted field because EDGE_CLIPPING /
#     IGNORE_MAP_EDGES clamps to where tiles exist. We repaint every floor
#     square outside FLOOR_KEEP (hex box) to the void tile (1), shrinking the
#     scrollable field to a 2-square margin around the exit grids.
#  2. SCROLL-BLOCKER FRAME. A solid axis-aligned rectangle ~3 hexes thick
#     (vanilla vctyctyd/denbus1/modmain style), inner edge at SCROLL_INNER -
#     drawn tight around the settlement core, NOT the exit-grid bounding box
#     (the exits sit on a rotated diamond whose AABB is nearly the whole map).
#     Harmless where blockers are ignored; the operative limit on a sane engine.
#
# The exit grids form a rotated quad (hull corners ~ (31,66) (107,31) (168,124)
# (96,163)); its AABB is nearly the whole map but the quad itself is ~half that
# - the rest is empty corner desert, which is most of what reads as "extra
# terrain". Keep painted floor only inside the exit-grid hull grown FLOOR_MARGIN
# hexes outward from its centroid; void (tile 1) everything outside.
# Floor trim is OFF: testing 2026-09-08 proved this HRP build (experimental
# zoom 4.1.8) clamps the camera to the raw 100x100 tile grid only - not to the
# painted-tile extent, not to scroll blockers, not to SCROLL_DIST. Voiding the
# outer floor just turned "empty desert past the town" into "black void past
# the town", which is worse. Left here to re-enable once the HRP is swapped.
TRIM_FLOOR = False
FLOOR_MARGIN = 6                     # hexes of painted ground beyond the exits
SCROLL_INNER = (54, 46, 152, 152)    # camera centre may reach here; then the frame
SCROLL_FRAME_THICK = 3               # hexes
VOID_TILE = 1                        # art\tiles\edge (black); FO2 "no floor here"


def read_critter_extras(data: bytes, off: int):
    return struct.unpack_from(">10i", data, off + 72 + 12 + 4)


def _convex_hull(points):
    pts = sorted(set(points))
    if len(pts) < 3:
        return pts

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return lower[:-1] + upper[:-1]


def _grow(hull, margin):
    """Push each hull vertex `margin` hexes away from the centroid."""
    cx = sum(x for x, _ in hull) / len(hull)
    cy = sum(y for _, y in hull) / len(hull)
    out = []
    for x, y in hull:
        dx, dy = x - cx, y - cy
        d = (dx * dx + dy * dy) ** 0.5 or 1.0
        out.append((x + dx / d * margin, y + dy / d * margin))
    return out


def _in_poly(x, y, poly):
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xint = x1 + (y - y1) / (y2 - y1) * (x2 - x1)
            if x < xint:
                inside = not inside
    return inside


def build(path: Path, m: MapFile, raw: bytes, gi: GameIndex):
    if m.num_global_vars or m.num_local_vars:
        sys.exit(f"{path.name} carries map vars; this round-trip would drop them")

    mb = MapBuilder(path.name, elevations=tuple(m.elevations),
                    map_id=m.map_id if m.map_id > 0 else 200,
                    map_script_index=m.map_script_id)
    for i, _e in enumerate(m.elevations):
        mb.floors[i] = list(m.floors[i])
        mb.roofs[i] = list(m.roofs[i])

    # --- painted-floor trim: void every square outside the exit-grid hull ----
    # floor squares and object tiles share the .map's mirrored raw convention;
    # a hex column ~= 2 square columns, so a square at (sqx,sqy) sits at hex
    # (~2*sqx, ~2*sqy). Keep only squares whose hex centre is inside the grown
    # exit-grid hull.
    eg_pts = [hex_xy(o.tile) for o in m.objects
              if o.pid in EXIT_GRID_PIDS and 0 <= o.tile < 40000]
    trimmed = 0
    if TRIM_FLOOR and len(eg_pts) >= 3:
        keep_poly = _grow(_convex_hull(eg_pts), FLOOR_MARGIN)
        for i, _e in enumerate(m.elevations):
            f = mb.floors[i]
            for sq in range(len(f)):
                if f[sq] <= 1:
                    continue
                if not _in_poly((sq % 100) * 2, (sq // 100) * 2, keep_poly):
                    f[sq] = VOID_TILE
                    trimmed += 1

    mb.start_tile = m.default_tile
    mb.start_elevation = getattr(m, "default_elevation", 0)
    mb.start_rotation = getattr(m, "default_orientation", 0)

    well = next((o for o in m.objects if o.pid == WELL_PID), None)
    if well is not None:
        wx, wy = hex_xy(well.tile)
        dx, dy = START_AT_WELL
        mb.start_tile = (wy + dy) * 200 + (wx + dx)
        moved_start = mb.start_tile
    else:
        moved_start = None

    brahmin = rebound = 0
    for o in m.objects:
        t = pid_type(o.pid)
        pr = gi.proto(o.pid)
        pid, fid, tile, extras = o.pid, o.fid, o.tile, ()
        sid, sidx = -1, -1

        if o.pid == SCROLL_BLOCKER_PID:
            continue                              # old scroll ring dropped, rebuilt below

        if t == OBJ_TYPE_CRITTER:
            extras = read_critter_extras(raw, o.off)
            is_brahmin = (o.pid == BESS_PID
                          or (o.pid == BRAHMIN_PID and o.script_index == RWBRAH_IDX))
            if is_brahmin:
                pid, fid, extras = BRAHMIN_PID, BRAHMIN_FID, BRAHMIN_EXTRAS
                sidx = RWBRAH_IDX
                sid = mb.add_script(SCRIPT_TYPE_CRITTER, RWBRAH_IDX)
                brahmin += 1
            elif o.script_index not in (-1, 0xFFFFFFFF):
                sidx = o.script_index
                sid = mb.add_script(SCRIPT_TYPE_CRITTER, o.script_index)
                rebound += 1
                if o.script_index == RWWATCH_IDX:
                    tile = REM_TILE            # move Rem to the corn
        elif o.pid == WELL_PID:
            extras = extras_for(t, o.pid, pr.subtype) if pr else ()
            sidx = RWWELL_IDX                      # drink-to-heal script
            sid = mb.add_script(SCRIPT_TYPE_SCENERY, RWWELL_IDX)
            rebound += 1
        else:
            extras = extras_for(t, o.pid, pr.subtype) if pr else ()
            if o.script_index not in (-1, 0xFFFFFFFF):
                sidx = o.script_index
                sid = mb.add_script(SCRIPT_TYPE_SCENERY, o.script_index)
                rebound += 1

        mb.add(MapObjectSpec(
            pid=pid, fid=fid, tile=tile, elevation=o.elevation,
            rotation=o.rotation, frame=o.frame,
            sid=sid, script_index=sidx, extras=extras))

    # --- blocking hexes -------------------------------------------------------
    occupied = {o.tile for o in m.objects
                if pid_type(o.pid) in (2, 3) or o.pid == BLOCKING_HEX_PID}
    added = 0

    for spec in blocker_specs(m, gi):          # cars / carts / trucks
        if spec.tile not in occupied:
            mb.add(spec)
            occupied.add(spec.tile)
            added += 1

    for o in m.objects:                         # the well rim
        if o.pid != WELL_PID:
            continue
        ax, ay = hex_xy(o.tile)
        for dx, dy in WELL_RIM:
            tile = (ay + dy) * 200 + (ax + dx)
            if 0 <= tile < 40000 and tile not in occupied:
                mb.add(MapObjectSpec(
                    pid=BLOCKING_HEX_PID, fid=BLOCKING_HEX_FID, tile=tile,
                    elevation=o.elevation, rotation=0, frame=0,
                    sid=-1, script_index=-1, extras=()))
                occupied.add(tile)
                added += 1

    # --- camera scroll-blocker frame -----------------------------------------
    # Solid rectangle SCROLL_FRAME_THICK hexes wide, inner edge at SCROLL_INNER
    # (the settlement core, not the exit-grid AABB). Sits inside FLOOR_KEEP so
    # it's on painted ground; kept in raw-hex coords like every other tile ref.
    ground = m.elevations[0]
    ring: set[tuple[int, int]] = set()
    old_ring = sum(1 for o in m.objects if o.pid == SCROLL_BLOCKER_PID)

    x0, y0, x1, y1 = SCROLL_INNER
    xa, xb = x0 - SCROLL_FRAME_THICK, x1 + SCROLL_FRAME_THICK
    ya, yb = y0 - SCROLL_FRAME_THICK, y1 + SCROLL_FRAME_THICK
    for hx in range(max(0, xa), min(200, xb + 1)):
        for hy in range(max(0, ya), min(200, yb + 1)):
            if hx < x0 or hx > x1 or hy < y0 or hy > y1:      # in the frame band
                ring.add((hx, hy))
    for (hx, hy) in sorted(ring):
        mb.add(MapObjectSpec(
            pid=SCROLL_BLOCKER_PID, fid=SCROLL_BLOCKER_FID,
            tile=hy * 200 + hx, elevation=ground, rotation=0, frame=0,
            flags=SCROLL_BLOCKER_FLAGS,
            sid=-1, script_index=-1, extras=()))

    net = len(m.objects) + added - old_ring + len(ring)
    return (mb, brahmin, rebound, added, old_ring, len(ring), net,
            moved_start, trimmed)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", default="mod/data/maps/REDWELL.MAP")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--render", metavar="PNG")
    args = ap.parse_args()

    gi = GameIndex()
    path = ROOT / args.map
    raw = path.read_bytes()
    m = MapFile.parse(raw, gi.proto)

    (mb, brahmin, rebound, added, old_ring, new_ring, net,
     moved_start, trimmed) = build(path, m, raw, gi)
    out = mb.to_bytes()
    check = MapFile.parse(out, gi.proto)
    assert len(check.objects) == net, (
        f"object count wrong: {len(check.objects)} != expected {net}")

    print(f"{path.name}: {len(m.objects)} -> {len(check.objects)} objects")
    print(f"  {brahmin} brahmin rebound to rwbrah, {rebound} existing scripts kept")
    print(f"  {added} blocking hexes added (vehicles + well rim)")
    print(f"  painted floor: {trimmed} squares voided outside the "
          f"exit-grid hull (+{FLOOR_MARGIN} hex)")
    print(f"  scroll frame: {old_ring} old blockers -> {new_ring} new "
          f"(solid {SCROLL_FRAME_THICK}-hex rectangle, inner edge {SCROLL_INNER})")
    if moved_start is not None:
        print(f"  player start -> tile {moved_start} "
              f"(hex {moved_start % 200},{moved_start // 200}) at the well")
    for o in check.objects:
        if o.script_index in (-1, 0xFFFFFFFF):
            continue
        hx, hy = hex_xy(o.tile)
        print(f"    ({hx // 2:2d},{hy // 2:2d})  pid=0x{o.pid:08X}  "
              f"script_index={o.script_index}")

    if args.render:
        _render(gi, check, ROOT / args.render, m)
        return 0
    if args.dry_run:
        print("dry run: nothing written")
        return 0

    shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    path.write_bytes(out)
    print(f"wrote {path.relative_to(ROOT)}  (backup {path.name}.bak)")
    return 0


def _render(gi, m, out: Path, orig: MapFile) -> None:
    import importlib.util
    from PIL import ImageDraw
    spec = importlib.util.spec_from_file_location(
        "focrender", str(Path(__file__).resolve().parent / "render.py"))
    r = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(r)
    img = r.render_map(gi, m, 0).convert("RGB")
    dr = ImageDraw.Draw(img)
    was = {o.tile for o in orig.objects if o.pid == BLOCKING_HEX_PID}
    old_scroll = {o.tile for o in orig.objects if o.pid == SCROLL_BLOCKER_PID}
    for o in m.objects:
        if o.pid == BLOCKING_HEX_PID and o.tile not in was:
            x, y = r.hex_xy_screen(o.tile)
            dr.ellipse([x + 13, y + 5, x + 19, y + 11], fill=(255, 40, 40))
        elif o.pid == SCROLL_BLOCKER_PID:
            x, y = r.hex_xy_screen(o.tile)
            dr.ellipse([x + 13, y + 5, x + 19, y + 11], fill=(60, 255, 90))
    for tile in old_scroll:
        x, y = r.hex_xy_screen(tile)
        dr.ellipse([x + 14, y + 6, x + 18, y + 10], fill=(255, 90, 90))
    scale = 3 if max(img.size) > 3500 else 1
    if scale > 1:
        img = img.resize((img.width // scale, img.height // scale))
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(f"  wrote {out} (vehicle/well blockers red, new scroll ring green, "
          f"old scroll ring dim red)")


if __name__ == "__main__":
    raise SystemExit(main())
