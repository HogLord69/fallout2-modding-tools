#!/usr/bin/env python3
"""
pc_yesterday.py - the male player sprite (hmpcot) from Fallout: Yesterday's
hmsmpl (a man in a T-shirt and jeans, every player animation), recoloured to
the owner's outfit: dusty yellow-white T-shirt, olive-brown pants. Skin,
hair, belt, boots and every held weapon keep hmsmpl's own colours.

    python tools/pc_yesterday.py              # recolour into build/pc_yesterday (nothing installed)
    python tools/pc_yesterday.py --install    # back up hmpcot*, replace it, deploy

Why hmsmpl as-is (owner, 2026-09-28): recolouring or re-mapping clothes onto
the jumpsuit sprites never came out clean, and hmsmpl's own action
animations are different moves from vanilla's, so its clothing layout cannot
be carried onto vanilla frames. hmsmpl is ~20% bulkier than vanilla men.

Palette-index changes only; no pixel moves, headers untouched.

WHICH PIXELS. The jeans are the sprite's only blue (hue 200-250). The shirt's
colours (light and warm greys) are also used by gun metal, so the shirt is
found by place as well as colour: the frame's big light patches, closed and
hole-filled so the folds' shadows count, and only shirt colours inside that.
A gun outside the shirt is untouched; small blue bits are
recoloured too (legs cut into pieces by arms and guns; no weapon uses blue).

COLOUR. Fixed brightness curves onto single-hue palette ramps (hmsmpl draws
its clothes consistently, so no per-frame ranking is needed):
  shirt  -> SHIRT_RAMP (dusty yellow-white, hue 30-39)
  jeans  -> PANTS_RAMP (olive-brown, hue 30-40)
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
STAGE = ROOT / "build" / "pc_yesterday" / "art" / "critters"
SRC_BASE, OUR_BASE = "hmsmpl", "hmpcot"

# Shirt and pants: vanilla's suit is shaded in six blocky steps (its blues 47,
# 46, 111, 110, 109, 108 cover 20/13/24/23/18/2% of it), where hmsmpl blends
# ~15 shades smoothly - the glossy look. Each frame's shirt and pants are
# ranked and cut into six steps in vanilla's proportions.
STEP_SHARES = [0.20, 0.13, 0.24, 0.23, 0.18, 0.02]
SHIRT_STEPS = [120, 119, 222, 170, 169, 221]            # dusty yellow-white, hue 31-52
PANTS_STEPS = [202, 204, 78, 206, 225, 77]              # dark olive-brown (202 = shadow grey)
# Outline: the cream shirt ran light right to the silhouette and softened
# the figure's edge; the outermost ring of recoloured pixels goes this many
# steps darker (vanilla's edge is darker than its inside).
RING_STEPS = {"shirt": 2, "pants": 1, "skin": 2}
# Less muscular (owner, 2026-09-28):
#   SOFTEN  - each shirt/skin pixel takes the most common shade among its 3x3
#             neighbours of the same material, SOFTEN_PASSES times: the small
#             highlight/shadow blobs that draw abs, pecs and biceps melt away.
#   THIN    - the outermost pixel of the shirt and bare arms, where it meets
#             the background, is removed (only where the part is at least
#             THIN_MIN_WIDTH wide, so fingers and thin sleeves survive); the new
#             edge then gets the darker outline.
SOFTEN = False
SOFTEN_PASSES = 2
THIN = False
THIN_MIN_WIDTH = 4
THIN_PX = 1                    # pixels shaved per side

# Skin: hmsmpl's is darker and far more contrasty than vanilla's (median
# brightness 74 vs 107, a quarter of it in deep muscle shadow at 40), which is
# most of its glossy "bodybuilder render" look. Each frame's skin is ranked and
# mapped onto vanilla HMJMPS's own tan skin tones with vanilla's spread
# (brightness at the 0/5/25/50/75/95/100th percentile, measured 2026-09-28).
SKIN_RAMP = [206, 123, 203, 122, 121, 173, 159, 172, 157, 144]
SKIN_TARGET = ([0, .05, .25, .5, .75, .95, 1], [50, 56, 81, 107, 124, 171, 178])
# the colours hmsmpl's bare skin is drawn in (unarmed stand/walk/punch, >0.3% each)
HMSMPL_SKIN = [226, 204, 206, 124, 123, 203, 122, 121, 205, 173, 120, 160, 172]
SKIN_CORE_LUM = 70            # clearly skin; darker skin-hued pixels count only next to it
SKIN_REACH = 2

SHIRT_MIN_LUM, SHIRT_MAX_SAT = 60, 0.35
LIGHT_LUM = 95                 # the patches the shirt is grown from
LIGHT_MIN_PX = 12
WARM_MIN_SAT = 0.10
NEUTRAL_WINDOW, NEUTRAL_WARM_SHARE = 5, 0.2   # neutral greys need this much warm shirt around them
JEANS_MIN_PX = 1              # every blue bit: small ones are legs cut up by arms and guns
K3 = np.ones((3, 3), bool)


def load_pal(src) -> np.ndarray:
    raw = src.vfs.read("color.pal")
    return np.array([[(raw[i * 3 + c] << 2) | (raw[i * 3 + c] >> 4) for c in range(3)]
                     for i in range(256)], float)


def palette_info(pal):
    lum = pal.mean(1)
    hsv = np.array([colorsys.rgb_to_hsv(*(pal[i] / 255)) for i in range(256)])
    hue, sat = hsv[:, 0] * 360, hsv[:, 1]
    usable = np.zeros(256, bool)
    usable[1:229] = True                      # no transparent 0, no colour cycling
    jeans = usable & (hue >= 200) & (hue <= 250) & (sat >= 0.3)
    skin = usable & (hue >= 15) & (hue <= 35) & (sat >= .35) & (sat <= .75) & (lum >= 70) & (lum <= 200)
    shirt = usable & (lum >= SHIRT_MIN_LUM) & (sat <= SHIRT_MAX_SAT) & ~skin & ~jeans
    # the shirt's own colours are warm (tan, pinkish greys); gun metal is neutral
    warm = shirt & (sat >= WARM_MIN_SAT) & ((hue <= 60) | (hue >= 330))
    light = warm & (lum >= LIGHT_LUM)

    skin_hue = np.zeros(256, bool)
    skin_hue[HMSMPL_SKIN] = True
    skin_core = skin_hue & (lum >= SKIN_CORE_LUM)
    return dict(jeans=jeans, shirt=shirt, warm=warm, light=light, lum=lum,
                skin_hue=skin_hue, skin_core=skin_core)


def step_map(vals: np.ndarray, steps: list[int], shares: list[float], lum) -> np.ndarray:
    """256-entry table: each source index in `vals` goes to the step its
    brightness rank falls in, the steps taking `shares` of the pixels."""
    table = np.arange(256, dtype=np.uint8)
    if vals.size == 0:
        return table
    idx, cnt = np.unique(vals, return_counts=True)
    order = np.argsort(lum[idx], kind="stable")
    idx, cnt = idx[order], cnt[order]
    q = (np.cumsum(cnt) - cnt / 2) / cnt.sum()
    edges = np.cumsum(shares)[:-1]
    for i, qq in zip(idx, q):
        table[i] = steps[int(np.searchsorted(edges, qq))]
    return table


def soften(out: np.ndarray, mask: np.ndarray, ramp: list[int]) -> None:
    """Majority filter in place: each pixel of `mask` takes the ramp shade most
    common among its 3x3 neighbours in `mask` (keeping its own on a tie)."""
    if not mask.any():
        return
    pos = {c: k for k, c in enumerate(ramp)}
    for _ in range(SOFTEN_PASSES):
        idx = np.vectorize(lambda c: pos.get(int(c), -1))(out)
        m = mask & (idx >= 0)
        counts = np.stack([ndimage.convolve(((idx == k) & m).astype(int), np.ones((3, 3), int), mode="constant")
                           for k in range(len(ramp))])
        best = counts.argmax(0)
        own = np.take_along_axis(counts, np.clip(idx, 0, None)[None], 0)[0]
        change = m & (counts.max(0) > own)
        out[change] = np.array(ramp, np.uint8)[best[change]]


def darker(out: np.ndarray, mask: np.ndarray, ramp: list[int], n: int) -> None:
    """Move the pixels in `mask` n places down `ramp` (in place)."""
    pos = {c: k for k, c in enumerate(ramp)}
    for y, x in zip(*np.nonzero(mask)):
        k = pos.get(int(out[y, x]))
        if k is not None:
            out[y, x] = ramp[max(0, k - n)]


def rank_map(vals: np.ndarray, ramp: list[int], target, lum) -> np.ndarray:
    """256-entry table: each source index in `vals` goes to the ramp colour at
    its brightness rank within `vals` (shading order kept)."""
    table = np.arange(256, dtype=np.uint8)
    if vals.size == 0:
        return table
    idx, cnt = np.unique(vals, return_counts=True)
    order = np.argsort(lum[idx], kind="stable")
    idx, cnt = idx[order], cnt[order]
    q = (np.cumsum(cnt) - cnt / 2) / cnt.sum()
    rl = lum[ramp]
    floor = 0
    for i, qq in zip(idx, q):
        k = max(int(np.abs(rl - np.interp(qq, *target)).argmin()), floor)
        table[i], floor = ramp[k], k
    return table


def dress(px: np.ndarray, P) -> np.ndarray:
    out = px.copy()
    lum = P["lum"]
    none = np.zeros(px.shape, bool)
    sk, jm, sm = none, none, none
    # skin: vanilla's tones and spread (see SKIN_RAMP)
    core = P["skin_core"][px]
    if core.any():
        sk = P["skin_hue"][px] & ndimage.binary_dilation(core, structure=K3, iterations=SKIN_REACH)
        out[sk] = rank_map(px[sk], SKIN_RAMP, SKIN_TARGET, lum)[px[sk]]
    # jeans: every blue bit, in vanilla's six steps
    jm = P["jeans"][px]
    lab, n = ndimage.label(jm, structure=K3)
    if n:
        sizes = np.bincount(lab.ravel())
        sizes[0] = 0
        jm = sizes[lab] >= JEANS_MIN_PX
        out[jm] = step_map(px[jm], PANTS_STEPS, STEP_SHARES, lum)[px[jm]]
    # shirt: grown from its warm light patches only (a gun's neutral metal can
    # touch the shirt but never seeds it); inside that area every warm shirt
    # colour counts, and a neutral grey only where warm shirt surrounds it
    lm = P["light"][px]
    lab, n = ndimage.label(lm, structure=K3)
    if n:
        sizes = np.bincount(lab.ravel())
        sizes[0] = 0
        big = sizes[lab] >= max(LIGHT_MIN_PX, 0.2 * sizes.max())
        area = ndimage.binary_fill_holes(ndimage.binary_closing(big, structure=K3) | big)
        area = ndimage.binary_dilation(area, structure=K3) & (px != 0)
        warm = P["warm"][px]
        warm_near = ndimage.uniform_filter(warm.astype(float), NEUTRAL_WINDOW) >= NEUTRAL_WARM_SHARE
        sm = area & (warm | (P["shirt"][px] & warm_near))
        out[sm] = step_map(px[sm], SHIRT_STEPS, STEP_SHARES, lum)[px[sm]]
    if SOFTEN:
        soften(out, sm, SHIRT_STEPS)
        soften(out, sk, SKIN_RAMP)
    for _ in range(THIN_PX if THIN else 0):
        body0 = (out != 0) & (out != 228)
        edge = body0 & ndimage.binary_dilation(out == 0, structure=K3)
        removed = np.zeros_like(body0)
        for part in (sm, sk):
            if part.any():
                wide = ndimage.binary_dilation(
                    ndimage.binary_opening(part, structure=np.ones((THIN_MIN_WIDTH, THIN_MIN_WIDTH), bool)),
                    structure=K3)
                removed |= edge & part & wide
        out[removed] = 0
        sm, sk = sm & ~removed, sk & ~removed
    # outline: the outermost ring of the figure (shadow dither excluded),
    # where it is recoloured clothing or skin, a few steps darker
    body = (out != 0) & (out != 228)
    tp = np.pad(~body, 1, constant_values=True)
    body &= (tp[:-2, 1:-1].astype(int) + tp[2:, 1:-1] + tp[1:-1, :-2] + tp[1:-1, 2:]) < 2
    ring = body & ~ndimage.binary_erosion(body, structure=K3)
    darker(out, ring & sm, SHIRT_STEPS, RING_STEPS["shirt"])
    darker(out, ring & jm, PANTS_STEPS, RING_STEPS["pants"])
    darker(out, ring & sk, SKIN_RAMP, RING_STEPS["skin"])
    return out


def frames_of(buf: bytes, single: bool):
    fpd = struct.unpack_from(">H", buf, 8)[0] or 1
    offs = struct.unpack_from(">6I", buf, 0x22)
    seen, out = set(), []
    for d in range(1 if single else 6):
        if d and offs[d] in seen:
            continue
        seen.add(offs[d])
        pos = 0x3E + offs[d]
        for _ in range(fpd):
            if pos + 12 > len(buf):
                break
            w, h, size = struct.unpack_from(">HHI", buf, pos)
            s = pos + 12
            if w and h and s + w * h <= len(buf):
                out.append((s, w, h))
            pos = s + size
    return out


def recolor(data: bytes, P, single: bool) -> bytes:
    buf = bytearray(data)
    for s, w, h in frames_of(data, single):
        px = np.frombuffer(data[s:s + w * h], np.uint8).reshape(h, w)
        buf[s:s + w * h] = dress(px, P).tobytes()
    return bytes(buf)


def source_files(src) -> list[str]:
    out = []
    for c in "abcdefghijklmnopqrst":
        for a in "abcdefghijklmnopqrstuvwxyz":
            for ext in ("frm", "fr0", "fr1", "fr2", "fr3", "fr4", "fr5"):
                p = f"art\\critters\\{SRC_BASE}{c}{a}.{ext}"
                if src.vfs.exists(p):
                    out.append(p)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--install", action="store_true",
                    help="replace mod/data/art/critters/hmpcot* with the staged set and deploy")
    args = ap.parse_args()

    src = port.open_source("yesterday")
    P = palette_info(load_pal(src))
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    files = source_files(src)
    for f in files:
        name = f.split("\\")[-1]
        code, ext = name[len(SRC_BASE):len(SRC_BASE) + 2], name.rsplit(".", 1)[1]
        dst = STAGE / f"{OUR_BASE}{code.upper()}.{ext.upper()}"
        dst.write_bytes(recolor(src.vfs.read(f), P, ext.lower() != "frm"))
    print(f"recoloured {len(files)} hmsmpl files -> {STAGE.relative_to(ROOT)}")
    if not args.install:
        return 0

    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup = ROOT / "_safety_backups" / f"pc_frm_{stamp}_yesterday"
    backup.mkdir(parents=True, exist_ok=True)
    old = sorted(CRIT.glob(f"{OUR_BASE}*"))
    new_codes = {p.name[len(OUR_BASE):len(OUR_BASE) + 2].lower() for p in STAGE.iterdir()}
    kept = []
    for p in old:
        shutil.copy2(p, backup / p.name)
        # an animation hmsmpl does not have (NA, the called-shot picture)
        # keeps the file it had rather than going missing
        if p.name[len(OUR_BASE):len(OUR_BASE) + 2].lower() in new_codes:
            p.unlink()
        else:
            kept.append(p.name)
    for p in sorted(STAGE.iterdir()):
        shutil.copy2(p, CRIT / p.name)
    print(f"  replaced hmpcot with {len(list(STAGE.iterdir()))} hmsmpl files; kept {kept or 'nothing'} "
          f"(no hmsmpl equivalent); old set backed up to {backup.relative_to(ROOT)}")
    row = port.ledger_row("yesterday", "art", f"art\\critters\\{SRC_BASE}*", SRC_BASE,
                          f"mod/data/art/critters/{OUR_BASE}*", OUR_BASE,
                          "male player sprite: Fallout: Yesterday hmsmpl, shirt/jeans recoloured (pc_yesterday.py)")
    have = {(r["source"], r["dest_path"]) for r in port.read_ledger()}
    if (row["source"], row["dest_path"]) not in have:
        port.append_ledger([row])
    port.regen_ledger_md()
    return subprocess.run([sys.executable, str(ROOT / "tools" / "deploy.py")], cwd=ROOT).returncode


if __name__ == "__main__":
    sys.exit(main())
