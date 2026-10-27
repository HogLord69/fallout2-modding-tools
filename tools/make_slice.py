#!/usr/bin/env python3
"""
make_slice.py - build the throwaway test map.

    python tools/make_slice.py [--fragment ID] [--name FOCTEST.MAP]

Takes one human-composed room out of the corpus and lays it into a map written
from scratch, then points the player at it. That tests three things in a single
launch:

  1. the map writer produces something the engine accepts
  2. the FLOOR RENDERS - i.e. the elevation-1 convention really was MDFG's
     black-floor bug
  3. a corpus fragment survives the trip: tiles, walls, scenery, the lot

Defaults to a fragment from `fo2`, which is our own base, so every tile and
proto resolves with nothing to port. That keeps this test about the pipeline
rather than about porting.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foclib import GameIndex, TYPE_NAME, parse_lst  # noqa: E402
from mapbuild import HEX_W, MapBuilder, MapObjectSpec, extras_for  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CORPUS = ROOT / "corpus" / "fragments.jsonl"
OUT_DIR = ROOT / "mod" / "data" / "maps"

# A small, dense, enclosed fo2 room with a door and scripted objects.
DEFAULT_FRAGMENT = "fo2:broken2:e0:30_57"


def load_fragment(frag_id: str) -> dict:
    if not CORPUS.is_file():
        sys.exit("no corpus - run: python tools/corpus.py index")
    with CORPUS.open(encoding="utf-8") as f:
        for line in f:
            if f'"id":"{frag_id}"' in line or f'"id": "{frag_id}"' in line:
                fr = json.loads(line)
                if fr["id"] == frag_id:
                    return fr
    sys.exit(f"no fragment {frag_id} - try: python tools/corpus.py search")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fragment", default=DEFAULT_FRAGMENT)
    ap.add_argument("--name", default="FOCTEST.MAP")
    ap.add_argument("--at", default="30,30", help="top-left square, sx,sy")
    args = ap.parse_args()

    gi = GameIndex()
    fr = load_fragment(args.fragment)
    ox, oy = (int(v) for v in args.at.split(","))

    print(f"fragment {fr['id']}")
    print(f"  {fr['source']} {fr['map']} elevation {fr['elevation']}, "
          f"{fr['size_sq'][0]}x{fr['size_sq'][1]} squares")
    print(f"  {len(fr['palette'])} distinct tiles, {fr['object_count']} objects")

    # ---- resolve tile names to OUR ids -----------------------------------
    tile_names = parse_lst(gi.vfs.read("art/tiles/tiles.lst"))
    # 0-based: art lists index directly (CLAUDE.md 4f).
    # tiles.lst registers 22 names at two consecutive indices each, so
    # name -> id is not a bijection; keep the FIRST, both point at the same art.
    tile_id = {}
    for i, n in enumerate(tile_names):
        if n:
            tile_id.setdefault(n.lower(), i)
    pal_ids, missing_tiles = [], []
    for n in fr["palette"]:
        tid = tile_id.get(n.lower())
        if tid is None:
            missing_tiles.append(n)
            pal_ids.append(0)
        else:
            pal_ids.append(tid)

    # ---- resolve protos ---------------------------------------------------
    # fo2 IS our base, so its proto filenames are directly valid here. For any
    # other source a filename like 00001417.pro is just the index wearing an
    # extension and means something else entirely - those need porting first.
    proto_pid: dict[tuple[int, str], int] = {}
    for ot in TYPE_NAME:
        for i, fn in enumerate(gi.proto_lst(ot)):
            if fn:
                proto_pid[(ot, fn.lower())] = (ot << 24) | (i + 1)

    if fr["source"] != "fo2":
        print(f"  !! fragment source is {fr['source']}, not our base. Proto "
              f"filenames are not portable across installs; this test resolves "
              f"them by filename and will misplace objects. Use an fo2 fragment "
              f"or port it first.")

    mb = MapBuilder(args.name, elevations=(0,), map_id=200)

    # ---- tiles ------------------------------------------------------------
    laid = 0
    for ry, row in enumerate(fr["floor"]):
        for rx, c in enumerate(row):
            if c < 0 or not pal_ids[c]:
                continue
            mb.set_floor(0, ox + rx, oy + ry, pal_ids[c])
            laid += 1
    for ry, row in enumerate(fr["roof"]):
        for rx, c in enumerate(row):
            if c >= 0 and pal_ids[c]:
                mb.set_roof(0, ox + rx, oy + ry, pal_ids[c])

    # ---- objects ----------------------------------------------------------
    placed = skipped = 0
    for o in fr["objects"]:
        ot = o["t"]
        if ot not in TYPE_NAME or not o["proto"]:
            skipped += 1
            continue
        pid = proto_pid.get((ot, o["proto"].lower()))
        if pid is None:
            skipped += 1
            continue
        pr = gi.proto(pid)
        if pr is None:
            skipped += 1
            continue
        hx = ox * 2 + o["dx"]
        hy = oy * 2 + o["dy"]
        if not (0 <= hx < HEX_W and 0 <= hy < 200):
            skipped += 1
            continue
        mb.add(MapObjectSpec(
            pid=pid, fid=pr.fid, tile=hy * HEX_W + hx, elevation=0,
            extras=extras_for(ot, pid, pr.subtype),
        ))
        placed += 1

    # ---- put the player on a floored square inside the room ---------------
    floors = mb.floors[0]
    start = None
    cy = oy + len(fr["floor"]) // 2
    cx = ox + len(fr["floor"][0]) // 2
    for radius in range(0, 20):
        for sy in range(cy - radius, cy + radius + 1):
            for sx in range(cx - radius, cx + radius + 1):
                if 0 <= sx < 100 and 0 <= sy < 100 and floors[sy * 100 + sx] > 1:
                    start = (sx, sy)
                    break
            if start:
                break
        if start:
            break
    if start is None:
        sys.exit("no floored square to stand on - the fragment laid no tiles")
    mb.start_tile = (start[1] * 2) * HEX_W + (start[0] * 2)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dst = OUT_DIR / args.name.upper()
    dst.write_bytes(mb.to_bytes())

    print()
    print(f"  tiles laid   : {laid}")
    print(f"  objects      : {placed} placed, {skipped} skipped")
    if missing_tiles:
        print(f"  MISSING tiles: {len(missing_tiles)} -> {missing_tiles[:6]}")
    print(f"  start        : square {start}, hex {mb.start_tile}, elevation 0")
    print(f"  flags        : 0x{mb.flags:02X} (elevations {mb.elevations})")
    print(f"  wrote        : {dst.relative_to(ROOT)} ({dst.stat().st_size} bytes)")

    # prove it reads back
    from foclib import MapFile
    m = MapFile.parse(dst.read_bytes(), gi.proto)
    print(f"  re-read      : {len(m.objects)} objects, "
          f"{sum(1 for f in m.floors[0] if f > 1)} floored squares, "
          f"elevations {m.elevations}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
