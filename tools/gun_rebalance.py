#!/usr/bin/env python3
"""
gun_rebalance.py - Sonora-style gun rules on every weapon proto the game can see.

    python tools/gun_rebalance.py --dry-run     # table of what would change
    python tools/gun_rebalance.py               # write, then deploy + validate

Two rules, both plain proto data (nothing in the engine is touched):

  skill   a two-handed conventional gun uses BIG GUNS. Engine mechanism
          (item.cc weaponGetSkillForHitMode): a gun whose attack mode maps to
          Small Guns is re-routed to Energy Weapons by damage type, else to Big
          Guns if item.extendedFlags has ItemProtoExtendedFlags_BigGun (0x0100).
          Two-handed is bit 0x0200. So: every non-energy gun with 0x0200 gets
          0x0100. One-handers keep Small Guns. Energy guns are untouched.

  AP      per attack mode, keyed on gun SIZE (one- vs two-handed). Burst is
          the common second mode, not flame, and is a flat 7 AP on a large
          (2H) gun and 5 AP on a small (1H) gun; a flamer's continuous fire
          counts as a burst and uses the same. Single shot stays quicker:

                              single   burst   continuous(flame)
            small (1H)          4        5          5
            large (2H)          6        7          7

          Energy guns follow the same size rule (a 2H laser/plasma rifle is a
          large gun), except their single shot: energy 1H = 4, energy 2H = 5.
          Vanilla is a flat 5 nearly everywhere with 6 for bursts, so this
          makes pistols/SMGs quick and rifles/heavy weapons deliberate. A
          mode of NONE is left alone (some vanilla protos carry junk AP in an
          unused secondary slot).

Item proto layout (proto.cc protoRead + protoItemDataRead, big-endian int32):
  24 extendedFlags   32 item type (3 = weapon)   57.. weapon block:
  57 animCode  61 minDmg  65 maxDmg  69 dmgType  73 range1  77 range2
  81 projPid   85 minST   89 AP1     93 AP2
extendedFlags low nibble = primary attack mode, next nibble = secondary
(0 none, 1 punch, 2 kick, 3 swing, 4 thrust, 5 throw, 6 single, 7 burst,
8 continuous) - item.cc _attack_skill / _attack_anim.

Output: a patched copy of each changed BASE proto in mod\\data\\proto\\items\\
(deploy.py copies it to base\\mods\\foc\\proto\\items\\, and the foc layer is
last in mods_order.txt so it wins over rpu.dat / master.dat). FOC-range protos
that are already ours are patched in place. Re-runnable: a proto already at
the target values is reported as unchanged.

NOT changed here: the skill descriptions in text\\english\\game\\skill.msg still
call Big Guns "the big ones" - update the wording separately if it matters.
"""

from __future__ import annotations

import argparse
import re
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foclib import GameIndex  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MOD_ITEMS = ROOT / "mod" / "data" / "proto" / "items"

EXT_OFF, TYPE_OFF = 24, 32
DMG_OFF, AP1_OFF, AP2_OFF = 69, 89, 93
ITEM_TYPE_WEAPON = 3
BIG_GUN, TWO_HANDED = 0x0100, 0x0200
MODE_NONE, MODE_SINGLE, MODE_BURST, MODE_CONT = 0, 6, 7, 8
GUN_MODES = {MODE_SINGLE, MODE_BURST, MODE_CONT}
ENERGY_DMG = {1, 3, 4}   # laser, plasma, electrical - weaponGetSkillForHitMode

# (energy, two_handed) -> {mode: ap}. Burst/continuous are keyed on size only:
# large (2H) 7, small (1H) 5. Single shot: conventional 4/6, energy 4/5.
AP_TABLE = {
    (False, False): {MODE_SINGLE: 4, MODE_BURST: 5, MODE_CONT: 5},
    (False, True):  {MODE_SINGLE: 6, MODE_BURST: 7, MODE_CONT: 7},
    (True,  False): {MODE_SINGLE: 4, MODE_BURST: 5, MODE_CONT: 5},
    (True,  True):  {MODE_SINGLE: 5, MODE_BURST: 7, MODE_CONT: 7},
}
MODE_NAME = {MODE_NONE: "-", MODE_SINGLE: "single", MODE_BURST: "burst", MODE_CONT: "cont"}

# Weapon protos the rules must not touch, by items.lst index (1-based).
SKIP = {
    270: "Robo Rocket Launcher - robot natural attack, AP 3 is its fire rate",
    427: "Flame Breath - fire gecko natural attack",
    574: "Lightsaber - RPU easter egg, hand-tuned",
    575: "Blaster - RPU easter egg, hand-tuned",
    576: "Lightsaber - RPU easter egg, hand-tuned",
    161: "Red Ryder BB Gun - a toy on Big Guns reads wrong; owner to decide",
    162: "Red Ryder LE BB Gun - same",
    261: "Jonny's BB Gun - same",
}


def item_names(gi: GameIndex) -> dict[int, str]:
    try:
        txt = gi.vfs.read("text\\english\\game\\pro_item.msg").decode("cp1252", "replace")
    except Exception:  # noqa: BLE001
        return {}
    return {int(a): b for a, b in re.findall(r"\{(\d+)\}\{\}\{([^}]*)\}", txt)}


def rebalance(raw: bytes) -> tuple[bytes, dict] | None:
    """Return (patched bytes, change record) for a gun, or None if not a gun."""
    if struct.unpack_from(">i", raw, TYPE_OFF)[0] != ITEM_TYPE_WEAPON:
        return None
    ext = struct.unpack_from(">I", raw, EXT_OFF)[0]
    p, s = ext & 0xF, (ext >> 4) & 0xF
    if p not in GUN_MODES and s not in GUN_MODES:
        return None                                   # melee / thrown / unarmed
    dmg = struct.unpack_from(">i", raw, DMG_OFF)[0]
    energy = dmg in ENERGY_DMG
    two = bool(ext & TWO_HANDED)
    ap1, ap2 = struct.unpack_from(">ii", raw, AP1_OFF)

    new_ext = ext
    if not energy and two:
        new_ext |= BIG_GUN
    table = AP_TABLE[(energy, two)]
    new_ap1 = table.get(p, ap1) if p in GUN_MODES else ap1
    new_ap2 = table.get(s, ap2) if s in GUN_MODES else ap2

    buf = bytearray(raw)
    struct.pack_into(">I", buf, EXT_OFF, new_ext)
    struct.pack_into(">ii", buf, AP1_OFF, new_ap1, new_ap2)
    rec = {
        "energy": energy, "two": two,
        "skill_from": "energy" if energy else ("big" if ext & BIG_GUN else "small"),
        "skill_to": "energy" if energy else ("big" if new_ext & BIG_GUN else "small"),
        "p": p, "s": s, "ap": (ap1, ap2), "ap_new": (new_ap1, new_ap2),
    }
    return bytes(buf), rec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--base", default=str(ROOT / "base"))
    ap.add_argument("--no-deploy", action="store_true", help="write protos only")
    args = ap.parse_args()

    gi = GameIndex(Path(args.base), pristine=False)
    names = item_names(gi)
    lst = gi.proto_lst(0)
    changed = unchanged = 0
    moved: list[str] = []
    rows: list[str] = []
    for i in range(1, len(lst) + 1):
        try:
            raw = gi.vfs.read(f"proto\\items\\{i:08d}.pro")
        except Exception:  # noqa: BLE001
            continue
        if i in SKIP:
            continue
        res = rebalance(raw)
        if res is None:
            continue
        out, r = res
        mid = struct.unpack_from(">i", raw, 4)[0]
        name = names.get(mid, f"#{i}")
        if out == raw:
            unchanged += 1
            continue
        changed += 1
        tag = f"{r['skill_from']}->{r['skill_to']}" if r["skill_from"] != r["skill_to"] else r["skill_to"]
        if r["skill_from"] != r["skill_to"]:
            moved.append(name)
        modes = f"{MODE_NAME.get(r['p'], r['p'])}/{MODE_NAME.get(r['s'], r['s'])}"
        rows.append(f"  #{i:<4d} {name[:30]:30s} {'2H' if r['two'] else '1H'} {tag:12s} "
                    f"{modes:14s} AP {r['ap'][0]}/{r['ap'][1]} -> {r['ap_new'][0]}/{r['ap_new'][1]}")
        if not args.dry_run:
            MOD_ITEMS.mkdir(parents=True, exist_ok=True)
            (MOD_ITEMS / f"{i:08d}.pro").write_bytes(out)

    print("\n".join(rows))
    print(f"\n{changed} weapon protos changed, {unchanged} already at target; "
          f"{len(moved)} moved to Big Guns; {len(SKIP)} skipped by rule (see SKIP)")
    if args.dry_run:
        print("dry run: nothing written")
        return 0
    print(f"wrote patched protos to {MOD_ITEMS.relative_to(ROOT)}")
    if not args.no_deploy:
        for cmd in (["deploy.py"], ["validate.py"]):
            print(f"\n$ python tools/{cmd[0]}")
            rc = subprocess.run([sys.executable, str(ROOT / "tools" / cmd[0])], cwd=ROOT).returncode
            if rc:
                return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
