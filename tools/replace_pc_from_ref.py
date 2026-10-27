#!/usr/bin/env python3
"""
replace_pc_from_ref.py - Rebuild the PC model (hmpcot/hfpcot) from the restyled
green sheets in art/pc_grids/.

Every grid <CODE>.png is a restyle of the vanilla HMJMPS<CODE> sheet that
extract_pc_anims.py lays out (anchor=frame, scale 2, pad 2): the same
6-row x fpd-column layout, but resized (slightly non-uniformly) and with the
content drifting several px - the whole sheet usually sits ~10 px up-left, so
the first column's arm is clipped at the image edge, and the restyle both eats
key-green wedges into the figure and sprays white speckle around it.

Tight-cropping each green blob and rescaling it to a per-row height (the old
approach) sized every animation differently and let the feet wander, because
nothing tied a blob back to the frame it came from. This tool instead treats
the VANILLA frame as the geometric ground truth for its restyled twin:

  1. decode the vanilla FRM -> per-frame w/h/offsets and the exact rect each
     frame occupies on the vanilla sheet;
  2. map that rect onto the green sheet (sheet-proportional scale) and
     REGISTER it: slide the vanilla silhouette over the green key mask and
     keep the best IoU (two passes: wide search, then +-14 px around the
     family's median shift so a near-identical neighbour can't steal a cell);
  3. cut the registered rect plus a small margin (sides/top only - the bottom
     edge is the feet anchor the engine draws at) and resample it back to
     vanilla resolution, premultiplied, so every output frame has vanilla
     dimensions (+margin), vanilla offsets and its feet on the vanilla anchor.
     Sizing and alignment across frames AND families then match vanilla by
     construction;
  4. clean with the vanilla silhouette: drop anything outside its dilation
     (white speckle, a neighbour's limb), near-white outside the figure, and
     tiny islands; fill small enclosed holes; inpaint anything missing inside
     its erosion (the shoulder wedges, the clipped arm) from the nearest
     painted pixel;
  5. tone down to vanilla critter brightness and quantize to color.pal,
     skipping index 0 and the animated palette entries.

Families with no grid are the vanilla FRM recolored by make_pc_colonist
(--fallback recolor, default) - a placeholder until their sheets exist; the
.FR0-.FR5 split death poses always take that path. hfpcot* is a byte copy
of hmpcot* (one colonist model for both sexes).

Run:  python tools/replace_pc_from_ref.py [--only AA,HC] [--preview] [--fallback recolor|skip]
      --preview writes build/pc_preview/<CODE>.png (every frame on its anchor)
      and build/pc_preview/_lineup.png (frame 0 of every family, feet on one
      baseline) for eyeballing size/alignment.
"""
from __future__ import annotations

import argparse
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from foclib import GameIndex
from PIL import Image, ImageDraw
from scipy import ndimage
from scipy.signal import fftconvolve

import make_pc_colonist as recolor

ROOT = Path(__file__).resolve().parent.parent
CRIT_DIR = ROOT / "mod" / "data" / "art" / "critters"
GRID_DIR = ROOT / "art" / "pc_grids"
PREVIEW_DIR = ROOT / "build" / "pc_preview"

# extract_pc_anims.compose_sheet() layout constants the green sheets inherit
SHEET_PAD, SHEET_SCALE = 2, 2

# output frame = vanilla frame + this margin (vanilla px). Sides are symmetric
# so the engine's centred blit (left = x - w/2) needs no correction; the
# bottom gets none because the engine bottom-anchors the frame at the feet.
M_SIDE, M_TOP = 4, 4

# silhouette cleanup radii (vanilla px)
DILATE_ALLOW = 3      # keep restyle pixels this far outside the vanilla figure
NEAR = 1              # ... but only DARK ones beyond this: bright = backdrop haze
BRIGHT = 120          # luma above this outside NEAR is dropped (white between legs)
ERODE_MUST = 2        # inpaint anything missing this far inside it
MIN_ISLAND = 8        # drop disconnected islands smaller than this
MAX_HOLE = 12         # fill enclosed transparent holes up to this size
ALPHA_CUT = 0.35      # coverage below this after resampling = transparent

# The AI reference art sits ~2x brighter than vanilla FO2 critters (measured:
# hmpcot mean luma ~85 vs HMJMPS ~43, HMMAXX ~36). Pull it down before the
# palette lookup so the colonist reads at the same value as everyone else on
# the map. A mild gamma keeps the darkest pixels off pure black.
DARKEN, GAMMA = 0.62, 1.08

# color.pal entries the engine cycles at runtime (slime, monitors, fire,
# shoreline, alarm) - a critter pixel landing on one would flicker. 0 = clear.
PAL_SKIP = {0} | set(range(229, 256))


# ------------------------------------------------------------------ palette

def load_8bit_palette(gi):
    raw = gi.vfs.read("color.pal")
    pal = []
    for i in range(256):
        r, g, b = raw[i * 3], raw[i * 3 + 1], raw[i * 3 + 2]
        pal.append((min(255, (r << 2) | (r >> 4)),
                    min(255, (g << 2) | (g >> 4)),
                    min(255, (b << 2) | (b >> 4))))
    return pal


def green_indices(pal_rgb) -> set[int]:
    """Palette entries that read as green - the olive ramp around 70-74, 96."""
    p = np.array(pal_rgb, int)
    return set(np.nonzero((p[:, 1] > p[:, 0] + 18) & (p[:, 1] > p[:, 2] + 18))[0].tolist())


def make_index_table(pal_rgb, bits=5, skip_green=False):
    """RGB (quantized to `bits` per channel) -> nearest usable palette index.

    `skip_green` removes the green ramp from the lookup entirely, so a pixel
    can never land on it. That is what chroma-keyed art needs: an un-mixed
    edge pixel like (70,85,60) is not green enough to reject by threshold, yet
    still quantizes onto the olive ramp - 4372 of FA's 4597 stray pixels were
    exactly this, all on the silhouette edge. Excluding the ramp snaps them to
    the nearest neutral instead, which keeps the silhouette intact.
    """
    levels = 1 << bits
    skip = set(PAL_SKIP) | (green_indices(pal_rgb) if skip_green else set())
    usable = np.array([i for i in range(256) if i not in skip])
    pal = np.array(pal_rgb, np.int32)[usable]
    grid = (np.arange(levels) * 255) // (levels - 1)
    r, g, b = np.meshgrid(grid, grid, grid, indexing="ij")
    pts = np.stack([r.ravel(), g.ravel(), b.ravel()], 1)          # (L^3, 3)
    d = ((pts[:, None, :] - pal[None, :, :]) ** 2).sum(2)         # (L^3, N)
    return usable[d.argmin(1)].astype(np.uint8), levels


_TONE_LUT = np.array([max(0, min(255, int(((v / 255) ** GAMMA) * 255 * DARKEN)))
                      for v in range(256)], np.uint8)


def quantize(rgb: np.ndarray, alpha: np.ndarray, table, levels, tone: bool = True,
             drop_green: bool | None = None) -> bytes:
    """rgb uint8 (h,w,3), alpha bool (h,w) -> palette indices, 0 where clear.

    `tone` applies the AI-art darkening; off for art that is already final
    (pc_import.py round-tripping an exported sheet).
    `drop_green` rejects pixels that are still green-dominant after keying.
    It must be ON for anything that came off a #00FF00 backdrop, or a rim of
    spill survives into the palette - 11-14% of opaque pixels in the first
    in-game build. It must be OFF for clean transparent art, where it would
    eat legitimate greens (palette index 70). Defaults to `tone` only for
    backwards compatibility; pass it explicitly.
    """
    if drop_green is None:
        drop_green = tone
    r, g, b = rgb[..., 0].astype(int), rgb[..., 1].astype(int), rgb[..., 2].astype(int)
    # residual green fringe: a half-covered edge pixel that averaged to a
    # greenish grey. Nothing on the colonist is green-dominant.
    keep = alpha & ~((g > r + 18) & (g > b + 18)) if drop_green else alpha
    t = (_TONE_LUT[rgb] if tone else rgb).astype(int)
    ri = (t[..., 0] * (levels - 1)) // 255
    gi = (t[..., 1] * (levels - 1)) // 255
    bi = (t[..., 2] * (levels - 1)) // 255
    idx = table[(ri * levels + gi) * levels + bi].astype(np.uint8)
    if not tone and _EXACT is not None:
        # a pixel that IS a palette colour keeps its own index (lossless
        # round trip of an exported sheet) instead of the 5-bit nearest
        key = (t[..., 0] << 16) | (t[..., 1] << 8) | t[..., 2]
        pos = np.searchsorted(_EXACT[0], key)
        pos = np.clip(pos, 0, len(_EXACT[0]) - 1)
        hit = _EXACT[0][pos] == key
        idx[hit] = _EXACT[1][pos][hit]
    idx[~keep] = 0
    return idx.tobytes()


_EXACT = None       # (sorted 24-bit keys, matching palette indices)


def set_exact_palette(pal_rgb):
    global _EXACT
    # every index but 0, static entries first so a colour shared by a static
    # and an animated entry resolves to the static one; an exact hit on an
    # animated colour (vanilla fire/electric deaths) keeps its cycling index
    static = [i for i in range(1, 256) if i not in PAL_SKIP]
    anim = [i for i in range(1, 256) if i in PAL_SKIP]
    idx = np.array(static + anim)
    keys = np.array([(pal_rgb[i][0] << 16) | (pal_rgb[i][1] << 8) | pal_rgb[i][2] for i in idx],
                    np.int64)
    order = np.argsort(keys, kind="stable")
    keys, idx = keys[order], idx[order]
    first = np.ones(len(keys), bool)
    first[1:] = keys[1:] != keys[:-1]          # keep the first (static) of duplicates
    _EXACT = (keys[first], idx[first].astype(np.uint8))


# ------------------------------------------------------------------ FRM I/O

class Frame:
    __slots__ = ("w", "h", "sx", "sy", "px")

    def __init__(self, w, h, sx, sy, px):
        self.w, self.h, self.sx, self.sy, self.px = w, h, sx, sy, px

    @property
    def alpha(self) -> np.ndarray:
        return np.frombuffer(self.px, np.uint8).reshape(self.h, self.w) > 0


def decode_frm(data: bytes):
    version, fps, action, fpd = struct.unpack_from(">IHHH", data, 0)
    xo = list(struct.unpack_from(">6h", data, 0x0A))
    yo = list(struct.unpack_from(">6h", data, 0x16))
    offs = struct.unpack_from(">6I", data, 0x22)
    frames: dict[int, list[Frame]] = {}
    for d in range(6):
        if d > 0 and offs[d] == 0 and offs[0] == 0:
            break                              # single-direction FRM
        pos = 0x3E + offs[d]
        row = []
        for _ in range(fpd):
            if pos + 12 > len(data):
                break
            w, h, size, sx, sy = struct.unpack_from(">HHIhh", data, pos)
            if w == 0 or h == 0 or size == 0 or size > 0x2000000:
                break
            row.append(Frame(w, h, sx, sy, data[pos + 12: pos + 12 + w * h]))
            pos += 12 + size
        frames[d] = row
    return dict(version=version, fps=fps, action=action, fpd=fpd, xo=xo, yo=yo,
                frames=frames)


def encode_frm(meta, out_frames: dict[int, list[tuple[int, int, int, int, bytes]]],
               split: bool = False) -> bytes:
    """out_frames[d] = [(w, h, sx, sy, indices)]; header fields from `meta`.
    `split` writes a single-direction .FR0-.FR5 file (frames from slot 0, all
    six direction offsets 0, as vanilla does)."""
    header = struct.pack(">IHHH", meta["version"], meta["fps"], meta["action"], meta["fpd"])
    header += struct.pack(">6h", *meta["xo"]) + struct.pack(">6h", *meta["yo"])
    offsets, body = [], bytearray()
    for d in range(6):
        offsets.append(0 if split else len(body))
        if not split or d == 0:
            for w, h, sx, sy, px in out_frames.get(d, []):
                body += struct.pack(">HHIhh", w, h, w * h, sx, sy) + px
    header += struct.pack(">6I", *offsets) + struct.pack(">I", len(body))
    return header + bytes(body)


def sheet_layout(frames: dict[int, list[Frame]]):
    """Where extract_pc_anims put each frame on the vanilla sheet.

    Returns (cell_w, cell_h, place) with place[(d, f)] = (x, y) of the frame's
    top-left in sheet px (already x SHEET_SCALE). Mirrors compose_sheet():
    every cell has the feet anchor (bottom-centre of the frame) at one spot.
    """
    minx = miny = 10 ** 9
    maxx = maxy = -(10 ** 9)
    for row in frames.values():
        for fr in row:
            left, top = -(fr.w // 2), -fr.h
            minx, miny = min(minx, left), min(miny, top)
            maxx, maxy = max(maxx, left + fr.w), max(maxy, top + fr.h)
    cw = (maxx - minx) + 2 * SHEET_PAD
    ch = (maxy - miny) + 2 * SHEET_PAD
    place = {}
    for d, row in frames.items():
        for f, fr in enumerate(row):
            x = (f * cw + (-(fr.w // 2) - minx) + SHEET_PAD) * SHEET_SCALE
            y = (d * ch + (-fr.h - miny) + SHEET_PAD) * SHEET_SCALE
            place[(d, f)] = (x, y)
    return cw, ch, place


# ------------------------------------------------------------------ green sheet

class GreenSheet:
    """A restyled sheet: soft chroma-key alpha, de-spilled premultiplied colour."""

    def __init__(self, path: Path):
        rgb = np.asarray(Image.open(path).convert("RGB"), np.float32)
        self.h, self.w = rgb.shape[:2]
        r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
        # k = 255 on the pure #00FF00 key, ~0 on the figure (nothing on the
        # colonist is green-dominant). A half-covered edge pixel is a linear
        # mix, so alpha = 1 - k/255 recovers its coverage.
        k = np.clip(g - np.maximum(r, b), 20, 255)
        a = (255 - k) / (255 - 20)
        self.alpha = a
        self.mask = a > 0.5
        # un-mix the key out of partially covered pixels: c = a*s + (1-a)*key
        key = np.array([0, 255, 0], np.float32)
        s = (rgb - (1 - a)[..., None] * key) / np.maximum(a, 1e-3)[..., None]
        s = np.clip(s, 0, 255)
        s[a < 0.02] = 0
        prem = s * a[..., None]
        # transparent border so a frame hanging off the sheet edge (the
        # clipped first column) can still be cut; it gets inpainted later
        P = self.PAD
        prem = np.pad(prem, ((P, P), (P, P), (0, 0)))
        a = np.pad(a, P)
        self.chan = [Image.fromarray(np.ascontiguousarray(prem[..., i]), "F") for i in range(3)]
        self.chan.append(Image.fromarray(np.ascontiguousarray(a.astype(np.float32)), "F"))

    PAD = 128

    def cut(self, box, size):
        """Resample float `box` (x0,y0,x1,y1) to `size` -> (rgb uint8, alpha f32)."""
        P = self.PAD
        W, H = self.w + 2 * P, self.h + 2 * P
        box = (min(max(box[0] + P, 0), W - 1), min(max(box[1] + P, 0), H - 1),
               min(max(box[2] + P, 1), W), min(max(box[3] + P, 1), H))
        # colour with LANCZOS for crispness; alpha with BOX - LANCZOS' negative
        # lobes ring interior coverage below the cutoff (holes in the shirt).
        ch = [c.resize(size, Image.LANCZOS, box=box) for c in self.chan[:3]]
        a = np.asarray(self.chan[3].resize(size, Image.BOX, box=box), np.float32)
        a = np.clip(a, 0, 1)
        prem = np.stack([np.asarray(c, np.float32) for c in ch], -1)
        rgb = np.clip(prem / np.maximum(a, 1e-3)[..., None], 0, 255).astype(np.uint8)
        return rgb, a


def register(sheet: GreenSheet, exp_x: float, exp_y: float, vmask: np.ndarray, R: int,
             pull: float = 0.0):
    """Best (dx, dy, iou) sliding `vmask` (bool, green-px scale) over the key
    mask within +-R px of its expected top-left (exp_x, exp_y). `pull` docks
    the score by that much per px of shift, so a near-identical neighbour
    (idle frames) cannot out-score the expected spot on a tie."""
    vh, vw = vmask.shape
    x0, y0 = int(round(exp_x)) - R, int(round(exp_y)) - R
    x1, y1 = x0 + vw + 2 * R, y0 + vh + 2 * R
    win = np.zeros((y1 - y0, x1 - x0), np.float32)
    sx0, sy0 = max(0, x0), max(0, y0)
    sx1, sy1 = min(sheet.w, x1), min(sheet.h, y1)
    if sx1 > sx0 and sy1 > sy0:
        win[sy0 - y0: sy1 - y0, sx0 - x0: sx1 - x0] = sheet.mask[sy0:sy1, sx0:sx1]
    v = vmask.astype(np.float32)
    inter = fftconvolve(win, v[::-1, ::-1], mode="valid")
    gbox = fftconvolve(win, np.ones_like(v), mode="valid")
    iou = inter / (v.sum() + gbox - inter + 1e-6)
    score = iou
    if pull:
        yy, xx = np.mgrid[-R:R + 1, -R:R + 1]
        score = iou - pull * np.hypot(xx, yy)
    i, j = np.unravel_index(int(score.argmax()), score.shape)
    return j - R, i - R, float(iou[i, j])


# ------------------------------------------------------------------ build

_CROSS = np.array([[0, 1, 0], [1, 0, 1], [0, 1, 0]], np.int32)


def tidy_outline(rgb, alpha, protect, allowed):
    """Smooth the 1-px raggedness the key + silhouette cut leaves behind:
    fill a clear pixel with 3+ opaque 4-neighbours (a notch) from their
    median, then drop an opaque pixel with <=1 opaque 4-neighbour (a spur),
    twice. Pixels inside `protect` (the vanilla body) are never dropped, so
    1-px-thin things vanilla draws (the spear shaft) survive."""
    rgb = rgb.copy()
    alpha = alpha.copy()
    h, w = alpha.shape
    for _ in range(2):
        n4 = ndimage.convolve(alpha.astype(np.int32), _CROSS, mode="constant")
        notch = ~alpha & allowed & (n4 >= 3)
        for y, x in zip(*np.nonzero(notch)):
            y0, y1, x0, x1 = max(0, y - 1), min(h, y + 2), max(0, x - 1), min(w, x + 2)
            m = alpha[y0:y1, x0:x1]
            rgb[y, x] = np.median(rgb[y0:y1, x0:x1][m], axis=0)
        alpha |= notch
        n4 = ndimage.convolve(alpha.astype(np.int32), _CROSS, mode="constant")
        alpha &= ~((n4 <= 1) & ~protect)
    return rgb, alpha


def despeckle(rgb: np.ndarray, alpha: np.ndarray) -> np.ndarray:
    """Kill the restyle's white specks INSIDE the figure (a bright pixel on the
    trousers or a hand with at most 2 bright neighbours) by replacing it with
    the median of its opaque neighbours. Shirt pixels have bright neighbours
    all round and are untouched."""
    r32 = rgb.astype(np.int32)
    luma = (r32[..., 0] * 299 + r32[..., 1] * 587 + r32[..., 2] * 114) // 1000
    bright = (luma > 150) & alpha
    nb = ndimage.convolve(bright.astype(np.int32), np.ones((3, 3), np.int32),
                          mode="constant") - bright
    specks = bright & (nb <= 2)
    if not specks.any():
        return rgb
    out = rgb.copy()
    h, w = alpha.shape
    for y, x in zip(*np.nonzero(specks)):
        y0, y1, x0, x1 = max(0, y - 1), min(h, y + 2), max(0, x - 1), min(w, x + 2)
        m = alpha[y0:y1, x0:x1].copy()
        m[y - y0, x - x0] = False
        if m.any():
            out[y, x] = np.median(rgb[y0:y1, x0:x1][m], axis=0)
    return out


def _fit_axis(exp, got, good):
    """Robust least-squares got = s*exp + t over `good` cells (2 passes)."""
    e, g = np.array(exp, float), np.array(got, float)
    sel = np.array(good, bool)
    if sel.sum() < 3 or np.ptp(e[sel]) < 1:
        t = float(np.median(g[sel] - e[sel])) if sel.any() else 0.0
        return 1.0, t
    for _ in range(2):
        sc, t = np.polyfit(e[sel], g[sel], 1)
        res = np.abs(g - (sc * e + t))
        tol = max(6.0, 2.5 * np.median(res[sel]))
        sel = sel & (res <= tol)
        if sel.sum() < 3:
            break
    return float(sc), float(t)


def build_family(code: str, van: bytes, sheet: GreenSheet, table, levels, log):
    meta = decode_frm(van)
    frames = meta["frames"]
    fpd = meta["fpd"]
    cw, ch, place = sheet_layout(frames)
    vw, vh = cw * fpd * SHEET_SCALE, ch * 6 * SHEET_SCALE
    ax, ay = sheet.w / vw, sheet.h / vh            # naive: vanilla sheet px -> green px
    pitch = min(cw * SHEET_SCALE * ax, ch * SHEET_SCALE * ay)
    R1 = int(max(12, min(64, 0.45 * pitch)))
    R2 = int(max(14, min(40, 0.4 * pitch)))

    def scaled_mask(fr: Frame, sx, sy):
        gw, gh = max(1, round(fr.w * SHEET_SCALE * sx)), max(1, round(fr.h * SHEET_SCALE * sy))
        return np.asarray(Image.fromarray(fr.alpha).resize((gw, gh), Image.NEAREST), bool)

    # pass 1: wide search at the naive placement, then fit the sheet's real
    # affine (the restyle spreads columns/rows a little wider or narrower than
    # the canvas ratio says, and shifts the lot up-left)
    keys = sorted(place)
    ex, ey, gx, gy, ok = [], [], [], [], []
    wide = {}
    for (d, f) in keys:
        px, py = place[(d, f)]
        dx, dy, iou = register(sheet, px * ax, py * ay, scaled_mask(frames[d][f], ax, ay), R1)
        ex.append(px); ey.append(py)
        gx.append(px * ax + dx); gy.append(py * ay + dy)
        wide[(d, f)] = (px * ax + dx, py * ay + dy, iou)
        ok.append(iou > 0.4)
    if not any(ok):
        ok = [True] * len(keys)
    sx, tx = _fit_axis(ex, gx, ok)
    sy, ty = _fit_axis(ey, gy, ok)

    out: dict[int, list] = {d: [] for d in range(6)}
    ious, low = [], []
    for d in range(6):
        for f, fr in enumerate(frames.get(d, [])):
            px, py = place[(d, f)]
            X, Y = sx * px + tx, sy * py + ty
            vm = scaled_mask(fr, sx, sy)
            # the restyle drifts single sprites by 30+ px, so search wide, but
            # never far enough to reach the next cell (R2 < half the pitch)
            dx, dy, iou = register(sheet, X, Y, vm, R2, pull=0.002)
            if iou < 0.3:
                # the fit missed this sprite: take the wide pass-1 hit if it
                # was solid (a sprite the restyle threw far off), else the fit
                wx, wy, wiou = wide[(d, f)]
                if wiou > 0.5:
                    dx, dy, iou = wx - X, wy - Y, wiou
                else:
                    dx = dy = 0
            ious.append(iou)
            if iou < 0.45:
                low.append(f"d{d}f{f}:{iou:.2f}")

            ow, oh = fr.w + 2 * M_SIDE, fr.h + M_TOP
            box = (X - M_SIDE * SHEET_SCALE * sx + dx,
                   Y - M_TOP * SHEET_SCALE * sy + dy,
                   X + fr.w * SHEET_SCALE * sx + dx,
                   Y + fr.h * SHEET_SCALE * sy + dy)
            rgb, a = sheet.cut(box, (ow, oh))

            # vanilla silhouette on the output canvas
            van_a = np.zeros((oh, ow), bool)
            van_a[M_TOP:, M_SIDE:M_SIDE + fr.w] = fr.alpha
            allowed = ndimage.binary_dilation(van_a, iterations=DILATE_ALLOW)
            near = ndimage.binary_dilation(van_a, iterations=NEAR)
            must = ndimage.binary_erosion(van_a, iterations=ERODE_MUST)

            # adaptive coverage cut: lenient where vanilla has body (a soft
            # restyle edge still counts), strict in the ring outside it so the
            # outline does not grow ragged half-pixels
            alpha = ((a >= ALPHA_CUT * 0.6) & near) | ((a >= 0.6) & allowed)
            # backdrop haze / white speckle: the restyle paints pale stuff into
            # the gap between the legs and around the figure. Nothing bright
            # belongs more than NEAR px outside the vanilla silhouette.
            r32 = rgb.astype(np.int32)
            luma = (r32[..., 0] * 299 + r32[..., 1] * 587 + r32[..., 2] * 114) // 1000
            alpha &= ~((luma > BRIGHT) & ~near)
            # tiny islands
            lbl, n = ndimage.label(alpha)
            if n > 1:
                sizes = ndimage.sum(alpha, lbl, range(1, n + 1))
                small = [i + 1 for i, s in enumerate(sizes) if s < MIN_ISLAND]
                if small and len(small) < n:
                    alpha &= ~np.isin(lbl, small)
            # small enclosed holes (shirt speckle) - not the gap between legs
            holes = ndimage.binary_fill_holes(alpha) & ~alpha
            if holes.any():
                hl, hn = ndimage.label(holes)
                hs = ndimage.sum(holes, hl, range(1, hn + 1))
                alpha |= np.isin(hl, [i + 1 for i, s in enumerate(hs) if s <= MAX_HOLE])
            # inpaint what the restyle lost inside the figure (shoulder wedge,
            # arm clipped at the sheet edge) from the nearest painted pixel
            missing = must & ~alpha
            if missing.any() and alpha.any():
                iy, ix = ndimage.distance_transform_edt(~alpha, return_distances=False,
                                                        return_indices=True)
                rgb[missing] = rgb[iy[missing], ix[missing]]
                alpha |= missing

            rgb, alpha = tidy_outline(rgb, alpha, van_a, allowed)
            rgb = despeckle(rgb, alpha)
            out[d].append((ow, oh, fr.sx, fr.sy, quantize(rgb, alpha, table, levels)))
    log(f"  {code}: {fpd}f x {len(frames)}dir  scale x{sx:.3f} y{sy:.3f} (canvas {ax:.3f} {ay:.3f})"
        f"  shift ({tx:+.0f},{ty:+.0f})px  iou mean {np.mean(ious):.2f} min {np.min(ious):.2f}"
        + (f"  low: {' '.join(low)}" if low else ""))
    return encode_frm(meta, out), meta, out


# ------------------------------------------------------------------ fallback

# make_pc_colonist's recolor lands ~65 mean luma and redder than the AI frames
# (~45; rgb 54/46/40 vs 76/61/56). Pull it part-way down so a placeholder
# family does not pop when the weapon comes out. Going all the way (0.70)
# posterises: the palette has no dark browns, so the trousers turn black.
FALLBACK_TONE = (0.82, 0.85, 0.82)


def tone_lut(pal_rgb, table, levels) -> np.ndarray:
    """palette index -> palette index after FALLBACK_TONE (0 stays 0)."""
    rgb = np.array(pal_rgb, np.float32) * np.array(FALLBACK_TONE, np.float32)
    rgb = np.clip(rgb, 0, 255).astype(np.int32)
    q = (rgb * (levels - 1)) // 255
    lut = table[(q[:, 0] * levels + q[:, 1]) * levels + q[:, 2]].copy()
    lut[0] = 0
    return lut


def recolor_fallback(van: bytes, engine, lut: np.ndarray) -> bytes:
    """Vanilla FRM -> colonist recolor -> toned to the AI frames' value."""
    data = bytearray(recolor.splice(van, engine))
    for _di, pos, w, h, size, px in recolor.walk_frames(bytes(data)):
        n = min(size, w * h)
        idx = np.frombuffer(bytes(data[pos + 12: pos + 12 + n]), np.uint8)
        data[pos + 12: pos + 12 + n] = lut[idx].tobytes()
    return bytes(data)


# ------------------------------------------------------------------ preview

def render_frame(px: bytes, w: int, h: int, pal_rgb) -> Image.Image:
    idx = np.frombuffer(px, np.uint8).reshape(h, w)
    lut = np.array(pal_rgb + [(0, 0, 0)] * (256 - len(pal_rgb)), np.uint8)
    rgba = np.dstack([lut[idx], np.where(idx > 0, 255, 0).astype(np.uint8)])
    return Image.fromarray(rgba, "RGBA")


def preview_family(code: str, out_frames, pal_rgb, path: Path, scale=2):
    fpd = max(len(v) for v in out_frames.values())
    cw = max(f[0] for v in out_frames.values() for f in v) + 4
    ch = max(f[1] for v in out_frames.values() for f in v) + 4
    img = Image.new("RGBA", (cw * fpd * scale, ch * 6 * scale), (96, 96, 96, 255))
    dr = ImageDraw.Draw(img)
    for d in range(6):
        for f, (w, h, sx, sy, px) in enumerate(out_frames.get(d, [])):
            # anchor = bottom-centre of the cell
            ax_, ay_ = (f * cw + cw // 2) * scale, ((d + 1) * ch - 2) * scale
            fr = render_frame(px, w, h, pal_rgb).resize((w * scale, h * scale), Image.NEAREST)
            x, y = ax_ - (w // 2) * scale, ay_ - h * scale
            dr.rectangle([x, y, x + w * scale - 1, y + h * scale - 1], outline=(140, 140, 140, 255))
            img.alpha_composite(fr, (x, y))
            dr.line([ax_ - 3 * scale, ay_, ax_ + 3 * scale, ay_], fill=(255, 80, 80, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def preview_lineup(entries, pal_rgb, path: Path, scale=3):
    """frame 0, dir 2 of every family, feet on one baseline."""
    cell_w = max(e[1][0] for e in entries) + 6
    cell_h = max(e[1][1] for e in entries) + 12
    img = Image.new("RGBA", (cell_w * len(entries) * scale, cell_h * scale), (96, 96, 96, 255))
    dr = ImageDraw.Draw(img)
    base = (cell_h - 10) * scale
    dr.line([0, base, img.width, base], fill=(255, 80, 80, 255))
    for i, (code, (w, h, sx, sy, px)) in enumerate(entries):
        fr = render_frame(px, w, h, pal_rgb).resize((w * scale, h * scale), Image.NEAREST)
        x = (i * cell_w + cell_w // 2 - w // 2) * scale
        img.alpha_composite(fr, (x, base - h * scale))
        dr.text(((i * cell_w + 2) * scale, base + 2), code, fill=(255, 255, 0, 255))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


# ------------------------------------------------------------------ main

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma list of family codes to rebuild (e.g. AA,HC)")
    ap.add_argument("--preview", action="store_true", help="write build/pc_preview/*.png")
    ap.add_argument("--fallback", choices=["recolor", "skip"], default="recolor",
                    help="families with no grid: recolored vanilla (default) or leave deployed")
    args = ap.parse_args()
    only = {c.strip().upper() for c in args.only.split(",")} if args.only else None

    gi = GameIndex()
    pal_rgb = load_8bit_palette(gi)
    table, levels = make_index_table(pal_rgb)
    engine = recolor.RecolorEngine(gi)
    lut = tone_lut(pal_rgb, table, levels)

    listing = subprocess.run([str(ROOT / "tools" / "dat" / "dat2.exe"), "l",
                              str(ROOT / "base" / "critter.dat")],
                             capture_output=True, text=True).stdout
    members = {line.strip().split("\\")[-1].strip().upper()
               for line in listing.splitlines() if "\\" in line}

    grids = {p.stem.upper()[:2]: p for p in sorted(GRID_DIR.glob("*.png")) if p.stem[0] != "_"}
    CRIT_DIR.mkdir(parents=True, exist_ok=True)

    log = print
    written = {}                 # suffix -> bytes (male), for the female copy
    lineup = []
    n_grid = n_fallback = n_split = 0
    for name in sorted(n for n in members if n.startswith("HMJMPS")):
        suffix = name[6:]                      # e.g. "AA.FRM", "BA.FR0"
        code = suffix[:2]
        if only and code not in only:
            continue
        van = gi.vfs.read(f"art\\critters\\{name}")
        dst = CRIT_DIR / ("hmpcot" + suffix)
        split = suffix[-4:-1].upper() == ".FR" and suffix[-1].isdigit()
        if split:
            # .FR0-.FR5 single-direction death poses: no grids for these yet
            # (the BD/BF/BG RGBA grids predate the green-sheet workflow and
            # don't fit it), so always the recolor placeholder
            n_split += 1
            data = None
        elif code in grids:
            try:
                sheet = GreenSheet(grids[code])
                data, meta, out = build_family(code, van, sheet, table, levels, log)
            except Exception as e:             # a bad sheet must not kill the run
                log(f"  {code}: FAILED ({e!r}) -> fallback")
                data, out = None, None
            if data is not None:
                n_grid += 1
                if args.preview:
                    preview_family(code, out, pal_rgb, PREVIEW_DIR / f"{code}.png")
                    if out.get(2):
                        lineup.append((code, out[2][0]))
        else:
            data = None
        if data is None:
            if args.fallback == "skip":
                continue
            data = recolor_fallback(van, engine, lut)
            n_fallback += 1
        dst.write_bytes(data)
        written[suffix] = data

    # female model = the same colonist; cover any HF-only suffix by recolor
    n_f = 0
    for name in sorted(n for n in members if n.startswith("HFJMPS")):
        suffix = name[6:]
        if only and suffix[:2] not in only:
            continue
        if suffix in written:
            (CRIT_DIR / ("hfpcot" + suffix)).write_bytes(written[suffix])
            n_f += 1
        elif args.fallback == "recolor":
            (CRIT_DIR / ("hfpcot" + suffix)).write_bytes(
                recolor_fallback(gi.vfs.read(f"art\\critters\\{name}"), engine, lut))
            n_f += 1

    if args.preview and lineup:
        preview_lineup(lineup, pal_rgb, PREVIEW_DIR / "_lineup.png")
    missing = sorted(c[:2] for c in {n[6:8] for n in members if n.startswith("HMJMPS")
                                     and n.endswith(".FRM")} - set(grids))
    print(f"male: {n_grid} families from grids, {n_fallback} {args.fallback} fallback, "
          f"of which {n_split} split .FRx; female copies: {n_f}")
    print(f"no grid yet ({len(missing)}): {' '.join(missing)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
