#!/usr/bin/env python3
"""pc_import.py - turn hand-edited per-family sheets back into PC FRMs.

Input: build/pc_sheet/families/<CODE>.png + <CODE>.json as written by
`pc_sheet.py --split` (edit the PNG in place; the JSON is the layout).

Per cell (6 rows = directions, columns = frames) the painted pixels
(alpha >= 128) are boxed around the cell's fixed feet anchor: the frame is
as wide as needed either side of the anchor and reaches from the topmost
pixel down to the anchor row, so the engine's centred, bottom-anchored blit
lands the feet exactly where they were. Per-frame offsets and the FRM header
are carried over from the JSON untouched. Colours are quantized to color.pal
as-is (no darkening - an exported sheet is already at game value).

Anything painted BELOW the anchor row is clipped (reported); paint above it.

Writes mod/data/art/critters/hmpcot<CODE>.FRM (or .FR0-.FR5 for a split
family) and the hfpcot copy. Then run tools/deploy.py.

Run:  python tools/pc_import.py                 # every PNG in the folder
      python tools/pc_import.py AA HC           # just these families
      python tools/pc_import.py --dir path/to/edited/sheets
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from foclib import GameIndex
from PIL import Image

import replace_pc_from_ref as R

ROOT = Path(__file__).resolve().parent.parent
CRIT_DIR = ROOT / "mod" / "data" / "art" / "critters"
FAM_DIR = ROOT / "build" / "pc_sheet" / "families"


def key_green(img: Image.Image) -> Image.Image:
    """Chroma-key a #00FF00 backdrop to alpha, and un-mix the green spill.

    A sheet that has been round-tripped through an image model comes back
    green-backed rather than transparent, often JPEG-compressed and rescaled.
    Edge pixels are a linear blend of sprite and key, so coverage is recovered
    as 1 - k/255 and the key colour is divided back out; without that un-mix
    every silhouette keeps a bright green rim after quantization.
    """
    a = np.asarray(img.convert("RGB"), np.float32)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    k = np.clip(g - np.maximum(r, b), 20, 255)
    cov = np.clip((255 - k) / (255 - 20), 0, 1)
    key = np.array([0, 255, 0], np.float32)
    s = np.clip((a - (1 - cov)[..., None] * key) / np.maximum(cov, 1e-3)[..., None], 0, 255)
    s[cov < 0.02] = 0
    # A JPEG-compressed sheet smears the key several px into the figure, and
    # un-mixing a barely-covered pixel amplifies that noise rather than fixing
    # it. Treat anything under ~70% covered as backdrop, then erode one pixel,
    # which removes the contaminated rim entirely.
    solid = cov >= 0.70
    er = solid.copy()
    er[1:, :] &= solid[:-1, :]; er[:-1, :] &= solid[1:, :]
    er[:, 1:] &= solid[:, :-1]; er[:, :-1] &= solid[:, 1:]
    out = np.dstack([s.astype(np.uint8), np.where(er, 255, 0).astype(np.uint8)])
    return Image.fromarray(out, "RGBA")


def import_family(png: Path, meta: dict, table, levels,
                  green: bool = False) -> tuple[dict[int, bytes], list[str]]:
    """-> {suffix: frm bytes}, warnings."""
    s = meta["scale"]
    img = Image.open(png)
    if green:
        img = key_green(img)
        # a restyled sheet often comes back rescaled; the layout in `meta` is
        # in original pixels, so put it back on that grid before slicing
        want = (meta["cell_w"] * meta["frames_per_dir"] * s, meta["cell_h"] * 6 * s)
        if img.size != want:
            img = img.resize(want, Image.LANCZOS)
    img = img.convert("RGBA")
    if s != 1:
        img = img.resize((img.width // s, img.height // s), Image.NEAREST)
    a = np.asarray(img)
    rgb, alpha = a[..., :3].copy(), a[..., 3] >= 128
    cw, ch, ax, ay = meta["cell_w"], meta["cell_h"], meta["anchor_x"], meta["anchor_y"]
    fpd = meta["frames_per_dir"]
    warn = []
    out: dict[int, list] = {}
    for d in meta["dirs"]:
        row = []
        for i in range(fpd):
            key = f"{d},{i}"
            if key not in meta["frames"]:
                continue
            x0, y0 = i * cw, d * ch
            cell_a = alpha[y0:y0 + ch, x0:x0 + cw]
            cell_rgb = rgb[y0:y0 + ch, x0:x0 + cw]
            below = cell_a[ay + 1:].sum()
            if below:
                warn.append(f"{meta['code']} d{d} f{i}: {below} px below the anchor row clipped")
            cell_a = cell_a.copy()
            cell_a[ay + 1:] = False
            ys, xs = np.nonzero(cell_a)
            fr = meta["frames"][key]
            if len(xs) == 0:                    # erased frame: 1x1 clear
                row.append((1, 1, fr["sx"], fr["sy"], b"\x00"))
                continue
            half = max(ax - xs.min(), xs.max() + 1 - ax, 1)
            w = 2 * half
            top = ys.min()
            h = ay - top + 1
            left = ax - w // 2
            box_a = np.zeros((h, w), bool)
            box_rgb = np.zeros((h, w, 3), np.uint8)
            sx0, sx1 = max(0, left), min(cw, left + w)
            box_a[:, sx0 - left:sx1 - left] = cell_a[top:ay + 1, sx0:sx1]
            box_rgb[:, sx0 - left:sx1 - left] = cell_rgb[top:ay + 1, sx0:sx1]
            px = R.quantize(box_rgb, box_a, table, levels, tone=False, drop_green=green)
            row.append((w, h, fr["sx"], fr["sy"], px))
        out[d] = row

    files = {}
    if meta["split"]:
        for d, row in out.items():
            hdr = meta["header"][str(d)]
            files[f".FR{d}"] = R.encode_frm(hdr, {0: row}, split=True)
    else:
        hdr = meta["header"]["0"]
        files[".FRM"] = R.encode_frm(hdr, out)
    return files, warn


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("codes", nargs="*", help="family codes (default: every PNG in --dir)")
    ap.add_argument("--dir", type=Path, default=FAM_DIR)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--green", action="store_true",
                    help="sheets are #00FF00-backed rather than transparent "
                         "(what comes back from a restyling pass)")
    ap.add_argument("--rules", type=Path,
                    help="BUILD_RULES.json: families to leave vanilla, and aliases")
    args = ap.parse_args()

    gi = GameIndex()
    pal = R.load_8bit_palette(gi)
    # chroma-keyed sheets must never resolve onto the palette's green ramp
    table, levels = R.make_index_table(pal, skip_green=args.green)
    R.set_exact_palette(pal)

    codes = [c.upper() for c in args.codes] or sorted(p.stem.upper() for p in args.dir.glob("*.png"))
    n = 0
    for code in codes:
        png, js = args.dir / f"{code}.png", args.dir / f"{code}.json"
        if not png.exists() or not js.exists():
            print(f"  {code}: missing {'PNG' if not png.exists() else 'JSON'} in {args.dir}")
            continue
        meta = json.loads(js.read_text())
        files, warn = import_family(png, meta, table, levels, green=args.green)
        for w in warn:
            print("  ! " + w)
        for ext, data in files.items():
            for prefix in ("hmpcot", "hfpcot"):
                if not args.dry_run:
                    (CRIT_DIR / f"{prefix}{code}{ext}").write_bytes(data)
            n += 1
        print(f"  {code}: {len(files)} file(s), {sum(len(v) for v in files.values())} bytes")
    print(f"{'would write' if args.dry_run else 'wrote'} {n} FRM(s) x2 (hmpcot + hfpcot). "
          f"Now: python tools/deploy.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
