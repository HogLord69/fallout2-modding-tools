#!/usr/bin/env python3
r"""
recolor_critter.py - make a recoloured copy of a critter FRM family.

Critter FRMs are 8-bit indexed against the shared color.pal (no embedded
palette), so a recolour is a remap of pixel indices: for every palette colour
work out what it should become, then pick the nearest palette index.
Indices 0 (transparent) and 229+ (animated colours) are never touched.

    python tools/recolor_critter.py MAMURT MAHOGX --preview
    python tools/recolor_critter.py MAMURT MAHOGX          # writes mod/data/art/critters/
"""
from __future__ import annotations

import argparse
import colorsys
import struct
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from foclib import GameIndex  # noqa: E402

USABLE = range(1, 229)
EXTS = ("FRM", "FR0", "FR1", "FR2", "FR3", "FR4", "FR5")


def load_palette(gi):
    raw = gi.vfs.read("color.pal")
    return [tuple((c << 2) | (c >> 4) for c in raw[i * 3:i * 3 + 3]) for i in range(256)]


def brown_target(rgb, hue, sat, val):
    """Same shading, re-hued to brown. Grey fur gets the full brown; strongly
    coloured pixels (eyes, blood, tongue) keep most of their own colour."""
    r, g, b = (c / 255 for c in rgb)
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    own = min(1.0, max(0.0, s - 0.55) * 1.2) if not (0.04 < h < 0.14) else 0.0  # only vivid pixels keep own hue
    fur_h, fur_s = hue, sat
    nh = h * own + fur_h * (1 - own)
    ns = s * own + max(fur_s, s * 0.9) * (1 - own)
    nv = v * val
    rr, gg, bb = colorsys.hsv_to_rgb(nh % 1.0, min(1, ns), min(1, nv))
    return (rr * 255, gg * 255, bb * 255)


def build_table(pal, hue, sat, val):
    table = list(range(256))
    for i in USABLE:
        t = brown_target(pal[i], hue, sat, val)
        best, bd = i, 1 << 30
        for j in USABLE:
            d = sum((a - b) ** 2 for a, b in zip(t, pal[j]))
            if d < bd:
                best, bd = j, d
        table[i] = best
    return table


def remap_frm(data: bytes, table) -> bytes:
    out = bytearray(data)
    pos = 0x3E
    while pos + 12 <= len(data):
        w, h, size, _x, _y = struct.unpack_from(">HHIhh", data, pos)
        start = pos + 12
        for i in range(start, min(start + size, len(data))):
            out[i] = table[out[i]]
        pos = start + size
    return bytes(out)


def family(gi, prefix):
    for a in "ABCDEFGHIJKLMNOPQRST":
        for b in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            for ext in EXTS:
                n = f"{prefix}{a}{b}.{ext}"
                if gi.vfs.exists("art/critters/" + n):
                    yield n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--hue", type=float, default=24, help="degrees (brown ~ 24)")
    ap.add_argument("--sat", type=float, default=0.50)
    ap.add_argument("--val", type=float, default=0.45, help="brightness multiplier")
    ap.add_argument("--preview", action="store_true", help="write a contact sheet only")
    ap.add_argument("--out", default=str(ROOT / "mod/data/art/critters"))
    a = ap.parse_args()
    src, dst = a.src.upper(), a.dst.upper()
    assert len(src) == 6 and len(dst) == 6, "critter art prefixes are 6 characters"

    gi = GameIndex(pristine=False)
    pal = load_palette(gi)
    table = build_table(pal, a.hue / 360, a.sat, a.val)
    names = list(family(gi, src))
    if not names:
        print(f"no {src}*.FRM in the game index")
        return 1

    if a.preview:
        sheet = Image.new("RGB", (4 * 140, 2 * 110), (40, 40, 40))
        rgbpal = [c for p in pal for c in (p if max(p) <= 255 else (0, 0, 0))]
        for n_i, n in enumerate(("AA", "BA")):
            for k, ext in enumerate(("FRM", "FR0")):
                fn = f"{src}{n}.{ext}"
                if not gi.vfs.exists("art/critters/" + fn):
                    continue
                d = gi.vfs.read("art/critters/" + fn)
                for col, tb in enumerate((None, table)):
                    dd = remap_frm(d, tb) if tb else d
                    w, h, sz, *_ = struct.unpack_from(">HHIhh", dd, 0x3E)
                    im = Image.frombytes("P", (w, h), dd[0x3E + 12:0x3E + 12 + w * h])
                    im.putpalette(rgbpal[:768])
                    im = im.convert("RGBA")
                    px = im.load()
                    for y in range(h):
                        for x in range(w):
                            if dd[0x3E + 12 + y * w + x] == 0:
                                px[x, y] = (40, 40, 40, 255)
                    ox = (n_i * 2 + col) * 140 + 70 - w // 2
                    sheet.paste(im.convert("RGB"), (max(0, ox), 10 + k * 0))
        out = ROOT / "mod/art_src/_recolor_preview.png"
        sheet.resize((sheet.width * 2, sheet.height * 2), Image.NEAREST).save(out)
        print(out)
        return 0

    outdir = Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)
    for n in names:
        data = gi.vfs.read("art/critters/" + n)
        (outdir / (dst + n[6:])).write_bytes(remap_frm(data, table))
    print(f"{len(names)} frames {src}* -> {dst}* in {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
