#!/usr/bin/env python3
"""identify_sheet.py - work out which animation family a restyled sheet is,
and file it under the right code.

Restyled sheets come back with no filename worth trusting, so guessing from the
grid aspect ratio is not enough - several families sit within 0.01 of each
other (AA vs BN vs KE). This matches on the thing that actually differs: the
SILHOUETTES. The restyled sheet is chroma-keyed to a mask, scaled onto each
candidate family's grid, and scored by mask IoU against that family's vanilla
sheet. The poses only line up for the family it really is.

Run:  python tools/identify_sheet.py <image> [<image> ...]        # report only
      python tools/identify_sheet.py --apply <image> [...]        # also file it
      python tools/identify_sheet.py --apply --inbox              # do the pasted-image folder
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
DROP = Path.home() / "OneDrive" / "Desktop" / "Restyled_DropHere"
INBOX = ROOT.parent / "AppData"  # overridden by --inbox-dir
MANIFEST = ROOT / "build" / "pc_anims" / "male" / "_manifest.json"

ASPECT_WINDOW = 0.06        # prefilter: only score families within this of the aspect
TOP = 3                     # how many candidates to report


def backdrop(a: np.ndarray) -> np.ndarray:
    """Median colour of the four corners - always backdrop on these sheets."""
    c = np.concatenate([a[:12, :12].reshape(-1, 3), a[:12, -12:].reshape(-1, 3),
                        a[-12:, :12].reshape(-1, 3), a[-12:, -12:].reshape(-1, 3)])
    return np.median(c, 0)


def key_mask(img: Image.Image) -> np.ndarray:
    """True where the sprite is, False on the backdrop.

    Not every restyled sheet comes back on pure #00FF00 - some land on a muted
    green like RGB(92,150,81). A fixed threshold either misses those or, worse,
    starts biting into olive trousers. So key on distance from the measured
    corner colour instead, and keep the green-dominance test only as a guard
    for sheets whose backdrop really is saturated.
    """
    a = np.asarray(img.convert("RGB"), np.int32)
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    bg = backdrop(a)
    if bg[1] > 200 and bg[1] - bg[0] > 120 and bg[1] - bg[2] > 120:
        # proper #00FF00 sheet: green-dominance is sharper than any distance
        # threshold, and measurably so (AQ scored 0.902 this way vs 0.785).
        return ~((g > 135) & (g - r > 30) & (g - b > 30))
    # off-colour backdrop (seen: RGB(92,150,81)) - fall back to distance
    return np.sqrt(((a - bg) ** 2).sum(-1)) > 48


def van_mask(p: Path) -> np.ndarray:
    return np.asarray(Image.open(p).convert("RGBA"))[..., 3] > 128


def score(sheet: np.ndarray, van: np.ndarray) -> float:
    """Mask IoU after putting the sheet on the vanilla sheet's exact grid."""
    h, w = van.shape
    m = np.asarray(Image.fromarray(sheet.astype(np.uint8) * 255)
                   .resize((w, h), Image.BILINEAR)) > 127
    inter = np.logical_and(m, van).sum()
    union = np.logical_or(m, van).sum()
    return float(inter) / float(union) if union else 0.0


def identify(path: Path, labels: dict):
    img = Image.open(path)
    ar = img.width / img.height
    sheet = key_mask(img)
    if sheet.mean() > 0.95:
        return None, [], "no green backdrop detected - is this a keyed sheet?"

    rows = []
    # full families, plus the halves of any family that was split for restyling
    # (a half-sheet cannot match its own full family, so it needs its own ref)
    cands = list(VAN.glob("*.json")) + list((VAN / "_parts").glob("*.json"))
    for js in sorted(cands):
        if js.stem.endswith("_plan"):
            continue
        code = js.stem.upper()
        meta = json.loads(js.read_text())
        exp = (meta["cell_w"] * meta["frames_per_dir"]) / (meta["cell_h"] * 6)
        if abs(exp - ar) > ASPECT_WINDOW:
            continue
        png = js.with_suffix(".png")
        if not png.exists():
            continue
        rows.append((score(sheet, van_mask(png)), code, meta["frames_per_dir"]))
    rows.sort(reverse=True)
    if not rows:
        return None, [], f"no family within {ASPECT_WINDOW} of aspect {ar:.3f}"
    best = rows[0]
    margin = best[0] - rows[1][0] if len(rows) > 1 else best[0]
    note = f"iou {best[0]:.3f}, next best {rows[1][1] if len(rows)>1 else '-'} " \
           f"by {margin:.3f}"
    if best[0] < 0.45:
        note += "  [LOW - check by eye]"
    elif margin < 0.04:
        note += "  [CLOSE CALL - check by eye]"
    return best[1], rows[:TOP], note


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="*", type=Path)
    ap.add_argument("--inbox-dir", type=Path,
                    help="folder of pasted images to identify (e.g. the session images dir)")
    ap.add_argument("--apply", action="store_true", help="copy into the drop folder as <CODE>.png")
    args = ap.parse_args()

    paths = list(args.images)
    if args.inbox_dir:
        paths += [p for p in sorted(args.inbox_dir.iterdir())
                  if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
    if not paths:
        sys.exit("give me image paths, or --inbox-dir <folder>")

    labels = {i["code"].upper(): i["label"] for i in json.loads(MANIFEST.read_text())}
    DROP.mkdir(parents=True, exist_ok=True)

    for p in paths:
        code, top, note = identify(p, labels)
        print(f"\n{p.name}  {Image.open(p).size}")
        for s, c, f in top:
            mark = "->" if c == code else "  "
            print(f"  {mark} {c}  {labels.get(c,'?'):32} {f:2}f  iou {s:.3f}")
        print(f"     {note}")
        if args.apply and code:
            dst = DROP / f"{code}.png"
            Image.open(p).convert("RGB").save(dst)
            print(f"     saved -> {dst.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
