#!/usr/bin/env python3
"""
restore_map.py - put a set-aside map back into mod/data/maps, with its art
re-pointed by name.

    python tools/restore_map.py set_aside/maps/RWFAC1/<file>.MAP RWFAC1.MAP --dry-run
    python tools/restore_map.py set_aside/maps/RWFAC1/<file>.MAP RWFAC1.MAP

WHY
---
A map object carries its art as a FID index into an art list. repack_art.py
rewrites those indices in every map inside base/mods/foc/maps and
mod/data/maps when it swaps art across the 4096 cap, but a map kept outside
those folders (set_aside/maps/) is not rewritten, so after a repack it points
at whatever art now sits at its old indices. Copying it back as it is would
draw the wrong pieces (on 2026-10-15 the sewer pieces the Facility Below uses
were swapped up, and an Olympus piece and a vault door took their slots).

HOW
---
The art registries (mod/ids/art_*.txt) as they were at --art-from (the
set-aside commit, 8aeca31a, by default) say which art each index drew when
the map left the game; today's registries say where that art is now. Every
object's FID, inventory included, is moved to the art's current index. Protos
need nothing (repack_art.py rewrites every .pro in place and PIDs never
change), and floor tiles need nothing (FOC has no tile registry).

Refuses to overwrite an existing map unless --force. Afterwards run
tools/repack_art.py: art nothing used when it last ran may sit above the cap,
and the engine would draw index & 0xFFF.
"""

from __future__ import annotations

import argparse
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foclib import GameIndex  # noqa: E402
from ids import ART_KEY, FOC_START  # noqa: E402
from repack_art import all_objects, fid_dir, fid_index, with_index  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
IDS = ROOT / "mod" / "ids"
MAPS = ROOT / "mod" / "data" / "maps"
SET_ASIDE_COMMIT = "8aeca31a"


def entries(text: str) -> list[str]:
    """The registry's entry lines (repack_art.registry_split), as art names."""
    lines = text.splitlines()
    out = [l for l in lines if not l.strip().startswith("#")]
    while out and not out[-1].strip():
        out.pop()
    return [l.split(",")[0].strip().lower() for l in out]


def registries(commit: str) -> dict[str, tuple[list[str], list[str]]]:
    """Per art dir, (entries then, entries now)."""
    out = {}
    for d, key in ART_KEY.items():
        rel = f"mod/ids/{key}.txt"
        now = IDS / f"{key}.txt"
        if not now.is_file():
            continue
        then = subprocess.run(["git", "show", f"{commit}:{rel}"], cwd=ROOT,
                              capture_output=True, text=True, encoding="utf-8")
        if then.returncode != 0:
            sys.exit(f"git show {commit}:{rel} failed: {then.stderr.strip()}")
        out[d] = (entries(then.stdout), entries(now.read_text(encoding="utf-8")))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("src", type=Path, help="the set-aside .MAP")
    ap.add_argument("name", help="file name in mod/data/maps, e.g. RWFAC1.MAP")
    ap.add_argument("--art-from", default=SET_ASIDE_COMMIT,
                    help=f"commit whose art registries the map was made against (default {SET_ASIDE_COMMIT})")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="overwrite an existing map")
    a = ap.parse_args()

    dest = MAPS / a.name
    clash = [p for p in MAPS.glob("*") if p.name.upper() == a.name.upper()]
    if clash and not a.force:
        sys.exit(f"{clash[0]} exists; refusing to overwrite it (--force)")

    regs = registries(a.art_from)
    where = {d: {n: i for i, n in enumerate(now) if n} for d, (_, now) in regs.items()}
    raw = a.src.read_bytes()
    gi = GameIndex(pristine=False)
    m = gi.load_map(raw)
    b = bytearray(raw)
    moved, missing = {}, {}
    for o in all_objects(m):
        fid = o.fid & 0xFFFFFFFF
        d = fid_dir(fid)
        if d not in regs:
            continue
        start = FOC_START[ART_KEY[d]] - 1           # art is 0-based (port.py cmd_art)
        k = fid_index(fid) - start
        then, now = regs[d]
        if not (0 <= k < len(then)) or (k < len(now) and now[k] == then[k]):
            continue
        name = then[k]
        if name not in where[d]:
            missing[(d, name)] = missing.get((d, name), 0) + 1
            continue
        struct.pack_into(">I", b, o.fid_offset, with_index(fid, start + where[d][name]))
        moved[(d, name)] = moved.get((d, name), 0) + 1

    gi.load_map(bytes(b))                           # still a readable map
    for (d, name), n in sorted(moved.items()):
        print(f"  {d}/{name}: {n} object(s) re-pointed")
    for (d, name), n in sorted(missing.items()):
        print(f"  MISSING {d}/{name}: {n} object(s) left as they were (no such art now)")
    print(f"{a.src.name} -> {dest}: {sum(moved.values())} re-pointed, {sum(missing.values())} missing"
          + (" (dry run)" if a.dry_run else ""))
    if not a.dry_run:
        dest.write_bytes(bytes(b))
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
