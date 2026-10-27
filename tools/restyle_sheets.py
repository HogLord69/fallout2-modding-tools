#!/usr/bin/env python3
"""restyle_sheets.py - batch-restyle the vanilla PC animation sheets into the
colonist look with the Gemini image model, the same way the first grids were
made by hand in the Gemini app.

For each family it takes the vanilla sheet from build/pc_sheet/vanilla/families
(transparent), flattens it onto pure #00FF00, upscales it so the model has
enough pixels to work with, sends it with the restyle prompt, and writes the
result to art/pc_grids/<CODE>.png - exactly where replace_pc_from_ref.py looks.

Each result is gated before it is kept: the sheet must still key green, and
registering the vanilla silhouettes against it must reach --min-iou (the same
IoU the rebuild reports). A family that fails is retried --retries times, and
whatever is rejected lands in build/restyle/rejected/<CODE>_<n>.png so you can
look at what the model did.

Existing grids are skipped unless --overwrite; every kept grid is backed up to
build/restyle/backup/ first. Nothing touches the deployed FRMs - after this,
run replace_pc_from_ref.py and deploy.py as usual.

The API key comes from $GEMINI_API_KEY or a file named .gemini_key in the
project root (one line, no quotes). Never pass it on the command line.

Run:  python tools/restyle_sheets.py --list            # what would be done
      python tools/restyle_sheets.py --only AA,HC      # a trial batch first
      python tools/restyle_sheets.py --all --overwrite # the full redo
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
import requests
from foclib import GameIndex
from PIL import Image

import replace_pc_from_ref as R

ROOT = Path(__file__).resolve().parent.parent
# The model must be shown the SAME layout replace_pc_from_ref expects back:
# extract_pc_anims' compose_sheet (scale 2, pad 2, uniform cells). That is
# build/pc_anims/male - and it is what the hand-made grids were restyled from.
# The per-family exports under build/pc_sheet are a different, editing-friendly
# layout and must NOT be used here.
VAN_DIR = ROOT / "build" / "pc_anims" / "male"
GRID_DIR = ROOT / "art" / "pc_grids"
WORK = ROOT / "build" / "restyle"

MODEL = "gemini-2.5-flash-image"
ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent"
COST_PER_IMAGE = 0.039          # ~1290 output tokens at $30/1M; for reporting only

PROMPT = (
    "Give this character a dusty white t-shirt and brown pants. "
    "Remove the yellow numbers from his back."
)
# Appended to every prompt: the failures in the hand-made sheets were all
# layout damage, not style - clipped first columns, repainted backdrop, and a
# sheet that came back a different shape.
# NB: an earlier version said "restyle every pose identically", which the
# model read as "make every pose identical" - it returned one static pose
# repeated across all 12 columns. Say the opposite, loudly.
CONSTRAINTS = (
    " This is an animation sprite sheet: a grid where EVERY CELL IS A "
    "DIFFERENT FRAME of the animation, each with its own distinct body pose. "
    "Recolour only. Keep each frame's pose, limb positions and silhouette "
    "exactly as they are - the frames differ from one another and every one of "
    "those differences must survive. Do not copy one pose across the grid, do "
    "not average the poses, do not redraw the character in a new stance. "
    "Keep the same image size, grid layout and the position and scale of every "
    "figure. "
    "Keep the background the exact same pure green (#00FF00) and paint nothing "
    "onto it: no shadows, no outlines, no white pixels, nothing in the gaps "
    "between the legs."
)

UPSCALE_TO = 1024               # long edge sent to the model


def load_key() -> str:
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        f = ROOT / ".gemini_key"
        if f.exists():
            key = f.read_text(encoding="utf-8").strip()
    if not key:
        sys.exit("no API key: set GEMINI_API_KEY or put it in F:\\FOCMod\\.gemini_key")
    return key


def to_green(png: Path) -> bytes:
    """Vanilla family sheet (transparent) -> green-backed, upscaled PNG bytes."""
    im = Image.open(png).convert("RGBA")
    bg = Image.new("RGBA", im.size, (0, 255, 0, 255))
    bg.alpha_composite(im)
    im = bg.convert("RGB")
    f = UPSCALE_TO / max(im.size)
    if f > 1:
        im = im.resize((round(im.width * f), round(im.height * f)), Image.NEAREST)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def call_gemini(key: str, image_png: bytes, prompt: str, timeout: int) -> bytes | None:
    body = {
        "contents": [{"parts": [
            {"text": prompt},
            {"inline_data": {"mime_type": "image/png",
                             "data": base64.b64encode(image_png).decode()}},
        ]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }
    r = requests.post(ENDPOINT.format(m=MODEL), params={"key": key},
                      json=body, timeout=timeout)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")
    data = r.json()
    for cand in data.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            inline = part.get("inline_data") or part.get("inlineData")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"])
    return None                  # model replied with text instead of an image


def check(code: str, png_bytes: bytes, van: bytes, table, levels, min_iou: float,
          min_floor: float = 0.40):
    """-> (ok, note). Keys green, then registers the vanilla frames against it."""
    tmp = WORK / "_check.png"
    tmp.write_bytes(png_bytes)
    try:
        im = Image.open(tmp).convert("RGB")
    except Exception as e:
        return False, f"unreadable ({e})"
    a = np.asarray(im, int)
    g = (a[..., 1] > 135) & (a[..., 1] - a[..., 0] > 30) & (a[..., 1] - a[..., 2] > 30)
    frac = g.mean()
    if not 0.25 < frac < 0.97:
        return False, f"green background {frac:.0%} of the image"
    notes = []
    try:
        sheet = R.GreenSheet(tmp)
        _data, _meta, _out = R.build_family(code, van, sheet, table, levels,
                                            lambda s: notes.append(s.strip()))
    except Exception as e:
        return False, f"rebuild failed ({e!r})"
    note = notes[0] if notes else ""
    iou = float(note.split("iou mean ")[1].split()[0]) if "iou mean " in note else 0.0
    lo = float(note.split("min ")[1].split()[0]) if " min " in note else 0.0
    if iou < min_iou:
        return False, f"iou mean {iou:.2f} < {min_iou:.2f}"
    # a good mean hides dropped frames: HD passed at mean 0.70 with three
    # cells the model simply left empty (iou 0.00). Gate the worst cell too.
    if lo < min_floor:
        return False, f"iou min {lo:.2f} < {min_floor:.2f} (dropped/garbled frame)"
    return True, note


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma list of family codes")
    ap.add_argument("--all", action="store_true", help="every vanilla family")
    ap.add_argument("--overwrite", action="store_true",
                    help="restyle families that already have a grid (backed up first)")
    ap.add_argument("--list", action="store_true", help="show the plan and cost, do nothing")
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--min-iou", type=float, default=0.70)
    ap.add_argument("--min-floor", type=float, default=0.40,
                    help="reject if ANY single frame registers below this "
                         "(catches frames the model dropped)")
    ap.add_argument("--prompt", default=PROMPT)
    ap.add_argument("--no-constraints", action="store_true",
                    help="send the bare prompt, no layout constraints appended "
                         "(this is what the hand-made sheets used)")
    ap.add_argument("--tag", default="", help="suffix for rejected/ filenames, for A/B runs")
    ap.add_argument("--timeout", type=int, default=180)
    ap.add_argument("--sleep", type=float, default=1.5, help="pause between calls (rate limit)")
    ap.add_argument("--budget", type=float, default=15.0,
                    help="stop once this many dollars of images have been requested")
    args = ap.parse_args()

    # build/pc_anims/male/hmjmps_<code>_<label>.png -> {CODE: path}
    src_of = {p.stem.split("_")[1].upper(): p
              for p in sorted(VAN_DIR.glob("hmjmps_*.png")) if len(p.stem.split("_")) > 2}
    codes = sorted(src_of)
    if not codes:
        sys.exit(f"no vanilla sheets in {VAN_DIR} - run: "
                 f"python tools/extract_pc_anims.py")
    if args.only:
        want = {c.strip().upper() for c in args.only.split(",")}
        codes = [c for c in codes if c in want]
    elif not args.all and not args.list:
        sys.exit("pass --only CODES for a trial batch, or --all for every family")
    if not args.overwrite:
        codes = [c for c in codes if not (GRID_DIR / f"{c}.png").exists()]

    if args.list:
        print(f"{len(codes)} famil{'y' if len(codes) == 1 else 'ies'} to restyle: "
              f"{' '.join(codes)}")
        print(f"~${len(codes) * COST_PER_IMAGE:.2f} for one pass, "
              f"~${len(codes) * COST_PER_IMAGE * (1 + args.retries * 0.4):.2f} with retries")
        return 0

    key = load_key()
    gi = GameIndex()
    pal = R.load_8bit_palette(gi)
    table, levels = R.make_index_table(pal)
    (WORK / "rejected").mkdir(parents=True, exist_ok=True)
    (WORK / "backup").mkdir(parents=True, exist_ok=True)

    spent = 0.0
    ok_list, fail_list = [], []
    for n, code in enumerate(codes, 1):
        van_png = src_of[code]
        try:
            van = gi.vfs.read(f"art\\critters\\HMJMPS{code}.FRM")
        except Exception:
            print(f"[{n}/{len(codes)}] {code}: no vanilla .FRM (split family) - skipped")
            continue
        src = to_green(van_png)
        print(f"[{n}/{len(codes)}] {code}: ", end="", flush=True)
        kept = False
        for attempt in range(1, args.retries + 2):
            if spent + COST_PER_IMAGE > args.budget:
                print(f"\nbudget ${args.budget:.2f} reached - stopping")
                codes = codes[:n]
                break
            try:
                full = args.prompt if args.no_constraints else args.prompt + CONSTRAINTS
                out = call_gemini(key, src, full, args.timeout)
                spent += COST_PER_IMAGE
            except Exception as e:
                print(f"\n    attempt {attempt}: {e}")
                time.sleep(5 * attempt)
                continue
            if out is None:
                print(f"\n    attempt {attempt}: model returned no image")
                continue
            good, note = check(code, out, van, table, levels, args.min_iou, args.min_floor)
            if good:
                dst = GRID_DIR / f"{code}.png"
                if dst.exists():
                    (WORK / "backup" / f"{code}.png").write_bytes(dst.read_bytes())
                dst.write_bytes(out)
                print(f"kept  ({note})")
                ok_list.append(code)
                kept = True
                break
            (WORK / "rejected" / f"{code}{args.tag}_{attempt}.png").write_bytes(out)
            print(f"\n    attempt {attempt} rejected: {note}")
            time.sleep(args.sleep)
        if not kept:
            fail_list.append(code)
            print(f"    {code}: kept nothing, existing grid untouched")
        time.sleep(args.sleep)

    (WORK / "last_run.json").write_text(json.dumps(
        {"kept": ok_list, "failed": fail_list, "approx_cost_usd": round(spent, 2),
         "prompt": args.prompt}, indent=1))
    print(f"\nkept {len(ok_list)}, failed {len(fail_list)}"
          f"{': ' + ' '.join(fail_list) if fail_list else ''}")
    print(f"~${spent:.2f} of images requested")
    if ok_list:
        print(f"next: python tools/replace_pc_from_ref.py --preview && python tools/deploy.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
