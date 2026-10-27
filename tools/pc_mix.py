"""pc_mix.py: the player sprites built from three sprites stacked frame by
frame (the owner's design, 2026-10-21): the brown vault-suit top with short
sleeves, bare arms, and the leather armour's camo trousers and boots.

    male    hmpbrn (pc_sonora.py) + hmmetl arms + hmlthr legs  -> hmpslv
    female  hfpbrn                + hfmetl arms + hflthr legs  -> hfpslv

Every Fallout 2 armour set was drawn from the same animation at the same
size, so a frame only needs shifting into line: each suit frame takes the
armour frame of the same direction whose shape overlaps it most (some armours
start their cycle on a different frame).

  arms   The metal armour's torso is metal, so the only skin below its head is
         the bare arms. The suit's own sleeve is the suit nearer either
         armour's skin than the metal torso; it takes the armour's arm pixel
         there, or turns skin by its brightness.
  legs   The leather armour's camo greens and yellows appear only on its
         trousers (its top has a few specks, so only solid camo counts); the
         boots are the dark pixels under them. Its legs replace the suit's,
         shape and all, and may grow SEAM px into the suit to close the waist.
  top    The brown suit as it is, running SLEEVE px down each arm from the
         shoulder: short sleeves.

A frame grows only sideways (evenly) and upward, so its anchor (the bottom
centre) stays put and the FRM offsets are unchanged. Animations the armours
lack are copied from the brown suit, as is any animation whose frames mostly
match the armours poorly (Sonora redrew a few) or that has a frame which
barely fits at all: an animation is all mixed or all brown, so the outfit
never flickers.

    python tools/pc_mix.py                    write the two sets + ledger rows
    python tools/pc_mix.py --preview OUT.png  a before/after sheet only
"""
import argparse
import multiprocessing
import os
import struct
import sys
from pathlib import Path

import numpy as np
from scipy import ndimage
from scipy.signal import fftconvolve

import port
import pc_jumpsuit as pj
import pc_sonora as ps

CRIT = port.ROOT / "mod" / "data" / "art" / "critters"
SETS = [  # suit (Sonora, for its blue), brown suit, arms, legs, output
    ("hmjmps", "hmpbrn", "hmmetl", "hmlthr", "hmpslv"),
    ("hfjmps", "hfpbrn", "hfmetl", "hflthr", "hfpslv"),
]
RING = np.ones((3, 3), bool)
SEAM = 3        # px the leather legs may grow into the suit at the waist
ARM_REACH = 4   # px from an armour's arm that the suit's sleeve can be
SLEEVE = 3      # px the top runs down each arm
POOR_FIT = 0.5  # shape overlap of a poor match: an animation with mostly poor frames keeps the brown suit
KEEP_FIT = 0.4  # and so does one with any frame this poor (half mixed, the outfit would flicker)

son = port.open_source("sonora")
fo2 = port.open_source("fo2")
pal = ps.load_pal(son)
lum = pal.mean(1)
table, blues = ps.brown_table(pal)
BLUE = np.zeros(256, bool)
BLUE[blues] = True
_s, _g, SKIN = pj.masks(pal)
SKIN = SKIN.copy()
SKIN[[194, 195, 193, 192, 161, 158]] = True     # the arms' red shadows
SKIN[203] = False                               # also on the leather trousers
CAMO = np.zeros(256, bool)
CAMO[[95, 96, 97, 98, 99, 65, 66, 67, 68, 124]] = True   # the leather trousers' own colours
METAL = np.zeros(256, bool)
METAL[[199, 13, 208, 14, 11, 12, 79, 209, 210, 213, 212, 86, 201, 211, 10, 214, 4, 5, 85, 3, 9, 119, 118, 76, 75, 74, 15]] = True
DARK = np.zeros(256, bool)                      # the suit's shading greys and greens (and the hair's)
DARK[[12, 13, 14, 15, 202, 207, 208, 75, 91, 92, 93, 94, 100, 114, 199, 78, 76]] = True
_browns = sorted(set(table[blues].tolist()), key=lambda k: lum[k])
BROWN_BY_LUM = np.array([_browns[int(np.abs(lum[_browns] - lum[i] * 1.15).argmin())] for i in range(256)], np.uint8)
# a sleeve with no armour arm on it: the suit's brown -> skin, learned from
# where the owner's New Sprites sheets put bare arms over the suit
_skin = {227: 192, 204: 191, 206: 173, 120: 159, 121: 159, 122: 159, 123: 159, 174: 159, 188: 159, 203: 159, 205: 159}
SLEEVE_SKIN = np.array([_skin.get(i, _skin[min(_skin, key=lambda b: abs(lum[b] - lum[i]))]) for i in range(256)], np.uint8)


# ----------------------------------------------------------------------- frm

def read_frm(data: bytes) -> dict:
    """header and frames; directions that share data stay shared"""
    version, fps, action, fpd = struct.unpack_from(">IHHH", data, 0)
    xo = struct.unpack_from(">6h", data, 10)
    yo = struct.unpack_from(">6h", data, 22)
    offs = struct.unpack_from(">6I", data, 34)
    blocks = {}
    for o in sorted(set(offs)):
        pos, row = 62 + o, []
        for _ in range(fpd):
            w, h, size, sx, sy = struct.unpack_from(">HHIhh", data, pos)
            row.append([w, h, sx, sy, np.frombuffer(data[pos + 12:pos + 12 + w * h], np.uint8).reshape(h, w)])
            pos += 12 + size
        blocks[o] = row
    return dict(version=version, fps=fps, action=action, fpd=fpd, xo=xo, yo=yo, offs=offs, blocks=blocks)


def write_frm(m: dict) -> bytes:
    body, new = bytearray(), {}
    for o in sorted(m["blocks"]):
        new[o] = len(body)
        for w, h, sx, sy, px in m["blocks"][o]:
            body += struct.pack(">HHIhh", w, h, w * h, sx, sy) + np.ascontiguousarray(px, np.uint8).tobytes()
    head = struct.pack(">IHHH", m["version"], m["fps"], m["action"], m["fpd"])
    head += struct.pack(">6h", *m["xo"]) + struct.pack(">6h", *m["yo"])
    head += struct.pack(">6I", *[new[o] for o in m["offs"]]) + struct.pack(">I", len(body))
    return head + bytes(body)


def donor_frames(base: str, code: str) -> dict:
    """{direction: [pixels per frame]} from an armour's .frm or .fr0-.fr5"""
    p = f"art\\critters\\{base}{code}.frm"
    files = [(p, None)] if fo2.vfs.exists(p) else \
        [(f"art\\critters\\{base}{code}.fr{d}", d) for d in range(6) if fo2.vfs.exists(f"art\\critters\\{base}{code}.fr{d}")]
    out = {}
    for path, fd in files:
        data = fo2.vfs.read(path)
        for d, frs in pj.frames_of(data, fd):
            out[d] = [np.frombuffer(data[s:s + w * h], np.uint8).reshape(h, w) for s, w, h in frs]
    return out


# ------------------------------------------------------------------- masks

def shift_onto(src: np.ndarray, dst: np.ndarray, pad: int):
    """src moved onto dst's canvas where their shapes overlap most, and that
    overlap (intersection over union)"""
    a = (dst != 0).astype(np.float32)
    py = max(pad, (dst.shape[0] - src.shape[0]) // 2 + pad)
    px = max(pad, (dst.shape[1] - src.shape[1]) // 2 + pad)
    b = np.pad(src, ((py, py), (px, px)))
    c = fftconvolve((b != 0).astype(np.float32), a[::-1, ::-1], mode="valid")
    i, j = np.unravel_index(int(c.argmax()), c.shape)
    out = b[i:i + dst.shape[0], j:j + dst.shape[1]]
    iou = ((out != 0) & (dst != 0)).sum() / max(1, ((out != 0) | (dst != 0)).sum())
    return out, float(iou)


def best_frame(donor: list, f: int, canvas: np.ndarray, pad: int):
    """the donor frame that fits best; its own index wins near-ties"""
    order = [f] + [k for k in range(len(donor)) if k != f] if f < len(donor) else list(range(len(donor)))
    best = None
    for k in order:
        got = shift_onto(donor[k], canvas, pad)
        if best is None or got[1] > best[1] + 0.01:
            best = got
    return best


def compete(region, a, b):
    """grow a and b through region a ring at a time, a winning ties; what a got"""
    a, b = a & region, b & region
    todo = region & ~a & ~b
    while todo.any():
        ga = ndimage.binary_dilation(a, RING) & todo
        gb = ndimage.binary_dilation(b, RING) & todo & ~ga
        if not ga.any() and not gb.any():
            break
        a |= ga
        b |= gb
        todo &= ~(ga | gb)
    return a


def head_mask(rp, cloth):
    """the head: what is drawn above the suit's top, and what joins it"""
    other = (rp != 0) & ~cloth
    lab, n = ndimage.label(other, RING)
    if not n:
        return other
    ys = np.nonzero(cloth.any(1))[0]
    top = ys.min() if len(ys) else rp.shape[0]
    keep = [k for k in range(1, n + 1) if np.nonzero(lab == k)[0].min() < top + 2]
    return ndimage.binary_dilation(np.isin(lab, keep), RING)


def leg_zone(lp):
    """the leather armour's trousers and boots"""
    camo = CAMO[lp]
    camo &= ndimage.uniform_filter(camo.astype(np.float32), 5) * 25 >= 7
    zone = ndimage.binary_closing(camo, RING, iterations=2) & (lp != 0)
    zone = ndimage.binary_fill_holes(zone)
    lab, n = ndimage.label(zone, RING)
    if n:
        sizes = ndimage.sum(np.ones_like(lab), lab, np.arange(1, n + 1))
        zone = np.isin(lab, 1 + np.nonzero(sizes >= 0.1 * sizes.max())[0])
    dark = (lp != 0) & (lum[lp] < 45) & ~zone
    rows = np.arange(lp.shape[0])[:, None]
    for _ in range(12):
        grow = ndimage.binary_dilation(zone, RING) & dark
        if zone.any():
            grow &= rows > np.nonzero(zone)[0].mean()
        if not grow.any():
            break
        zone |= grow
        dark &= ~grow
    return zone


# ------------------------------------------------------------------- frames

def mix(rp, bp, arms_donor, legs_donor, f):
    """one frame: the mixed pixels on the brown frame's own anchor (None if
    nothing is left), and how well each armour fits"""
    h, w = rp.shape
    big = max([a.shape[0] for a in arms_donor + legs_donor] + [a.shape[1] for a in arms_donor + legs_donor])
    pad = 12 + max(0, big - min(h, w)) // 2
    cr, cb = np.pad(rp, pad), np.pad(bp, pad)
    mp, fit_m = best_frame(arms_donor, f, cr, pad + 6)
    lp, fit_l = best_frame(legs_donor, f, cr, pad + 6)
    cloth = BLUE[cr] | ((cb != cr) & ~BLUE[cr])
    nb = ndimage.convolve(cloth.astype(np.int16), np.ones((3, 3), np.int16), mode="constant")
    suit = cloth | (DARK[cr] & (nb >= 5))
    head = head_mask(cr, cloth)
    arms = SKIN[mp] & (mp != 0) & ~head
    legs = leg_zone(lp)
    # the waist seam: the suit near the legs goes with them, unless the metal
    # armour has its torso there
    seeds_t = suit & METAL[mp] & ~arms & ~ndimage.binary_dilation(legs, RING, iterations=2)
    reach = ndimage.binary_dilation(legs, RING, iterations=SEAM)
    legs = legs | (compete(suit & ~arms & reach, legs, seeds_t) & suit)
    # the suit's own sleeves
    region = suit & ~legs & ~head
    arm_seed = region & (SKIN[mp] | (SKIN[lp] & ~METAL[mp]))
    torso_seed = region & METAL[mp] & ~arm_seed
    sleeves = region & ~compete(region, torso_seed, arm_seed)
    arms |= sleeves & ndimage.binary_dilation(arm_seed, RING, iterations=ARM_REACH)
    # the top: the suit's biggest piece left, and whatever joins the head
    rest = suit & ~legs & ~arms
    lab, n = ndimage.label(rest, RING)
    torso = np.zeros_like(rest)
    if n:
        sizes = ndimage.sum(np.ones_like(lab), lab, np.arange(1, n + 1))
        near_head = ndimage.binary_dilation(head, RING, iterations=2)
        keep = [k for k in range(1, n + 1) if k == 1 + int(np.argmax(sizes)) or (lab == k)[near_head].any()]
        torso = np.isin(lab, keep)
        holes, hn = ndimage.label(ndimage.binary_fill_holes(torso) & ~torso)
        if hn:
            hs = ndimage.sum(np.ones_like(holes), holes, np.arange(1, hn + 1))
            torso |= np.isin(holes, 1 + np.nonzero(hs <= 4)[0]) & (lum[cr] < 90) & ~SKIN[cr]
    px = cb.copy()
    # suit leg showing past the armour's legs goes (not a sleeve the leather
    # armour has an arm on)
    stray = rest & ~torso & ndimage.binary_dilation(legs, RING, iterations=3) & ~SKIN[lp]
    px = np.where(stray, lp, px)
    sb = np.where(cloth, cb, BROWN_BY_LUM[cr])
    px = np.where(torso, sb, px)
    # the legs: the leather armour's on the suit's trousers and past them; the
    # suit sprite's own shadow, boots, hands and gun there stay (the leather
    # armour shadows with a dark red the game's other sprites don't)
    lpx = np.where(lp == 31, 207, lp)
    px = np.where(legs & (suit | (cr == 0)), lpx, px)
    px = np.where(legs & (lp == 0) & suit, 0, px)
    armpx = np.where(SKIN[mp] & (mp != 0), mp, np.where(SKIN[lp] & (lp != 0), lp, SLEEVE_SKIN[sb]))
    px = np.where(arms, armpx, px)
    # short sleeves: the top runs down each arm from where it meets the arm
    # highest (the shoulder, not a hand on the chest)
    alab, an = ndimage.label(arms, RING)
    near_t = ndimage.binary_dilation(torso, RING)
    rows = np.arange(px.shape[0])[:, None]
    for k in range(1, an + 1):
        comp = alab == k
        join = comp & near_t
        if not join.any():
            continue
        sl = join & (rows <= np.nonzero(join)[0].min() + 1)
        for _ in range(SLEEVE):
            sl = sl | (ndimage.binary_dilation(sl, RING) & comp)
        px = np.where(sl, np.where(suit, cb, BROWN_BY_LUM[mp]), px)
    # back onto the brown frame's anchor: grow evenly sideways and upward
    # only (what falls below its bottom row is cut)
    px = px[:pad + h]
    ys, xs = np.nonzero(px)
    if not len(ys):
        return None, (fit_m, fit_l)
    e = max(0, pad - xs.min(), xs.max() + 1 - (pad + w))
    return px[min(ys.min(), pad):, pad - e:pad + w + e], (fit_m, fit_l)


def build(suit, brown, arms, legs, code):
    """the mixed .frm for one animation, how many frames kept the brown suit,
    and the worst fit; None when the armours lack it or match it poorly"""
    A, L = donor_frames(arms, code), donor_frames(legs, code)
    if not A or not L:
        return None
    S = read_frm(son.vfs.read(f"art\\critters\\{suit}{code}.frm"))
    B = read_frm((CRIT / f"{brown}{code}.frm").read_bytes())
    done = []
    for o, row in B["blocks"].items():
        d = B["offs"].index(o)
        srow = S["blocks"][S["offs"][d]]
        for f, fr in enumerate(row):
            bp = fr[4]
            if d not in A or d not in L or f >= len(srow) or srow[f][4].shape != bp.shape:
                done.append((fr, None, 0.0))
                continue
            px, fit = mix(srow[f][4], bp, A[d], L[d], f)
            done.append((fr, px, min(fit)))
    if not done or sum(fit < POOR_FIT for _fr, _px, fit in done) > len(done) / 2 \
            or any(px is None or fit < KEEP_FIT for _fr, px, fit in done):
        return None
    kept = 0
    for fr, px, fit in done:
        if px is None or fit < KEEP_FIT:
            kept += 1
            continue
        fr[0], fr[1], fr[4] = px.shape[1], px.shape[0], px
    return write_frm(B), kept, min(fit for _fr, _px, fit in done)


def _job(job):
    i, code = job
    suit, brown, arms, legs, ours = SETS[i]
    return i, code, build(suit, brown, arms, legs, code)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--preview", type=Path, help="write a before/after sheet and stop")
    ap.add_argument("--only", help="comma list of animation codes (for testing)")
    ap.add_argument("--jobs", type=int, default=max(1, (os.cpu_count() or 2) - 1), help="worker processes")
    args = ap.parse_args()
    if args.preview:
        return preview(args.preview)
    jobs = []
    for i, (suit, brown, arms, legs, ours) in enumerate(SETS):
        codes = sorted({p.name[len(brown):len(brown) + 2] for p in CRIT.glob(f"{brown}*.frm")})
        if args.only:
            codes = [c for c in codes if c in args.only.split(",")]
        jobs += [(i, c) for c in codes]
    with multiprocessing.Pool(args.jobs) as pool:
        results = pool.map(_job, jobs, chunksize=1)
    rows = []
    for i, (suit, brown, arms, legs, ours) in enumerate(SETS):
        mixed, copied = 0, []
        for _i, code, got in (r for r in results if r[0] == i):
            dst = CRIT / f"{ours}{code}.frm"
            if got is None:
                dst.write_bytes((CRIT / f"{brown}{code}.frm").read_bytes())
                copied.append(code)
                continue
            data, kept, worst = got
            dst.write_bytes(data)
            mixed += 1
            print(f"  {ours}{code}: worst fit {worst:.2f}" + (f", {kept} frame(s) kept the brown suit" if kept else ""))
        print(f"{ours}: {mixed} mixed, {len(copied)} copied from {brown} ({' '.join(copied)})")
        for src, path, name, what in (("sonora", f"art\\critters\\{suit}*", suit, "top (via " + brown + ")"),
                                      ("fo2", f"art\\critters\\{arms}*", arms, "bare arms"),
                                      ("fo2", f"art\\critters\\{legs}*", legs, "trousers and boots")):
            rows.append(port.ledger_row(src, "art", path, name, f"mod/data/art/critters/{ours}*", ours,
                                        f"player sprite: brown vault-suit top with short sleeves, metal-armour bare arms, "
                                        f"leather-armour legs; this source gives the {what} (pc_mix.py)"))
    have = {(r["source"], r["source_id"], r["dest_path"]) for r in port.read_ledger()}
    port.append_ledger([r for r in rows if (r["source"], r["source_id"], r["dest_path"]) not in have])
    return 0


def preview(out: Path) -> int:
    from PIL import Image, ImageDraw
    from extract_pc_anims import decode_frm_all_dirs, load_palette
    rgba = load_palette(son)
    cells = []
    for suit, brown, arms, legs, ours in SETS:
        for code, d in (("aa", 2), ("aa", 0), ("ab", 1), ("ja", 2), ("ka", 2), ("ba", 2)):
            got = build(suit, brown, arms, legs, code)
            if got is None:
                continue
            for tag, data in (("before", (CRIT / f"{brown}{code}.frm").read_bytes()), ("after", got[0])):
                ds, _ = decode_frm_all_dirs(data, rgba)
                f = ds[d][len(ds[d]) // 2].img
                cells.append((f"{ours[:2]} {code} d{d} {tag}", f.resize((f.width * 3, f.height * 3), Image.NEAREST)))
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
