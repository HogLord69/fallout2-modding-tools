#!/usr/bin/env python3
"""
darken_frm.py - darken a critter FRM family by remapping pixel indices
through a darkened copy of the game palette (color.pal).

Critter FRMs (v4.0) are 8-bit indexed images drawn with the shared
color.pal - there is no embedded palette. To darken the sprite we scale
every palette entry's RGB toward black, then map each original index to
the nearest index in the darkened palette and rewrite the pixel bytes.
Only frame pixel data changes; every header/frame-hdr byte is preserved.

Usage:
    python tools/darken_frm.py <dir> [--factor 0.65] [--dry-run]
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from foclib import GameIndex  # noqa: E402

FILLER_FRAME = b"\x00"


def load_palette(gi: GameIndex) -> list[tuple[int, int, int]]:
    raw = gi.vfs.read("color.pal")
    pal = []
    for i in range(256):
        r, g, b = raw[i * 3], raw[i * 3 + 1], raw[i * 3 + 2]
        pal.append(((r << 2) | (r >> 4), (g << 2) | (g >> 4), (b << 2) | (b >> 4)))
    return pal


def darken_palette(pal, factor: float) -> list[tuple[int, int, int]]:
    return [(int(r * factor), int(g * factor), int(b * factor)) for r, g, b in pal]


def nearest_index(pix: tuple[int, int, int], pal: list[tuple[int, int, int]]) -> int:
    """Nearest palette index (Euclidean, skipping nothing)."""
    best, bestd = 0, 1 << 30
    r, g, b = pix
    for i, (pr, pg, pb) in enumerate(pal):
        d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
        if d < bestd:
            best, bestd = i, d
    return best


def remap_index(orig: int, table: list[int]) -> int:
    return table[orig]


def darken_frm(data: bytes, table: list[int]) -> bytes:
    """Rewrite pixel bytes of every frame in one FRM file."""
    if len(data) < 0x3E:
        return data
    out = bytearray(data)
    fpd = struct.unpack_from(">H", data, 0x08)[0]
    if fpd == 0:
        fpd = 1
    offsets = struct.unpack_from(">6I", data, 0x22)
    # frames are laid out sequentially from 0x3E, one per (dir, frame)
    pos = 0x3E
    total_frames = 0
    for d in range(6):
        if offsets[d]:
            pass  # offsets are relative to 0x3E
    # walk every frame in order (each orientation block, fpd frames each)
    for _d in range(6):
        for _f in range(fpd):
            if pos + 12 > len(data):
                break
            w, h, size, _ox, _oy = struct.unpack_from(">HHIhh", data, pos)
            start = pos + 12
            n = w * h
            if size < n:
                n = size
            for i in range(n):
                idx = out[start + i]
                if idx:
                    out[start + i] = remap_index(idx, table)
            pos = start + size
            total_frames += 1
    return bytes(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("dir", help="directory of FRM/FR0-5 files (e.g. mod/data/art/critters/ for the NMRANG family)")
    ap.add_argument("--factor", type=float, default=0.65)
    ap.add_argument("--prefix", default="NMRANG")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    gi = GameIndex()
    pal = load_palette(gi)
    dark = darken_palette(pal, args.factor)
    # remap: for each original palette color, find the ORIGINAL-palette index
    # whose color most resembles the DARKENED version of that color.
    table = [nearest_index(dark[i], pal) for i in range(256)]

    d = Path(args.dir)
    files = sorted(
        p for p in d.iterdir()
        if p.suffix.upper() in (".FRM", ".FR0", ".FR1", ".FR2", ".FR3", ".FR4", ".FR5")
        and p.name.upper().startswith(args.prefix.upper())
    )
    if not files:
        print(f"no {args.prefix}.* files in {d}")
        return 1

    changed = 0
    for p in files:
        data = p.read_bytes()
        new = darken_frm(data, table)
        if new != data:
            changed += 1
            if not args.dry_run:
                p.write_bytes(new)
        print(f"{'DRY' if args.dry_run else 'OK '} {p.name}: "
              f"{len(data)} -> {len(new)} bytes")
    print(f"\n{changed}/{len(files)} frames darkened (factor {args.factor})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())