#!/usr/bin/env python3
"""
paint_worldmap.py - paint FOC's West Texas worldmap in the style of Fallout 2's own.

    python tools/paint_worldmap.py              # preview only: build/worldmap/painted.png
    python tools/paint_worldmap.py --write      # also write mod/data/art/intrface/WRLDMP*.FRM

The geography is real: a USGS 3DEP elevation grid over the same bounding box as
the satellite map (build/worldmap/bbox.txt), fetched once into
build/worldmap/dem.tif. The same projection puts Lamesa, Midland and Odessa on
the pixel positions already registered in mod/ids/maps.txt, so no location moves.

The LOOK is Fallout 2's: every pixel of texture comes from the vanilla map in
master.dat (not RPU's enhanced worldmap, which repaints it with city ruins and a
blue sea). The original is a matte painting of three things, and so is this:

  plains     mottled tan-brown ground, synthesised from patches of the vanilla
             map's flattest land
  crags      dark, heavily lit relief with pale tops, synthesised from patches
             of its roughest land, and laid wherever the real terrain is broken:
             the Caprock escarpment, the canyon country east of it, the breaks
             along the southern edge (local relief from the DEM)
  riverbeds  the pale sand winding through vanilla's mountains; here they
             follow real drainage (D8 flow accumulation on the DEM), so the
             draws and the Colorado River show where they really run

Shading from the DEM, lit from the north-west like the vanilla art, runs over
all of it, much stronger in broken country. Lakes (dark blobs in the satellite
image) get vanilla's sea treatment: murky haze inside a pale sandy rim. Then
vanilla's own grid (1 px, olive, every 50 px) and its Vault-Tec Maps plate go
on, the whole thing is matched to vanilla's tone and quantised to color.pal
without the transparent index 0 or the colour-cycling 229..255.
"""

from __future__ import annotations

import argparse
import struct
import sys
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage as ndi

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from foclib import GameIndex          # noqa: E402

WORK = ROOT / "build" / "worldmap"
OUT = ROOT / "mod" / "data" / "art" / "intrface"

TILE_W, TILE_H, GRID_W, GRID_H = 350, 300, 4, 5
MAP_W, MAP_H = TILE_W * GRID_W, TILE_H * GRID_H
M_PER_PX = 162.0                      # ~226 km / 1400 px, ~243 km / 1500 px

# Local relief (m over ~1.1 km) where plains turn into broken country, and how
# hard the DEM's light lands on each. Tuned by eye against the vanilla map.
ROUGH_LO, ROUGH_HI = 12.0, 28.0
MASS_GROW, MASS_BLUR = 7, 4
PLAIN_SHADE, CRAG_SHADE = 0.6, 0.5
TONE = 1.0
# which vanilla ground counts as plains / crags: percentiles of local texture
# contrast over its land. Plains must be strict - vanilla's flat ground is
# smooth, and a few crag specks per patch turn a synthesised plain to gravel.
PLAIN_PCT, CRAG_PCT = 12, 72
CRAG_BRIGHT_PCT = 65

GRID_RGB = np.array([165.0, 134.0, 28.0])
GRID_ALPHA = 0.70
GRID_STEP = 50

DEM_URL = ("https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/"
           "ImageServer/exportImage?bbox={bbox}&bboxSR=4326&imageSR=4326"
           "&size={w},{h}&format=tiff&pixelType=F32"
           "&interpolation=RSP_BilinearInterpolation&f=image")


# ---------------------------------------------------------------- inputs

def load_dem() -> np.ndarray:
    path = WORK / "dem.tif"
    if not path.is_file():
        bbox = (WORK / "bbox.txt").read_text().strip()
        url = DEM_URL.format(bbox=bbox, w=MAP_W, h=MAP_H)
        print(f"fetching USGS 3DEP elevation for {bbox} ...")
        with urllib.request.urlopen(url, timeout=120) as r:
            path.write_bytes(r.read())
    z = np.array(Image.open(path), dtype=float)
    if z.shape != (MAP_H, MAP_W):
        raise SystemExit(f"{path}: {z.shape}, expected {(MAP_H, MAP_W)}")
    # 3DEP tiles leave a few nodata/seam squares; fill anything implausible
    bad = (z < 0) | (z > 3000)
    if bad.any():
        z[bad] = ndi.median_filter(z, 9)[bad]
    return z


def vanilla_tiles(gi: GameIndex) -> tuple[np.ndarray, np.ndarray, list[bytes]]:
    """master.dat's worldmap as palette indices, the palette, and the FRM blobs."""
    master = next(p for p in gi.vfs.providers if p.label.lower().endswith("master.dat"))
    raw = gi.vfs.read("color.pal")
    pal = np.array([[min(255, raw[i * 3 + j] * 4) for j in range(3)]
                    for i in range(256)], float)
    idx = np.zeros((MAP_H, MAP_W), np.uint8)
    blobs = []
    for t in range(GRID_W * GRID_H):
        b = master.read(f"art\\intrface\\wrldmp{t:02d}.frm")
        w, h = struct.unpack_from(">HH", b, 0x3E)
        if (w, h) != (TILE_W, TILE_H):
            raise SystemExit(f"vanilla tile {t} is {w}x{h}")
        y0, x0 = (t // GRID_W) * TILE_H, (t % GRID_W) * TILE_W
        idx[y0:y0 + h, x0:x0 + w] = np.frombuffer(b[0x3E + 12:0x3E + 12 + w * h],
                                                   np.uint8).reshape(h, w)
        blobs.append(b)
    return idx, pal, blobs


# ------------------------------------------------------------ vanilla samples

def strip_grid(img: np.ndarray) -> np.ndarray:
    """Replace vanilla's baked grid lines with their neighbours so patches don't carry them."""
    out = img.copy()
    for x in range(0, MAP_W, GRID_STEP):
        l, r = max(x - 1, 0), min(x + 1, MAP_W - 1)
        out[:, x] = (img[:, l] + img[:, r]) / 2
    for y in range(0, MAP_H, GRID_STEP):
        u, d = max(y - 1, 0), min(y + 1, MAP_H - 1)
        out[y, :] = (out[u, :] + out[d, :]) / 2
    return out


def vanilla_land_mask() -> np.ndarray:
    """Vanilla's land, by hand: west of this line is the Pacific (and the logo plate)."""
    yy, xx = np.mgrid[0:MAP_H, 0:MAP_W]
    cut = np.where(yy < 800, 170, 170 + (yy - 800) * (600 - 170) / 700)
    return xx > cut + 40


def sample_classes(van: np.ndarray, land: np.ndarray):
    lum = van.mean(2)
    m = ndi.uniform_filter(lum, 31)
    std = np.sqrt(np.maximum(ndi.uniform_filter(lum * lum, 31) - m * m, 0))
    lo, hi = np.percentile(std[land], [PLAIN_PCT, CRAG_PCT])
    plains = land & (std < lo)
    # brown crags only: vanilla's pale grey ranges (the south-east) read as
    # snow-capped sierra, not Texas breaks
    wide = ndi.uniform_filter(lum, 91)
    crags = land & (std > hi) & (wide < np.percentile(wide[land & (std > hi)], CRAG_BRIGHT_PCT))
    return plains, crags


# ------------------------------------------------------------ texture synthesis

def synth(src: np.ndarray, valid: np.ndarray, rng, patch=64, step=40, feather=14) -> np.ndarray:
    """
    Fill a MAP_H x MAP_W field with patches of `src`, each taken from a place
    where the whole patch lies inside `valid`. A regular grid of patches is laid
    first so nothing is left empty, then many more land at random places, each
    painted OVER what is there with a feathered edge. Painting over (rather than
    averaging overlaps) keeps vanilla's contrast and breaks the grid rhythm.
    """
    # a patch qualifies when most of it lies in the class (centred window)
    ok = ndi.uniform_filter(valid.astype(float), patch, mode="constant") >= 0.85
    cy, cx = np.nonzero(ok)
    ty, tx = cy - patch // 2, cx - patch // 2
    keep = (ty >= 0) & (tx >= 0) & (ty + patch <= MAP_H) & (tx + patch <= MAP_W)
    ty, tx = ty[keep], tx[keep]
    if len(ty) == 0:
        raise SystemExit("no source patches for a texture class")
    ramp = np.clip(np.minimum(np.arange(patch) + 1, patch - np.arange(patch)) / feather, 0, 1)
    win = np.outer(ramp, ramp)[..., None]
    out = np.zeros((MAP_H + patch, MAP_W + patch, 3))

    def put(jy, jx, alpha):
        k = rng.integers(len(ty))
        p = src[ty[k]:ty[k] + patch, tx[k]:tx[k] + patch]
        y0, x0 = max(jy, 0), max(jx, 0)
        py0, px0 = y0 - jy, x0 - jx
        a = alpha[py0:, px0:]
        h, w = a.shape[:2]
        region = out[y0:y0 + h, x0:x0 + w]
        region[:] = region * (1 - a) + p[py0:, px0:] * a

    solid = np.ones_like(win)
    for y in range(-patch // 2, MAP_H, patch - 2):         # base coat
        for x in range(-patch // 2, MAP_W, patch - 2):
            put(y, x, solid)
    for _ in range(int(3 * MAP_H * MAP_W / step ** 2)):    # random over-painting
        put(int(rng.integers(-patch // 2, MAP_H)), int(rng.integers(-patch // 2, MAP_W)), win)
    return out[:MAP_H, :MAP_W]


def fbm(rng, octaves: list[tuple[float, float]]) -> np.ndarray:
    """Sum of blurred white noise, one (blur sigma px, weight) per octave, unit std each."""
    out = np.zeros((MAP_H, MAP_W))
    for sigma, wgt in octaves:
        n = ndi.gaussian_filter(rng.standard_normal((MAP_H, MAP_W)), sigma, mode="wrap")
        out += wgt * n / n.std()
    return out


def plains_texture(van: np.ndarray, valid: np.ndarray, rng) -> np.ndarray:
    """
    Vanilla's flat ground is a smooth, softly mottled wash; there is too little
    of it to cut patches from without visible repeats. So: a noise field with
    the same brightness spread, coloured through vanilla's own plains pixels
    (mean colour per brightness level), with a second slow field shifting the
    hue between its warmer and greyer tans.
    """
    px = van[valid]
    lum = px.mean(1)
    bins = np.linspace(np.percentile(lum, 1), np.percentile(lum, 99), 33)
    which = np.clip(np.digitize(lum, bins) - 1, 0, 31)
    centres = (bins[:-1] + bins[1:]) / 2
    warm = px[:, 0] - px[:, 2]
    lut, lut_w, lut_c = [], [], []
    for b in range(32):
        sel = which == b
        if sel.sum() < 20:
            lut.append(None)
            continue
        cols = px[sel][np.argsort(warm[sel])]
        half = len(cols) // 2
        lut.append(cols.mean(0))
        lut_w.append(cols[half:].mean(0))
        lut_c.append(cols[:half].mean(0))
    good = [i for i, v in enumerate(lut) if v is not None]
    lut_w = np.array(lut_w)
    lut_c = np.array(lut_c)
    xs = centres[good]

    field = fbm(rng, [(40, 0.35), (14, 0.45), (4, 0.6), (1.2, 0.55), (0.6, 0.35)])
    # vanilla's grain is lit: small bumps with a bright north-west face
    bumps = fbm(rng, [(2.5, 1.0), (1.2, 0.6)])
    gy, gx = np.gradient(bumps)
    field += 0.9 * (-(gx + gy))
    field = lum.mean() + field / field.std() * lum.std() * 0.65
    tint = np.clip(0.5 + 0.35 * fbm(rng, [(70, 1.0), (20, 0.4)]), 0, 1)
    out = np.empty((MAP_H, MAP_W, 3))
    for c in range(3):
        w_ = np.interp(field, xs, lut_w[:, c])
        c_ = np.interp(field, xs, lut_c[:, c])
        out[..., c] = w_ * tint + c_ * (1 - tint)
    return out


def match_hist(img: np.ndarray, ref: np.ndarray) -> np.ndarray:
    out = np.empty_like(img)
    q = np.linspace(0, 100, 257)
    for c in range(3):
        a = img[..., c]
        src_q = np.percentile(a, q)
        ref_q = np.percentile(ref[:, c], q)
        out[..., c] = np.interp(a, src_q, ref_q)
    return out


# ------------------------------------------------------------------ terrain

def hillshade(z: np.ndarray, exag: float, az_deg=315.0, alt_deg=40.0) -> np.ndarray:
    gy, gx = np.gradient(z, M_PER_PX)
    gx, gy = gx * exag, gy * exag
    az, alt = np.radians(az_deg), np.radians(alt_deg)
    # unit vector toward the light; image x grows east, y grows south
    lx, ly, lz = np.sin(az) * np.cos(alt), -np.cos(az) * np.cos(alt), np.sin(alt)
    n = np.sqrt(gx * gx + gy * gy + 1)
    return (-gx * lx - gy * ly + lz) / n


def flow_accumulation(z: np.ndarray) -> np.ndarray:
    """D8: every cell drains to its lowest lower neighbour; count upstream cells."""
    h, w = z.shape
    zp = np.pad(z, 1, mode="edge")
    best = np.zeros_like(z)
    rec = np.full(z.shape, -1, np.int64)
    flat = np.arange(h * w).reshape(h, w)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy == dx == 0:
                continue
            drop = (z - zp[1 + dy:1 + dy + h, 1 + dx:1 + dx + w]) / np.hypot(dy, dx)
            better = drop > best
            best[better] = drop[better]
            ny = np.clip(np.arange(h)[:, None] + dy, 0, h - 1)
            nx = np.clip(np.arange(w)[None, :] + dx, 0, w - 1)
            rec[better] = (ny * w + nx)[better]
    order = np.argsort(-z, axis=None).tolist()
    acc = [1.0] * (h * w)
    recf = rec.ravel().tolist()
    for i in order:                       # high to low
        r = recf[i]
        if r >= 0:
            acc[r] += acc[i]
    return np.array(acc).reshape(h, w)


def lakes_from_imagery() -> np.ndarray:
    path = WORK / "imagery.png"
    if not path.is_file():
        return np.zeros((MAP_H, MAP_W), bool)
    a = np.asarray(Image.open(path).convert("RGB").resize((MAP_W, MAP_H))).astype(float)
    dark = ndi.uniform_filter(a.mean(2), 3) < 62
    dark = ndi.binary_opening(dark, np.ones((3, 3)))
    lab, n = ndi.label(dark)
    sizes = ndi.sum(dark, lab, range(1, n + 1))
    keep = np.isin(lab, 1 + np.nonzero(sizes >= 40)[0])
    return ndi.binary_closing(keep, np.ones((3, 3)))


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


# -------------------------------------------------------------------- paint

def paint(gi: GameIndex, seed: int):
    rng = np.random.default_rng(seed)
    z = load_dem()
    vidx, pal, blobs = vanilla_tiles(gi)
    van = strip_grid(pal[vidx])
    land = vanilla_land_mask()
    plains_ok, crags_ok = sample_classes(van, land)

    print("synthesising plains + crag texture from the vanilla map ...")
    plains = plains_texture(van, plains_ok, rng)
    crags = synth(van, crags_ok, rng)

    zs = ndi.gaussian_filter(z, 1.0)
    relief = ndi.maximum_filter(zs, 7) - ndi.minimum_filter(zs, 7)
    # broad masses, not gully-thin bands: vanilla paints ranges as blocks
    rough = ndi.gaussian_filter(ndi.maximum_filter(relief, MASS_GROW), MASS_BLUR)
    m = smoothstep(ROUGH_LO, ROUGH_HI, rough)            # 0 plain .. 1 broken country

    # the DEM only gives the big shapes; the crag detail is vanilla's own
    # (pixel-scale DEM shading combs the crags into stripes)
    shade = hillshade(ndi.gaussian_filter(z, 2.5), exag=8.0)
    flat = np.median(shade)
    k = PLAIN_SHADE + CRAG_SHADE * m
    light = np.clip(1 + k * (shade - flat), 0.6, 1.4)

    img = plains * (1 - m[..., None]) + crags * m[..., None]
    img *= light[..., None]

    print("tracing drainage ...")
    acc = flow_accumulation(ndi.gaussian_filter(z, 2.0))
    sand = np.array([205.0, 172.0, 112.0])
    bed = smoothstep(np.log(600), np.log(6000), np.log(acc))
    bed = ndi.gaussian_filter(np.maximum(bed, ndi.maximum_filter(bed, 3) * 0.6), 0.8)
    bed *= 0.35 + 0.65 * m                                # draws faint, canyons bright
    grain = 0.85 + 0.3 * rng.random((MAP_H, MAP_W))
    img = img * (1 - bed[..., None]) + (sand * grain[..., None]) * bed[..., None]

    lakes = lakes_from_imagery()
    if lakes.any():
        haze = synth(van, ~land & (np.arange(MAP_W)[None, :] < 120), rng)
        inner = ndi.gaussian_filter(lakes.astype(float), 1.2)
        rim = np.clip(ndi.gaussian_filter(ndi.binary_dilation(lakes, iterations=3).astype(float), 1.0)
                      - inner, 0, 1)
        img = img * (1 - rim[..., None]) + sand * 1.05 * rim[..., None]
        img = img * (1 - inner[..., None]) + haze * 0.8 * inner[..., None]
        print(f"lakes: {ndi.label(lakes)[1]} bodies, {int(lakes.sum())} px")

    img *= TONE

    # grid and the Vault-Tec plate, as vanilla draws them
    for x in range(0, MAP_W, GRID_STEP):
        img[:, x] = img[:, x] * (1 - GRID_ALPHA) + GRID_RGB * GRID_ALPHA
    for y in range(0, MAP_H, GRID_STEP):
        img[y, :] = img[y, :] * (1 - GRID_ALPHA) + GRID_RGB * GRID_ALPHA
    return img, pal, vidx, blobs


def logo_box(vidx: np.ndarray) -> tuple[int, int, int, int]:
    """The Vault-Tec Maps plate, bottom-left of vanilla tile 16: its dark frame."""
    return 50, 1349, 203, 1451          # x0, y0, x1, y1 (measured on master.dat)


def quantise(img: np.ndarray, pal: np.ndarray) -> np.ndarray:
    allowed = np.arange(1, 229)
    ref = pal[allowed]
    g = (np.arange(32) * 8 + 4).astype(float)
    rr, gg, bb = np.meshgrid(g, g, g, indexing="ij")
    pts = np.stack([rr, gg, bb], -1).reshape(-1, 3)
    lut = np.empty(len(pts), np.uint8)
    for i in range(0, len(pts), 4096):
        d = ((pts[i:i + 4096, None, :] - ref[None]) ** 2).sum(2)
        lut[i:i + 4096] = allowed[d.argmin(1)]
    lut = lut.reshape(32, 32, 32)
    q = np.clip(img, 0, 255).astype(np.uint8)
    return lut[q[..., 0] >> 3, q[..., 1] >> 3, q[..., 2] >> 3]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true",
                    help="write the 20 WRLDMP tiles into mod/data/art/intrface")
    ap.add_argument("--seed", type=int, default=39)
    args = ap.parse_args()

    gi = GameIndex(ROOT / "base", pristine=True)
    img, pal, vidx, blobs = paint(gi, args.seed)
    idx = quantise(img, pal)
    x0, y0, x1, y1 = logo_box(vidx)
    idx[y0:y1, x0:x1] = vidx[y0:y1, x0:x1]
    assert idx.min() >= 1 and idx.max() <= 228

    WORK.mkdir(parents=True, exist_ok=True)
    Image.fromarray(pal[idx].astype(np.uint8)).save(WORK / "painted.png")
    print(f"preview: {WORK / 'painted.png'}")

    if args.write:
        OUT.mkdir(parents=True, exist_ok=True)
        for t in range(GRID_W * GRID_H):
            tpl = bytearray(blobs[t])
            ty, tx = (t // GRID_W) * TILE_H, (t % GRID_W) * TILE_W
            tpl[0x3E + 12:0x3E + 12 + TILE_W * TILE_H] = idx[ty:ty + TILE_H, tx:tx + TILE_W].tobytes()
            (OUT / f"WRLDMP{t:02d}.FRM").write_bytes(bytes(tpl))
        print(f"wrote 20 tiles to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
