#!/usr/bin/env python3
"""pc_sheet.py - dump every frame of the deployed PC model (hmpcot*) onto one
transparent sprite sheet.

Every animation family (the 6-direction .FRM ones and the .FR0-.FR5 split
death poses) becomes a block of 6 rows (directions NE E SE SW W NW) x fpd
columns. Blocks are packed left-to-right into bands no wider than --width.
Each block's cells are that family's largest frame (a few families - the
explosion deaths, the called-shot portrait - are 200+ px and would blow up a
uniform cell); every frame sits on its cell's feet anchor (bottom-centre) and
all blocks share the same pixel scale, so frames compare across families
exactly as the engine draws them.

Writes build/pc_sheet/hmpcot_sheet.png (clean, transparent, no labels),
hmpcot_sheet_labeled.png (family code + label per block) and
hmpcot_sheet.json (where each block/frame is).

--split additionally writes build/pc_sheet/families/<CODE>.png + .json, one
editable sheet per family (6 rows x frames, uniform cells, fixed feet anchor).
Edit those in any image editor, then `python tools/pc_import.py` turns them
back into hmpcot/hfpcot FRMs.

--source vanilla does all of the above for the UNMODDED HMJMPS frames from
critter.dat (blue vault suit), under build/pc_sheet/vanilla/ - the reference
to paint over for families that have no restyled sheet yet. An edited vanilla
family imports with `pc_import.py --dir build/pc_sheet/vanilla/families CODE`.

Run:  python tools/pc_sheet.py [--scale 1] [--width 4096] [--grids-only] [--split] [--source vanilla]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from foclib import GameIndex
from PIL import Image, ImageDraw

import replace_pc_from_ref as R

ROOT = Path(__file__).resolve().parent.parent
CRIT_DIR = ROOT / "mod" / "data" / "art" / "critters"
OUT_DIR = ROOT / "build" / "pc_sheet"
MANIFEST = ROOT / "build" / "pc_anims" / "male" / "_manifest.json"


def vanilla_files(gi):
    """(name, bytes) for every HMJMPS* member of the unmodded critter.dat."""
    import subprocess
    listing = subprocess.run([str(ROOT / "tools" / "dat" / "dat2.exe"), "l",
                              str(ROOT / "base" / "critter.dat")],
                             capture_output=True, text=True).stdout
    names = sorted({line.strip().split("\\")[-1].strip().upper()
                    for line in listing.splitlines() if "\\" in line})
    for n in names:
        if n.startswith("HMJMPS"):
            yield "hmpcot" + n[6:], gi.vfs.read("art\\critters\\" + n)


def load_families(grids_only: bool, with_meta: bool = False, source: str = "mod", gi=None):
    """code -> {d: [Frame]} for every family. source="mod" reads the deployed
    hmpcot* files, "vanilla" the unmodded HMJMPS* from critter.dat. With
    `with_meta` also returns code -> {d: header meta} (one per file: a .FRM
    shares one header across directions, a split family has one per .FRn)."""
    fams: dict[str, dict[int, list]] = {}
    metas: dict[str, dict[int, dict]] = {}
    splits: set[str] = set()
    grids = {p.stem.upper()[:2] for p in (ROOT / "art" / "pc_grids").glob("*.png")}
    if source == "vanilla":
        items = list(vanilla_files(gi))
    else:
        items = [(p.name, p.read_bytes()) for p in sorted(CRIT_DIR.glob("hmpcot*"))]
    for name, data in items:
        suffix = name[6:].upper()
        code, ext = suffix[:2], suffix[2:]
        if grids_only and code not in grids:
            continue
        m = R.decode_frm(data)
        hdr = {k: m[k] for k in ("version", "fps", "action", "fpd", "xo", "yo")}
        if ext == ".FRM":
            fams[code] = m["frames"]
            metas[code] = {d: hdr for d in range(6)}
        elif ext.startswith(".FR") and ext[-1].isdigit():
            fams.setdefault(code, {})[int(ext[-1])] = m["frames"].get(0, [])
            metas.setdefault(code, {})[int(ext[-1])] = hdr
            splits.add(code)
    return (fams, metas, splits) if with_meta else fams


# headroom around the largest frame so an editor can paint a little outside
# the current silhouette; pc_import.py re-derives each frame's box from the
# painted pixels, so this is purely working room
EDIT_PAD_X, EDIT_PAD_Y = 6, 6


def export_families(fams, metas, splits, labels, pal, out_dir: Path, scale: int):
    """One transparent PNG + JSON per family, for hand editing. Layout: 6 rows
    (dir 0..5) x fpd columns of uniform cells; every frame's feet anchor is at
    (cell_w // 2, cell_h - 1 - EDIT_PAD_Y) of its cell."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for code, f in fams.items():
        fpd = max((len(r) for r in f.values()), default=0)
        if not fpd:
            continue
        cw = max(fr.w for r in f.values() for fr in r) + 2 * EDIT_PAD_X
        ch = max(fr.h for r in f.values() for fr in r) + 2 * EDIT_PAD_Y
        ax, ay = cw // 2, ch - 1 - EDIT_PAD_Y
        sheet = Image.new("RGBA", (cw * fpd * scale, ch * 6 * scale), (0, 0, 0, 0))
        frames = {}
        for d in range(6):
            for i, fr in enumerate(f.get(d, [])):
                im = R.render_frame(fr.px, fr.w, fr.h, pal)
                if scale != 1:
                    im = im.resize((fr.w * scale, fr.h * scale), Image.NEAREST)
                x = i * cw + ax - fr.w // 2
                y = d * ch + ay - fr.h + 1
                sheet.alpha_composite(im, (x * scale, y * scale))
                frames[f"{d},{i}"] = {"w": fr.w, "h": fr.h, "sx": fr.sx, "sy": fr.sy}
        sheet.save(out_dir / f"{code}.png")
        (out_dir / f"{code}.json").write_text(json.dumps({
            "code": code, "label": labels.get(code, ""), "scale": scale,
            "split": code in splits,
            "cell_w": cw, "cell_h": ch, "anchor_x": ax, "anchor_y": ay,
            "frames_per_dir": fpd, "dirs": sorted(f),
            "header": {str(d): metas[code][d] for d in sorted(metas[code])},
            "frames": frames,
        }, indent=1))
    print(f"exported {len(fams)} families -> {out_dir}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scale", type=int, default=1)
    ap.add_argument("--width", type=int, default=4096, help="max sheet width (px, pre-scale)")
    ap.add_argument("--grids-only", action="store_true",
                    help="only families built from art/pc_grids (skip placeholders)")
    ap.add_argument("--split", action="store_true",
                    help="also write one editable PNG+JSON per family to build/pc_sheet/families/")
    ap.add_argument("--source", choices=["mod", "vanilla"], default="mod",
                    help="mod = deployed hmpcot (default); vanilla = unmodded HMJMPS from "
                         "critter.dat, written under build/pc_sheet/vanilla/")
    args = ap.parse_args()
    out_dir = OUT_DIR / "vanilla" if args.source == "vanilla" else OUT_DIR

    gi = GameIndex()
    pal = R.load_8bit_palette(gi)
    labels = {}
    if MANIFEST.exists():
        labels = {it["code"].upper(): it["label"] for it in json.loads(MANIFEST.read_text())}

    fams, metas, splits = load_families(args.grids_only, with_meta=True, source=args.source, gi=gi)
    if not fams:
        print("no source FRMs found"); return 1
    if args.split:
        export_families(fams, metas, splits, labels, pal, out_dir / "families", args.scale)
    cell = {c: (max(fr.w for r in f.values() for fr in r) + 2,
                max(fr.h for r in f.values() for fr in r) + 2) for c, f in fams.items()}
    pad = 4                                    # gap between blocks

    # pack blocks into bands
    bands, cur, x = [], [], 0
    for code, f in fams.items():
        fpd = max((len(r) for r in f.values()), default=0)
        bw = fpd * cell[code][0]
        if cur and x + bw > args.width:
            bands.append(cur); cur, x = [], 0
        cur.append((code, x, fpd)); x += bw + pad
    if cur:
        bands.append(cur)
    W = max(b[-1][1] + b[-1][2] * cell[b[-1][0]][0] for b in bands)
    band_h = [max(6 * cell[c][1] for c, _, _ in b) for b in bands]
    H = sum(band_h) + pad * (len(bands) - 1)
    s = args.scale
    sheet = Image.new("RGBA", (W * s, H * s), (0, 0, 0, 0))
    legend = {"scale": s, "anchor": "bottom-centre of cell",
              "rows": "6 per block: dir 0..5 = NE E SE SW W NW", "blocks": []}
    y0 = 0
    for bi, band in enumerate(bands):
        if bi:
            y0 += band_h[bi - 1] + pad
        for code, x0, fpd in band:
            f = fams[code]
            cw, ch = cell[code]
            for d in range(6):
                for i, fr in enumerate(f.get(d, [])):
                    im = R.render_frame(fr.px, fr.w, fr.h, pal)
                    if s != 1:
                        im = im.resize((fr.w * s, fr.h * s), Image.NEAREST)
                    ax = x0 + i * cw + cw // 2
                    ay = y0 + (d + 1) * ch - 1
                    sheet.alpha_composite(im, ((ax - fr.w // 2) * s, (ay - fr.h + 1) * s))
            legend["blocks"].append({"code": code, "label": labels.get(code, ""),
                                     "x": x0, "y": y0, "cell_w": cw, "cell_h": ch,
                                     "frames_per_dir": fpd, "dirs": sorted(f)})
    out_dir.mkdir(parents=True, exist_ok=True)
    sheet.save(out_dir / "hmpcot_sheet.png")
    (out_dir / "hmpcot_sheet.json").write_text(json.dumps(legend, indent=1))

    lab = sheet.copy()
    dr = ImageDraw.Draw(lab)
    for b in legend["blocks"]:
        dr.rectangle([b["x"] * s, b["y"] * s, (b["x"] + b["frames_per_dir"] * b["cell_w"]) * s - 1,
                      (b["y"] + 6 * b["cell_h"]) * s - 1], outline=(255, 255, 0, 160))
        dr.text((b["x"] * s + 2, b["y"] * s + 1), f"{b['code']} {b['label']}",
                fill=(255, 255, 0, 255))
    lab.save(out_dir / "hmpcot_sheet_labeled.png")
    print(f"{len(fams)} families, sheet {sheet.size[0]}x{sheet.size[1]} "
          f"-> {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
