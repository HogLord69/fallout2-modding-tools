#!/usr/bin/env python3
"""
tune_weapon.py - set individual weapon-proto fields on a FOC item, in place.

    python tools/tune_weapon.py 1059 --dmg 5 12 --range 20 --perk none
    python tools/tune_weapon.py 1059 --min-st 4 --ap 6 --cap 6 --dry-run

Edits mod/data/proto/items/<index>.pro (a FOC-range item or a base-range
override we already ship) and prints before -> after for every field it
touched. Runs deploy + validate unless --no-deploy. Only the fields you name
change; everything else in the proto is untouched.

Weapon block offsets (proto.cc protoItemDataRead, item data starts @57):
  61 minDmg  65 maxDmg  73 maxRange1  77 maxRange2  85 minStrength
  89 AP1  93 AP2  101 perk  109 caliber  113 ammoTypePid  117 ammoCapacity
perk names: none(-1) longrange(58) accurate(59) penetrate(60) knockback(61)
  scoperange(64) fastreload(65) nightsight(66)  - perk_defs.h enum Perk.
"""

from __future__ import annotations

import argparse
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ITEMS = ROOT / "mod" / "data" / "proto" / "items"

PERKS = {"none": -1, "longrange": 58, "accurate": 59, "penetrate": 60, "knockback": 61,
         "scoperange": 64, "fastreload": 65, "nightsight": 66}
FIELDS = {   # name: (offset, label)
    "min_dmg": (61, "minDmg"), "max_dmg": (65, "maxDmg"),
    "range1": (73, "range1"), "range2": (77, "range2"),
    "min_st": (85, "minST"), "ap1": (89, "AP1"), "ap2": (93, "AP2"),
    "perk": (101, "perk"), "cap": (117, "ammoCapacity"),
    "caliber": (109, "caliber"), "ammo_pid": (113, "ammoTypePid"),
}
# caliber id -> (id, default ammo pid). Every value READ from this base's ammo
# protos (caliber field @57) on 2026-09-21, not remembered - remembered ones
# were wrong for 5 of 9. Weapon.caliber must equal ammo.caliber to reload.
CALIBERS = {"223": (5, 34), "5mm": (6, 35), "10mm": (8, 29), "44": (9, 31),
            "14mm": (10, 33), "12ga": (11, 95), "9mm": (12, 121), "45": (14, 357), "762": (18, 363)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("index", type=int, help="item proto index (1-based items.lst line)")
    ap.add_argument("--dmg", nargs=2, type=int, metavar=("MIN", "MAX"))
    ap.add_argument("--range", type=int, help="maxRange1 (single-shot range)")
    ap.add_argument("--range2", type=int)
    ap.add_argument("--min-st", type=int)
    ap.add_argument("--ap", type=int, help="AP1")
    ap.add_argument("--ap2", type=int)
    ap.add_argument("--cap", type=int, help="magazine size")
    ap.add_argument("--perk", choices=sorted(PERKS))
    ap.add_argument("--caliber", choices=sorted(CALIBERS),
                    help="switch ammo type; sets caliber AND ammoTypePid to that round's default")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-deploy", action="store_true")
    a = ap.parse_args()

    p = ITEMS / f"{a.index:08d}.pro"
    if not p.exists():
        sys.exit(f"{p.relative_to(ROOT)} not found - only FOC items / shipped overrides can be tuned")
    buf = bytearray(p.read_bytes())
    if struct.unpack_from(">i", buf, 32)[0] != 3:
        sys.exit(f"item {a.index} is not a weapon (type {struct.unpack_from('>i', buf, 32)[0]})")

    want = {}
    if a.dmg: want["min_dmg"], want["max_dmg"] = a.dmg
    if a.range is not None: want["range1"] = a.range
    if a.range2 is not None: want["range2"] = a.range2
    if a.min_st is not None: want["min_st"] = a.min_st
    if a.ap is not None: want["ap1"] = a.ap
    if a.ap2 is not None: want["ap2"] = a.ap2
    if a.cap is not None: want["cap"] = a.cap
    if a.perk: want["perk"] = PERKS[a.perk]
    if a.caliber: want["caliber"], want["ammo_pid"] = CALIBERS[a.caliber]
    if not want:
        sys.exit("nothing to change")

    changed = 0
    for k, v in want.items():
        off, label = FIELDS[k]
        old = struct.unpack_from(">i", buf, off)[0]
        mark = "" if old == v else "  *"
        print(f"  {label:12s} {old:>4} -> {v:<4}{mark}")
        if old != v:
            struct.pack_into(">i", buf, off, v); changed += 1
    if a.dry_run:
        print(f"dry run: {changed} field(s) would change"); return 0
    if not changed:
        print("already at target"); return 0
    p.write_bytes(bytes(buf))
    print(f"wrote {p.relative_to(ROOT)} ({changed} field(s))")
    if not a.no_deploy:
        for t in ("deploy.py", "validate.py"):
            print(f"\n$ python tools/{t}")
            if subprocess.run([sys.executable, str(ROOT / "tools" / t)], cwd=ROOT).returncode:
                return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
