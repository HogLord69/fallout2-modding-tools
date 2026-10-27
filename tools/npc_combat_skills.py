#!/usr/bin/env python3
"""
npc_combat_skills.py - give each named FOC colonist the gun skill its weapon
uses, as a foc-layer override of that critter's proto.

    python tools/npc_combat_skills.py --dry-run
    python tools/npc_combat_skills.py            # write overrides, deploy, validate

Why: combat to-hit uses the skill of the equipped weapon (item.cc
weaponGetSkillForHitMode -> that critter's skill). After the gun rebalance
(tools/gun_rebalance.py) a rifle trains Big Guns, so an NPC handed a rifle
whose Big Guns is 0 whiffs every shot. Owner assigns each colonist a primary
gun skill; this moves their combat points onto it.

Each entry is (proto_index): (name, target_skill, value). The proto is a base
vanilla critter proto reused for the colonist and, verified, is used by no one
else in any FOC map, so overriding it touches only that NPC.

value = None  -> relocate: the target skill gets the NPC's current highest of
                 {Small Guns, Big Guns, Energy}; the other two are zeroed.
value = int   -> set the target skill to that number (used when the NPC has no
                 gun skill to move); the other two are zeroed. FLAGGED below.

Only the three gun skills are touched. Melee, Unarmed, Throwing and every
non-combat skill are left exactly as the base proto has them.

Critter proto layout (proto.cc): skills[18] @ byte 328, big-endian int32, in
SKILL-enum order 0 SmallGuns, 1 BigGuns, 2 Energy, 3 Unarmed, ...
"""

from __future__ import annotations

import argparse
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foclib import GameIndex  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
CRIT_DIR = ROOT / "mod" / "data" / "proto" / "critters"

SKILLS_OFF = 328
GUN_SKILLS = {"SmallGuns": 0, "BigGuns": 1, "Energy": 2}

# proto_index: (name, target_skill, value)  -- value None = relocate the NPC's
# highest gun skill; int = set explicitly (NPC had no gun points to move).
NPC_SKILLS = {
    38: ("Arren",   "SmallGuns", 95),     # owner-set (was Small 29 / Big 59 / Energy 9)
    32: ("Rem",     "BigGuns",   85),     # owner-set
    13: ("Callum",  "Energy",    70),     # owner-set (Elder proto had no gun skill to relocate)
    95: ("Kilgore", "BigGuns",   65),     # owner-set (was tools/kilgore_skills.py)
}


def patch(raw: bytes, target: str, value: int | None) -> tuple[bytes, dict]:
    buf = bytearray(raw)

    def rd(i):
        return struct.unpack_from(">i", buf, SKILLS_OFF + 4 * i)[0]

    def wr(i, v):
        struct.pack_into(">i", buf, SKILLS_OFF + 4 * i, v)

    before = {name: rd(i) for name, i in GUN_SKILLS.items()}
    combat = value if value is not None else max(before.values())
    for name, i in GUN_SKILLS.items():
        wr(i, combat if name == target else 0)
    after = {name: rd(i) for name, i in GUN_SKILLS.items()}
    return bytes(buf), {"before": before, "after": after, "value": combat}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--base", default=str(ROOT / "base"))
    ap.add_argument("--no-deploy", action="store_true")
    args = ap.parse_args()

    gi = GameIndex(Path(args.base), pristine=False)
    wrote = 0
    for idx, (name, target, value) in sorted(NPC_SKILLS.items()):
        fn = gi.proto_filename(0x01000000 | idx)
        raw = gi.vfs.read(("proto\\critters\\" + fn))
        out, rep = patch(raw, target, value)
        b = " ".join(f"{k[:1]}{v}" for k, v in rep["before"].items())
        a = " ".join(f"{k[:1]}{v}" for k, v in rep["after"].items())
        src = "set" if value is not None else "relocate"
        print(f"{name:8s} proto {idx:>3} ({fn}): [{b}] -> [{a}]  ({target} {rep['value']}, {src})")
        if out == raw:
            continue
        if not args.dry_run:
            CRIT_DIR.mkdir(parents=True, exist_ok=True)
            (CRIT_DIR / fn).write_bytes(out)
        wrote += 1

    if args.dry_run:
        print(f"dry run: {wrote} proto(s) would change")
        return 0
    print(f"wrote {wrote} override proto(s) to {CRIT_DIR.relative_to(ROOT)}")
    if wrote and not args.no_deploy:
        for t in ("deploy.py", "validate.py"):
            print(f"\n$ python tools/{t}")
            rc = subprocess.run([sys.executable, str(ROOT / "tools" / t)], cwd=ROOT).returncode
            if rc:
                return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
