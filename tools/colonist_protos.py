#!/usr/bin/env python3
"""
colonist_protos.py - set the Redwell colonists' HP, gender and gun skill in
their critter protos (foc-layer overrides of the vanilla protos they reuse).

    python tools/colonist_protos.py --dry-run
    python tools/colonist_protos.py            # write, deploy, validate

Every colonist reuses a vanilla critter proto that no other FOC map uses
(checked 2026-09-28 against every map in base/mods/foc/maps), so an override
touches only that colonist. Owner-approved values (loadout table, 2026-09-28).

What changes, and nothing else:
  max HP          stat 7: baseStats[7] (@48) PLUS bonusStats[7] (@188). The
                  engine recomputes the base from SPECIAL when a critter is
                  spawned, so base = derived and bonus = target - base
                  (foclib.critter_stats)
  gender          stat 34  (0 male, 1 female) - Callum's proto is the vanilla
                           Elder, which is female
  gun skills      skills[0..2] @328: SmallGuns, BigGuns, Energy. The named one
                  is set, the other two zeroed (as npc_combat_skills.py did),
                  so a colonist fights with the gun they carry.

Current HP on a map is a separate field of the placed object; the colonists'
scripts top it up to the new maximum on map entry (rw_kit.h).
"""

from __future__ import annotations

import argparse
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foclib import GameIndex  # noqa: E402
from foclib.critter_stats import set_total, total  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CRIT_DIR = ROOT / "mod" / "data" / "proto" / "critters"
STATS_OFF = 48
SKILLS_OFF = 328
STAT_HP, STAT_GENDER = 7, 34
GUN = {"SmallGuns": 0, "BigGuns": 1, "Energy": 2}

# proto index: (name, max HP, gender or None, gun skill or None, value)
COLONISTS = {
    38:  ("Arren",   65, None, "SmallGuns", 95),
    13:  ("Callum",  45, 0,    "Energy",    70),
    32:  ("Rem",     60, None, "BigGuns",   85),
    42:  ("Dozer",   80, None, "BigGuns",   75),
    43:  ("Wren",    60, None, "SmallGuns", 70),
    95:  ("Kilgore", 55, None, "BigGuns",   65),
    211: ("Sable",   45, None, None,        None),
    104: ("Nettle",  75, None, "BigGuns",   45),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-deploy", action="store_true")
    args = ap.parse_args()

    base = GameIndex()                           # pristine: base + RPU
    for idx, (name, hp, gender, skill, value) in COLONISTS.items():
        out = CRIT_DIR / f"{idx:08d}.pro"
        raw = out.read_bytes() if out.is_file() else base.vfs.read(base.proto_path((1 << 24) | idx))
        buf = bytearray(raw)
        rd = lambda off: struct.unpack_from(">i", buf, off)[0]  # noqa: E731
        before = (total(buf, STAT_HP), rd(STATS_OFF + 4 * STAT_GENDER),
                  [rd(SKILLS_OFF + 4 * i) for i in range(3)])
        set_total(buf, STAT_HP, hp)
        if gender is not None:
            struct.pack_into(">i", buf, STATS_OFF + 4 * STAT_GENDER, gender)
        if skill is not None:
            for s, i in GUN.items():
                struct.pack_into(">i", buf, SKILLS_OFF + 4 * i, value if s == skill else 0)
        after = (total(buf, STAT_HP), rd(STATS_OFF + 4 * STAT_GENDER),
                 [rd(SKILLS_OFF + 4 * i) for i in range(3)])
        print(f"  {name:8s} proto {idx:3d}  HP {before[0]}->{after[0]}  gender {before[1]}->{after[1]}  "
              f"small/big/energy {before[2]}->{after[2]}" + ("" if out.is_file() else "  (new override)"))
        if not args.dry_run:
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(bytes(buf))

    if args.dry_run or args.no_deploy:
        return 0
    for t in ("deploy.py", "validate.py"):
        rc = subprocess.run([sys.executable, str(ROOT / "tools" / t)], cwd=ROOT).returncode
        if rc:
            return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
