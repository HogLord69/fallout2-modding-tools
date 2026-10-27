#!/usr/bin/env python3
"""
make_pc_colonist.py - Pixel-perfect recolor of HMJMPS/HFJMPS matching the user reference:
- Light off-white/light-grey crew tee with visible fold shading & highlight
- Defined dark-brown belt with silver buckle
- Earthy olive/khaki-brown trousers with fold shadows & highlights
- Natural peachy-tan arms/skin
- Dark-brown boots with highlight separation
- Dark hair
"""
from __future__ import annotations

import re
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
from foclib import GameIndex  # noqa: E402

CRIT_DIR = ROOT / "mod" / "data" / "art" / "critters"
IDS_DIR = ROOT / "mod" / "ids"
DRAW_INI = ROOT / "base" / "ddraw.ini"

# Vault suit fabric census
SUIT_BLUES = {35, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 104, 105, 106,
              107, 108, 109, 110, 111, 113, 114, 115, 116}
SUIT_GOLDS = {56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68,
              70, 71, 72, 73, 74, 75, 79, 80, 81, 82, 83, 87, 88, 89,
              90, 91, 92, 93, 94, 95, 99, 214}
SUIT_WARM = {120, 163, 164}
SUIT_SPEC = {32, 33, 34, 36, 37}
SUIT_FABRIC = SUIT_BLUES | SUIT_GOLDS | SUIT_WARM | SUIT_SPEC

# Existing skin indices
SKIN_HI = {144, 156, 157, 158, 159, 160, 161, 162,
           172, 173, 174, 188, 189, 190, 191, 192, 193, 194}
# Existing hair indices
HAIR = {27, 28, 29}

# TARGET LADDERS (Dark -> Bright)
# ---- Target ladders (dark -> bright), sampled directly from the owner's
# reference image (composer_2026-08-31_21-01-37-271_ee63d6.jpg), pixel by
# pixel, then matched to the nearest color.pal index. This is NOT a color
# guess - these are the reference's actual measured RGB values.
SHIRT_LADDER = [24, 201, 118, 19, 18]        # warm off-white/tan
PANTS_LADDER = [31, 78, 203, 224, 76]        # warm brown (dark->light)
BOOT_LADDER = [31, 30, 204, 206, 77]         # dark brown
HAIR_LADDER = [31, 30, 29, 206, 77]          # dark brown
SKIN_LADDER = [27, 205, 20, 19, 183]         # warm tan skin

# Belt & Buckle
BELT_COLOR = 30     # Dark leather (44, 24, 24)
BUCKLE_HI = 3       # Silver highlight (207, 207, 207)
BUCKLE_MID = 6      # Silver midtone (162, 162, 162)


def _palette(gi):
    raw = gi.vfs.read("color.pal")
    pal = []
    for i in range(256):
        r, g, b = raw[i * 3], raw[i * 3 + 1], raw[i * 3 + 2]
        pal.append((min(255, (r << 2) | (r >> 4)),
                    min(255, (g << 2) | (g >> 4)),
                    min(255, (b << 2) | (b >> 4))))
    return pal


def _luma(v, pal):
    r, g, b = pal[v]
    return (r * 299 + g * 587 + b * 114) // 1000


def _pick(ladder, rk):
    rk = max(0.0, min(1.0, rk))
    i = round(rk * (len(ladder) - 1))
    return ladder[max(0, min(len(ladder) - 1, i))]


class RecolorEngine:
    def __init__(self, gi):
        self.pal = _palette(gi)
        p = self.pal
        
        base_suit = SUIT_BLUES | SUIT_GOLDS | SUIT_WARM
        suit_lumas = {v: _luma(v, p) for v in base_suit}
        lo, hi = min(suit_lumas.values()), max(suit_lumas.values())
        self.suit_rank = {v: (lum - lo) / max(1, hi - lo) for v, lum in suit_lumas.items()}
        for v in SUIT_SPEC:
            self.suit_rank[v] = 1.0
            
        sk = {v: _luma(v, p) for v in SKIN_HI}
        slo, shi = min(sk.values()), max(sk.values())
        self.skin_rank = {v: (lum - slo) / max(1, shi - slo) for v, lum in sk.items()}
        
        hk = {v: _luma(v, p) for v in HAIR}
        hlo, hhi = min(hk.values()), max(hk.values())
        self.hair_rank = {v: (lum - hlo) / max(1, hhi - hlo) for v, lum in hk.items()}


def recolor_frame(px: bytearray, w, h, di, engine: RecolorEngine) -> None:
    head_bottom = int(h * 0.15)
    waist = int(h * 0.42)
    boot_top = int(h * 0.82)
    sleeve_cut = int(h * 0.26)

    for y in range(h):
        xs = [x for x in range(w) if px[y * w + x] != 0]
        if not xs:
            continue
        min_x, max_x = min(xs), max(xs)

        for x in range(w):
            idx = y * w + x
            v = px[idx]
            if v == 0:
                continue

            # Hair
            if v in HAIR:
                px[idx] = _pick(HAIR_LADDER, engine.hair_rank[v])
                continue

            # Head / Face zone
            if y < head_bottom:
                if v in SKIN_HI:
                    px[idx] = _pick(SKIN_LADDER, engine.skin_rank[v])
                elif v in SUIT_FABRIC:
                    # Collar -> shirt fabric
                    rk = engine.suit_rank.get(v, 0.7)
                    px[idx] = _pick(SHIRT_LADDER, rk)
                continue

            # Forearms on side/front
            arm_inset = 1 if di in (1, 4) else 3
            is_outer_arm = (sleeve_cut <= y < waist and (x <= min_x + arm_inset or x >= max_x - arm_inset))

            # Torso / Belt span
            torso_inset = 3
            torso_lo = min_x + torso_inset
            torso_hi = max_x - torso_inset
            is_belt_row = (waist <= y <= waist + 1 and torso_lo <= x <= torso_hi)

            # Lower body (Waist down)
            if y >= waist:
                if y >= boot_top and not is_belt_row:
                    rk = engine.suit_rank.get(v, 0.3)
                    px[idx] = _pick(BOOT_LADDER, rk)
                elif is_belt_row:
                    cx = (torso_lo + torso_hi) // 2
                    if di in (2, 3) and abs(x - cx) <= 1:
                        px[idx] = BUCKLE_HI if x == cx else BUCKLE_MID
                    else:
                        px[idx] = BELT_COLOR
                else:
                    if v in SUIT_FABRIC:
                        rk = engine.suit_rank.get(v, 0.5)
                        px[idx] = _pick(PANTS_LADDER, rk)
                    elif v in SKIN_HI:
                        px[idx] = _pick(SKIN_LADDER, engine.skin_rank[v])
            else:
                # Upper body (Waist up)
                if is_outer_arm and v not in SUIT_GOLDS:
                    rk = engine.suit_rank.get(v, 0.6) if v in SUIT_FABRIC else engine.skin_rank.get(v, 0.6)
                    px[idx] = _pick(SKIN_LADDER, rk)
                else:
                    if v in SUIT_FABRIC:
                        rk = engine.suit_rank.get(v, 0.6)
                        px[idx] = _pick(SHIRT_LADDER, rk)
                    elif v in SKIN_HI:
                        px[idx] = _pick(SKIN_LADDER, engine.skin_rank[v])


def walk_frames(data: bytes):
    fpd = struct.unpack_from(">H", data, 0x08)[0] or 1
    pos = 0x3E
    for di in range(6):
        for _f in range(fpd):
            if pos + 12 > len(data):
                return
            w, h, size, _, _ = struct.unpack_from(">HHIhh", data, pos)
            px = data[pos + 12: pos + 12 + min(size, w * h)]
            yield di, pos, w, h, size, px
            pos += 12 + size


def splice(jump_raw: bytes, engine: RecolorEngine) -> bytes:
    out = bytearray(jump_raw)
    for di, pos, w, h, size, px in walk_frames(jump_raw):
        b = bytearray(px)
        recolor_frame(b, w, h, di, engine)
        out[pos + 12: pos + 12 + len(b)] = b
    return bytes(out)


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    gi = GameIndex()
    engine = RecolorEngine(gi)
    listing = subprocess.run([str(ROOT / "tools" / "dat" / "dat2.exe"), "l",
                              str(ROOT / "base" / "critter.dat")],
                             capture_output=True, text=True).stdout
    critter_files = set()
    for line in listing.splitlines():
        if "\\" in line:
            critter_files.add(line.strip().split("\\")[-1].strip().upper())

    CRIT_DIR.mkdir(parents=True, exist_ok=True)
    pairs = [("HMJMPS", "hmpcot"), ("HFJMPS", "hfpcot")]
    written = 0
    detail = []
    for src_prefix, dst_prefix in pairs:
        members = sorted(n for n in critter_files
                         if n.startswith(src_prefix) and n.endswith(
                             (".FRM", ".FR0", ".FR1", ".FR2", ".FR3", ".FR4", ".FR5")))
        ok = 0
        for name in members:
            suffix = name[len(src_prefix):]
            dst = dst_prefix + suffix
            try:
                raw = gi.vfs.read(f"art\\critters\\{name}")
            except Exception:
                continue
            new = splice(raw, engine)
            if not args.dry_run:
                (CRIT_DIR / dst).write_bytes(new)
            ok += 1
        written += ok
        detail.append(f"{src_prefix}: {ok}")
    print(f"{' | '.join(detail)} ({'dry' if args.dry_run else 'written'}) total {written}")

    if not args.dry_run:
        reg = IDS_DIR / "art_critters.txt"
        lines = [l for l in reg.read_text(encoding="utf-8").splitlines()
                 if l.strip() and not l.startswith("#")]
        lines = [l for l in lines if not l.lower().startswith(("hmpcot", "hfpcot"))]
        lines += ["hmpcot,11,1", "hfpcot,11"]
        header = ("# FOC critters art. First line = FOC_START[art_critters] (250).\n"
                  "# Entry = art prefix,flags as used by the engine.\n")
        reg.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")

        ini = DRAW_INI.read_text(encoding="cp1252", errors="replace")
        for key, val in (("MaleDefaultModel", "hmpcot"), ("FemaleDefaultModel", "hfpcot")):
            pat = re.compile(rf"^;?\s*{key}\s*=.*$", re.M)
            ini = pat.sub(f"{key}={val}", ini)
        if "MaleDefaultModel" not in ini:
            ini = re.sub(r"^\[Misc\]\s*$",
                         "[Misc]\nMaleDefaultModel=hmpcot\nFemaleDefaultModel=hfpcot",
                         ini, count=1, flags=re.M)
        DRAW_INI.write_text(ini, encoding="cp1252")
    return 0


if __name__ == "__main__":
    sys.exit(main())
