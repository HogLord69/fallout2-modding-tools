#!/usr/bin/env python3
"""
splice_head.py - put the old man's (narobe) head on the NCR Ranger body.

Callum is the NMRANG ranger sprite; the owner wants the old man's face
(the previous narobe robe sprite's head) on the ranger body.

Index-level splice (no RGB round-trip so body pixels never change):
  * parse both FRMs' frame tables (same layout walk)
  * for each body frame, rows 0..RANGER_HEAD_ROWS-1 are REPLACED by the
    narobe head rows (with the ranger head band cleared first), centered
    on the body's shoulder center line
  * the head's indices go through the SAME darken table as the body
    (factor 0.65) so the face matches the darkened armor
  * everything else stays byte-identical

Usage:
    python tools/splice_head.py [--dry-run] [--factor 0.65]
"""
from __future__ import annotations

import argparse
import os
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from foclib import GameIndex  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CRIT_DIR = ROOT / "mod" / "data" / "art" / "critters"
DAT2 = ROOT / "tools" / "dat" / "dat2.exe"
BASE_CRITTER_DAT = ROOT / "base" / "critter.dat"

RANGER_HEAD_ROWS = 8   # ranger head band (rows 0..7); shoulders widen at 8
NAROBE_HEAD_ROWS = 8   # use the old man's top 8 rows (rows 8-9 are neck/shoulder)


def darken_table(pal: list[tuple[int, int, int]], factor: float) -> list[int]:
    def nearest(pix, p):
        r, g, b = pix
        best, bd = 0, 1 << 30
        for i, (pr, pg, pb) in enumerate(p):
            d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
            if d < bd:
                best, bd = i, d
        return best
    dark = [(int(r * factor), int(g * factor), int(b * factor)) for r, g, b in pal]
    return [nearest(dark[i], pal) for i in range(256)]


def load_palette(gi):
    raw = gi.vfs.read("color.pal")
    return [((raw[i*3] << 2) | (raw[i*3] >> 4),
             (raw[i*3+1] << 2) | (raw[i*3+1] >> 4),
             (raw[i*3+2] << 2) | (raw[i*3+2] >> 4)) for i in range(256)]


def walk_frames(data: bytes):
    """Yield (dir, pos, w, h, size) for every frame in an FRM."""
    fpd = struct.unpack_from(">H", data, 0x08)[0] or 1
    pos = 0x3E
    for di in range(6):
        for _f in range(fpd):
            if pos + 12 > len(data):
                return
            w, h, size, _, _ = struct.unpack_from(">HHIhh", data, pos)
            yield di, pos, w, h, size
            pos += 12 + size


def count_in_dir(frames, di, pos):
    """0-based index of (di, pos) within its direction's frame run."""
    n = 0
    for d, p, *_ in frames:
        if d != di:
            continue
        if p == pos:
            return n
        n += 1
    return 0


def head_pixels(data: bytes, rows: int):
    """Return list of per-frame pixel bytearrays for the narobe head file,
    cropped/windowed the same way the body will be sampled."""
    frames = []
    for di, pos, w, h, size in walk_frames(data):
        px = bytearray(data[pos + 12: pos + 12 + min(size, w * h)])
        frames.append((di, pos, w, h, size, px))
    return frames


def splice_one(gi, body_name: str, head_vfs: str, table: list[int],
               head_rows: int = NAROBE_HEAD_ROWS) -> bytes:
    body = (CRIT_DIR / body_name).read_bytes()
    head = gi.vfs.read(head_vfs)

    bframes = list(walk_frames(body))
    hframes = head_pixels(head, head_rows)

    # group head frames by direction; within a direction, use the last
    # narobe frame as the stand-in when the ranger has extra frames
    h_by_dir: dict[int, list] = {}
    for hd, hpos, hw, hh, hsize, hpx in hframes:
        h_by_dir.setdefault(hd, []).append((hpos, hw, hh, hsize, hpx))

    out = bytearray(body)
    for di, pos, w, h, size in bframes:
        dir_frames = h_by_dir.get(di)
        if not dir_frames:
            continue
        # pick the narobe frame at the same *within-direction index*;
        # clamp to the last available if the ranger has more frames
        idx_in_dir = count_in_dir(bframes, di, pos)
        hpos, hw, hh, hsize, hpx = dir_frames[min(idx_in_dir, len(dir_frames) - 1)]
        # body pixel window
        b = bytearray(out[pos + 12: pos + 12 + min(size, w * h)])
        hp = hpx

        # shoulder center line = first row below the head band
        neck_y = min(RANGER_HEAD_ROWS, h - 1)
        xs = [x for x in range(w) if b[neck_y * w + x]]
        if not xs:
            continue
        cx = (min(xs) + max(xs)) // 2

        # head horizontal extent in narobe coords
        hl, hr = hw, -1
        for y in range(min(head_rows, hh)):
            for x in range(hw):
                if hp[y * hw + x]:
                    hl = min(hl, x)
                    hr = max(hr, x)
        if hr < hl:
            continue
        head_w = hr - hl + 1

        # step 1: clear the ranger head band
        for y in range(min(RANGER_HEAD_ROWS, h)):
            for x in range(w):
                b[y * w + x] = 0
        # step 2: paste narobe head (rows 0..head_rows-1), darkened
        dx0 = cx - head_w // 2
        for y in range(min(head_rows, hh, h)):
            for x in range(hl, hr + 1):
                idx = hp[y * hw + x]
                if not idx:
                    continue
                tx = dx0 + (x - hl)
                if 0 <= tx < w:
                    b[y * w + tx] = table[idx]
        # write back
        out[pos + 12: pos + 12 + len(b)] = b
    return bytes(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--factor", type=float, default=0.65)
    args = ap.parse_args()

    gi = GameIndex()
    table = darken_table(load_palette(gi), args.factor)

    # narobe family listing from critter.dat
    listing = subprocess.run([str(DAT2), "l", str(BASE_CRITTER_DAT)],
                             capture_output=True, text=True).stdout
    naro = set()
    for line in listing.splitlines():
        if "NAROBE" in line.upper():
            naro.add(line.strip().split("\\")[-1].upper())
    naro_by_code: dict[str, list[str]] = {}
    for fn in naro:
        naro_by_code.setdefault(fn[6:8], []).append(fn)

    srcs = sorted(p.name for p in CRIT_DIR.glob("NMRANG*"))
    changed = 0
    for src in srcs:
        code = src[6:8]
        ext = Path(src).suffix.upper()  # .FRM / .FR0
        cands = [f for f in naro_by_code.get(code, []) if f.endswith(ext)]
        if not cands and ext == ".FRM":
            cands = [f for f in naro_by_code.get(code, []) if f.endswith(".FR0")]
        head_src = cands[0] if cands else None
        if head_src is None:
            # missing code: use the standing head (AA) for small/brief anims;
            # multi-direction .FRM only (per-direction .FR0-5 get AA's .FR0)
            fallback = (f"NAROBEAA.FRM" if ext == ".FRM" else f"NAROBEAA.FR0")
            head_src = fallback if fallback in naro else None
        if head_src is None:
            print(f"  skip {src}: no narobe head (code {code} {ext})")
            continue
        new = splice_one(gi, src, f"art\\critters\\{head_src}", table)
        if new != (CRIT_DIR / src).read_bytes():
            changed += 1
            if not args.dry_run:
                (CRIT_DIR / src).write_bytes(new)
            print(f"  {'DRY' if args.dry_run else 'OK '} {src} <- {head_src}")
        else:
            print(f"  noop {src} <- {head_src}")
    print(f"\n{changed}/{len(srcs)} frames spliced (factor {args.factor})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())