#!/usr/bin/env python3
"""split_sheet.py - cut a wide animation sheet into column-groups for restyling,
and glue the restyled pieces back together.

Some families are very wide: AR kick is 17 frames (2.4:1), BD big_hole is 22
(3.8:1). Fed to an image model whole, each sprite occupies so few pixels that
the result comes back soft, and the backdrop drifts off pure #00FF00. Splitting
into vertical groups gives every part roughly the proportions of AA (~1.2:1),
so the sprites get a sensible share of the canvas.

The cut always lands on a cell boundary and every part keeps all six direction
rows, so the pieces stay independently meaningful and rejoin exactly.

  split:  python tools/split_sheet.py split AR            # auto part count
          python tools/split_sheet.py split BD --parts 3
  join:   python tools/split_sheet.py join AR             # from the parts folder

Parts are written to / read from Desktop\\Sheet_Parts\\<CODE>_<n>of<N>.png.
A joined sheet lands in Desktop\\Restyled_DropHere\\<CODE>.png, ready to be
identified and imported like any other.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
VAN = Path.home() / "OneDrive" / "Desktop" / "Vanilla Sprite Families"
GREEN = VAN / "_green_for_gemini"
PARTS = Path.home() / "OneDrive" / "Desktop" / "Sheet_Parts"
DROP = Path.home() / "OneDrive" / "Desktop" / "Restyled_DropHere"

TARGET_ASPECT = 1.35        # aim each part near AA's 1.16, allowing some slack
WORK_SCALE = 2              # parts are emitted at 2x so the model has pixels


def layout(code: str) -> dict:
    return json.loads((VAN / f"{code}.json").read_text())


def plan(meta: dict, parts: int | None) -> list[tuple[int, int]]:
    """-> [(first_col, last_col_exclusive)] split as evenly as possible."""
    fpd = meta["frames_per_dir"]
    if parts is None:
        ar = (meta["cell_w"] * fpd) / (meta["cell_h"] * 6)
        parts = max(1, round(ar / TARGET_ASPECT))
    parts = max(1, min(parts, fpd))
    edges = [round(i * fpd / parts) for i in range(parts + 1)]
    return [(edges[i], edges[i + 1]) for i in range(parts)]


PARTREF = VAN / "_parts"          # transparent part masks, for identification


def do_split(code: str, parts: int | None, inplace: bool = False) -> int:
    """Cut <CODE> into column groups.

    inplace=True replaces the wide sheet in _green_for_gemini with its parts,
    so the folder can just be worked through in order. A transparent copy of
    each part goes to _parts/ so identify_sheet.py can recognise a restyled
    half on its own - a half-sheet will not match the full family.
    """
    meta = layout(code)
    src = GREEN / f"{code}.png"
    if not src.exists():
        sys.exit(f"no green sheet for {code} at {src}")
    img = Image.open(src).convert("RGB")
    van = Image.open(VAN / f"{code}.png").convert("RGBA")
    cw, ch, fpd = meta["cell_w"], meta["cell_h"], meta["frames_per_dir"]
    sx = img.width / (cw * fpd)
    groups = plan(meta, parts)
    if len(groups) < 2:
        return 1
    dst = GREEN if inplace else PARTS
    dst.mkdir(parents=True, exist_ok=True)
    PARTREF.mkdir(parents=True, exist_ok=True)
    for i, (a, b) in enumerate(groups, 1):
        name = f"{code}_{i}of{len(groups)}"
        box = (round(a * cw * sx), 0, round(b * cw * sx), img.height)
        part = img.crop(box)
        part = part.resize((part.width * WORK_SCALE, part.height * WORK_SCALE), Image.NEAREST)
        part.save(dst / f"{name}.png")
        # transparent reference at 1:1, plus a layout json mirroring a family
        vbox = (a * cw, 0, b * cw, ch * 6)
        van.crop(vbox).save(PARTREF / f"{name}.png")
        pm = dict(meta)
        pm.update(code=name, frames_per_dir=b - a,
                  frames={k: v for k, v in meta["frames"].items()
                          if a <= int(k.split(",")[1]) < b})
        (PARTREF / f"{name}.json").write_text(json.dumps(pm, indent=1))
        print(f"  {name}.png  frames {a}-{b-1}  {part.size}  "
              f"aspect {part.width/part.height:.2f}")
    (PARTREF / f"{code}_plan.json").write_text(json.dumps(
        {"code": code, "groups": groups, "cell_w": cw, "cell_h": ch,
         "frames_per_dir": fpd, "scale": WORK_SCALE}, indent=1))
    if inplace:
        src.unlink()
    return len(groups)


def find_part(name: str) -> Path | None:
    """Restyled parts land in the drop folder; Windows casing varies."""
    for d in (DROP, PARTS):
        for p in d.glob("*.png"):
            if p.stem.lower() == name.lower():
                return p
    return None


def do_join(code: str) -> None:
    planf = PARTREF / f"{code}_plan.json"
    if not planf.exists():
        planf = PARTS / f"{code}_plan.json"
    if not planf.exists():
        sys.exit(f"no split plan for {code}; run 'split' first")
    p = json.loads(planf.read_text())
    groups, cw, ch = p["groups"], p["cell_w"], p["cell_h"]
    S = p["scale"]
    H = ch * 6 * S
    canvas = Image.new("RGB", (cw * p["frames_per_dir"] * S, H), (0, 255, 0))
    for i, (a, b) in enumerate(groups, 1):
        f = find_part(f"{code}_{i}of{len(groups)}")
        if f is None:
            sys.exit(f"missing restyled part: {code}_{i}of{len(groups)}.png "
                     f"(looked in {DROP} and {PARTS})")
        want = ((b - a) * cw * S, H)
        im = Image.open(f).convert("RGB")
        if im.size != want:
            im = im.resize(want, Image.LANCZOS)
        canvas.paste(im, (a * cw * S, 0))
        print(f"  placed {f.name}  frames {a}-{b-1}")
    DROP.mkdir(parents=True, exist_ok=True)
    out = DROP / f"{code}.png"
    canvas.save(out)
    print(f"joined -> {out}  {canvas.size}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["split", "join", "splitall"])
    ap.add_argument("code", nargs="?")
    ap.add_argument("--parts", type=int)
    ap.add_argument("--inplace", action="store_true",
                    help="replace the wide sheet in _green_for_gemini with its parts")
    a = ap.parse_args()
    if a.action == "splitall":
        import json as _j
        done = []
        for j in sorted(VAN.glob("*.json")):
            c = j.stem.upper()
            if not (GREEN / f"{c}.png").exists():
                continue
            m = _j.loads(j.read_text())
            if len(plan(m, None)) < 2:
                continue
            print(f"{c}:")
            n = do_split(c, None, inplace=True)
            done.append((c, n))
        print("")
        print(f"split {len(done)} wide famil{'y' if len(done) == 1 else 'ies'}: "
              + " ".join(f"{c}x{n}" for c, n in done))
        return 0
    code = a.code.upper()
    if a.action == "split":
        n = do_split(code, a.parts, inplace=a.inplace)
        print(f"\n{n} part(s) in {PARTS}")
        print("restyle each one, save it back over the SAME filename, then:")
        print(f"  python tools/split_sheet.py join {code}")
    else:
        do_join(code)
    return 0


if __name__ == "__main__":
    sys.exit(main())
