#!/usr/bin/env python3
r"""
scale_critter.py - make a smaller (or bigger) copy of a critter FRM family, every
animation and direction, scaled to match another critter's size.

    python tools/scale_critter.py MAMRAT MAHOGX --like MAMURT --preview
    python tools/scale_critter.py MAMRAT MAHOGX --like MAMURT        # writes mod/data/art/critters/

Owner, 2026-10-20: "shrink down the size of the mole rats to match that of the pig
rats and make a new critter that is called a hograt".

The factor is the ratio of the two families' standing height: the median height of
the opaque pixels over every frame and direction of their AA (standing) animation.
Each frame is drawn in the shared color.pal (index 0 transparent), scaled with area
averaging on premultiplied colour, and put back in the palette (alpha 50% or more
is opaque; a colour goes to the nearest of indices 1-228, the palette's fixed colours;
an animated colour 229+ that covers most of the area it came from is kept). The
frame's bottom centre stays where it was: the image is scaled about it, and the
direction shifts and per-frame offsets (the animation's movement) are scaled with
error carried from frame to frame, so a walk covers proportionally less ground per
frame, as a smaller animal's does in the originals.
"""
from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from foclib import GameIndex  # noqa: E402

EXTS = ("FRM", "FR0", "FR1", "FR2", "FR3", "FR4", "FR5")
FIXED = range(1, 229)


def load_palette(gi):
    raw = gi.vfs.read("color.pal")
    return [tuple(min(255, c * 4) for c in raw[i * 3:i * 3 + 3]) for i in range(256)]


def family(gi, prefix):
    for a in "ABCDEFGHIJKLMNOPQRST":
        for b in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            for ext in EXTS:
                n = f"{prefix}{a}{b}.{ext}"
                if gi.vfs.exists("art/critters/" + n):
                    yield n


def parse(data):
    """header fields and frames: [(w, h, ox, oy, pixels)] per direction."""
    version, fps, action, nframes = struct.unpack_from(">IHHH", data, 0)
    shx = list(struct.unpack_from(">6h", data, 0x0A))
    shy = list(struct.unpack_from(">6h", data, 0x16))
    offs = list(struct.unpack_from(">6I", data, 0x22))
    dirs = []
    seen = {}
    for d in range(6):
        if offs[d] in seen:
            dirs.append(seen[offs[d]])
            continue
        pos = 0x3E + offs[d]
        frames = []
        for _ in range(nframes):
            w, h, size, ox, oy = struct.unpack_from(">HHIhh", data, pos)
            frames.append([w, h, ox, oy, data[pos + 12:pos + 12 + w * h]])
            pos += 12 + size
        seen[offs[d]] = d
        dirs.append(frames)
    return dict(version=version, fps=fps, action=action, nframes=nframes, shx=shx, shy=shy, offs=offs, dirs=dirs)


def write(h):
    body = bytearray()
    offs = [0] * 6
    written = {}
    for d in range(6):
        fr = h["dirs"][d]
        if isinstance(fr, int):
            offs[d] = written[fr]
            continue
        written[d] = len(body)
        offs[d] = len(body)
        for w, hh, ox, oy, px in fr:
            body += struct.pack(">HHIhh", w, hh, w * hh, ox, oy) + px
    head = struct.pack(">IHHH", h["version"], h["fps"], h["action"], h["nframes"])
    head += struct.pack(">6h", *h["shx"]) + struct.pack(">6h", *h["shy"]) + struct.pack(">6I", *offs)
    head += struct.pack(">I", len(body))
    return bytes(head) + bytes(body)


def opaque_height(w, h, px):
    rows = [y for y in range(h) if any(px[y * w + x] for x in range(w))]
    return (rows[-1] - rows[0] + 1) if rows else 0


def standing_height(gi, prefix):
    hs = []
    for ext in EXTS:
        n = f"{prefix}AA.{ext}"
        if gi.vfs.exists("art/critters/" + n):
            hd = parse(gi.vfs.read("art/critters/" + n))
            for fr in hd["dirs"]:
                if isinstance(fr, list):
                    hs += [opaque_height(w, h, px) for w, h, ox, oy, px in fr]
    hs.sort()
    return hs[len(hs) // 2]


class Quant:
    def __init__(self, pal):
        self.pal = pal
        self.cache = {}

    def __call__(self, rgb):
        k = tuple(int(c) >> 2 for c in rgb)
        if k not in self.cache:
            best, bd = 1, 1 << 30
            for j in FIXED:
                p = self.pal[j]
                d = (p[0] - rgb[0]) ** 2 + (p[1] - rgb[1]) ** 2 + (p[2] - rgb[2]) ** 2
                if d < bd:
                    best, bd = j, d
            self.cache[k] = best
        return self.cache[k]


def scale_frame(w, h, px, s, pal, quant):
    nw, nh = max(1, round(w * s)), max(1, round(h * s))
    rgba = Image.new("RGBA", (w, h))
    rgba.putdata([(0, 0, 0, 0) if c == 0 else pal[c] + (255,) for c in px])
    # premultiplied area averaging
    pm = Image.new("RGBA", (w, h))
    pm.putdata([(r * a // 255, g * a // 255, b * a // 255, a) for r, g, b, a in rgba.getdata()])
    small = pm.resize((nw, nh), Image.BOX)
    # animated colours: keep one where it covered most of the source area
    anim = Image.new("L", (w, h))
    anim.putdata([255 if c >= 229 else 0 for c in px])
    anim_small = anim.resize((nw, nh), Image.BOX)
    idx_small = Image.frombytes("L", (w, h), bytes(px)).resize((nw, nh), Image.NEAREST)
    out = bytearray(nw * nh)
    for i, ((r, g, b, a), an, near) in enumerate(zip(small.getdata(), anim_small.getdata(), idx_small.getdata())):
        if a < 128:
            continue
        if an > 128 and near >= 229:
            out[i] = near
            continue
        out[i] = quant((r * 255 / a, g * 255 / a, b * 255 / a))
    return nw, nh, bytes(out)


def scale_family(gi, name, s, pal, quant):
    hd = parse(gi.vfs.read("art/critters/" + name))
    hd["shx"] = [round(v * s) for v in hd["shx"]]
    hd["shy"] = [round(v * s) for v in hd["shy"]]
    for d, fr in enumerate(hd["dirs"]):
        if isinstance(fr, int):
            continue
        ex = ey = 0.0
        new = []
        for w, h, ox, oy, px in fr:
            nw, nh, npx = scale_frame(w, h, px, s, pal, quant)
            tx, ty = ox * s + ex, oy * s + ey
            rx, ry = round(tx), round(ty)
            ex, ey = tx - rx, ty - ry
            new.append([nw, nh, rx, ry, npx])
        hd["dirs"][d] = new
    return write(hd)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("src")
    ap.add_argument("dst")
    ap.add_argument("--like", help="scale to this family's standing height")
    ap.add_argument("--scale", type=float)
    ap.add_argument("--preview", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "mod/data/art/critters"))
    a = ap.parse_args()
    src, dst = a.src.upper(), a.dst.upper()
    assert len(src) == 6 and len(dst) == 6, "critter art prefixes are 6 characters"
    gi = GameIndex(pristine=False)
    pal = load_palette(gi)
    quant = Quant(pal)
    if a.like:
        hs, hl = standing_height(gi, src), standing_height(gi, a.like.upper())
        s = hl / hs
        print(f"{src} stands {hs}px, {a.like.upper()} {hl}px: scale {s:.3f}")
    else:
        s = a.scale
    names = list(family(gi, src))
    if a.preview:
        out = ROOT / "build" / "scale_critter"
        out.mkdir(parents=True, exist_ok=True)
        tiles = []
        for n in [f"{src}AA.FRM", f"{a.like.upper() if a.like else src}AA.FRM"]:
            if gi.vfs.exists("art/critters/" + n):
                tiles.append((n, gi.vfs.read("art/critters/" + n)))
        tiles.insert(1, ("scaled", scale_family(gi, f"{src}AA.FRM", s, pal, quant)))
        sheet = Image.new("RGB", (len(tiles) * 160, 140), (60, 60, 60))
        for k, (n, data) in enumerate(tiles):
            hd = parse(data)
            w, h, ox, oy, px = hd["dirs"][2][0] if isinstance(hd["dirs"][2], list) else hd["dirs"][hd["dirs"][2]][0]
            im = Image.new("RGBA", (w, h))
            im.putdata([(0, 0, 0, 0) if c == 0 else pal[c] + (255,) for c in px])
            sheet.paste(im, (k * 160 + 80 - w // 2, 120 - h), im)
        p = out / f"{dst}_preview.png"
        sheet.resize((sheet.width * 2, sheet.height * 2), Image.NEAREST).save(p)
        print(p)
        return 0
    outdir = Path(a.out)
    outdir.mkdir(parents=True, exist_ok=True)
    for old in outdir.glob(f"{dst}??.FR*"):
        old.unlink()
    for n in names:
        (outdir / (dst + n[6:])).write_bytes(scale_family(gi, n, s, pal, quant))
    print(f"{len(names)} files {src}* -> {dst}* at {s:.3f} in {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
