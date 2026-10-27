#!/usr/bin/env python3
"""
recolor_frm.py - recolour the grey parts of a scenery FRM into another
material, keeping its coloured details (seals, brass, paper).

    python tools/recolor_frm.py ENCL40.FRM --wood --preview build/encl40_wood.png
    python tools/recolor_frm.py ENCL40.FRM --wood --write

Each pixel's colour comes from color.pal. Pixels that are nearly grey (low
saturation) and not near-white are re-toned along a wood ramp by their
brightness, and matched back to the nearest palette colour, never to the
palette's animated colours (229-254, which cycle in game). Coloured pixels and
the near-white highlights of paper stay as they are.

--write puts the result at mod/data/art/scenery/<NAME>, where it replaces the
art of that name for every object that uses it (check the maps first;
ENCL40.FRM, the president's desk, is used only by CLCOURT's judge's bench).
"""

from __future__ import annotations

import argparse
import colorsys
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foclib import GameIndex  # noqa: E402
from replace_pc_from_ref import decode_frm, encode_frm, load_8bit_palette  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "mod" / "data" / "art" / "scenery"

# wood, measured from Fallout 2's own wooden furniture (abdesk, ltable2, tbl1000):
# hue 0.08, saturation 0.45-0.64, brightness about 0.22 median and 0.4 at the top
WOOD = dict(hue=0.065, sat_dark=0.78, sat_light=0.6, gain=0.5, base=0.07)
# light oak: the owner's pick for the judge's bench (2026-10-15)
LIGHT = dict(hue=0.075, sat_dark=0.62, sat_light=0.45, gain=0.86, base=0.04)


def tone(lum, m):
    """Brightness 0..1 -> wood RGB 0..255."""
    sat = m["sat_dark"] + (m["sat_light"] - m["sat_dark"]) * lum
    r, g, b = colorsys.hsv_to_rgb(m["hue"], sat, min(1.0, lum * m["gain"] + m["base"]))
    return np.array([r, g, b]) * 255


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("name")
    ap.add_argument("--wood", action="store_true")
    ap.add_argument("--light", action="store_true", help="light oak: any palette colour, brighter ramp")
    ap.add_argument("--match", help="take the colours from this scenery FRM, e.g. ltable2.frm")
    ap.add_argument("--like", help="recolour every pixel like this scenery FRM, e.g. sherm101.frm")
    ap.add_argument("--preview", type=Path)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    gi = GameIndex(pristine=True)
    # Always recolour from the original art: the base game's, or for art the mod
    # imported, the untouched copy kept in mod/art_src/frm_originals (saved the
    # first time), so a second run never recolours a recoloured file.
    keep = ROOT / "mod" / "art_src" / "frm_originals" / args.name.lower()
    try:
        data = gi.vfs.read(f"art\\scenery\\{args.name}")
    except FileNotFoundError:
        if not keep.is_file():
            keep.parent.mkdir(parents=True, exist_ok=True)
            keep.write_bytes(GameIndex(pristine=False).vfs.read(f"art\\scenery\\{args.name}"))
            print(f"kept the original at {keep.relative_to(ROOT)}")
        data = keep.read_bytes()
    meta = decode_frm(data)
    pal = np.array(load_8bit_palette(gi), dtype=float)
    usable = [i for i in range(1, 256) if not 229 <= i <= 254]
    if args.wood and not args.light:    # only the palette's real browns, so nothing drifts olive
        def brown(i):
            h, s, v = colorsys.rgb_to_hsv(*(pal[i] / 255))
            return 0.03 <= h <= 0.10 and s >= 0.45 or v < 0.08
        usable = [i for i in usable if brown(i)]
    upal = pal[usable]

    def hsv(i):
        return colorsys.rgb_to_hsv(*(pal[i] / 255))

    def is_grey(i):
        h, s, v = hsv(i)
        return s < 0.22 and v < 0.86

    lut = {i: i for i in range(1, 256)}
    if args.like:
        # Recolour every pixel like another art: each colour of this art, by its
        # brightness rank, takes the other art's most common colour at that rank.
        ref = decode_frm(GameIndex(pristine=False).vfs.read("art\\scenery\\" + args.like))   # may be mod art
        rpx = np.concatenate([np.frombuffer(f.px, np.uint8) for row in ref["frames"].values() for f in row])
        rsorted = sorted((int(i) for i in rpx if i > 0 and not 229 <= i <= 254), key=lambda i: hsv(i)[2])
        spx = np.concatenate([np.frombuffer(f.px, np.uint8) for row in meta["frames"].values() for f in row])
        mine = sorted({int(i) for i in spx if i > 0 and not 229 <= i <= 254}, key=lambda i: hsv(i)[2])
        counts = {i: int((spx == i).sum()) for i in mine}
        total, seen = sum(counts.values()), 0
        w = max(3, len(rsorted) // 40)
        for i in mine:
            mid = (seen + counts[i] / 2) / total
            seen += counts[i]
            k = min(len(rsorted) - 1, int(mid * len(rsorted)))
            window = rsorted[max(0, k - w): k + w + 1]
            lut[i] = max(set(window), key=window.count)
    if args.match:
        # Match another FRM's wood (e.g. the room's tables): its median hue and
        # saturation, and its brightness range (10th to 90th percentile) spread
        # over this art's grey range, drawn from the palette colours near that hue.
        ref = decode_frm(gi.vfs.read("art\\scenery\\" + args.match))
        rpx = np.concatenate([np.frombuffer(f.px, np.uint8) for row in ref["frames"].values() for f in row])
        rh = np.array([hsv(int(i)) for i in rpx if i > 0 and not 229 <= i <= 254 and hsv(int(i))[1] > 0.2])
        hue, sat = float(np.median(rh[:, 0])), float(np.median(rh[:, 1]))
        lo, hi = np.percentile(rh[:, 2], [10, 90])
        spx = np.concatenate([np.frombuffer(f.px, np.uint8) for row in meta["frames"].values() for f in row])
        gv = np.array([hsv(int(i))[2] for i in spx if i > 0 and is_grey(int(i))])
        glo, ghi = np.percentile(gv, [10, 90])
        near = [i for i in range(1, 256) if not 229 <= i <= 254 and
                (abs(hsv(i)[0] - hue) < 0.04 and abs(hsv(i)[1] - sat) < 0.2 or hsv(i)[2] < 0.06)]
        npal = pal[near]
        for i in range(1, 256):
            if is_grey(i):
                t = min(1.0, max(0.0, (hsv(i)[2] - glo) / max(1e-6, ghi - glo)))
                v = lo + t * (hi - lo)
                want = np.array(colorsys.hsv_to_rgb(hue, sat, v)) * 255
                lut[i] = near[int(np.argmin(((npal - want) ** 2).sum(axis=1)))]
        print(f"matched {args.match}: hue {hue:.3f} sat {sat:.2f} brightness {lo:.2f}-{hi:.2f}")
    elif args.wood:
        for i in range(1, 256):
            if is_grey(i):
                want = tone(hsv(i)[2], LIGHT if args.light else WOOD)
                j = int(np.argmin(((upal - want) ** 2).sum(axis=1)))
                lut[i] = usable[j]
    table = bytes([0] + [lut[i] for i in range(1, 256)])

    out_frames = {}
    for d, row in meta["frames"].items():
        out_frames[d] = [(f.w, f.h, f.sx, f.sy, f.px.translate(table)) for f in row]
    # a one-direction FRM keeps all six direction offsets at 0, as the original does
    result = encode_frm(meta, out_frames, split=len(out_frames) == 1)
    if len(result) != len(data):
        sys.exit(f"size changed ({len(data)} -> {len(result)}); not writing")

    if args.preview:
        f0 = out_frames[0][0]
        idx = np.frombuffer(f0[4], np.uint8).reshape(f0[1], f0[0])
        rgb = pal[idx].astype(np.uint8)
        a = np.where(idx > 0, 255, 0).astype(np.uint8)
        im = Image.fromarray(np.dstack([rgb, a]), "RGBA")
        im.resize((im.width * 4, im.height * 4), Image.NEAREST).save(args.preview)
        print(f"preview {args.preview}")
    if args.write:
        OUT.mkdir(parents=True, exist_ok=True)
        dest = OUT / args.name.lower()          # gecko looks art up in lower case
        dest.write_bytes(result)
        print(f"wrote {dest.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
