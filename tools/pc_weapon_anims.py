#!/usr/bin/env python3
"""
pc_weapon_anims.py - point the weapons that use RPU's extra animation groups
back at vanilla's, so the player sprite can hold them.

    python tools/pc_weapon_anims.py --dry-run
    python tools/pc_weapon_anims.py

RPU moved the Hunting Rifle, the Scoped Hunting Rifle, the Sniper Rifle, the
three FN FALs and the Wakizashi to new animation groups (weapon animation
codes 13 and 14, the n/o/p/q FRMs) and added two Lightsabers on 11 and 12.
The player sprites (pc_sonora.py) have only vanilla's groups, and a critter
with no FRM for the weapon in its hand has no sprite. Each weapon here gets
the code it has in master.dat (the Lightsabers, which vanilla lacks, the
knife's), written into the item's FOC override in mod/data/proto/items
(made from the game's copy when there is none yet). The file is the one
items.lst names for the pid (pid 10's is 00000011.pro: vanilla's list swaps
10 and 11).

The animation code is the weapon proto's first field after the item header
(offset 57, big-endian).
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foclib import GameIndex  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ITEMS = ROOT / "mod" / "data" / "proto" / "items"
ANIM_OFF = 57
KNIFE = 1

# pid: (name, vanilla animation code; None = not in vanilla, use the knife's)
WEAPONS = {
    10: ("Hunting Rifle", 7),
    143: ("Sniper Rifle", 7),
    287: ("Scoped Hunting Rifle", 7),
    351: ("FN FAL", 7),
    403: ("FN FAL (Night Sight)", 7),
    500: ("FN FAL HPFA", 7),
    522: ("Wakizashi Blade", 1),
    574: ("Lightsaber", None),
    576: ("Lightsaber", None),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    gi = GameIndex(pristine=False)
    for pid, (name, code) in WEAPONS.items():
        dst = ITEMS / Path(gi.proto_path(pid).replace(chr(92), "/")).name
        raw = bytearray(dst.read_bytes() if dst.is_file() else gi.vfs.read(gi.proto_path(pid)))
        old = struct.unpack_from(">i", raw, ANIM_OFF)[0]
        new = KNIFE if code is None else code
        print(f"  {pid:4} {name:24} animation {old} -> {new}  ({'override' if dst.is_file() else 'new override'})")
        if not args.dry_run and old != new:
            struct.pack_into(">i", raw, ANIM_OFF, new)
            dst.write_bytes(bytes(raw))
    return 0


if __name__ == "__main__":
    sys.exit(main())
