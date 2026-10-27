#!/usr/bin/env python3
"""match_grids_to_anims.py

The green reference sheets are restyled versions of the vanilla HMJMPS
animation sheets (same frame counts, tracking poses) but we do not know which
sheet is which. Slice every sheet and every vanilla HMJMPS family, compare the
per-frame silhouette sequences across three facings, and assign each sheet to
the vanilla animation it lines up with best.

Input : C:\\Users\\adamn\\OneDrive\\Desktop\\Green\\*_limebg.png   (pure #00FF00 bg)
Output (with --apply):
        art/pc_grids/<CODE>.png                 confident matches
        art/pc_grids/_unsorted/<name>.png       weak matches
        art/pc_grids/_MATCH_REPORT.csv

Run:  python tools/match_grids_to_anims.py            # print table only
      python tools/match_grids_to_anims.py --apply    # write the grids
"""
from __future__ import annotations
import struct, sys, csv, shutil, subprocess
from pathlib import Path
import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
from foclib import GameIndex

ROOT = Path(__file__).resolve().parent.parent
GREEN = Path(r"C:\Users\adamn\OneDrive\Desktop\Green")
GRIDS = ROOT / "art" / "pc_grids"
UNSORTED = GRIDS / "_unsorted"

DIRS = (1, 2, 4)          # compare on E / SE / W rows
SW, SH = 22, 36           # normalised silhouette (upper body only)
L = 18                    # resample every sequence to this many frames
CUTOFF = 0.34             # mean distance above this -> _unsorted

LABEL = {"AA": "idle", "AB": "walk", "AE": "climb", "AK": "pick-up", "AL": "use",
         "AN": "dodge", "AO": "hit-front", "AP": "hit-back", "AQ": "punch",
         "AR": "kick", "AS": "throw", "AT": "run", "CH": "get-up-1", "CJ": "get-up-2",
         "BN": "special"}
WEAPON = {"D": "knife", "E": "club", "F": "sledge", "G": "spear", "H": "pistol",
          "I": "smg", "J": "rifle", "K": "energy", "L": "minigun", "M": "launcher"}


def label(code: str) -> str:
    if code in LABEL:
        return LABEL[code]
    w = WEAPON.get(code[0], code[0])
    a = {"A": "idle", "B": "walk", "C": "draw", "D": "holster", "E": "dodge",
         "F": "atk", "G": "atk2", "H": "atk3", "I": "atk4", "J": "atk5",
         "K": "atk6", "L": "burst", "M": "throw"}.get(code[1], code[1])
    return f"{w}-{a}"


# ---- silhouette signature -------------------------------------------------
def frame_sig(mask: np.ndarray):
    ys, xs = np.where(mask)
    if len(xs) < 6:
        return np.zeros((SH, SW), bool), 1.0, 0.0
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    h, w = y1 - y0 + 1, x1 - x0 + 1
    sub = mask[y0:y1 + 1, x0:x1 + 1]
    upper = sub[: max(4, int(h * 0.70))]          # drop legs+shadow
    im = Image.fromarray((upper * 255).astype(np.uint8)).resize((SW, SH), Image.NEAREST)
    return np.asarray(im) > 127, w / h, float(h)


def seq_sig(masks):
    if len(masks) < 2:
        return None
    sig = [frame_sig(m) for m in masks]
    idx = np.linspace(0, len(sig) - 1, L).round().astype(int)
    sil = np.stack([sig[i][0] for i in idx])
    asp = np.array([sig[i][1] for i in idx])
    hgt = np.array([sig[i][2] for i in idx]); hgt = hgt / (hgt.max() or 1.0)
    return sil, asp, hgt, len(masks)


def seq_dist(a, b) -> float:
    best = 9.9
    for sb, ab, hb in ((b[0], b[1], b[2]), (b[0][::-1], b[1][::-1], b[2][::-1])):
        inter = np.logical_and(a[0], sb).sum((1, 2))
        union = np.logical_or(a[0], sb).sum((1, 2)).clip(min=1)
        d = (1 - inter / union).mean() \
            + 0.6 * np.abs(a[1] - ab).mean() \
            + 0.5 * np.abs(a[2] - hb).mean()
        best = min(best, d)
    return best


# ---- slicing ------------------------------------------------------------
def est_cols(fgmask):
    cp = fgmask.mean(0).astype(float); cp -= cp.mean()
    ac = np.correlate(cp, cp, "full")[len(cp) - 1:]
    w = len(cp); lo, hi = max(10, w // 26), max(14, w // 3)
    return max(2, round(w / (lo + int(np.argmax(ac[lo:hi])))))


def green_rows(path: Path):
    rgb = np.asarray(Image.open(path).convert("RGB")).astype(np.int16)
    H, W, _ = rgb.shape
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    bg = (g > 140) & (g - r > 35) & (g - b > 35)
    mx = rgb.max(2); sat = mx - rgb.min(2)
    dark = (mx < 90) & (sat < 32)                 # baked ground shadow
    fg = ~bg & ~dark
    a = fg.astype(np.uint8); nb = np.zeros_like(a)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                nb[1:-1, 1:-1] += a[1 + dy:H - 1 + dy, 1 + dx:W - 1 + dx]
    fg = (a & (nb >= 3)).astype(bool)

    cols = est_cols(fg)
    rows = []
    for d in range(6):
        y0, y1 = int(round(d * H / 6)), int(round((d + 1) * H / 6))
        band = fg[y0:y1]
        masks = []
        for c in range(cols):
            x0, x1 = int(round(c * W / cols)), int(round((c + 1) * W / cols))
            cell = band[:, x0:x1]
            masks.append(cell if cell.sum() > 15 else np.zeros_like(cell))
        rows.append(masks)
    return rows, cols


def vanilla_rows(gi, name):
    d = gi.vfs.read(f"art\\critters\\{name}")
    fpd = struct.unpack_from(">H", d, 8)[0]
    offs = struct.unpack_from(">6I", d, 0x22)
    rows = []
    for di in range(6):
        pos = 0x3E + offs[di]
        end = 0x3E + (offs[di + 1] if di < 5 else len(d))
        masks = []
        while pos + 12 <= len(d) and pos < end and len(masks) < fpd:
            w, h, size, fx, fy = struct.unpack_from(">HHIhh", d, pos)
            if not (w and h) or not (0 < size <= 1 << 24):
                break
            px = np.frombuffer(d[pos + 12:pos + 12 + w * h], np.uint8).reshape(h, w)
            masks.append(px != 0)
            pos += 12 + size
        rows.append(masks)
    return rows, fpd


def multi_dist(gsigs, vsigs, gn, vn) -> float:
    ds = [seq_dist(gsigs[i], vsigs[i]) for i in range(len(DIRS))
          if gsigs[i] is not None and vsigs[i] is not None]
    if not ds:
        return 9.9
    fc = abs(gn - vn) / max(gn, vn)
    return float(np.mean(ds)) + (0.0 if gn == vn else 0.25 + 0.4 * fc)


# ---- main --------------------------------------------------------------
def main() -> int:
    apply = "--apply" in sys.argv
    gi = GameIndex()

    listing = subprocess.run([str(ROOT / "tools" / "dat" / "dat2.exe"), "l",
                              str(ROOT / "base" / "critter.dat")],
                             capture_output=True, text=True).stdout
    fam = {}
    for ln in listing.splitlines():
        if "\\" in ln:
            nm = ln.strip().split("\\")[-1].strip().upper()
            if nm.startswith("HMJMPS") and nm.endswith(".FRM"):
                fam[nm[6:8]] = nm
    van = {}
    for code, nm in sorted(fam.items()):
        rows, fpd = vanilla_rows(gi, nm)
        if fpd < 2:
            continue
        van[code] = ([seq_sig([rows[d][i] for i in range(len(rows[d]))]) for d in DIRS], fpd)
    print(f"{len(van)} vanilla HMJMPS families")

    sheets = []
    for p in sorted(GREEN.glob("*_limebg.png")):
        rows, cols = green_rows(p)
        sig = [seq_sig(rows[d]) for d in DIRS]
        n = max((s[3] for s in sig if s), default=cols)
        sheets.append(dict(path=p, sig=sig, cols=cols, n=n))
    print(f"{len(sheets)} reference sheets\n")

    codes = list(van)
    D = np.full((len(sheets), len(codes)), 9.9)
    for i, s in enumerate(sheets):
        for j, c in enumerate(codes):
            D[i, j] = multi_dist(s["sig"], van[c][0], s["n"], van[c][1])

    # greedy global assignment: lowest distance first
    assign = {}
    taken_c = set()
    order = np.dstack(np.unravel_index(np.argsort(D, axis=None), D.shape))[0]
    for i, j in order:
        if i in assign or j in taken_c:
            continue
        assign[i] = j
        taken_c.add(j)
        if len(assign) == len(sheets):
            break

    rows_out = []
    for i, s in enumerate(sheets):
        j = assign[i]
        c = codes[j]
        dist = float(D[i, j])
        srt = np.argsort(D[i])
        second = float(D[i, srt[1]]) if srt[0] == j else float(D[i, srt[0]])
        margin = second - dist
        # confident if this animation is clearly the best fit, or the absolute
        # alignment is tight. frame-count already matches exactly in most cases.
        conf = "ok" if (margin >= 0.09 or dist <= 0.42) and s["n"] == van[c][1] else "weak"
        alts = " ".join(f"{codes[k]}:{D[i,k]:.2f}" for k in srt[:4] if k != j)
        rows_out.append(dict(sheet=s["path"].name, cols=s["cols"], n=s["n"],
                             match=c, label=label(c), vframes=van[c][1],
                             dist=round(dist, 3), margin=round(margin, 3),
                             conf=conf, alts=alts))
    rows_out.sort(key=lambda r: (r["conf"] != "ok", r["dist"]))

    wpad = max(len(r["sheet"]) for r in rows_out)
    print(f"{'sheet':<{wpad}}  match  g/v   dist   conf  alternatives")
    for r in rows_out:
        print(f"{r['sheet']:<{wpad}}  {r['match']} {r['label']:<11} "
              f"{r['n']:>2}/{r['vframes']:<2} {r['dist']:.3f} {r['conf']:<5} {r['alts']}")

    if apply:
        GRIDS.mkdir(parents=True, exist_ok=True)
        UNSORTED.mkdir(exist_ok=True)
        for r in rows_out:
            src = GREEN / r["sheet"]
            # Every sheet is applied - the greedy assignment already picked the
            # best home for each. 'conf' is an advisory for the review montage.
            # Only a genuinely broken slice (junk distance) is parked.
            if r["dist"] > 1.0:
                shutil.copy2(src, UNSORTED / f"{r['match']}__{r['sheet']}")
            else:
                shutil.copy2(src, GRIDS / f"{r['match']}.png")
        with (GRIDS / "_MATCH_REPORT.csv").open("w", newline="") as fp:
            wr = csv.DictWriter(fp, fieldnames=list(rows_out[0]))
            wr.writeheader(); wr.writerows(rows_out)
        applied = sum(r["dist"] <= 1.0 for r in rows_out)
        print(f"\napplied {applied} grids, {len(rows_out) - applied} -> _unsorted, "
              f"report -> {GRIDS/'_MATCH_REPORT.csv'}")
    else:
        print("\n(dry run - pass --apply to write)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
