#!/usr/bin/env python3
"""
pc_sonora.py - the player sprites (hmpbrn / hfpbrn) from Fallout: Sonora's
vault dwellers (hmjmps / hfjmps), the blue jumpsuit recoloured brown.

    python tools/pc_sonora.py --preview out.png    # before/after sheet, writes nothing
    python tools/pc_sonora.py                      # write the FRMs, the ledger rows

Owner, 2026-10-21: a plain-backed suit (Sonora's has no 13 and no skull on
the back), brown. Sonora's male has 124 of the player's 127 animations (not
jump and climb-stairs, which the engine never plays, or the spear's swing,
which spears don't use), the female 115 (also not the special deaths:
critters.lst's alias, vanilla hmjmps, covers the electrified and burned ones,
and the others fall back to an ordinary death).

Palette-index swap; no pixel moves, headers are untouched. The suit is every
blue in the palette (hue 195-255): Nevada's black-suit sprite was drawn over
vanilla's blue one and recoloured every one of those blues in every armed
frame, so no gun, holster, skin or belt pixel uses them. Each blue maps, by
brightness and keeping the shading order, onto the palette's browns
(hue 20-34), a shade brighter so a dark blue reads as brown and not black.

The yellow belt and the trim down the front are taken out (owner,
2026-10-21: "I don't need the belt to be present at all"): each of their
pixels takes the most common brown among the suit pixels around it, filling
inward from the edges, so the fabric runs straight through. With no belt to
show, every golden colour (hue 30-65) touching it is taken in as well, and
only skin (redder than hue 30) stays a hand. --belt with a
name from BELT_COLOURS instead gives the belt that colour in three tones by
brightness (an edge, the belt, the glints).

Gold is not only the suit's: flames and sparks in the burning and
electrified deaths and parts of the minigun and rocket launcher are gold
too. So per frame a patch of gold (8-connected) is the suit's when at least
BELT_SHARE of its pixels are within BELT_NEAR px of the suit's blue, and only
those patches change. Sonora also shades the belt with yellow-greens, pale
beiges and dark golds: every colour that, in the unarmed frames, is mostly
(BELT_COMPANION_SHARE) found right next to the belt joins it wherever it
touches the belt, except the skin-like beiges, which join only where most of
their neighbours are belt (FILL_NEIGHBOURS), so a hand on the hip stays a
hand.

Neither set has RPU's extra rifle, wakizashi and lightsaber animations;
tools/pc_weapon_anims.py points those weapons at vanilla's.
"""

from __future__ import annotations

import argparse
import colorsys
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
from scipy import ndimage  # noqa: E402

import port  # noqa: E402
from pc_jumpsuit import file_dir_of, frames_of, nevada_files  # noqa: E402

ROOT = port.ROOT
CRIT = ROOT / "mod" / "data" / "art" / "critters"
PAIRS = (("hmjmps", "hmpbrn"), ("hfjmps", "hfpbrn"))
CYCLE_FROM = 229
LIFT = 1.15           # brown a shade brighter than the blue it replaces
LIFT_ADD = 4
BELT_NEAR = 2         # px from the suit's blue
BELT_SHARE = 0.6      # of a gold patch's pixels that must be that close
# (edge, belt, glint), darkest first
BELT_COLOURS = {
    "leather": [227, 204, 206],      # dark leather brown
    "oxblood": [195, 194, 193],
    "suit": [206, 123, 122],         # the suit's own brown
    "black": [207, 15, 13],
    "olive": [95, 75, 74],
    "tan": [206, 121, 120],
}
EDGE_LUM, GLINT_LUM = 70, 190
SUIT_MID = 110               # a mid blue of the suit: its brown fills a belt pixel with no suit near
BELT_COMPANION_SHARE = 0.6   # of a colour's pixels next to the belt, in unarmed frames
FILL_NEIGHBOURS = 3          # belt neighbours (of 8) for a skin-like beige to count as belt


def load_pal(src) -> np.ndarray:
    raw = src.vfs.read("color.pal")
    return np.array([[(raw[i * 3 + c] << 2) | (raw[i * 3 + c] >> 4) for c in range(3)]
                     for i in range(256)], float)


def hue_sat(rgb):
    h, s, _v = colorsys.rgb_to_hsv(*(np.asarray(rgb) / 255))
    return h * 360, s


def brown_table(pal: np.ndarray):
    """palette index -> brown for every suit blue (identity elsewhere), and the blues."""
    lum = pal.mean(1)
    blues, browns = [], []
    for i in range(1, CYCLE_FROM):
        h, s = hue_sat(pal[i])
        if 195 <= h <= 255 and s >= 0.25 and lum[i] >= 8:
            blues.append(i)
        if 20 <= h <= 34 and 0.30 <= s <= 0.72 and 10 <= lum[i] <= 150:
            browns.append(i)
    browns.sort(key=lambda k: lum[k])
    blum = lum[browns]
    table = np.arange(256, dtype=np.uint8)
    floor = 0
    for i in sorted(blues, key=lambda k: lum[k]):
        want = lum[i] * LIFT + LIFT_ADD
        k = max(int(np.abs(blum - want).argmin()), floor)
        table[i], floor = browns[k], k
    return table, blues


def is_skinlike(rgb, lum) -> bool:
    h, s = hue_sat(rgb)
    return 15 <= h <= 36 and s >= 0.35 and lum >= 100


def golds_of(pal: np.ndarray) -> list[int]:
    lum = pal.mean(1)
    out = []
    for i in range(1, CYCLE_FROM):
        h, s = hue_sat(pal[i])
        if 38 <= h <= 65 and s >= 0.45 and lum[i] >= 15:
            out.append(i)
    return out


def belt_patches(px, gold, blue):
    """the frame's gold patches that belong to the suit"""
    g = gold[px]
    if not g.any():
        return g
    near = ndimage.binary_dilation(blue[px], iterations=BELT_NEAR)
    lab, n = ndimage.label(g, structure=np.ones((3, 3), bool))
    share = ndimage.mean(near, lab, range(1, n + 1))
    keep = np.zeros(n + 1, bool)
    keep[1:] = np.asarray(share) >= BELT_SHARE
    return keep[lab]


def companions(src, pal, gold, blue):
    """(colours that go with the belt, skin-like ones among them) as masks"""
    from collections import Counter
    lum = pal.mean(1)
    near, total = Counter(), Counter()
    ring = np.ones((3, 3), bool)
    for base, _ours in PAIRS:
        for f in nevada_files(src, base):
            if f.split("\\")[-1][6:7].lower() != "a":
                continue
            data = src.vfs.read(f)
            for _d, frs in frames_of(data, file_dir_of(f)):
                for s, w, h in frs:
                    px = np.frombuffer(data[s:s + w * h], np.uint8).reshape(h, w)
                    m = belt_patches(px, gold, blue)
                    adj = ndimage.binary_dilation(m, structure=ring) & ~m & (px != 0)
                    near.update(px[adj].tolist())
                    total.update(px[px != 0].tolist())
    comp = np.zeros(256, bool)
    skin = np.zeros(256, bool)
    for i, n in near.items():
        if n >= 30 and n >= BELT_COMPANION_SHARE * total[i] and not gold[i] and not blue[i]:
            comp[i] = True
            skin[i] = is_skinlike(pal[i], lum[i])
    return comp, skin


def belt_table(pal: np.ndarray, colour: str) -> np.ndarray:
    """palette index -> the belt colour's tone for that brightness"""
    lum = pal.mean(1)
    edge, main, glint = BELT_COLOURS[colour]
    return np.array([edge if lum[i] < EDGE_LUM else (glint if lum[i] > GLINT_LUM else main)
                     for i in range(256)], np.uint8)


def fill_from_suit(out: np.ndarray, m: np.ndarray, suit: np.ndarray, mid: int) -> np.ndarray:
    """the belt's pixels take the commonest brown of the suit around them,
    growing inward ring by ring; any left over (no suit near) the mid brown"""
    from collections import Counter
    out = out.copy()
    todo = m.copy()
    src = suit & ~m
    h, w = out.shape
    while todo.any():
        newly = []
        for y, x in zip(*np.nonzero(todo)):
            vals = [out[yy, xx] for yy in range(max(0, y - 1), min(h, y + 2))
                    for xx in range(max(0, x - 1), min(w, x + 2)) if src[yy, xx]]
            if vals:
                newly.append((y, x, Counter(vals).most_common(1)[0][0]))
        if not newly:
            break
        for y, x, v in newly:
            out[y, x] = v
            src[y, x] = True
            todo[y, x] = False
    out[todo] = mid
    return out


def recolor(data: bytes, table: np.ndarray, file_dir, belt=None) -> bytes:
    """belt: (belt table, gold, blue, companions, skin-like companions) masks,
    or None to leave the gold."""
    buf = bytearray(data)
    for _d, frs in frames_of(data, file_dir):
        for s, w, h in frs:
            px = np.frombuffer(data[s:s + w * h], np.uint8).reshape(h, w)
            out = table[px]
            if belt is not None:
                btab, gold, blue, comp, skin = belt
                m = belt_patches(px, gold, blue)
                if m.any():
                    ring = np.ones((3, 3), bool)
                    c = comp[px] & ~skin[px]
                    for _ in range(2):        # a shading colour touching the belt, twice over
                        m = m | (ndimage.binary_dilation(m, structure=ring) & c)
                    nb = ndimage.convolve(m.astype(np.int16), np.ones((3, 3), np.int16), mode="constant") - m
                    m = m | (skin[px] & (nb >= FILL_NEIGHBOURS))
                    if btab is None:
                        out = fill_from_suit(out, m, blue[px], table[SUIT_MID])
                    else:
                        out = np.where(m, btab[px], out)
            buf[s:s + w * h] = out.astype(np.uint8).tobytes()
    return bytes(buf)


def preview(src, table, belt, out: Path) -> None:
    from PIL import Image, ImageDraw
    from extract_pc_anims import decode_frm_all_dirs, load_palette
    rgba = load_palette(src)
    cells = []
    for base in ("hmjmps", "hfjmps"):
        for code, dirs in (("aa", (2, 0, 5)), ("ab", (1, 4)), ("ha", (2,)), ("ja", (2, 5)),
                           ("kj", (2,)), ("ia", (0, 3)), ("bb", (2,))):
            p = f"art\\critters\\{base}{code}.frm"
            if not src.vfs.exists(p):
                continue
            raw = src.vfs.read(p)
            for tag, data in (("before", raw), ("after", recolor(raw, table, None, belt))):
                ds, _ = decode_frm_all_dirs(data, rgba)
                for d in dirs:
                    if d in ds:
                        f = ds[d][len(ds[d]) // 2].img
                        cells.append((f"{base[:2]} {code} d{d} {tag}", f.resize((f.width * 3, f.height * 3), Image.NEAREST)))
    cols = 8
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
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--preview", type=Path, help="write a before/after sheet and stop")
    ap.add_argument("--belt", choices=["none"] + sorted(BELT_COLOURS), default="none",
                    help="none (the default, the owner's pick): no belt, the suit's brown; or the belt's colour")
    args = ap.parse_args()

    src = port.open_source("sonora")
    pal = load_pal(src)
    table, blues = brown_table(pal)
    golds = golds_of(pal)
    blue_m = np.zeros(256, bool)
    blue_m[blues] = True
    gold_m = np.zeros(256, bool)
    gold_m[golds] = True
    comp, skin = companions(src, pal, gold_m, blue_m)
    print("blue -> brown:", ", ".join(f"{i}->{table[i]}" for i in blues))
    print("belt: golds", golds, "shading", list(np.nonzero(comp & ~skin)[0]), "skin-like", list(np.nonzero(skin)[0]))
    if args.belt == "none":
        # with no belt left, any golden colour touching it goes too (the
        # belt's highlights the game also uses elsewhere); skin is redder
        lum = pal.mean(1)
        for i in range(1, CYCLE_FROM):
            h, sat = hue_sat(pal[i])
            if 30 <= h <= 65 and sat >= 0.3 and lum[i] >= 50 and not blue_m[i]:
                comp[i] = True
            if skin[i] and h >= 30:
                skin[i] = False
    belt = (None if args.belt == "none" else belt_table(pal, args.belt), gold_m, blue_m, comp, skin)
    if args.preview:
        preview(src, table, belt, args.preview)
        return 0

    rows = []
    for son_base, ours in PAIRS:
        n = 0
        for f in nevada_files(src, son_base):
            name = f.split("\\")[-1].lower()
            dst = CRIT / (ours + name[len(son_base):])
            dst.write_bytes(recolor(src.vfs.read(f), table, file_dir_of(name), belt))
            n += 1
        print(f"  {son_base} -> {ours}: {n} files")
        rows.append(port.ledger_row("sonora", "art", f"art\\critters\\{son_base}*", son_base,
                                    f"mod/data/art/critters/{ours}*", ours,
                                    "player sprite: Sonora's vault suit (plain back), blue recoloured brown, " + ("no belt" if args.belt == "none" else f"belt {args.belt}") + " (pc_sonora.py)"))
    have = {(r["source"], r["dest_path"]) for r in port.read_ledger()}
    port.append_ledger([r for r in rows if (r["source"], r["dest_path"]) not in have])
    return 0


if __name__ == "__main__":
    sys.exit(main())
