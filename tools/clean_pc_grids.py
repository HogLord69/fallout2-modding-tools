#!/usr/bin/env python3
"""clean_pc_grids.py

Optional in-place touch-ups for art/pc_grids/*.png (green background kept so
replace_pc_from_ref.py still slices them). BOTH passes are OFF by default -
the current build maps each grid 1:1 to the vanilla frame count, which is the
smoothest result; these are here if a specific grid needs them.

  --trim          locomotion families only: drop near-static bookend frames
                  and re-tile. NOTE: this changes the grid's column count, so
                  the forced even split in replace_pc_from_ref.py must be told
                  the new count - not wired up, so leave off for now.
  --strip-shadow  repaint the baked ground shadow to key green. The heuristic
                  removed too much of the boots; needs work.

Run:  python tools/clean_pc_grids.py [--dry-run] [--trim] [--strip-shadow]
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
from PIL import Image
from scipy import ndimage

ROOT = Path(__file__).resolve().parent.parent
GRIDS = ROOT / "art" / "pc_grids"
KEY = (0, 255, 0)

LOCOMOTION = {"AB", "AT", "DB", "EB", "FB", "GB", "HB", "IB", "JB"}
# prone / on-the-ground poses: the shadow heuristics assume an upright figure,
# so skip them entirely
NO_SHADOW_SCRUB = {"BA", "BB", "BC", "BD", "BE", "BF", "BG", "BH", "BI", "BJ",
                   "BK", "BL", "BM", "BN", "BO", "BP", "CH", "CJ",
                   "RA", "RB", "RC", "RD", "RE", "RF", "RG", "RH", "RI", "RJ",
                   "RK", "RL", "RM", "RN", "RO", "RP"}

SHADOW_LUMA = 30        # ground-shadow core is near-black ...
SHADOW_SAT = 12         # ... and neutral. even dark boots clear this.


def key_mask(rgb):
    r, g, b = rgb[..., 0].astype(int), rgb[..., 1].astype(int), rgb[..., 2].astype(int)
    return ~((g > 140) & (g - r > 40) & (g - b > 40))          # True = sprite


def est_cols(mask):
    cp = mask.mean(0).astype(float); cp -= cp.mean()
    ac = np.correlate(cp, cp, "full")[len(cp) - 1:]
    w = len(cp); lo, hi = max(10, w // 26), max(14, w // 3)
    return max(2, round(w / (lo + int(np.argmax(ac[lo:hi])))))


def scrub_shadow(a):
    """a: HxWx3 uint8 (green bg). The baked shadow is a flat patch on the
    ground: it lives only in the bottom sliver of the frame. Any column whose
    sprite content sits ENTIRELY in the bottom ~16% of the bbox is shadow-only
    (the sideways smear); plus dark-neutral pixels in the bottom 4 rows (the
    puddle right under the feet). Legs always reach far above that, so the body
    is never touched."""
    rgb = a.astype(int)
    luma = 0.299 * rgb[..., 0] + 0.587 * rgb[..., 1] + 0.114 * rgb[..., 2]
    sat = rgb.max(2) - rgb.min(2)
    sprite = key_mask(a)
    H, W = sprite.shape
    ncols = est_cols(sprite)
    out = a.copy()
    removed = 0
    for d in range(6):
        y0, y1 = int(round(d * H / 6)), int(round((d + 1) * H / 6))
        for c in range(ncols):
            x0, x1 = int(round(c * W / ncols)), int(round((c + 1) * W / ncols))
            reg = (slice(y0, y1), slice(x0, x1))
            m = sprite[reg].copy()
            ys, xs = np.where(m)
            if len(ys) < 25:
                continue
            top, bot = ys.min(), ys.max()
            hh = bot - top + 1
            lu, sa = luma[reg], sat[reg]
            dark_neutral = m & (lu < 52) & (sa < 26)
            drop = np.zeros_like(m)

            # (a) any column whose sprite content is only in the bottom 16%
            foot_line = bot - int(hh * 0.16)
            for x in range(m.shape[1]):
                col = np.where(m[:, x])[0]
                if len(col) and col.min() >= foot_line:
                    drop[col, x] = True

            # (b) in the bottom third, any ROW that is mostly dark-neutral is a
            # shadow row - remove its dark-neutral pixels (brown boots/pants are
            # never >60% dark-neutral across a row)
            for row in range(bot - int(hh * 0.33), bot + 1):
                rm = m[row]
                if rm.sum() >= 6 and dark_neutral[row].sum() / rm.sum() > 0.6:
                    drop[row] |= dark_neutral[row]

            # safety: never strip more than a third of the figure
            if drop.sum() <= 0.34 * m.sum():
                out[reg][drop] = KEY
                removed += int(drop.sum())
    return out, removed


def leg_spread(cell_mask):
    ys, xs = np.where(cell_mask)
    if len(xs) < 10:
        return 0.0
    lo = ys.min() + int((ys.max() - ys.min()) * 0.62)
    band = cell_mask[lo:]
    bx = np.where(band.any(0))[0]
    return float(bx.max() - bx.min()) if len(bx) else 0.0


def trim_locomotion(a):
    sprite = key_mask(a)
    H, W = sprite.shape
    ncols = est_cols(sprite)
    d = 2                                            # SE reference row
    y0, y1 = int(round(d * H / 6)), int(round((d + 1) * H / 6))
    spreads = []
    for c in range(ncols):
        x0, x1 = int(round(c * W / ncols)), int(round((c + 1) * W / ncols))
        spreads.append(leg_spread(sprite[y0:y1, x0:x1]))
    if not spreads or max(spreads) == 0:
        return a, (0, ncols)
    rest = min(s for s in spreads if s > 0)
    thr = rest * 1.22                       # only the clearly-legs-together ones
    keep_min = max(6, ncols - 3)            # never cut a cycle below 6 frames
    lo = 0
    while lo < ncols - keep_min and spreads[lo] <= thr:
        lo += 1
    hi = ncols
    while hi > lo + keep_min and spreads[hi - 1] <= thr:
        hi -= 1
    if (lo, hi) == (0, ncols):
        return a, (0, ncols)
    keep = list(range(lo, hi))
    cw = round(W / ncols)
    new = np.full((H, cw * len(keep), 3), KEY, np.uint8)
    for d in range(6):
        yy0, yy1 = int(round(d * H / 6)), int(round((d + 1) * H / 6))
        for j, c in enumerate(keep):
            sx0 = int(round(c * W / ncols))
            src = a[yy0:yy1, sx0:sx0 + cw]
            new[yy0:yy1, j * cw:j * cw + src.shape[1]] = src
    return new, (lo, hi)


def main() -> int:
    dry = "--dry-run" in sys.argv
    for p in sorted(GRIDS.glob("*.png")):
        code = p.stem.upper()[:2]
        a = np.asarray(Image.open(p).convert("RGB")).copy()
        if "--strip-shadow" in sys.argv and code not in NO_SHADOW_SCRUB:
            a, removed = scrub_shadow(a)
            note = f"shadow -{removed}px"
        else:
            note = "shadow kept"
        if "--trim" in sys.argv and code in LOCOMOTION:
            a, (lo, hi) = trim_locomotion(a)
            note += f", trim [{lo}:{hi}]" if (lo, hi) != (0, a.shape[1]) else ", trim none"
        if not dry:
            Image.fromarray(a, "RGB").save(p)
        print(f"  {p.name:10s} {note}")
    print("done" + (" (dry run)" if dry else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
