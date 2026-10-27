#!/usr/bin/env python3
"""apply_build_rules.py - apply the owner's per-family decisions after import.

Reads BUILD_RULES.json from the drop folder:

  leave_vanilla: the body is destroyed or charred, so restyling cannot show.
                 These get the UNTOUCHED vanilla frames - not the recoloured
                 placeholder, which would tint a charred corpse an odd colour.
  alias:         {"BF": "BG"} means "whenever the game triggers BF, play BG's
                 frames". Used where a family's cells are mostly empty so its
                 sprites do not survive restyling (BF chunks_of_flesh), or the
                 owner simply prefers another death to stand in.

Both are done by writing files, so the engine needs no special support: an
alias is a byte copy of the target's FRMs under the source's name.

Run:  python tools/apply_build_rules.py [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from foclib import GameIndex

ROOT = Path(__file__).resolve().parent.parent
CRIT = ROOT / "mod" / "data" / "art" / "critters"
RULES = Path.home() / "OneDrive" / "Desktop" / "Restyled_DropHere" / "BUILD_RULES.json"


def members(gi) -> set[str]:
    out = subprocess.run([str(ROOT / "tools" / "dat" / "dat2.exe"), "l",
                          str(ROOT / "base" / "critter.dat")],
                         capture_output=True, text=True).stdout
    return {l.strip().split("\\")[-1].strip().upper()
            for l in out.splitlines() if "\\" in l}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    rules = json.loads(RULES.read_text())
    gi = GameIndex()
    mem = members(gi)

    n_van = n_alias = 0
    for code in rules.get("leave_vanilla", []):
        for name in sorted(n for n in mem if n.startswith("HMJMPS" + code)):
            suffix = name[6:]
            data = gi.vfs.read(f"art\\critters\\{name}")
            for prefix in ("hmpcot", "hfpcot"):
                if not args.dry_run:
                    (CRIT / f"{prefix}{suffix}").write_bytes(data)
            n_van += 1
        print(f"  {code}: vanilla frames restored")

    for src, dst in sorted(rules.get("alias", {}).items()):
        got = 0
        for name in sorted(n for n in mem if n.startswith("HMJMPS" + dst)):
            suffix = name[6:]                      # e.g. ".FR0" / "AA.FRM"
            ext = suffix[2:]
            for prefix in ("hmpcot", "hfpcot"):
                target = CRIT / f"{prefix}{dst}{ext}"
                if not target.exists():
                    continue
                if not args.dry_run:
                    (CRIT / f"{prefix}{src}{ext}").write_bytes(target.read_bytes())
                got += 1
        n_alias += got
        print(f"  {src} -> {dst}: {got} file(s) copied")

    print(f"\n{'would write' if args.dry_run else 'wrote'} "
          f"{n_van} vanilla restores, {n_alias} alias copies")
    print("next: python tools/deploy.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
