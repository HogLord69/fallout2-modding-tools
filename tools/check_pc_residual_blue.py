#!/usr/bin/env python3
"""check_pc_residual_blue.py - verify no vault-suit blue survives in the
recolored PC model (hmpcot/hfpcot).

Recolors every HMJMPS/HFJMPS family in memory with the CURRENT
make_pc_colonist.py logic and counts pixels whose color.pal RGB has
b - max(r,g) > 15 (the vault-suit blue family). Catches the "blue fringe"
bug class: an incomplete SUIT_BLUES census left ~45k blue pixels (v1-v5);
complete census + collar-zone fix dropped it to ~5 (v6, commit 9be6d99).

Usage: python tools/check_pc_residual_blue.py
Exits 1 if any family exceeds THRESHOLD per file, else 0.
"""
from __future__ import annotations

import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

from foclib import GameIndex  # noqa: E402
import make_pc_colonist as m  # noqa: E402

THRESHOLD = 40  # per family; low single digits are acceptable hair shadows


def main() -> int:
    gi = GameIndex(base=str(ROOT / "base"), pristine=True)
    pal = m._palette(gi)
    engine = m.RecolorEngine(gi)

    listing = subprocess.run(
        [str(ROOT / "tools" / "dat" / "dat2.exe"), "l", str(ROOT / "base" / "critter.dat")],
        capture_output=True, text=True, cwd=str(ROOT)).stdout
    members = set()
    for line in listing.splitlines():
        s = line.strip()
        if "\\" in s:
            members.add(s.split("\\")[-1].strip().upper())

    total = 0
    bad = []
    for name in sorted(members):
        if not (name.startswith("HMJMPS") or name.startswith("HFJMPS")):
            continue
        try:
            data = gi.vfs.read("art/critters/" + name)
        except Exception:
            continue
        new = m.splice(data, engine)
        fpd = struct.unpack_from(">H", new, 8)[0] or 1
        pos = 0x3E
        blue = 0
        for _di in range(6):
            for _f in range(fpd):
                if pos + 12 > len(new):
                    break
                w, h, size, _, _ = struct.unpack_from(">HHIhh", new, pos)
                if size == 0 or size > 0x1000000:
                    break
                px = new[pos + 12: pos + 12 + min(size, w * h)]
                for v in px:
                    if v == 0:
                        continue
                    r, g, b = pal[v]
                    if b - max(r, g) > 15:
                        blue += 1
                pos += 12 + size
        total += blue
        if blue > THRESHOLD:
            bad.append((blue, name))

    bad.sort(reverse=True)
    for blue, name in bad:
        print(f"  {blue:6d}  {name}")
    print(f"residual blue: {total} px across {len(members)} families "
          f"(threshold {THRESHOLD}/file)")
    if not bad and total < THRESHOLD:
        print("OK: no residual suit blue")
        return 0
    print("PROBLEM: blue survivors above threshold - re-census SUIT_BLUES "
          "and re-check the head/collar zone")
    return 1


if __name__ == "__main__":
    sys.exit(main())