#!/usr/bin/env python3
"""
scale_scenery.py - add a bigger (or smaller) copy of a scenery object as a new
FOC piece: its own art and its own proto, the original left as it is.

    python tools/scale_scenery.py 0x02001362 ntheatr2.frm --scale 2 --preview build/s.png
    python tools/scale_scenery.py 0x02001362 ntheatr2.frm --scale 2 --write

Owner, 2026-10-22: "the silver screen ... can you make another version of it
that is like 200% larger?"

The art is the source proto's current art, every frame scaled about the hex
it stands on: the header's direction offsets and each frame's shift are
scaled too, so what touched the hex still does. Each frame is drawn in the
shared color.pal, resized on premultiplied colour (Lanczos when growing, area
averaging when shrinking) and put back in the palette the way scale_critter.py
does (alpha 50% or more is opaque; colours go to the nearest of the fixed
indices 1-228; an animated colour 229+ is kept where it covered the spot).
--pixel doubles pixels instead (nearest neighbour, the exact source colours).
--ai upscales with Real-ESRGAN x4 through the local stable-diffusion.cpp
(F:\\sdcpp, `sd-cli -M upscale`) and brings that down to the wanted size,
blended 60/40 with a Lanczos resize and dithered into the palette: the
frame's colours are spread into its transparent area first so the edges get
no dark halo, and the outline comes from the source's own alpha, resized.
The proto is a byte copy of the source with its PID and FID repointed, so it
keeps the source's name and flags. Both are appended to the ID registry and
to mod/ids/keep_protos.txt, as mirror_scenery.py does. Afterwards run
gen_ids.py, deploy.py, repack_art.py and validate.py.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foclib import GameIndex, parse_lst  # noqa: E402
from ids import FOC_START, check_art_name  # noqa: E402
from mirror_scenery import ART, IDS, PROTO, next_index  # noqa: E402
from replace_pc_from_ref import decode_frm, encode_frm  # noqa: E402
from scale_critter import FIXED, Quant, load_palette  # noqa: E402


SD_CLI = Path(r"F:\sdcpp\sd-cli.exe")
ESRGAN = Path(r"F:\sdcpp\models\esrgan\RealESRGAN_x4plus.pth")
WORK = Path(__file__).resolve().parent.parent / "build" / "scale_scenery"
AI_PAD = 16


def filled_rgb(w, h, px, pal):
    """The frame as RGB, its colours spread outwards into the empty pixels,
    padded by AI_PAD with the edge colours."""
    import numpy as np
    from scipy.ndimage import gaussian_filter
    idx = np.frombuffer(bytes(px), np.uint8).reshape(h, w)
    a = (idx > 0).astype(np.float32)
    rgb = np.array(pal, dtype=np.float32)[idx] * a[..., None]
    for r in (1, 2, 4, 8, 16):
        br = np.stack([gaussian_filter(rgb[..., c] * a, r) for c in range(3)], -1)
        ba = gaussian_filter(a, r)
        m = (a == 0) & (ba > 1e-3)
        rgb[m] = br[m] / ba[m][:, None]
        a[m] = 1
    img = np.pad(np.clip(rgb, 0, 255).astype(np.uint8), ((AI_PAD, AI_PAD), (AI_PAD, AI_PAD), (0, 0)), mode="edge")
    return Image.fromarray(img, "RGB")


def esrgan_x4(img):
    import subprocess
    WORK.mkdir(parents=True, exist_ok=True)
    src, dst = WORK / "in.png", WORK / "out.png"
    img.save(src)
    if dst.exists():
        dst.unlink()
    subprocess.run([str(SD_CLI), "-M", "upscale", "--upscale-model", str(ESRGAN), "-i", str(src), "-o", str(dst)],
                   check=True, capture_output=True, cwd=SD_CLI.parent)
    return Image.open(dst).convert("RGB")


def scale_frame(w, h, px, s, pal, quant, pixel, ai=False):
    nw, nh = max(1, round(w * s)), max(1, round(h * s))
    idx = Image.frombytes("L", (w, h), bytes(px))
    near = idx.resize((nw, nh), Image.NEAREST)
    if pixel:
        return nw, nh, near.tobytes()
    if ai:
        # ESRGAN sharpens the edges but smooths fine grain into flat patches,
        # which the palette turns pink and blue; 40% of a plain Lanczos resize
        # and Floyd-Steinberg dithering into the fixed colours bring the grain
        # back (owner's silver screen, 2026-10-22)
        src = filled_rgb(w, h, px, pal)
        pw, ph = round((w + 2 * AI_PAD) * s), round((h + 2 * AI_PAD) * s)
        p = round(AI_PAD * s)
        up = esrgan_x4(src).resize((pw, ph), Image.LANCZOS).crop((p, p, p + nw, p + nh))
        lz = src.resize((pw, ph), Image.LANCZOS).crop((p, p, p + nw, p + nh))
        flat = []
        for i in range(256):
            flat += list(pal[i] if i in FIXED else pal[1])
        palimg = Image.new("P", (1, 1))
        palimg.putpalette(flat)
        q = Image.blend(up, lz, 0.4).quantize(palette=palimg, dither=Image.Dither.FLOYDSTEINBERG).tobytes()
        alpha = Image.frombytes("L", (w, h), bytes(255 if c else 0 for c in px)).resize((nw, nh), Image.LANCZOS)
        anim = Image.frombytes("L", (w, h), bytes(255 if c >= 229 else 0 for c in px)).resize((nw, nh), Image.LANCZOS)
        out = bytearray(nw * nh)
        for i, (aa, an, nr) in enumerate(zip(alpha.tobytes(), anim.tobytes(), near.tobytes())):
            if aa < 128:
                continue
            out[i] = nr if (an > 128 and nr >= 229) else (q[i] if q[i] in FIXED else 1)
        return nw, nh, bytes(out)
    pm = Image.new("RGBA", (w, h))
    pm.putdata([(0, 0, 0, 0) if c == 0 else tuple(v for v in pal[c]) + (255,) for c in px])
    pm = Image.alpha_composite(Image.new("RGBA", (w, h)), pm)
    flt = Image.LANCZOS if s > 1 else Image.BOX
    # premultiply, resize, and read back
    r, g, b, a = pm.split()
    prem = Image.merge("RGBA", [Image.composite(ch, Image.new("L", (w, h)), a) for ch in (r, g, b)] + [a])
    big = prem.resize((nw, nh), flt)
    anim = Image.frombytes("L", (w, h), bytes(255 if c >= 229 else 0 for c in px)).resize((nw, nh), flt)
    out = bytearray(nw * nh)
    for i, ((rr, gg, bb, aa), an, nr) in enumerate(zip(big.getdata(), anim.getdata(), near.getdata())):
        if aa < 128:
            continue
        if an > 128 and nr >= 229:
            out[i] = nr
            continue
        out[i] = quant((min(255, rr * 255 / aa), min(255, gg * 255 / aa), min(255, bb * 255 / aa)))
    return nw, nh, bytes(out)


def scale_art(data, s, pal, pixel, ai=False):
    meta = decode_frm(data)
    meta["xo"] = [round(v * s) for v in meta["xo"]]
    meta["yo"] = [round(v * s) for v in meta["yo"]]
    quant = Quant(pal)
    out = {}
    for d, row in meta["frames"].items():
        out[d] = []
        for f in row:
            nw, nh, npx = scale_frame(f.w, f.h, f.px, s, pal, quant, pixel, ai)
            out[d].append((nw, nh, round(f.sx * s), round(f.sy * s), npx))
    return encode_frm(meta, out, split=len(out) == 1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pid", type=lambda s: int(s, 0))
    ap.add_argument("art_name")
    ap.add_argument("--scale", type=float, default=2.0)
    ap.add_argument("--pixel", action="store_true", help="double pixels instead of smoothing")
    ap.add_argument("--ai", action="store_true", help="upscale with Real-ESRGAN (F:\\sdcpp)")
    ap.add_argument("--preview", type=Path)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    name = args.art_name.lower()
    check_art_name("scenery", name)
    if (ART / name).exists() or name in (IDS / "art_scenery.txt").read_text().lower().split():
        sys.exit(f"{name} already exists")
    gi = GameIndex(pristine=False)
    pr = gi.proto(args.pid)
    if pr is None or (args.pid >> 24) != 2:
        sys.exit(f"no scenery proto 0x{args.pid:08X}")
    lst = parse_lst(gi.vfs.read("art\\scenery\\scenery.lst"))
    art_src = lst[pr.fid & 0xFFFFFF]
    data = gi.vfs.read("art\\scenery\\" + art_src)
    pal = load_palette(gi)
    scaled = scale_art(data, args.scale, pal, args.pixel, args.ai)

    art_idx = next_index(IDS / "art_scenery.txt", FOC_START["art_scenery"] - 1)   # art is 0-based
    pid_idx = next_index(IDS / "proto_scenery.txt", FOC_START["proto_scenery"])
    proto_bytes = bytearray(gi.vfs.read(gi.proto_path(args.pid)))
    struct.pack_into(">I", proto_bytes, 0, 0x02000000 | pid_idx)
    struct.pack_into(">I", proto_bytes, 8, 0x02000000 | art_idx)
    proto_file = f"{pid_idx:08d}.pro"
    f0 = decode_frm(scaled)["frames"][0][0]
    print(f"{art_src} x{args.scale:g} -> {name} {f0.w}x{f0.h} (art {art_idx}); "
          f"proto 0x{args.pid:08X} -> 0x{0x02000000 | pid_idx:08X} ({proto_file})")

    if args.preview:
        def rgba(frm):
            f = decode_frm(frm)["frames"][0][0]
            im = Image.new("RGBA", (f.w, f.h))
            im.putdata([(0, 0, 0, 0) if c == 0 else pal[c] + (255,) for c in f.px])
            return im
        a, b = rgba(data), rgba(scaled)
        sheet = Image.new("RGBA", (a.width + b.width + 20, max(a.height, b.height)), (40, 40, 40, 255))
        sheet.alpha_composite(a, (0, sheet.height - a.height))
        sheet.alpha_composite(b, (a.width + 20, sheet.height - b.height))
        sheet.save(args.preview)
        print(f"preview {args.preview}")
    if args.write:
        if (PROTO / proto_file).exists():
            sys.exit(f"{proto_file} already exists")
        (ART / name).write_bytes(scaled)
        (PROTO / proto_file).write_bytes(bytes(proto_bytes))
        with open(IDS / "art_scenery.txt", "a", newline="\r\n") as fh:     # the registry is CRLF
            fh.write(name + "\n")
        with open(IDS / "proto_scenery.txt", "a", newline="\r\n") as fh:
            fh.write(proto_file + "\n")
        with open(IDS / "keep_protos.txt", "a", newline="\r\n") as fh:   # keep its art under the cap
            fh.write(f"0x{0x02000000 | pid_idx:08X}  # {name}, x{args.scale:g} of 0x{args.pid:08X}\n")
        print("written; now run tools/gen_ids.py, deploy.py, repack_art.py, validate.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
