#!/usr/bin/env python3
"""
make_slide.py - make an ending slide (640x480 FRM and its own palette) from
a render of a FOC map.

    python tools/make_slide.py RWCORE2.MAP 0 100,94 --zoom 1.6 --name EG_ARO01
    python tools/make_slide.py RWCORE2.MAP 0 100,94 --zoom 1.6 --tint ember --name EG_BRO01
    python tools/make_slide.py ... --preview build/slides/x.png   (no FRM written)

The ending slideshow (endgame.cc) draws each slide with the palette in
art\\intrface\\<name>.pal, so a slide gets its own 256 colours, quantised from
the picture itself, instead of the game palette. The .pal is the engine's
colour file: 768 bytes of 6-bit RGB, then the 32768-byte table that maps a
15-bit colour to its nearest index (color.cc colorPaletteLoad).

FOC takes over the vanilla ending slots (EG_*.FRM in intrface.lst 440-473);
the FRM and .pal go to mod/data/art/intrface. --zoom is how many screen
pixels of the render fill one slide pixel (bigger shows more of the map).
--tint: dusk, ember (Redwell burning), mould (the Root Chamber's green), night.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import render  # noqa: E402
from foclib import GameIndex, MapFile  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "mod" / "data" / "art" / "intrface"
W, H = 640, 480

TINTS = {
    "dusk": ((1.08, 0.88, 0.70), 0.0),
    "ember": ((1.25, 0.62, 0.38), 0.10),
    "mould": ((0.75, 1.05, 0.80), 0.05),
    "night": ((0.55, 0.62, 0.85), 0.25),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("map")
    ap.add_argument("elev", type=int)
    ap.add_argument("center", help="hex x,y to centre on")
    ap.add_argument("--zoom", type=float, default=1.5)
    ap.add_argument("--tint", choices=sorted(TINTS))
    ap.add_argument("--name", help="EG_xxxxx: write mod/data/art/intrface/<name>.FRM and .pal")
    ap.add_argument("--preview")
    args = ap.parse_args()
    from PIL import Image, ImageEnhance

    gi = GameIndex(pristine=False)
    raw = (ROOT / "base" / "mods" / "foc" / "maps" / args.map).read_bytes()
    m = MapFile.parse(raw, gi.proto)
    ei = m.elevations.index(args.elev)
    img = render.render_map(gi, m, ei).convert("RGB")
    pts = []
    for sq, tid in enumerate(m.floors[ei]):
        if tid > 1:
            pts.append(render.square_xy(sq))
    for o in m.objects:
        if o.elevation == args.elev and 0 <= o.tile < 40000:
            x, y = render.hex_xy_screen(o.tile)
            pts.append((x - 100, y - 200))
            pts.append((x + 100, y + 60))
    minx = min(p[0] for p in pts)
    miny = min(p[1] for p in pts)
    hx, hy = map(int, args.center.split(","))
    cx, cy = render.hex_xy_screen(hy * 200 + hx)
    cx, cy = cx + 16 - minx, cy + 8 - miny
    cw, ch = int(W * args.zoom), int(H * args.zoom)
    box = (cx - cw // 2, cy - ch // 2, cx + cw // 2, cy + ch // 2)
    crop = Image.new("RGB", (cw, ch), (0, 0, 0))
    crop.paste(img.crop(box), (0, 0))
    pic = crop.resize((W, H), Image.LANCZOS)
    if args.tint:
        (r, g, b), dark = TINTS[args.tint]
        px = pic.load()
        for y in range(H):
            for x in range(W):
                R, G, B = px[x, y]
                px[x, y] = (min(255, int(R * r * (1 - dark))), min(255, int(G * g * (1 - dark))),
                            min(255, int(B * b * (1 - dark))))
    pic = ImageEnhance.Contrast(pic).enhance(1.05)
    if args.preview:
        Path(args.preview).parent.mkdir(parents=True, exist_ok=True)
        pic.save(args.preview)
        print(f"preview {args.preview}")
    if not args.name:
        return 0

    q = pic.quantize(colors=255, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.FLOYDSTEINBERG)
    pal = q.getpalette()[:255 * 3]
    # index 0 stays black; the picture uses 1..255
    pix = bytes(i + 1 for i in q.tobytes())
    rgb = [(0, 0, 0)] + [tuple(pal[i * 3:i * 3 + 3]) for i in range(255)]
    pal6 = bytearray()
    for r, g, b in rgb:
        pal6 += bytes((r >> 2, g >> 2, b >> 2))
    # 15-bit inverse table: nearest palette index for every 5:5:5 colour
    import numpy as np
    P = np.array(rgb, dtype=np.int32)
    v = np.arange(32768, dtype=np.int32)
    R = ((v >> 10) & 31) * 255 // 31
    G = ((v >> 5) & 31) * 255 // 31
    B = (v & 31) * 255 // 31
    table = bytearray(32768)
    step = 4096
    for s in range(0, 32768, step):
        d = ((R[s:s + step, None] - P[None, 1:, 0]) ** 2 + (G[s:s + step, None] - P[None, 1:, 1]) ** 2
             + (B[s:s + step, None] - P[None, 1:, 2]) ** 2)
        table[s:s + step] = (d.argmin(axis=1) + 1).astype(np.uint8).tobytes()
    OUT.mkdir(parents=True, exist_ok=True)
    head = bytearray(62)
    head[0:10] = struct.pack(">IHHH", 4, 0, 0, 1)
    head[58:62] = struct.pack(">I", len(pix) + 12)
    frm = bytes(head) + struct.pack(">HHIhh", W, H, len(pix), 0, 0) + pix
    (OUT / f"{args.name}.FRM").write_bytes(frm)
    (OUT / f"{args.name}.pal").write_bytes(bytes(pal6) + bytes(table))
    print(f"wrote {args.name}.FRM ({len(frm)} bytes) and {args.name}.pal")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
