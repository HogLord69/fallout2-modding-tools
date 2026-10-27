#!/usr/bin/env python3
"""
port_look.py - import one hero-appearance look (a full critter animation set
for one outfit) from an appearance .dat as a new FOC critter sprite.

    python tools/port_look.py --dat "C:\\Fallout Nevada (Expansion Version)\\appearance\\HMR00S01.dat.orig" \
        --look hmmaxx --name rwremx --credit nevada
    add --dry-run to preview.

Hero appearance mods ship each look as a complete player sprite set - every
animation, every weapon - named "_<vanilla base><anim>.frm" (e.g.
_hmmaxxaa.frm). The same body as the vanilla generic humans, a different head
and skin. That makes them the cheapest way to give an NPC its own face AND a
full weapon set: several vanilla NPC sprites (hmbmet, nfmetl, nmmaxx) have no
pistol, rifle or shotgun poses at all.

The files are copied to mod/data/art/critters under the new base name (critter
bases are 6 characters, see port.CRITTER_NAME_LEN), and the new base is
appended to mod/ids/art_critters.txt with the vanilla look's own critters.lst
fields (e.g. "hmmaxx,11,1" -> "rwremx,11,1"), so the engine treats it exactly
as it treats the vanilla sprite. One ledger row per look, not per file.

Prints the new art index and the critter FID (0x01000000 | index) a script
passes to art_change_fid_num().
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import port  # noqa: E402
from foclib import GameIndex, parse_lst  # noqa: E402
from foclib.dat2 import Dat2  # noqa: E402

IDS, FOC_START = port.IDS, port.FOC_START
KEY = "art_critters"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dat", required=True, help="appearance .dat holding the look")
    ap.add_argument("--look", required=True, help="vanilla base the look replaces, e.g. hmmaxx")
    ap.add_argument("--name", required=True, help="new 6-character critter base name")
    ap.add_argument("--credit", required=True, help="sources.json name to credit in the ledger")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    name = args.name.lower()
    if len(name) != port.CRITTER_NAME_LEN or not name.isalnum():
        sys.exit(f"--name must be {port.CRITTER_NAME_LEN} letters/digits, got {name!r}")
    look = args.look.lower()

    base_lst = parse_lst(GameIndex(pristine=False).vfs.read("art\\critters\\critters.lst"))
    fields = next((e for e in base_lst if e.split(",", 1)[0].strip().lower() == look), None)
    if fields is None:
        sys.exit(f"{look} is not in critters.lst")
    entry = name + fields[len(fields.split(",", 1)[0]):]

    taken = {e.split(",", 1)[0].strip().lower() for e in base_lst}
    taken |= {e.split(",", 1)[0].strip().lower() for e in port.registry_entries(IDS / f"{KEY}.txt")}
    mine = next((i for i, e in enumerate(port.registry_entries(IDS / f"{KEY}.txt"))
                 if e.split(",", 1)[0].strip().lower() == name), None)
    if name in taken and mine is None:
        sys.exit(f"{name} is already a critter base")

    dat = Dat2(args.dat)
    prefix = "_" + look
    files = [n for n in dat.names()
             if n.lower().startswith("art\\critters\\" + prefix)]
    if not files:
        sys.exit(f"no art\\critters\\{prefix}* in {args.dat}")
    if not any(n.lower().endswith(prefix + "aa.frm") for n in files):
        sys.exit(f"{prefix}aa.frm (the standing pose) is missing - not a usable look")

    out_dir = port.MOD / "data" / "art" / "critters"
    print(f"{len(files)} files {prefix}* -> {name}*  (critters.lst entry {entry!r})")
    if args.dry_run:
        return 0

    out_dir.mkdir(parents=True, exist_ok=True)
    for n in files:
        fname = n.split("\\")[-1].lower()
        (out_dir / (name + fname[len(prefix):])).write_bytes(dat.read(n))

    idx = port.allocate(IDS / f"{KEY}.txt", entry, FOC_START[KEY] - 1)
    port.append_ledger([port.ledger_row(
        args.credit, "art", f"{Path(args.dat).name}:art\\critters\\{prefix}*", look,
        f"mod/data/art/critters/{name}*", idx,
        f"hero appearance look, {len(files)} files, for an NPC sprite (port_look.py)")])
    port.regen_ledger_md()
    print(f"  art index {idx}  ->  critter FID 0x{(1 << 24) | idx:08X}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
