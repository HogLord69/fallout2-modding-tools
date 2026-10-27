#!/usr/bin/env python3
"""
make_red_pal.py - build the red-wash palettes used by rwwell.ssl for the
first-drink fade.

A Fallout 2 .pal is: 256 * 3 bytes of 6-bit RGB (0..63), then a 0x8000-byte
15-bit-RGB -> palette-index colour table. We redden only the RGB block and
keep the colour table as-is, so set_palette("rwredN.pal") tints every pixel
on screen red, and set_palette("color.pal") puts it straight back.

Every gfade_in/gfade_out call is a FIXED ~700ms fade - paletteInit()
calibrates gPaletteFadeSteps once at startup so each call takes about the
same wall-clock time no matter what. There is no per-call speed argument.
The only way to make the red sequence slower is to chain more stages, so
this generates a run of N palettes from bright red down to near-black red;
rwwell.ssl fades through all of them in order, then does one real gfade_out
to true black. N stages ~= (N+1) * 700ms of screen time.

Source palette is pulled from the game's own color.pal via the VFS.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from foclib import GameIndex  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "mod" / "data"

RGB_BYTES = 256 * 3
TABLE_BYTES = 0x8000

STAGE_COUNT = 10          # ~(10+1)*0.7s = ~7.7s of screen time for the red sequence
FLOOR_START, FLOOR_END = 24, 2      # dark-area glow: bright red -> almost none
SCALE_START, SCALE_END = 1.0, 0.05  # overall brightness: full -> nearly black


def lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def redden(pal: bytearray, floor: int, scale: float) -> bytearray:
    out = bytearray(pal)
    for i in range(256):
        o = i * 3
        r, g, b = pal[o], pal[o + 1], pal[o + 2]
        if i == 0:                      # index 0 stays the sentinel entry
            continue
        lum = (r * 30 + g * 59 + b * 11) // 100
        lum = int(lum * scale)
        nr = min(63, floor + lum)
        ng = lum // 6
        nb = lum // 10
        out[o], out[o + 1], out[o + 2] = nr, ng, nb
    return out


def main() -> None:
    gi = GameIndex()
    src = bytearray(gi.vfs.read("color.pal"))
    if len(src) < RGB_BYTES + TABLE_BYTES:
        sys.exit(f"color.pal is {len(src)} bytes, expected >= {RGB_BYTES + TABLE_BYTES}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    table = src[RGB_BYTES:]

    # clear any previous stage count before writing the current one
    for old in sorted(OUT_DIR.glob("rwred*.pal")):
        old.unlink()

    for i in range(1, STAGE_COUNT + 1):
        t = (i - 1) / (STAGE_COUNT - 1)
        floor = round(lerp(FLOOR_START, FLOOR_END, t))
        scale = lerp(SCALE_START, SCALE_END, t)
        rgb = redden(src[:RGB_BYTES], floor, scale)
        out_path = OUT_DIR / f"rwred{i}.pal"
        out_path.write_bytes(bytes(rgb) + bytes(table))
        print(f"wrote {out_path}  (floor={floor} scale={scale:.2f})")

    print(f"{STAGE_COUNT} stages; chained in rwwell.ssl for ~{(STAGE_COUNT + 1) * 0.7:.1f}s of red before true black")


if __name__ == "__main__":
    main()
