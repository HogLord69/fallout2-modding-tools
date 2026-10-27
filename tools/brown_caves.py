#!/usr/bin/env python3
"""
brown_caves.py - swap the blue cave walls on FOC's maps for Fallout 2's dark
brown cave walls of the same shape (owner, 2026-10-20: "replace all blue cave
wall assets with the dark brown ones of the same type").

    python tools/brown_caves.py RWFAC1.MAP RWFAC2.MAP --dry-run
    python tools/brown_caves.py RWFAC1.MAP RWFAC2.MAP

The blue ones are Sonora's cave set (scave*, a recolour of Fallout 2's) and
Yesterday's (yca*). Every one of them has a Fallout 2 ca* piece with exactly
the same outline (frame 0's opaque pixels, anchored at the bottom centre:
overlap 1.00), though not always the same number (scave034 is ca071). Each
blue wall object gets the brown piece's proto and art. Writes mod/data/maps
and the deployed copy; close gecko and the game first.
"""

from __future__ import annotations

import argparse
import re
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foclib import GameIndex, parse_lst  # noqa: E402
from foclib.formats import MapFile  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
AUTH = ROOT / "mod" / "data" / "maps"
DEPL = ROOT / "base" / "mods" / "foc" / "maps"
BLUE = re.compile(r"^(scave|yca)\d+[a-z]?\.frm$", re.I)
BROWN = re.compile(r"^ca\d+\.frm$", re.I)


def frame(gi, name):
    d = gi.vfs.read("art\\walls\\" + name)
    shx = struct.unpack_from(">h", d, 0x0A)[0]
    shy = struct.unpack_from(">h", d, 0x16)[0]
    w, h, _, ox, oy = struct.unpack_from(">HHIhh", d, 0x3E)
    px = d[0x3E + 12:0x3E + 12 + w * h]
    return w, h, ox + shx, oy + shy, {(i % w, i // w) for i, c in enumerate(px) if c}


def overlap(a, b):
    wa, ha, oxa, oya, ma = a
    wb, hb, oxb, oyb, mb = b
    dx = (wb // 2 - oxb) - (wa // 2 - oxa)
    dy = (hb - oyb) - (ha - oya)
    ma2 = {(x + dx, y + dy) for x, y in ma}
    return len(ma2 & mb) / max(1, len(ma2 | mb))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("maps", nargs="+")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not a.dry_run:
        running = subprocess.run(["tasklist"], capture_output=True, text=True).stdout.lower()
        if "gecko" in running or "fallout2" in running:
            sys.exit("close gecko and the game first")
    gi = GameIndex(pristine=False)
    walls = parse_lst(gi.vfs.read("art\\walls\\walls.lst"))
    proto_of_art = {}
    for i in range(1, len(gi.proto_lst(3)) + 1):
        pid = 0x03000000 | i
        pr = gi.proto(pid)
        if pr is not None:
            proto_of_art.setdefault(pr.fid & 0xFFFFFF, pid)
    brown = {i: frame(gi, n) for i, n in enumerate(walls) if n and BROWN.match(n) and i in proto_of_art}
    swap = {}                                   # blue art index -> (brown pid, brown fid)
    for name in a.maps:
        path = next(q for q in AUTH.iterdir() if q.name.upper() == name.upper())
        raw = path.read_bytes()
        dep = DEPL / path.name
        if dep.exists() and dep.read_bytes() != raw and not a.dry_run:
            sys.exit(f"{path.name}: the deployed copy differs from mod/data/maps; run tools/sync_maps.py first")
        m = MapFile.parse(raw, gi.proto)
        out = bytearray(raw)
        n = 0
        for o in m.objects:
            if (o.pid >> 24) != 3:
                continue
            ai = o.fid & 0xFFFFFF
            if ai >= len(walls) or not BLUE.match(walls[ai] or ""):
                continue
            if ai not in swap:
                f = frame(gi, walls[ai])
                bi, bf = max(brown.items(), key=lambda kv: overlap(f, kv[1]))
                ov = overlap(f, bf)
                if ov < 0.95:
                    sys.exit(f"{walls[ai]}: the nearest brown piece {walls[bi]} only overlaps {ov:.2f}")
                pid = proto_of_art[bi]
                swap[ai] = (pid, gi.proto(pid).fid, walls[bi])
                print(f"  {walls[ai]} -> {walls[bi]} (overlap {ov:.2f}, proto 0x{pid:08X})")
            pid, fid, _ = swap[ai]
            struct.pack_into(">I", out, o.pid_offset, pid)
            struct.pack_into(">I", out, o.fid_offset, fid)
            n += 1
        MapFile.parse(bytes(out), gi.proto)
        print(f"{path.name}: {n} blue cave walls made brown" + (" (dry run)" if a.dry_run else ""))
        if not a.dry_run and n:
            path.write_bytes(bytes(out))
            if dep.exists():
                dep.write_bytes(bytes(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
