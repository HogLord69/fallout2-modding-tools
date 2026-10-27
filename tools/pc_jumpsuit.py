#!/usr/bin/env python3
"""
pc_jumpsuit.py - rebuild the player sprites (hmpcot / hfpcot) from Fallout:
Nevada's jumpsuit (hmjmps / hfjmps) with only the PANTS recoloured olive-brown.
The torso, sleeves, the skull on the back, the belt, skin, boots and every
held weapon stay exactly as Nevada drew them (owner's call, 2026-09-28: the
whole-suit recolour tinted the guns, left bits of skull in the action frames
and drifted in hue).

    python tools/pc_jumpsuit.py --preview out.png    # before/after sheet, writes nothing
    python tools/pc_jumpsuit.py                      # back up, replace, deploy

Palette-index swap on a per-frame mask; no pixel moves, headers are untouched.

FINDING THE PANTS. The suit, the torso and the guns all use the same neutral
greys, so the pants are found by position, frame by frame:
  1. the belt: a line through the frame's belt-gold pixels (principal axis,
     so it follows the belt when he lies down in the death animations);
  2. which side is the legs: the side AWAY from the skin (face and hands);
  3. pants = suit-grey pixels on that side, inside a wedge that starts at the
     belt's width and widens with distance (a stride spreads the legs; a
     sleeve hanging beside the hip stays outside it), in pieces that touch
     the belt - so a gun held away from the legs is never touched.
A frame whose belt is hidden borrows the line of the nearest frame in the same
direction (in feet-anchor coordinates, the frame's bottom centre); a whole
direction without a belt is left unrecoloured.

Colour: the suit greys map in brightness order onto PANTS_RAMP, a run of the
palette's olive-browns that all sit at hue 30-40 so the shade never drifts
toward green or red; the darkest step is the outline black.

Any animation Nevada lacks (hfjmps has 9 fewer than our hfpcot) keeps the
current hfpcot file. The files being replaced are copied to
_safety_backups/pc_frm_<date>/ first.
"""

from __future__ import annotations

import argparse
import colorsys
import datetime as dt
import shutil
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
from scipy import ndimage  # noqa: E402

import port  # noqa: E402

ROOT = port.ROOT
CRIT = ROOT / "mod" / "data" / "art" / "critters"
PAIRS = (("hmjmps", "hmpcot"), ("hfjmps", "hfpcot"))
CYCLE_FROM = 229

# Belt buckle/strap and the torso trim: Nevada's yellow/gold ramp.
GOLD = [56, 57, 58, 59, 60, 61, 62, 63, 64, 79, 80, 81, 82, 83]
NAVY = [47]                     # the female suit's darkest shade
# olive-brown, darkest first, all hue 30-40 (204 48,40,32 .. 222 211,186,138)
PANTS_RAMP = [207, 204, 78, 225, 77, 224, 223, 222]
PANTS_CURVE = ([0, 12, 30, 45, 60, 75, 100, 140, 200],
               [12, 12, 40, 47, 60, 70, 85, 118, 160])

MIN_GOLD = 6          # fewer belt pixels than this and the frame borrows a line
WEDGE = 0.9           # lateral widening of the legs' region per px below the belt
BELT_MARGIN = 1.0     # px past the belt line before cloth counts as pants
TOUCH = 3             # a pants piece must come within this many px of the belt
RANSAC_TOL = 1.8      # px from the belt line that still counts as belt
LEVEL = 0.6           # |cos| of belt angle above which "legs are below" (~53 deg)
STEEP_MIN = 10        # a steep (lying) belt needs this many pixels and px of span
FOLLOW_DEG = 40       # a frame's belt may turn this far from the previous frame's


def load_pal(src) -> np.ndarray:
    raw = src.vfs.read("color.pal")
    return np.array([[(raw[i * 3 + c] << 2) | (raw[i * 3 + c] >> 4) for c in range(3)]
                     for i in range(256)], float)


def masks(pal: np.ndarray):
    """(suit greys, gold, skin) as 256-entry palette masks."""
    suit = np.zeros(256, bool)
    skin = np.zeros(256, bool)
    for i in range(1, CYCLE_FROM):
        r, g, b = pal[i]
        lum = (r + g + b) / 3
        if abs(r - g) <= 8 and abs(g - b) <= 12 and lum >= 10:
            suit[i] = True
        h, s, _v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if 15 <= h * 360 <= 35 and 0.35 <= s <= 0.75 and 70 <= lum <= 200:
            skin[i] = True
    suit[NAVY] = True
    gold = np.zeros(256, bool)
    gold[GOLD] = True
    skin[GOLD] = False
    return suit, gold, skin


def pants_table(pal: np.ndarray, suit: np.ndarray) -> np.ndarray:
    """palette index -> pants colour, for every suit grey (identity elsewhere)."""
    lum = pal.mean(1)
    rlum = lum[PANTS_RAMP]
    table = np.arange(256, dtype=np.uint8)
    floor = 0
    for i in sorted(np.nonzero(suit)[0], key=lambda k: lum[k]):
        want = np.interp(lum[i], *PANTS_CURVE)
        k = max(int(np.abs(rlum - want).argmin()), floor)   # keep the shading order
        table[i], floor = PANTS_RAMP[k], k
    return table


# ------------------------------------------------------------------ geometry

def _angle_ok(u, prev_u) -> bool:
    return abs(float(u @ prev_u)) >= np.cos(np.radians(FOLLOW_DEG))


def belt_fit(px, gold, prev_u=None):
    """(centre, along, half_width) of the belt in feet-anchor coords, or None.

    The front views also carry a gold trim stripe down the chest (and the
    female suit's V-neck), and gun stocks use the same golds, so a plain fit
    is dragged off the belt. RANSAC keeps the line most gold agrees with,
    among lines that are level (no previous frame) or close to the previous
    frame's belt (a falling body turns gradually). A steep belt with no
    previous frame to follow is only believed when it is long (a lying body).
    """
    h, w = px.shape
    ys, xs = np.nonzero(gold[px])
    if len(xs) < MIN_GOLD:
        return None
    pts = np.stack([xs - w / 2, ys - h], 1).astype(float)
    rng = np.random.default_rng(len(pts))
    best = {"any": (None, -1)}
    cands = {"follow": [], "level": []}
    for _ in range(200):
        i, j = rng.choice(len(pts), 2, replace=False)
        v = pts[j] - pts[i]
        L = np.hypot(*v)
        if L < 2:
            continue
        uu = v / L
        nrm = np.array([-uu[1], uu[0]])
        inl = np.abs((pts - pts[i]) @ nrm) <= RANSAC_TOL
        k = int(inl.sum())
        if k > best["any"][1]:
            best["any"] = (inl, k)
        if abs(uu[0]) >= LEVEL:
            cands["level"].append((inl, k))
        if prev_u is not None and _angle_ok(uu, prev_u):
            cands["follow"].append((inl, k))

    def lowest(cs):
        # a print on the back (vanilla's '13') can hold more gold than the
        # belt; the belt is the LOWEST well-supported run
        cs = [(inl, k) for inl, k in cs if k >= MIN_GOLD]
        if not cs:
            return None
        top = max(k for _i, k in cs)
        cs = [(inl, k) for inl, k in cs if k >= max(MIN_GOLD, 0.4 * top)]
        return max(cs, key=lambda c: pts[c[0], 1].mean())[0]

    pick = lowest(cands["follow"]) if prev_u is not None else lowest(cands["level"])
    if pick is not None:
        sel = pick
    else:
        sel, k = best["any"]
        if k < STEEP_MIN or np.ptp(pts[sel], axis=0).max() < STEEP_MIN:
            return None                # short steep run: edge-on belt or stray gold
    # the belt is one run of gold: keep the biggest connected piece
    img = np.zeros((h, w), bool)
    img[ys[sel], xs[sel]] = True
    lab, nl = ndimage.label(ndimage.binary_dilation(img, iterations=1))
    if nl > 1:
        sizes = ndimage.sum(img, lab, range(1, nl + 1))
        sel = sel & (lab == 1 + int(np.argmax(sizes)))[ys, xs]
    pts = pts[sel]
    c = pts.mean(0)
    evals, evecs = np.linalg.eigh(np.cov((pts - c).T))
    u = evecs[:, 1]
    if np.sqrt(max(evals[1], 0)) < 2.0:  # a belt seen edge-on: take it as level
        u = np.array([1.0, 0.0])
    half = np.abs((pts - c) @ u).max() + 1
    return c, u, half


def legs_normal(px, fit, gold, skin, prev_n=None):
    """The belt's normal pointing at the legs."""
    h, w = px.shape
    c, u, _half = fit
    n = np.array([-u[1], u[0]])
    if prev_n is not None:
        # follow the previous frame: the legs cannot jump to the other side
        return n if n @ prev_n >= 0 else -n
    if abs(u[0]) >= LEVEL:
        return n if n[1] >= 0 else -n    # level belt: legs are below it
    # steep belt and nothing to follow (a single-frame death pose): the legs
    # are on the side away from the skin (face, hands)
    sy, sx = np.nonzero(skin[px] & ~ndimage.binary_dilation(gold[px], iterations=2))
    if len(sx):
        s = np.array([sx.mean() - w / 2, sy.mean() - h])
        return -n if n @ (s - c) > 0 else n
    return n if n[1] >= 0 else -n


def belt_lines(pxs, gold, skin):
    """(centre, along, legs normal, half) per frame of one direction, in order;
    None where no frame of the direction has a belt."""
    out = [None] * len(pxs)
    prev = None
    for i, px in enumerate(pxs):
        fit = belt_fit(px, gold, None if prev is None else prev[1])
        if fit is None:
            out[i] = prev                # hidden belt: keep the last line
            continue
        n = legs_normal(px, fit, gold, skin, None if prev is None else prev[2])
        prev = out[i] = (fit[0], fit[1], n, fit[2])
    first = next((ln for ln in out if ln is not None), None)
    return [ln if ln is not None else first for ln in out]


def pants_mask(px, line, suit, gold):
    h, w = px.shape
    c, u, n, half = line
    yy, xx = np.mgrid[0:h, 0:w]
    P = np.stack([xx - w / 2, yy - h], -1).astype(float)
    d = (P - c) @ n                        # distance past the belt, legs side
    lat = np.abs((P - c) @ u)
    region = (d > BELT_MARGIN) & (lat <= half + WEDGE * np.maximum(d, 0))
    cand = suit[px] & region
    if not cand.any():
        return cand
    near_belt = ndimage.binary_dilation(gold[px], iterations=TOUCH) | (np.abs(d) <= TOUCH) & (lat <= half)
    lab, nlab = ndimage.label(cand, structure=np.ones((3, 3), bool))
    keep = np.unique(lab[near_belt & cand])
    return np.isin(lab, keep[keep > 0])


# ------------------------------------------------------------------ files

def frames_of(buf: bytes, file_dir: int | None):
    """[(direction, [(pixel offset, w, h), ...]), ...] for an .frm/.fr? file."""
    fpd = struct.unpack_from(">H", buf, 8)[0] or 1
    offs = struct.unpack_from(">6I", buf, 0x22)
    out, seen = [], set()
    for d in range(6):
        if d and offs[d] in seen:
            continue
        seen.add(offs[d])
        pos = 0x3E + offs[d]
        fr = []
        for _ in range(fpd):
            if pos + 12 > len(buf):
                break
            w, h, size = struct.unpack_from(">HHI", buf, pos)
            s = pos + 12
            if w and h and s + w * h <= len(buf):
                fr.append((s, w, h))
            pos = s + size
        out.append((file_dir if file_dir is not None else d, fr))
        if file_dir is not None:
            break
    return out


def recolor(data: bytes, table: np.ndarray, suit, gold, skin,
            file_dir: int | None = None, stats: dict | None = None) -> bytes:
    buf = bytearray(data)
    for _d, frs in frames_of(data, file_dir):
        pxs = [np.frombuffer(data[s:s + w * h], np.uint8).reshape(h, w) for s, w, h in frs]
        lines = belt_lines(pxs, gold, skin)
        for i, (px, (s, w, h)) in enumerate(zip(pxs, frs)):
            ln = lines[i]
            if stats is not None:
                stats["frames"] = stats.get("frames", 0) + 1
                if ln is None:
                    stats["skipped"] = stats.get("skipped", 0) + 1
            if ln is None:
                continue
            m = pants_mask(px, ln, suit, gold)
            out = np.where(m, table[px], px)
            buf[s:s + w * h] = out.astype(np.uint8).tobytes()
    return bytes(buf)


def nevada_files(src, base: str) -> list[str]:
    out = []
    for c in "ABCDEFGHIJKLMNOPQRST":
        for a in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            for ext in ("frm", "fr0", "fr1", "fr2", "fr3", "fr4", "fr5"):
                p = f"art\\critters\\{base}{c}{a}.{ext}"
                if src.vfs.exists(p):
                    out.append(p)
    return out


def file_dir_of(name: str) -> int | None:
    ext = name.lower().rsplit(".", 1)[-1]
    return int(ext[2]) if ext[:2] == "fr" and ext[2:].isdigit() else None


def preview(src, pal, table, suit, gold, skin, out: Path) -> None:
    from PIL import Image, ImageDraw
    from extract_pc_anims import decode_frm_all_dirs, load_palette
    rgba = load_palette(src)
    cells = []
    for base in ("hmjmps", "hfjmps"):
        for code, dirs in (("aa", (2, 5, 0)), ("ab", (1, 4)), ("ja", (2, 5)), ("ia", (0, 3)), ("bb", (2,))):
            p = f"art\\critters\\{base}{code}.frm"
            if not src.vfs.exists(p):
                continue
            raw = src.vfs.read(p)
            for tag, data in (("before", raw), ("after", recolor(raw, table, suit, gold, skin))):
                ds, _ = decode_frm_all_dirs(data, rgba)
                for d in dirs:
                    if d in ds:
                        fr = ds[d]
                        f = fr[len(fr) // 2].img
                        cells.append((f"{base[:2]} {code} d{d} {tag}", f.resize((f.width * 3, f.height * 3), Image.NEAREST)))
    cols = 6
    cw = max(c.width for _, c in cells) + 8
    ch = max(c.height for _, c in cells) + 22
    rows = (len(cells) + cols - 1) // cols
    sheet = Image.new("RGBA", (cols * cw, rows * ch), (70, 64, 54, 255))
    dr = ImageDraw.Draw(sheet)
    for k, (lab, c) in enumerate(cells):
        x, y = (k % cols) * cw, (k // cols) * ch
        sheet.alpha_composite(c, (x + 4, y + ch - 22 - c.height))
        dr.text((x + 4, y + ch - 18), lab, fill=(255, 255, 0, 255))
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
    pal = load_pal(src)
    suit, gold, skin = masks(pal)
    table = pants_table(pal, suit)
    if args.preview:
        preview(src, pal, table, suit, gold, skin, args.preview)
        return 0

    # one folder per run: a second run must never overwrite the backup of the
    # sprites the first run replaced
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup = ROOT / "_safety_backups" / f"pc_frm_{stamp}_jumpsuit"
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
            dst.write_bytes(recolor(src.vfs.read(f), table, suit, gold, skin,
                                    file_dir_of(name), stats))
            replaced.add(dst.name.lower())
        kept = [p.name for p in old if p.name.lower() not in replaced]
        print(f"  {nev_base} -> {ours}: {len(replaced)} files from Nevada, "
              f"{len(kept)} current files kept (no Nevada equivalent); "
              f"{stats.get('frames', 0)} frames, {stats.get('skipped', 0)} left as drawn "
              f"(no belt anywhere in that direction)")
        rows.append(port.ledger_row("nevada", "art", f"art\\critters\\{nev_base}*", nev_base,
                                    f"mod/data/art/critters/{ours}*", ours,
                                    "player sprite: Nevada jumpsuit, pants recoloured olive-brown (pc_jumpsuit.py)"))
    have = {(r["source"], r["dest_path"]) for r in port.read_ledger()}
    port.append_ledger([r for r in rows if (r["source"], r["dest_path"]) not in have])
    port.regen_ledger_md()
    print(f"  previous files backed up to {backup.relative_to(ROOT)}")
    if not args.no_deploy:
        return subprocess.run([sys.executable, str(ROOT / "tools" / "deploy.py")], cwd=ROOT).returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
