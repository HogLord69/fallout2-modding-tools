#!/usr/bin/env python3
"""
pc_gallery.py - one HTML page showing every frame of the player sprite.

    python tools/pc_gallery.py            # male   (hmpcot) -> build/pc_gallery/hmpcot.html
    python tools/pc_gallery.py --female   # female (hfpcot) -> build/pc_gallery/hfpcot.html

Reads the authored FRMs in mod/data/art/critters (what deploy ships), or --dir. Each
animation gets a looping preview of all six directions and a sheet of every
frame: rows are directions 0-5 (NE, E, SE, SW, W, NW), columns are frames.
Where both a .FRM and split .FR0-.FR5 exist for one code, the .FRM is shown
(the engine loads the .frm name; art.cc builds "<base><c1><c2>.frm").
"""

from __future__ import annotations

import argparse
import base64
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from PIL import Image  # noqa: E402

from extract_pc_anims import (CODE_LABELS, compose_sheet, decode_frm_all_dirs,  # noqa: E402
                              decode_frx, load_palette, make_gif)
from foclib import GameIndex  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CRIT = ROOT / "mod" / "data" / "art" / "critters"
OUT = ROOT / "build" / "pc_gallery"
DIR_NAMES = ["NE", "E", "SE", "SW", "W", "NW"]
BG = (58, 54, 46, 255)


def load_anims(base: str, pal, crit: Path = CRIT):
    groups: dict[str, dict] = {}
    for p in sorted(crit.glob(f"{base}*")):
        stem, ext = p.stem.lower(), p.suffix.lower()
        if len(stem) != len(base) + 2:
            continue
        code = stem[-2:]
        g = groups.setdefault(code, {})
        if ext == ".frm":
            g["frm"] = p
        elif ext[:3] == ".fr" and ext[3:].isdigit():
            g[int(ext[3])] = p
    out = []
    for code in sorted(groups):
        g = groups[code]
        if "frm" in g:
            dirs, fpd = decode_frm_all_dirs(g["frm"].read_bytes(), pal)
            src = g["frm"].name
        else:
            dirs, fpd = {}, 0
            for d in range(6):
                if d in g:
                    one, fpd = decode_frx(g[d].read_bytes(), d, pal)
                    dirs.update(one)
            src = f"{base}{code.upper()}.FR0-5"
        out.append((code, src, dirs, fpd))
    return out


def png_uri(im: Image.Image) -> str:
    bg = Image.new("RGBA", im.size, BG)
    bg.alpha_composite(im)
    buf = io.BytesIO()
    bg.convert("RGB").save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def gif_uri(frames, fps=10) -> str:
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:],
                   duration=int(1000 / fps), loop=0, disposal=2)
    return "data:image/gif;base64," + base64.b64encode(buf.getvalue()).decode()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--female", action="store_true")
    ap.add_argument("--base", help="sprite name to show instead of hmpcot/hfpcot (e.g. nmengr)")
    ap.add_argument("--scale", type=int, default=2)
    ap.add_argument("--dir", type=Path, default=CRIT,
                    help="folder of FRMs to show (default: mod/data/art/critters)")
    ap.add_argument("--name", help="output file stem (default: the sprite base)")
    args = ap.parse_args()
    base = args.base or ("hfpcot" if args.female else "hmpcot")

    pal = load_palette(GameIndex(pristine=True))
    anims = load_anims(base, pal, args.dir)
    total = 0
    blocks = []
    for code, src, dirs, fpd in anims:
        sheet, meta = compose_sheet(dirs, args.scale, anchor="frame")
        if sheet is None:
            continue
        n = sum(len(v) for v in dirs.values())
        total += n
        gif = make_gif(dirs, args.scale) if fpd > 1 else None
        label = CODE_LABELS.get(code, "").replace("__", " / ").replace("_", " ")
        rows_lbl = "".join(f'<div style="height:{meta["cell_h"] * args.scale}px">{DIR_NAMES[d]}</div>'
                           for d in range(6))
        blocks.append(f"""
<section id="{code}">
  <h2>{code.upper()} <span>{label}</span></h2>
  <p class="meta">{src} &middot; {len(dirs)} direction(s) &middot; {fpd} frame(s) each &middot; {n} frames</p>
  {f'<img class="gif" src="{gif_uri(gif)}" alt="{code} animated">' if gif else ''}
  <div class="sheet"><div class="rows">{rows_lbl}</div><img src="{png_uri(sheet)}" alt="{code} frames"></div>
</section>""")
        print(f"  {code}: {n} frames")

    nav = " ".join(f'<a href="#{c}">{c.upper()}</a>' for c, *_ in anims)
    title = f"{'Female' if args.female else 'Male'} player sprite"
    html = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} frames</title>
<style>
  :root {{ --bg:#1f1d1a; --panel:#2a2723; --ink:#e8e2d4; --muted:#a79f8e; --accent:#d9b75a; }}
  body {{ margin:0; background:var(--bg); color:var(--ink); font:14px/1.4 system-ui, sans-serif; }}
  header {{ position:sticky; top:0; background:var(--bg); padding:12px 16px; border-bottom:1px solid #3a362f; z-index:1; }}
  h1 {{ margin:0 0 6px; font-size:18px; }}
  nav a {{ color:var(--accent); text-decoration:none; margin-right:6px; font-family:monospace; }}
  main {{ padding:8px 16px 40px; }}
  section {{ background:var(--panel); border-radius:6px; padding:12px; margin:14px 0; overflow-x:auto; }}
  h2 {{ margin:0; font-size:16px; font-family:monospace; }}
  h2 span {{ font-family:system-ui, sans-serif; color:var(--muted); font-weight:normal; margin-left:8px; }}
  .meta {{ color:var(--muted); margin:4px 0 8px; font-size:12px; }}
  img {{ image-rendering:pixelated; display:block; }}
  .gif {{ margin-bottom:8px; }}
  .sheet {{ display:flex; gap:6px; }}
  .rows div {{ display:flex; align-items:center; color:var(--muted); font-size:11px; font-family:monospace; }}
</style></head><body>
<header><h1>{title} ({base}): {len(blocks)} animations, {total} frames</h1><nav>{nav}</nav></header>
<main>{''.join(blocks)}</main>
</body></html>"""
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{args.name or base}.html"
    path.write_text(html, encoding="utf-8")
    print(f"{len(blocks)} animations, {total} frames -> {path} ({path.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
