#!/usr/bin/env python3
"""
make_ruins.py - build RWRUINS.MAP, the gecko-hunt ruins near Redwell, from a
vanilla city-encounter map.

    python tools/make_ruins.py [--template city1] [--archive master.dat] [--dry-run] [--force]

WHY A VANILLA TEMPLATE
    Kilgore's first quest sends the player (with Kilgore along) to "the ruins
    nearby" to kill five geckos. city1/3/4.map are vanilla's scattered-ruins
    random-encounter maps: pre-war foundations and rubble walls, open ground,
    a full exit-grid ring to the worldmap, correct object flags, no critters.
    That is the whole brief; the map itself needs no editing.

WHY STRAIGHT FROM master.dat
    The Restoration Project ships its own city1.map in rpu.dat, and that copy
    uses RP-only protos (scenery 2298 and friends). The game resolves them,
    gecko does not - its data paths stop at master.dat/critter.dat - so a map
    built from the RP copy cannot be opened in the editor. Reading the template
    from the named archive (default master.dat) keeps every proto vanilla; the
    tool checks that and refuses otherwise.

WHAT IT DOES (byte-level, the map's own objects are untouched)
    * header name  -> RWRUINS.MAP (the engine matches it against maps.txt)
    * header script -> SCRIPT_RWRUINS (1-based scripts.lst line; the engine
      creates the map script from this field alone - no table entry needed)
    * header start tile -> the arrival hex (also what the map script uses)
    * picks and prints the five gecko spawn hexes + the arrival hex, so the
      constants in scripts_src/foc/rwruins.ssl can be checked against them.
      Hexes are chosen inside the exit ring, on painted floor, with no
      blocking object on them or their neighbours, near fixed target points
      so the geckos are spread across the ruins and the party arrives at the
      south-east edge.

    Writes to mod/data/maps and base/mods/foc/maps; refuses to overwrite an
    existing RWRUINS.MAP without --force (map_crop.stash_existing keeps the
    old one).
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foclib import GameIndex, MapFile, hex_xy, hex_to_square  # noqa: E402
from map_crop import (  # noqa: E402
    AUTHORED, DEPLOYED, EXIT_GRID_PIDS, HEADER_NAME_LEN, HEADER_NAME_OFF,
    OBJ_FLAGS_OFF, ROOT, SCROLL_BLOCKER_PID, F_NO_BLOCK, stash_existing,
)
from redwell_fauna import _convex_hull, _in_poly  # noqa: E402

OUT_NAME = "RWRUINS.MAP"
HEADER_SCRIPT_OFF = 0x24
HEADER_START_TILE_OFF = 0x14
W = 200
# tile.cc _dir_tile for a 200-wide grid, [parity][rotation]
DIR = [[-1, W - 1, W, W + 1, 1, -W], [-W - 1, -1, W, 1, 1 - W, -W]]

# Where we want things, in hex coords - nudged to the nearest clear hex.
ARRIVE_TARGET = (140, 122)          # south-east, well inside the ring
ARRIVE_RING_GAP = 6                 # hexes between the landing zone and any exit grid
GECKO_TARGETS = [(88, 68), (112, 58), (128, 88), (96, 104), (118, 122)]


def neighbours(t: int):
    p = (t % W) & 1
    for r in range(6):
        n = t + DIR[p][r]
        if 0 <= n < 40000 and abs((n % W) - (t % W)) <= 1:
            yield n


def script_index(gi: GameIndex, name: str) -> int:
    """1-based scripts.lst line, straight from the registry (deploy may not have
    regenerated scripts.lst yet when this runs)."""
    from gen_ids import read_registry
    from ids import FOC_START
    entries = read_registry(ROOT / "mod" / "ids" / "scripts.txt")
    want = name.lower() + ".int"
    for i, e in enumerate(entries):
        if e.lower() == want:
            return FOC_START["script"] + i
    sys.exit(f"{name}.int is not in mod/ids/scripts.txt")


def blocked_hexes(raw: bytes, m: MapFile) -> set[int]:
    out = set()
    for o in m.objects:
        t = o.pid >> 24
        if t not in (1, 2, 3) or not (0 <= o.tile < 40000):
            continue
        flags = struct.unpack_from(">I", raw, o.off + OBJ_FLAGS_OFF)[0]
        if flags & (F_NO_BLOCK | 0x1):
            continue
        out.add(o.tile)
    return out


def clear_hex(t: int, m: MapFile, blocked: set[int], hull, ring: set[int]) -> bool:
    if t in blocked or t in ring:
        return False
    x, y = hex_xy(t)
    if not _in_poly(x, y, hull):
        return False
    if m.floors[0][hex_to_square(t)] <= 1:
        return False
    return all(n not in blocked and n not in ring for n in neighbours(t))


def ring_gap(t: int, ring_xy: list[tuple[int, int]]) -> int:
    """Chebyshev distance in hex coords from t to the nearest exit/scroll tile."""
    x, y = hex_xy(t)
    return min(max(abs(x - rx), abs(y - ry)) for rx, ry in ring_xy)


def nearest_clear(target, m, blocked, hull, ring, taken, min_gap: int = 1) -> int:
    tx, ty = target
    ring_xy = [hex_xy(r) for r in ring]
    best = None
    for dy in range(-12, 13):
        for dx in range(-12, 13):
            x, y = tx + dx, ty + dy
            if not (0 <= x < W and 0 <= y < W):
                continue
            t = y * W + x
            if t in taken or not clear_hex(t, m, blocked, hull, ring):
                continue
            if min_gap > 1 and ring_gap(t, ring_xy) < min_gap:
                continue
            d = dx * dx + dy * dy
            if best is None or d < best[0]:
                best = (d, t)
    if best is None:
        sys.exit(f"no clear hex within 12 of {target} (gap >= {min_gap} from the exits)")
    return best[1]


def read_from_archive(gi: GameIndex, label: str, path: str) -> bytes:
    for prov in gi.vfs.providers:
        if prov.label.lower() == label.lower() and prov.has(path):
            return prov.read(path)
    sys.exit(f"{path} not found in {label} (providers: "
             f"{', '.join(p.label for p in gi.vfs.providers)})")


def vanilla_only(gi: GameIndex, m: MapFile, archive: str) -> list[str]:
    """Protos the map uses that the named archive does not contain at all.
    (The RP overrides some vanilla protos in rpu.dat; those still exist in
    master.dat, so an editor without rpu.dat can open them.)"""
    names = {0: "items", 1: "critters", 2: "scenery", 3: "walls", 4: "tiles", 5: "misc"}
    arc = next((p for p in gi.vfs.providers if p.label.lower() == archive.lower()), None)
    if arc is None:
        sys.exit(f"no provider named {archive}")
    bad = []
    for pid in sorted({o.pid for o in m.objects}):
        fn = gi.proto_filename(pid)
        if fn is None:
            bad.append(f"0x{pid:08X} (not in any .lst)")
            continue
        rel = "proto\\" + names[pid >> 24] + "\\" + fn
        if not arc.has(rel):
            prov = gi.vfs.provider_for(rel)
            bad.append(f"0x{pid:08X} <- {prov.label if prov else 'missing'}")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default="city1")
    ap.add_argument("--archive", default="master.dat",
                    help="read the template from this archive only (RP copies use RP-only protos)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    gi = GameIndex(pristine=False)
    raw = read_from_archive(gi, args.archive, f"maps\\{args.template}.map")
    m = MapFile.parse(raw, gi.proto)
    if m.elevations != [0]:
        sys.exit(f"{args.template}: expected one elevation, got {m.elevations}")
    foreign = vanilla_only(gi, m, args.archive)
    if foreign:
        sys.exit(f"{args.template} from {args.archive} still uses protos outside it "
                 f"(gecko would not open the result): {foreign[:8]}")

    exits = [o for o in m.objects if o.pid in EXIT_GRID_PIDS]
    hull = _convex_hull([hex_xy(o.tile) for o in exits])
    ring = {o.tile for o in exits} | {o.tile for o in m.objects if o.pid == SCROLL_BLOCKER_PID}
    blocked = blocked_hexes(raw, m)

    taken: set[int] = set()
    arrive = nearest_clear(ARRIVE_TARGET, m, blocked, hull, ring, taken, ARRIVE_RING_GAP)
    taken.add(arrive)
    # keep the party's landing zone clear so followers have room
    for n in neighbours(arrive):
        taken.add(n)
    geckos = []
    for tgt in GECKO_TARGETS:
        t = nearest_clear(tgt, m, blocked, hull, ring, taken)
        geckos.append(t)
        taken.add(t)

    sidx = script_index(gi, "rwruins")
    buf = bytearray(raw)
    name = OUT_NAME.encode("ascii")
    buf[HEADER_NAME_OFF:HEADER_NAME_OFF + HEADER_NAME_LEN] = name + b"\0" * (HEADER_NAME_LEN - len(name))
    struct.pack_into(">i", buf, HEADER_SCRIPT_OFF, sidx)
    struct.pack_into(">i", buf, HEADER_START_TILE_OFF, arrive)
    out = bytes(buf)

    check = MapFile.parse(out, gi.proto)
    assert check.name == OUT_NAME and check.map_script_id == sidx and check.default_tile == arrive
    assert len(check.objects) == len(m.objects)

    print(f"{args.archive}:{args.template}.map -> {OUT_NAME}: {len(check.objects)} objects, all protos vanilla, "
          f"map script rwruins (line {sidx}), exit ring hex "
          f"x{min(x for x, _ in hull)}..{max(x for x, _ in hull)} "
          f"y{min(y for _, y in hull)}..{max(y for _, y in hull)}")
    print(f"  ARRIVE_TILE  {arrive:6d}   hex {hex_xy(arrive)}   (target {ARRIVE_TARGET}, "
          f"{ring_gap(arrive, [hex_xy(r) for r in ring])} hexes from the exits)")
    for i, (t, tgt) in enumerate(zip(geckos, GECKO_TARGETS), 1):
        print(f"  GECKO_{i}_TILE {t:6d}   hex {hex_xy(t)}   (target {tgt})")
    print("  -> these must match the #defines in scripts_src/foc/rwruins.ssl")

    if args.dry_run:
        print("dry run: nothing written")
        return 0
    existing = [d / OUT_NAME for d in (AUTHORED, DEPLOYED) if (d / OUT_NAME).is_file()]
    if existing and not args.force:
        sys.exit(f"refusing to overwrite existing {OUT_NAME} ({', '.join(str(e.relative_to(ROOT)) for e in existing)}); "
                 f"re-run with --force to replace it (old file kept in mod/data/maps/_replaced)")
    for d in (AUTHORED, DEPLOYED):
        d.mkdir(parents=True, exist_ok=True)
        stashed = stash_existing(d / OUT_NAME)
        if stashed:
            print(f"stashed old {(d / OUT_NAME).relative_to(ROOT)} -> {stashed.relative_to(ROOT)}")
        (d / OUT_NAME).write_bytes(out)
        print(f"wrote {(d / OUT_NAME).relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
