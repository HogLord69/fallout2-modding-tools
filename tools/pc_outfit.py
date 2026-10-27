#!/usr/bin/env python3
"""
pc_outfit.py - dress the player sprites (hmpcot / hfpcot), built from Fallout:
Nevada's jumpsuit (hmjmps / hfjmps), in the owner's outfit (2026-09-28, after
the Gemini restyle references in Desktop/Green): a dusty yellow-white
short-sleeved T-shirt, olive-brown pants and a dark leather belt. Weapons,
hair, boots and skin stay exactly as Nevada drew them.

    python tools/pc_outfit.py --preview out.png    # before/after sheet, writes nothing
    python tools/pc_outfit.py                      # back up, replace, deploy

Palette-index changes only, on per-frame masks; no pixel moves, headers untouched.

WHICH PIXELS ARE SUIT. Nevada's suit, its guns and its outlines share the same
neutral greys, so colour alone cannot say. But Nevada's jumpsuit is vanilla's
vault suit repainted: in ~90% of the male frames (fewer female) the vanilla
HMJMPS/HFJMPS frame has exactly the same silhouette, and there the suit is
BLUE (and its trim yellow) while guns are grey. So where the vanilla frame
lines up, only pixels vanilla drew as suit are touched. Where it does not
(Nevada redrew the pistol, knife and a few stand/death animations), only suit
greys joined to the belt are touched; a gun held in a hand is a separate piece
(the hand is skin) and is left alone. The outline (black next to transparency)
never changes.

SHIRT / PANTS / BELT. A line through the belt splits the suit (see
pc_jumpsuit.belt_lines: RANSAC over the belt gold, followed frame to frame so
it tracks a falling body); the legs side is the pants, the rest the shirt.

SHORT SLEEVES. From each hand (a skin blob away from the face) the arm is
grown back along the shirt for FOREARM px, through thin parts only (not the
chest); that is bare forearm and becomes skin. The rest of the arm stays shirt.

PRINTS. The skull on the back, the red shoulder patch and the gold chest trim
are painted over from the surrounding shirt, so the T-shirt is plain.

COLOUR. Each part maps onto one palette ramp of a single hue (SHIRT_RAMP etc.)
by RANK within the frame, not raw brightness: Nevada draws the suit mid-grey
standing but near-black in the weapon animations, and a brightness mapping
made the shirt change shade between animations.
"""

from __future__ import annotations

import argparse
import colorsys
import datetime as dt
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
from scipy import ndimage  # noqa: E402

import port  # noqa: E402
from foclib import GameIndex  # noqa: E402
from pc_jumpsuit import (BELT_MARGIN, RANSAC_TOL, TOUCH, WEDGE, belt_lines,  # noqa: E402
                         file_dir_of, frames_of, load_pal, masks, nevada_files)

ROOT = port.ROOT
CRIT = ROOT / "mod" / "data" / "art" / "critters"
PAIRS = (("hmjmps", "hmpcot"), ("hfjmps", "hfpcot"))

# (ramp darkest first, rank -> brightness target)
SHIRT_RAMP = [77, 76, 120, 119, 222, 170, 169]          # dusty yellow-white, hue 30-39
SHIRT_TARGET = ([0, .12, .45, .85, 1], [72, 120, 178, 205, 226])
PANTS_RAMP = [207, 204, 78, 225, 77, 224, 223]          # olive-brown, hue 30-40
PANTS_TARGET = ([0, .15, .5, .85, 1], [20, 40, 50, 70, 92])
BELT_RAMP = [227, 226, 225, 206, 224, 203]              # dark leather
BELT_TARGET = ([0, .3, .7, 1], [17, 40, 60, 82])
SKIN_RAMP = [123, 122, 121, 173, 159, 172, 157, 143]    # Nevada's own hand/face tones
SKIN_TARGET = ([0, .2, .5, .85, 1], [74, 95, 124, 150, 172])

FOREARM = 9            # px of arm grown back from the hand that is bare skin
ARM_THIN = 2.6         # distance-to-edge above which a shirt pixel is chest, not arm
HAND_FROM_FACE = 9     # a skin blob this far from the face is a hand
MATCH_IOU = 0.97       # vanilla frame silhouette agreement to trust its suit pixels
PRINT_MIN_PX = 4
PRINT_LUM = 70
PRINT_GROW = 2
RED = [30, 31, 193, 194, 195]                           # the shoulder patch


def palette_masks(pal):
    suit, gold, skin = masks(pal)
    blue = np.zeros(256, bool)
    for i in range(1, 229):
        r, g, b = pal[i] / 255
        h, s, _v = colorsys.rgb_to_hsv(r, g, b)
        if 190 <= h * 360 <= 250 and s >= 0.3:
            blue[i] = True
    red = np.zeros(256, bool)
    red[RED] = True
    lum = pal.mean(1)
    neutral = (np.abs(pal[:, 0] - pal[:, 1]) <= 8) & (np.abs(pal[:, 1] - pal[:, 2]) <= 12)
    light = neutral & (lum >= PRINT_LUM)
    light[0] = False
    return dict(suit=suit, gold=gold, skin=skin, blue=blue, red=red, light=light, lum=lum)


def rank_map(vals: np.ndarray, ramp: list[int], target, lum) -> np.ndarray:
    """256-entry table sending each source index in `vals` to a ramp colour by
    its brightness rank among `vals` (ties share a rank; order is kept)."""
    table = np.arange(256, dtype=np.uint8)
    if vals.size == 0:
        return table
    idx, cnt = np.unique(vals, return_counts=True)
    order = np.argsort(lum[idx], kind="stable")
    idx, cnt = idx[order], cnt[order]
    cum = np.cumsum(cnt) - cnt / 2
    q = cum / cnt.sum()
    rlum = lum[ramp]
    floor = 0
    for i, qq in zip(idx, q):
        want = np.interp(qq, *target)
        k = max(int(np.abs(rlum - want).argmin()), floor)
        table[i], floor = ramp[k], k
    return table


def _coords(h, w, line):
    c, u, n, half = line
    yy, xx = np.mgrid[0:h, 0:w]
    P = np.stack([xx - w / 2, yy - h], -1).astype(float)
    return (P - c) @ n, np.abs((P - c) @ u), half


def dress(px: np.ndarray, vpx: np.ndarray | None, line, M) -> np.ndarray:
    h, w = px.shape
    body = px != 0
    outline = (px == 207) & ndimage.binary_dilation(~body, structure=np.ones((3, 3), bool))
    paintable = (M["suit"][px] | M["gold"][px] | M["red"][px]) & ~outline
    d, lat, half = _coords(h, w, line)
    belt = M["gold"][px] & (np.abs(d) <= RANSAC_TOL + 0.7) & (lat <= half + 0.5)

    if vpx is not None:
        allowed = paintable & (M["blue"][vpx] | M["gold"][vpx])
    else:
        # no vanilla frame to go by: the suit is what joins the belt
        lab, _n = ndimage.label(paintable, structure=np.ones((3, 3), bool))
        near = ndimage.binary_dilation(belt, iterations=TOUCH) if belt.any() else (np.abs(d) <= TOUCH) & (lat <= half)
        keep = np.unique(lab[near & paintable])
        allowed = np.isin(lab, keep[keep > 0])
    allowed |= belt

    pants = allowed & ~belt & (d > BELT_MARGIN) & (lat <= half + WEDGE * np.maximum(d, 0))
    torso = allowed & ~belt & ~pants

    # --- hands, and the bare forearm grown back from them
    skin = M["skin"][px] & body
    lab, n = ndimage.label(skin, structure=np.ones((3, 3), bool))
    forearm = np.zeros_like(torso)
    if n:
        cents = ndimage.center_of_mass(skin, lab, range(1, n + 1))
        sizes = ndimage.sum(skin, lab, range(1, n + 1))
        dd = [d[int(round(cy)), int(round(cx))] for cy, cx in cents]
        face = int(np.argmin(dd))                       # the most torso-side blob
        fy, fx = cents[face]
        hands = np.zeros_like(skin)
        for k, ((cy, cx), sz) in enumerate(zip(cents, sizes)):
            if k != face and sz >= 2 and np.hypot(cy - fy, cx - fx) >= HAND_FROM_FACE:
                hands |= lab == k + 1
        if hands.any():
            thin = ndimage.distance_transform_edt(torso | hands) <= ARM_THIN
            grow = torso & thin
            reach = hands.copy()
            for _ in range(FOREARM):
                reach |= ndimage.binary_dilation(reach, structure=np.ones((3, 3), bool)) & grow
            forearm = reach & torso
    shirt = torso & ~forearm

    # --- prints on the shirt: skull (light blobs inside the shirt), patch, trim
    prints = np.zeros_like(shirt)
    llab, ln = ndimage.label(M["light"][px] & shirt, structure=np.ones((3, 3), bool))
    for k in range(1, ln + 1):
        comp = llab == k
        if comp.sum() < PRINT_MIN_PX:
            continue
        ring = ndimage.binary_dilation(comp, structure=np.ones((3, 3), bool)) & ~comp
        if ring.any() and (shirt | forearm)[ring].mean() >= 0.5:
            prints |= comp
    if prints.any():
        prints = ndimage.binary_fill_holes(prints)
        prints = ndimage.binary_dilation(prints, structure=np.ones((3, 3), bool),
                                         iterations=PRINT_GROW) & shirt
    prints |= shirt & (M["red"][px] | M["gold"][px])

    lum = M["lum"]
    out = px.copy()
    base_shirt = shirt & ~prints
    out[base_shirt] = rank_map(px[base_shirt], SHIRT_RAMP, SHIRT_TARGET, lum)[px[base_shirt]]
    out[pants] = rank_map(px[pants], PANTS_RAMP, PANTS_TARGET, lum)[px[pants]]
    out[belt] = rank_map(px[belt], BELT_RAMP, BELT_TARGET, lum)[px[belt]]
    out[forearm] = rank_map(px[forearm], SKIN_RAMP, SKIN_TARGET, lum)[px[forearm]]
    if prints.any():
        out = _fill(out, prints, base_shirt, lum)
    return out


def _fill(out, holes, known, lum, radius=3):
    """Paint `holes` from the outside in with the shirt shade nearest the
    average brightness of the known shirt around each pixel."""
    h, w = out.shape
    res = out.copy()
    known = known.copy()
    todo = holes.copy()
    rl = lum[SHIRT_RAMP]
    for _ in range(40):
        if not todo.any():
            break
        done = []
        for y, x in zip(*np.nonzero(todo)):
            y0, y1 = max(0, y - radius), min(h, y + radius + 1)
            x0, x1 = max(0, x - radius), min(w, x + radius + 1)
            vals = res[y0:y1, x0:x1][known[y0:y1, x0:x1]]
            if vals.size:
                res[y, x] = SHIRT_RAMP[int(np.abs(rl - lum[vals].mean()).argmin())]
                done.append((y, x))
        if not done:
            # nothing known nearby: the plain shirt mid-tone
            res[todo] = SHIRT_RAMP[len(SHIRT_RAMP) // 2 + 1]
            break
        for y, x in done:
            known[y, x] = True
            todo[y, x] = False
    return res


# ------------------------------------------------------------------ files

class Vanilla:
    def __init__(self):
        gi = GameIndex(pristine=True)
        self.provs = [p for p in gi.vfs.providers
                      if p.label.lower().endswith(("critter.dat", "master.dat"))]

    def read(self, name: str) -> bytes | None:
        path = f"art\\critters\\{name}"
        for p in self.provs:
            try:
                if p.has(path):
                    return p.read(path)
            except Exception:
                pass
        return None


def _pxs(data: bytes, file_dir):
    return [[np.frombuffer(data[s:s + w * h], np.uint8).reshape(h, w) for s, w, h in frs]
            for _d, frs in frames_of(data, file_dir)]


def recolor(data: bytes, vdata: bytes | None, M, file_dir=None, stats=None) -> bytes:
    buf = bytearray(data)
    groups = frames_of(data, file_dir)
    vgroups = _pxs(vdata, file_dir) if vdata else []
    for g, (_d, frs) in enumerate(groups):
        pxs = [np.frombuffer(data[s:s + w * h], np.uint8).reshape(h, w) for s, w, h in frs]
        lines = belt_lines(pxs, M["gold"], M["skin"])
        vg = vgroups[g] if g < len(vgroups) else []
        for i, (px, (s, w, h)) in enumerate(zip(pxs, frs)):
            if stats is not None:
                stats["frames"] = stats.get("frames", 0) + 1
            if lines[i] is None:
                if stats is not None:
                    stats["skipped"] = stats.get("skipped", 0) + 1
                continue
            vpx = vg[i] if i < len(vg) else None
            if vpx is not None:
                ok = vpx.shape == px.shape
                if ok:
                    a, b = px != 0, vpx != 0
                    ok = (a & b).sum() / max((a | b).sum(), 1) >= MATCH_IOU
                if not ok:
                    vpx = None
            if stats is not None:
                stats["vanilla" if vpx is not None else "fallback"] = \
                    stats.get("vanilla" if vpx is not None else "fallback", 0) + 1
            out = dress(px, vpx, lines[i], M)
            buf[s:s + w * h] = out.astype(np.uint8).tobytes()
    return bytes(buf)


def preview(src, van, M, out: Path, codes=None) -> None:
    from PIL import Image, ImageDraw
    from extract_pc_anims import decode_frm_all_dirs, load_palette
    rgba = load_palette(src)
    cells = []
    codes = codes or [("aa", (2, 5, 0)), ("ab", (1, 3)), ("ja", (2, 5)), ("ia", (3, 0)),
                      ("ha", (2, 4)), ("da", (2,)), ("gc", (3,))]
    for base in ("hmjmps", "hfjmps"):
        for code, dirs in codes:
            name = f"{base}{code}.frm"
            p = f"art\\critters\\{name}"
            if not src.vfs.exists(p):
                continue
            raw = src.vfs.read(p)
            new = recolor(raw, van.read(name), M)
            for d in dirs:
                pair = []
                for data in (raw, new):
                    ds, _ = decode_frm_all_dirs(data, rgba)
                    if d in ds:
                        fr = ds[d]
                        f = fr[len(fr) // 2].img
                        pair.append(f.resize((f.width * 3, f.height * 3), Image.NEAREST))
                if len(pair) == 2:
                    cells.append((f"{base[:2]} {code} d{d}", pair))
    cols = 4
    cw = max(a.width + b.width for _, (a, b) in cells) + 16
    ch = max(max(a.height, b.height) for _, (a, b) in cells) + 22
    rows = (len(cells) + cols - 1) // cols
    sheet = Image.new("RGBA", (cols * cw, rows * ch), (70, 64, 54, 255))
    dr = ImageDraw.Draw(sheet)
    for k, (lab, (a, b)) in enumerate(cells):
        x, y = (k % cols) * cw, (k // cols) * ch
        sheet.alpha_composite(a, (x + 4, y + ch - 22 - a.height))
        sheet.alpha_composite(b, (x + 8 + a.width, y + ch - 22 - b.height))
        dr.text((x + 4, y + ch - 18), lab + "  before | after", fill=(255, 255, 0, 255))
    sheet.save(out)
    print("preview:", out)


def main() -> int:
    if "--force" not in sys.argv:
        print("superseded: the male player sprite now comes from tools/pc_yesterday.py "
              "(Fallout: Yesterday's hmsmpl). This tool would overwrite it; pass --force "
              "to run it anyway. Its geometry helpers are still imported elsewhere.")
        return 1
    sys.argv.remove("--force")
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--preview", type=Path, help="write a before/after sheet and stop")
    ap.add_argument("--no-deploy", action="store_true")
    args = ap.parse_args()

    src = port.open_source("nevada")
    M = palette_masks(load_pal(src))
    van = Vanilla()
    if args.preview:
        preview(src, van, M, args.preview)
        return 0

    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup = ROOT / "_safety_backups" / f"pc_frm_{stamp}_outfit"
    backup.mkdir(parents=True, exist_ok=True)
    rows = []
    for nev_base, ours in PAIRS:
        old = sorted(CRIT.glob(f"{ours}*"))
        for p in old:
            shutil.copy2(p, backup / p.name)
        stats: dict = {}
        replaced = set()
        for f in nevada_files(src, nev_base):
            name = f.split("\\")[-1].lower()
            dst = CRIT / (ours + name[len(nev_base):])
            dst.write_bytes(recolor(src.vfs.read(f), van.read(name), M, file_dir_of(name), stats))
            replaced.add(dst.name.lower())
        kept = [p.name for p in old if p.name.lower() not in replaced]
        print(f"  {nev_base} -> {ours}: {len(replaced)} files from Nevada, {len(kept)} kept "
              f"(no Nevada equivalent); {stats.get('frames', 0)} frames: "
              f"{stats.get('vanilla', 0)} masked by vanilla, {stats.get('fallback', 0)} by the belt, "
              f"{stats.get('skipped', 0)} left as drawn")
        rows.append(port.ledger_row("nevada", "art", f"art\\critters\\{nev_base}*", nev_base,
                                    f"mod/data/art/critters/{ours}*", ours,
                                    "player sprite: Nevada jumpsuit redressed as T-shirt + olive pants (pc_outfit.py)"))
    have = {(r["source"], r["dest_path"]) for r in port.read_ledger()}
    port.append_ledger([r for r in rows if (r["source"], r["dest_path"]) not in have])
    port.regen_ledger_md()
    print(f"  previous files backed up to {backup.relative_to(ROOT)}")
    if not args.no_deploy:
        return subprocess.run([sys.executable, str(ROOT / "tools" / "deploy.py")], cwd=ROOT).returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
