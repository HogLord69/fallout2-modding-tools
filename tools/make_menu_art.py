#!/usr/bin/env python3
r"""
make_menu_art.py - build the hi-res main-menu background (HR_MAINMENU.FRM).

f2_res (USE_HIRES_IMAGES=1) loads art\intrface\HR_MAINMENU.FRM in place of
MAINMENU.FRM and stretches it to the screen keeping aspect (MAIN_MENU_SIZE=1).
It is an ordinary single-frame 8-bit FRM v4 of any size, drawn with color.pal.

Quantises with Floyd-Steinberg dithering to palette indices 1..228. 0 is
transparent and 229+ are the engine's animated colours (slime, fire, shore,
monitors), which would shimmer across the picture.

Usage: python tools/make_menu_art.py [source.jpg] [-o out.FRM]
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from foclib import GameIndex  # noqa: E402

USABLE = range(1, 229)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", nargs="?", default=str(ROOT / "mod/art_src/mainmenu_helmet_1920x1080.jpg"))
    ap.add_argument("-o", "--out", default=str(ROOT / "mod/data/art/intrface/HR_MAINMENU.FRM"))
    a = ap.parse_args()

    raw = GameIndex(pristine=False).vfs.read("color.pal")
    pal = []
    for i in range(256):
        r, g, b = raw[i * 3:i * 3 + 3]
        pal.append(((r << 2) | (r >> 4), (g << 2) | (g >> 4), (b << 2) | (b >> 4)))

    # PIL quantises to an indexed palette image; give it only the usable colours
    # (remaining slots repeat colour 1 so they are never nearest-chosen over it).
    flat = []
    for i in range(256):
        flat += pal[i if i in USABLE else 1]
    pimg = Image.new("P", (1, 1))
    pimg.putpalette(flat)

    src = Image.open(a.src).convert("RGB")
    q = src.quantize(palette=pimg, dither=Image.Dither.FLOYDSTEINBERG)
    w, h = q.size
    # unusable slots hold a copy of colour 1, so folding them back to 1 is lossless
    pix = bytearray(q.tobytes().translate(bytes(i if i in USABLE else 1 for i in range(256))))
    assert 0 not in pix and max(pix) <= 228, "quantiser leaked an unusable index"

    # 62-byte header: version, fps, action frame, frames/dir, shifts, offsets, data size
    ref = bytearray(62)
    ref[0:10] = struct.pack(">IHHH", 4, 0, 0, 1)
    ref[58:62] = struct.pack(">I", len(pix) + 12)
    frame = struct.pack(">HHIhh", w, h, len(pix), 0, 0)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(bytes(ref) + frame + bytes(pix))
    print(f"{out}  {w}x{h}  {out.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
