#!/usr/bin/env python3
"""
restyle_walls.py - match wall pieces of one family to the same-shaped pieces
of another, so a building lifted from one town can be re-skinned in another
town's style.

    python tools/restyle_walls.py adb,adw nec --sheet build/restyle/adb_to_nec.png

Fallout wall families share no numbering, but every piece is a shape: a run
one way or the other, a corner, an end, a doorway, a window. A piece's
footprint (its bottom rows, where it meets the floor) placed where the engine
anchors it (object.cc: bottom-centre at the hex + 16,8 + the frame's offset)
says which shape it is; height and texture do not. So each source piece is
matched to the target piece whose footprint overlaps it best.

match(src_prefixes, dst_prefixes) -> {source art name: target art name}
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import render  # noqa: E402
from foclib import GameIndex, parse_lst  # noqa: E402

FOOT = 36          # rows at the bottom of a piece that make up its footprint
W = 200            # canvas the footprints are laid on


def footprint(img: Image.Image, ox: int, oy: int) -> np.ndarray:
    """The piece's lowest FOOT rows of alpha, anchored like the engine."""
    a = np.asarray(img.split()[-1]) > 0
    canvas = np.zeros((FOOT, W), bool)
    h, w = a.shape
    left = W // 2 + ox - w // 2
    band = a[max(0, h - FOOT):, :]
    top = FOOT - band.shape[0] + min(0, oy)          # a positive offset lowers the piece
    for r in range(band.shape[0]):
        rr = top + r + max(0, oy)
        if 0 <= rr < FOOT:
            cols = np.nonzero(band[r])[0] + left
            cols = cols[(cols >= 0) & (cols < W)]
            canvas[rr, cols] = True
    return canvas


def load(gi: GameIndex, prefixes: list[str], art):
    wl = parse_lst(gi.vfs.read("art\\walls\\walls.lst"))
    out = {}
    pat = re.compile(rf"^({'|'.join(map(re.escape, prefixes))})\d", re.I)
    for i, n in enumerate(wl[:4096]):
        if n and pat.match(n):
            img, ox, oy = art.obj(3, 0x03000000 | i, 0)
            if img is None:
                continue
            out[n.lower()] = (i, img, ox, oy, footprint(img, ox, oy))
    return out


def match(gi: GameIndex, src_prefixes: list[str], dst_prefixes: list[str], only: set[str] | None = None):
    art = render.ArtCache(gi, render.load_palette(gi))
    src = load(gi, src_prefixes, art)
    dst = load(gi, dst_prefixes, art)
    result = {}
    for name, (_, _, _, _, fa) in src.items():
        if only is not None and name not in only:
            continue
        best, bs = None, -1.0
        for dn, (_, _, _, _, fb) in dst.items():
            inter = np.logical_and(fa, fb).sum()
            union = np.logical_or(fa, fb).sum()
            s = inter / union if union else 0.0
            if s > bs:
                best, bs = dn, s
        result[name] = (best, round(float(bs), 3))
    return result, src, dst


def sheet(result, src, dst, out: Path):
    rows = sorted(result)
    cell_w, cell_h = 260, 190
    s = Image.new("RGB", (cell_w * 4, cell_h * ((len(rows) + 1) // 2)), (35, 35, 35))
    d = ImageDraw.Draw(s)
    for k, name in enumerate(rows):
        dn, score = result[name]
        for j, (img, label) in enumerate(((src[name][1], name), (dst[dn][1], f"{dn} {score}"))):
            im = img.copy()
            im.thumbnail((cell_w - 10, cell_h - 24))
            x = (k % 2) * 2 * cell_w + j * cell_w
            y = (k // 2) * cell_h
            s.paste(im, (x + 5, y + 5), im)
            d.text((x + 5, y + cell_h - 16), label, fill=(255, 220, 60))
    out.parent.mkdir(parents=True, exist_ok=True)
    s.save(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("src", help="source family prefixes, comma separated (e.g. adb,adw)")
    ap.add_argument("dst", help="target family prefixes (e.g. nec)")
    ap.add_argument("--sheet", type=Path)
    args = ap.parse_args()
    gi = GameIndex(pristine=False)
    result, src, dst = match(gi, args.src.split(","), args.dst.split(","))
    for k in sorted(result):
        print(f"{k:14} -> {result[k][0]:14} {result[k][1]}")
    if args.sheet:
        sheet(result, src, dst, args.sheet)
        print(f"sheet: {args.sheet}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
