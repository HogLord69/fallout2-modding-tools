#!/usr/bin/env python3
"""pc_grids_from_newart.py

Populate art/pc_grids/ from the prepped New-Sprites sheets so
replace_pc_from_ref.py can rebuild hmpcot/hfpcot from them.

Source: C:\\Users\\adamn\\OneDrive\\Desktop\\New Sprites\\_prepped\\NN_<name>.png
        (48 clean transparent 6-row grids produced by prep_new_sprites.py)

The 2-char FRM family code is the filename; renaming a file re-maps it.
Low-confidence guesses land in art/pc_grids/_unsorted/ where the rebuild
tool does NOT look, so nothing wrong ships until the owner promotes it.

Run:  python tools/pc_grids_from_newart.py [--dry-run]
"""
from __future__ import annotations
import shutil, sys, csv
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREP = Path(r"C:\Users\adamn\OneDrive\Desktop\New Sprites\_prepped")
GRIDS = ROOT / "art" / "pc_grids"
UNSORTED = GRIDS / "_unsorted"

# idx -> (family code | None, human label, confidence)
# code None  -> copied to _unsorted/ , not consumed by the rebuild
MAP = {
    9:  ("AB", "unarmed walk",            "high"),   # also the SRC_PNG walk base
    13: ("AT", "unarmed run",             "high"),
    10: ("AR", "unarmed kick",            "high"),
    33: ("AQ", "unarmed straight punch",  "high"),
    36: ("AE", "climb",                   "high"),
    11: ("AA", "idle / stand",            "med"),
    18: ("AS", "throw",                   "med"),
    39: ("AK", "pick up / kneel",         "med"),
    37: ("AO", "hit from front",          "med"),
    31: ("AP", "hit from back",           "med"),
    24: ("AN", "dodge",                   "med"),

    23: ("BA", "death - fall backward",   "med"),
    14: ("BB", "death - fall forward",    "med"),

    35: ("DA", "knife - idle",            "low"),
    32: ("DF", "knife - slash",           "low"),
    12: ("DB", "knife - walk",            "low"),
    22: ("EF", "club - overhead swing",   "low"),
    16: ("EE", "club - swing 2",          "low"),
    19: ("EG", "club - swing 3",          "low"),
    27: ("EB", "club - walk",             "low"),
    5:  ("FB", "sledgehammer - walk",     "low"),
    0:  ("FF", "sledgehammer - swing",    "low"),
    42: ("FG", "sledgehammer - swing 2",  "low"),
    44: ("GA", "spear - idle",            "low"),
    7:  ("GB", "spear - walk",            "low"),
    2:  ("GF", "spear - thrust",          "low"),
    45: ("GG", "spear - thrust 2",        "low"),
    3:  ("GD", "spear - move 2",          "low"),
    1:  ("GC", "spear - ready",           "low"),
    43: ("GE", "spear - move 3",          "low"),
    4:  ("HA", "pistol - idle",           "low"),
    40: ("HC", "pistol - draw",           "low"),
    46: ("HH", "pistol - fire",           "low"),
    47: ("HG", "pistol - aim",            "low"),
    17: ("HE", "pistol - move",           "low"),
    6:  ("JA", "rifle - idle",            "low"),
    8:  ("JB", "rifle - walk",            "low"),
    34: ("IH", "smg - burst / prone",     "low"),
    41: ("IB", "smg - walk",              "low"),

    15: (None, "unarmed walk (duplicate of 9)",   "unsorted"),
    21: (None, "run / lunge - unclear",           "unsorted"),
    25: (None, "lunging punch - unclear",         "unsorted"),
    26: (None, "lunging attack - unclear",        "unsorted"),
    28: (None, "weapon walk - unclear",           "unsorted"),
    29: (None, "jump kick - unclear",             "unsorted"),
    30: (None, "dodge with weapon - unclear",     "unsorted"),
    38: (None, "boxing / jab - unclear",          "unsorted"),
    20: (None, "kick / jump - unclear",           "unsorted"),
}


def main() -> int:
    dry = "--dry-run" in sys.argv
    prepped = {int(p.name.split("_", 1)[0]): p
               for p in PREP.glob("*.png")
               if not p.name.endswith("__cleaned_fullsheet.png")
               and not p.name.startswith("_")
               and p.name.split("_", 1)[0].isdigit()}
    if not prepped:
        print(f"no prepped sheets in {PREP}", file=sys.stderr)
        return 1

    if not dry:
        GRIDS.mkdir(parents=True, exist_ok=True)
        UNSORTED.mkdir(parents=True, exist_ok=True)

    rows, used = [], {}
    for idx, (code, label, conf) in sorted(MAP.items()):
        src = prepped.get(idx)
        if src is None:
            print(f"  !! sheet #{idx} not found in _prepped"); continue
        if code:
            if code in used:
                print(f"  !! code {code} already used by #{used[code]}, #{idx} -> _unsorted")
                dst = UNSORTED / f"{code}_dup_{idx:02d}.png"
            else:
                used[code] = idx
                dst = GRIDS / f"{code}.png"          # matches existing convention
        else:
            dst = UNSORTED / f"sheet{idx:02d}.png"
        if not dry:
            shutil.copy2(src, dst)
        rows.append({"sheet": idx, "code": code or "", "label": label,
                     "confidence": conf, "file": dst.relative_to(ROOT).as_posix()})
        print(f"  #{idx:02d} -> {dst.relative_to(GRIDS.parent).as_posix():40s} [{conf}] {label}")

    man = GRIDS / "_MAPPING.csv"
    if not dry:
        with man.open("w", newline="") as fp:
            w = csv.DictWriter(fp, fieldnames=["sheet", "code", "label", "confidence", "file"])
            w.writeheader(); w.writerows(rows)
    print(f"\n{len(rows)} sheets placed ({len(used)} family codes, "
          f"{len(rows)-len(used)} unsorted).  mapping -> {man}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
