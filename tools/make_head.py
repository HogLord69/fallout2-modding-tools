#!/usr/bin/env python3
"""
make_head.py - build a talking head from a few photos of one character turning
their head, front pose first; --fidget sets the order the photos play in.

    python tools/make_head.py --name rwcal --crop 380,0,990,410 IMG1 IMG2 ... --preview out.gif
    python tools/make_head.py --name rwcal --crop 380,0,990,410 IMG1 IMG2 ...      # write + register

Callum (rwcal), from art/heads_src/callum:
    python tools/make_head.py --name rwcal --crop 380,0,990,410 --credit owner_callum_photos         art/heads_src/callum/*.jpg --fidget 1,3,2,3,1,4,5,4,1 --fidget 1,4,1
(what ships for now is the still front photo: --fidget 1 --fidget 1 --linger 1)

What the engine needs (read off RPU's heads: 298x200, one direction, index 0
transparent so the dialogue background shows, fps 0):
  <n>nf1 <n>nf2   neutral fidgets      <n>gf1/2, <n>bf1/2  good / bad fidgets
  <n>ng <n>nb <n>gn <n>bn              mood transitions
  <n>np <n>gp <n>bp                    lip-sync (phoneme frames)
heads.lst: "<n>,2,2,2" - two fidgets per mood.

This is a neutral-only head for a face that is never seen (a helmet): every
mood gets the same fidgets (--fidget) and the transitions and lip-sync hold the front pose. That keeps
it neutral whatever mood a script asks for.

Motion: the engine plays a head at the FRM's fps (10 when it is 0;
art.cc artGetFramesPerSecond), so --fps sets the speed; --linger repeats
each photo so it stays up longer than the steps between. Between photos that
are close (--max-gap) a cross-faded in-between smooths the step; a far pair
is left as a cut, since its cross-fade shows two faces at once.

Pipeline per photo: crop -> align to the first photo on the lower third
(the body, which should not move; phase correlation) -> resize to 298x200 ->
background (near-white, connected to the frame edge) made transparent, with
a one-pixel trim so no white fringe survives -> Fallout palette (indices
1..228: 0 is transparent, 229+ cycle), Floyd-Steinberg dithered.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
from scipy import ndimage  # noqa: E402

import port  # noqa: E402
from foclib import GameIndex  # noqa: E402

W, H = 298, 200
KEY = "art_heads"


def load_palette(gi) -> list[tuple[int, int, int]]:
    raw = gi.vfs.read("color.pal")
    return [tuple(min(255, (raw[i * 3 + c] << 2) | (raw[i * 3 + c] >> 4)) for c in range(3)) for i in range(256)]


def align(ref: np.ndarray, img: np.ndarray) -> tuple[int, int]:
    """(dy, dx) that moves img onto ref, measured on the lower third."""
    h = ref.shape[0]
    a = ref[2 * h // 3:].mean(2)
    b = img[2 * h // 3:].mean(2)
    fa, fb = np.fft.fft2(a - a.mean()), np.fft.fft2(b - b.mean())
    r = np.fft.ifft2(fa * np.conj(fb) / (np.abs(fa * np.conj(fb)) + 1e-9)).real
    dy, dx = np.unravel_index(r.argmax(), r.shape)
    if dy > a.shape[0] // 2:
        dy -= a.shape[0]
    if dx > a.shape[1] // 2:
        dx -= a.shape[1]
    return int(dy), int(dx)


def background_mask(rgb: np.ndarray, thresh: int) -> np.ndarray:
    """Near-white, low-saturation pixels connected to the border, plus the
    pale halo around them (photo edges blend into the white)."""
    lo, hi = rgb.min(2), rgb.max(2)
    white = (lo >= thresh) & (hi - lo <= 24)
    lab, _ = ndimage.label(white)
    edge = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    bg = np.isin(lab, list(edge))
    for _ in range(4):
        bg |= ndimage.binary_dilation(bg) & (lo >= thresh - 70) & (hi - lo <= 40)
    return ndimage.binary_dilation(bg, iterations=2)


def cut_out(rgb: np.ndarray, thresh: int, darken: float) -> tuple[Image.Image, np.ndarray]:
    """(image, background mask) at head size. The mask is made at photo
    resolution; background pixels take the colour of the nearest subject pixel
    before the resize so no white bleeds into the edge."""
    bg = background_mask(rgb.astype(int), thresh)
    _, (iy, ix) = ndimage.distance_transform_edt(bg, return_indices=True)
    filled = rgb[iy, ix] * darken
    img = Image.fromarray(np.clip(filled, 0, 255).astype(np.uint8)).resize((W, H), Image.LANCZOS)
    cover = np.asarray(Image.fromarray((~bg * 255).astype(np.uint8)).resize((W, H), Image.BOX))
    return img, cover < 200


def grade(rgb: np.ndarray, bg: np.ndarray, amount: float) -> np.ndarray:
    """Take the product-shot look off: soften the plastic sheen, pull the
    colour toward the desert background, and light the subject from the
    upper left (warm key, cool shadow side, the coat falling off into
    shade). Lighting is fixed to the frame, so the head turns through it."""
    if amount <= 0:
        return rgb
    x = rgb / 255.0
    # highlight roll-off: gloss hot spots are what read as plastic
    knee = 0.42
    x = np.where(x > knee, knee + (x - knee) / (1 + 2.5 * (x - knee) / (1 - knee)), x)
    # grit: local contrast brings out the sculpted texture as wear, not sheen
    x = x + 0.45 * amount * (x - ndimage.gaussian_filter(x, (5, 5, 0)))
    # desaturate, then a dusty warm cast (the silver mask becomes gunmetal)
    lum = (x * [0.299, 0.587, 0.114]).sum(2, keepdims=True)
    x = lum + (x - lum) * (1 - 0.35 * amount)
    x = x * (1 + amount * np.array([0.08, 0.02, -0.15]))

    fg = (~bg).astype(np.float32)
    ys, xs = np.mgrid[0:H, 0:W].astype(np.float32)
    # broad key from the upper left, darkening toward lower right and down the coat
    key = 1 + amount * (0.38 * (0.45 - xs / W) + 0.34 * (0.3 - ys / H))
    # edge light: surface normal from the blurred silhouette
    soft = ndimage.gaussian_filter(fg, 5)
    gy, gx = np.gradient(soft)
    mag = np.hypot(gx, gy) + 1e-6
    nx, ny = -gx / mag, -gy / mag               # outward
    edge = np.clip(mag * 10, 0, 1)
    facing = nx * -0.8 + ny * -0.6              # toward the light (upper left)
    rim = np.clip(facing, 0, 1) * edge
    shade = np.clip(-facing, 0, 1) * edge
    x = x * np.clip(key, 0.45, 1.4)[..., None]
    x = x * (1 - 0.55 * amount * shade)[..., None]
    x = x + (amount * 0.4 * rim)[..., None] * np.array([1.0, 0.75, 0.45])
    return np.clip(x * 255, 0, 255)


def morph(a: tuple, b: tuple, t: float) -> tuple[np.ndarray, np.ndarray]:
    """Cross-fade of two shots at t (0 = a, 1 = b). Only used between shots
    close enough not to show a double image (see apart())."""
    return a[0] * (1 - t) + b[0] * t, a[1] & b[1]


def apart(a: tuple, b: tuple) -> float:
    """Mean colour difference over the subject: how far two shots are apart."""
    fg = ~(a[1] | b[1])
    return float(np.abs(a[0] - b[0]).mean(2)[fg].mean())


def to_indices(img: Image.Image, bg: np.ndarray, pal: list) -> bytes:
    pimg = Image.new("P", (1, 1))
    flat = []
    for i, c in enumerate(pal):
        flat += list(c) if 1 <= i <= 228 else [255, 0, 255]   # never chosen
    pimg.putpalette(flat)
    q = img.convert("RGB").quantize(palette=pimg, dither=Image.Dither.FLOYDSTEINBERG)
    idx = np.array(q, dtype=np.uint8)
    idx[bg] = 0
    idx[(idx == 0) & ~bg] = 1
    return idx.tobytes()


def frm(frames: list[bytes], fps: int) -> bytes:
    header = struct.pack(">IHHH", 4, fps, 0, len(frames)) + struct.pack(">6h", 0, 0, 0, 0, 0, 0) \
        + struct.pack(">6h", 0, 0, 0, 0, 0, 0)
    body = b"".join(struct.pack(">HHIhh", W, H, W * H, 0, 0) + f for f in frames)
    return header + struct.pack(">6I", 0, 0, 0, 0, 0, 0) + struct.pack(">I", len(body)) + body


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("images", nargs="+", help="front pose first")
    ap.add_argument("--fidget", action="append",
                    help="play order for one fidget, e.g. 1,3,2+,3,1 ('+' = hold); give it twice for "
                         "the two fidgets. Default: every photo in turn out and back, then half of them")
    ap.add_argument("--name", required=True, help="5-character head name, e.g. rwcal")
    ap.add_argument("--crop", required=True, help="x0,y0,x1,y1 in the photos")
    ap.add_argument("--white", type=int, default=225, help="background threshold (0-255)")
    ap.add_argument("--darken", type=float, default=0.78, help="brightness multiplier (1 = as photographed)")
    ap.add_argument("--grade", type=float, default=1.0, help="colour grade + lighting strength (0 = off)")
    ap.add_argument("--fps", type=int, default=10, help="playback rate written to the FRMs (engine default 10)")
    ap.add_argument("--linger", type=int, default=3, help="frames each photo stays up (in-betweens get one)")
    ap.add_argument("--tween", type=int, default=1, help="blended frames between each pair of photos")
    ap.add_argument("--max-gap", type=float, default=13, help="skip in-betweens for photos further apart than this")
    ap.add_argument("--hold", type=int, default=0, help="extra frames to hold a '+' photo")
    ap.add_argument("--preview", type=Path, help="write a GIF over the wasteland background and stop")
    ap.add_argument("--credit", default="owner", help="ledger source name")
    args = ap.parse_args()

    name = args.name.lower()
    if len(name) != 5 or not name.isalnum():
        sys.exit("--name must be 5 letters/digits")
    x0, y0, x1, y1 = (int(v) for v in args.crop.split(","))
    gi = GameIndex(pristine=False)
    pal = load_palette(gi)

    crops = [np.asarray(Image.open(p).convert("RGB").crop((x0, y0, x1, y1)), dtype=np.float32) for p in args.images]
    shots, raw = [], []   # raw (ungraded) is what --max-gap measures
    for i, c in enumerate(crops):
        if i:
            dy, dx = align(crops[0], c)
            c = ndimage.shift(c, (dy, dx, 0), order=1, mode="nearest")
            print(f"  image {i + 1}: shifted {dx:+d},{dy:+d} px onto image 1")
        img, bg = cut_out(c, args.white, args.darken)
        raw.append((np.asarray(img, dtype=np.float32), bg))
        shots.append((grade(raw[-1][0], bg, args.grade), bg))

    cache: dict[tuple, bytes] = {}

    def pose(key: tuple) -> bytes:
        """(a, b, t): photo a, or the in-between a -> b at t."""
        if key not in cache:
            a, b, t = key
            rgb, bg = shots[a] if t == 0 else morph(shots[a], shots[b], t)
            cache[key] = to_indices(Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8)), bg, pal)
        return cache[key]

    n = len(shots)
    step = 1 / (args.tween + 1)
    gaps: dict[tuple, float] = {}

    def path(spec: str) -> list[tuple]:
        """'1,3,2+,3,1': photos in play order (1-based); '+' holds that
        photo; in-betweens only where two photos are close (a far pair
        would cross-fade as a ghost)."""
        keys = []
        prev = None
        for tok in spec.split(","):
            i = int(tok.rstrip("+")) - 1
            if prev is not None and prev != i:
                pair = (min(prev, i), max(prev, i))
                if pair not in gaps:
                    gaps[pair] = apart(raw[pair[0]], raw[pair[1]])
                    print(f"  photos {pair[0] + 1}-{pair[1] + 1}: difference {gaps[pair]:.0f}")
                if gaps[pair] <= args.max_gap:
                    keys += [(prev, i, round(k * step, 4)) for k in range(1, args.tween + 1)]
            keys += [(i, i, 0)] * (args.linger + args.hold * tok.endswith("+"))
            prev = i
        return keys

    last = n  # default: the photos are one turn, front to furthest
    fidgets = args.fidget or [",".join(map(str, range(1, last))) + f",{last}+," +
                              ",".join(map(str, range(last - 1, 0, -1))),
                              ",".join(map(str, range(1, (last + 1) // 2))) + f",{(last + 1) // 2}+," +
                              ",".join(map(str, range((last + 1) // 2 - 1, 0, -1)))]
    turns = [path(s) for s in fidgets[:2]]
    if len(turns) == 1:
        turns.append(turns[0])
    front = [pose((0, 0, 0))]
    files = {}
    for mood in "gnb":
        files[f"{mood}f1"] = [pose(k) for k in turns[0]]
        files[f"{mood}f2"] = [pose(k) for k in turns[1]]
        files[f"{mood}p"] = front * 9
    for t in ("ng", "nb", "gn", "bn"):
        files[t] = front

    if args.preview:
        bgraw = gi.vfs.read("art\\backgrnd\\wastelnd.frm")
        bw, bh = struct.unpack_from(">HH", bgraw, 0x3E)
        back = np.frombuffer(bgraw, np.uint8, count=bw * bh, offset=0x3E + 12).reshape(bh, bw)
        lut = np.array(pal, np.uint8)
        gif = []
        rest = [(0, 0, 0)] * 4
        for k in turns[0] + rest + turns[1] + rest:
            idx = np.frombuffer(pose(k), np.uint8).reshape(H, W)
            scene = back.copy()
            oy, ox = max(0, (bh - H) // 2), max(0, (bw - W) // 2)
            region = scene[oy:oy + H, ox:ox + W]
            region[idx != 0] = idx[idx != 0]
            gif.append(Image.fromarray(lut[scene]).resize((bw * 2, bh * 2), Image.NEAREST))
        gif[0].save(args.preview, save_all=True, append_images=gif[1:], duration=1000 // args.fps, loop=0)
        gif[0].save(args.preview.with_suffix(".png"))
        print(f"preview: {args.preview} ({len(gif)} frames)")
        return 0

    out = port.MOD / "data" / "art" / "heads"
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob(f"{name}*"):
        old.unlink()
    for suffix, frames in files.items():
        (out / f"{name}{suffix}.frm").write_bytes(frm(frames, args.fps))
    idx = port.allocate(port.IDS / f"{KEY}.txt", f"{name},2,2,2", port.FOC_START[KEY] - 1)
    have = {(r["source"], r["dest_path"]) for r in port.read_ledger()}
    row = port.ledger_row(args.credit, "art", ", ".join(Path(p).name for p in args.images), name,
                          f"mod/data/art/heads/{name}*", idx, "talking head built by make_head.py")
    if (row["source"], row["dest_path"]) not in have:
        port.append_ledger([row])
    port.regen_ledger_md()
    print(f"wrote {len(files)} files {name}*; head index {idx}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
