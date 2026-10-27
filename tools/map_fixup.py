#!/usr/bin/env python3
"""
map_fixup.py - make a gecko-saved Redwell map game-ready, in place, losslessly.

    python tools/map_fixup.py RWCORE2.MAP            # base/mods/foc/maps/RWCORE2.MAP
    python tools/map_fixup.py RWCORE2.MAP --dry-run
    python tools/map_fixup.py path/to/any.map

Run it after every gecko session on a map. It never crops or moves anything;
it patches exactly three things gecko cannot get right, then copies the result
to mod\\data\\maps so deploy.py will not overwrite it with a stale authored copy:

  header   gecko keeps the header name of the map you OPENED, so "save as
           RWCORE2.MAP" still says RWCORE.MAP inside. The engine matches that
           name against maps.txt (map.cc: wmMapMatchNameToIdx) to decide which
           map it is on - with the wrong name, cur_map_index is 200 on RWCORE2
           and the well's arrival branch never fires. Renamed to the filename.
  well     gecko cannot write script ids; the town well gets rwwell back
           (map_crop.bind_well - reuses the map's own script-table entry).
  flags    gecko stores every object with flags 0 = solid and non-flat, which
           turns weeds, dirt and shrubs into invisible walls. Objects with
           stored flags 0 get their proto's placement flags and light
           (map_crop.normalize_flags, mirroring object.cc::objectCreateWithPid).
  critters gecko also stores hp 0, AI packet 0 and team 0: the colonist looks
           fine and dies to the first hit, and fights like a wimpy addict.
           Critters with hp 0 get their proto's max hp; AI packet / team 0 get
           the proto's; whoHitMe 0 becomes -1. A `results` word that still
           holds the AI packet (the 09-19..09-21 offset bug - everyone loaded
           KNOCKED_OUT, no Talk verb, USE opened an empty inventory) is cleared.
  doors    gecko can store a door drawn shut (frame 0, not open in its door
           data) with the engine's OBJECT_OPEN_DOOR flags (shoot-through,
           light-through, no-block), so the game lets everyone walk through
           it, locked or not. Those flags are cleared on shut doors.

The previous file is kept as <name>.<timestamp>.bak beside it.
"""

from __future__ import annotations

import argparse
import shutil
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foclib import GameIndex, MapFile  # noqa: E402
from map_crop import (  # noqa: E402
    AUTHORED, DEPLOYED, HEADER_NAME_LEN, HEADER_NAME_OFF, ROOT,
    bind_well, critter_note, normalize_flags,
)


def rename_header(raw: bytes, name: str) -> tuple[bytes, str]:
    cur = raw[HEADER_NAME_OFF:HEADER_NAME_OFF + HEADER_NAME_LEN].split(b"\0")[0].decode("cp1252", "replace")
    want = name.upper()
    if cur.upper() == want:
        return raw, f"header already {cur}"
    enc = want.encode("cp1252", "replace")[:HEADER_NAME_LEN - 1]
    buf = bytearray(raw)
    buf[HEADER_NAME_OFF:HEADER_NAME_OFF + HEADER_NAME_LEN] = enc + b"\0" * (HEADER_NAME_LEN - len(enc))
    return bytes(buf), f"header {cur} -> {want}"


OBJ_FRAME_OFF = 0x18
OBJ_FLAGS_OFF_DOOR = 0x24
DOOR_OPEN_FLAGS_OFF = 0x58     # header (0x48) + inventory (3 words) + updated flags
OBJECT_OPEN_DOOR = 0xA0000010  # obj_types.h: SHOOT_THRU | LIGHT_THRU | NO_BLOCK
SCENERY_SUBTYPE_OFF = 0x20     # scenery proto: 0 = door


def shut_doors(out: bytes, gi: GameIndex) -> tuple[bytes, int]:
    m = MapFile.parse(out, gi.proto)
    buf = bytearray(out)
    fixed = 0
    for o in m.objects:
        if (o.pid >> 24) != 2:
            continue
        try:
            proto = gi.vfs.read(gi.proto_path(o.pid))
        except Exception:  # noqa: BLE001 - a missing proto is normalize_flags' problem
            continue
        if struct.unpack_from(">i", proto, SCENERY_SUBTYPE_OFF)[0] != 0:
            continue
        flags = struct.unpack_from(">I", buf, o.off + OBJ_FLAGS_OFF_DOOR)[0]
        frame = struct.unpack_from(">i", buf, o.off + OBJ_FRAME_OFF)[0]
        open_flags = struct.unpack_from(">i", buf, o.off + DOOR_OPEN_FLAGS_OFF)[0]
        if frame == 0 and (open_flags & 1) == 0 and (flags & OBJECT_OPEN_DOOR) == OBJECT_OPEN_DOOR:
            struct.pack_into(">I", buf, o.off + OBJ_FLAGS_OFF_DOOR, flags & ~OBJECT_OPEN_DOOR & 0xFFFFFFFF)
            fixed += 1
    return bytes(buf), fixed


INVEN_LEN_OFF = 0x48           # after the 18-word header: length, capacity, pointer


def fix_inventory_capacity(out: bytes, gi: GameIndex) -> tuple[bytes, int]:
    """gecko's inventory editor updates an object's item count but not its
    capacity, so a container filled in gecko saves e.g. 2 items with capacity
    0. The engine allocates `capacity` slots and then reads `length` items
    into them (object.cc objectLoadAllInternal), which corrupts the heap:
    "Error reading objects" and a crash at 0x48B1F2 on entering the map.
    Raise the capacity to the length wherever it is short."""
    m = MapFile.parse(out, gi.proto)
    buf = bytearray(out)
    fixed = 0

    def walk(objs):
        nonlocal fixed
        for o in objs:
            length, capacity = struct.unpack_from(">ii", buf, o.off + INVEN_LEN_OFF)
            if length > capacity:
                struct.pack_into(">i", buf, o.off + INVEN_LEN_OFF + 4, length)
                fixed += 1
            walk(o.inventory)

    walk(m.objects)
    return bytes(buf), fixed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("map", help="map filename in base/mods/foc/maps, or a path")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-sync", action="store_true",
                    help="do not copy the result into mod/data/maps")
    args = ap.parse_args()

    path = Path(args.map)
    if not path.is_file():
        path = DEPLOYED / args.map
    if not path.is_file():
        sys.exit(f"no such map: {args.map}")
    if len(path.name) > HEADER_NAME_LEN - 1:
        sys.exit(f"{path.name}: the .map header holds {HEADER_NAME_LEN - 1} chars of name")

    gi = GameIndex(pristine=False)
    raw = path.read_bytes()
    before = MapFile.parse(raw, gi.proto)

    out, h_note = rename_header(raw, path.name)
    out, w_note = bind_well(out, gi)
    out, f_stats = normalize_flags(out, gi)
    out, doors_fixed = shut_doors(out, gi)
    out, inven_fixed = fix_inventory_capacity(out, gi)

    after = MapFile.parse(out, gi.proto)
    assert len(after.objects) == len(before.objects)
    assert after.default_tile == before.default_tile

    print(f"{path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}: "
          f"{len(after.objects)} objects")
    print(f"  {h_note}")
    print(f"  {w_note}")
    print(f"  flags: {f_stats['flagged']} objects given their proto's flags "
          f"({f_stats['walkable']} walkable, {f_stats['flat']} flat), {f_stats['lit']} given light")
    print("  " + critter_note(f_stats))
    print(f"  doors: {doors_fixed} shut doors had the open-door flags cleared")
    print(f"  inventories: {inven_fixed} containers had their capacity raised to their item count")

    if out == raw:
        print("  nothing to change")
    if args.dry_run:
        print("dry run: nothing written")
        return 0

    if out != raw:
        stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(path.stat().st_mtime))
        bak = path.with_name(f"{path.name}.{stamp}.bak")
        shutil.copy2(path, bak)
        path.write_bytes(out)
        print(f"wrote {path.name}  (previous copy: {bak.name})")

    if not args.no_sync and path.parent.resolve() == DEPLOYED.resolve():
        AUTHORED.mkdir(parents=True, exist_ok=True)
        dst = AUTHORED / path.name
        if dst.is_file() and dst.read_bytes() != out:
            stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(dst.stat().st_mtime))
            shutil.copy2(dst, dst.with_name(f"{dst.name}.{stamp}.bak"))
        dst.write_bytes(out)
        print(f"synced -> {dst.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
