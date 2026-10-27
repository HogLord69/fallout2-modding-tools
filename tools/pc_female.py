#!/usr/bin/env python3
"""
pc_female.py - the female player sprite (hfpcot) from Fallout: Olympus's
nflife, copied unchanged (owner, 2026-09-28). nflife has all 127 player
animations; Olympus's color.pal differs from ours only at indices 84, 117
and 255, which nflife never uses, so no pixel needs remapping (checked
below, the install stops if that ever changes).

    python tools/pc_female.py              # copy into build/pc_female (nothing installed)
    python tools/pc_female.py --install    # back up hfpcot*, replace it, deploy

Any hfpcot animation nflife lacks keeps its current file.
"""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np  # noqa: E402

import port  # noqa: E402
from foclib import GameIndex  # noqa: E402
from pc_yesterday import frames_of  # noqa: E402

ROOT = port.ROOT
CRIT = ROOT / "mod" / "data" / "art" / "critters"
STAGE = ROOT / "build" / "pc_female" / "art" / "critters"
SOURCE, SRC_BASE, OUR_BASE = "olympus", "nflife", "hfpcot"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--install", action="store_true")
    args = ap.parse_args()

    src = port.open_source(SOURCE)
    theirs = src.vfs.read("color.pal")[:768]
    ours = GameIndex(pristine=False).vfs.read("color.pal")[:768]
    differ = [i for i in range(256) if theirs[i * 3:i * 3 + 3] != ours[i * 3:i * 3 + 3]]

    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    n = 0
    for c in "abcdefghijklmnopqrst":
        for a in "abcdefghijklmnopqrstuvwxyz":
            for ext in ("frm", "fr0", "fr1", "fr2", "fr3", "fr4", "fr5"):
                p = "art\\critters\\" + f"{SRC_BASE}{c}{a}.{ext}"
                if not src.vfs.exists(p):
                    continue
                data = src.vfs.read(p)
                for s, w, h in frames_of(data, ext != "frm"):
                    px = np.frombuffer(data[s:s + w * h], np.uint8)
                    bad = [i for i in differ if (px == i).any()]
                    if bad:
                        sys.exit(f"{p} uses palette entries {bad}, which differ from ours - needs a remap")
                (STAGE / f"{OUR_BASE}{c.upper()}{a.upper()}.{ext.upper()}").write_bytes(data)
                n += 1
    print(f"copied {n} {SRC_BASE} files -> {STAGE.relative_to(ROOT)} (palette check passed)")
    if not args.install:
        return 0

    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    backup = ROOT / "_safety_backups" / f"pc_frm_{stamp}_female"
    backup.mkdir(parents=True, exist_ok=True)
    new_codes = {p.name[len(OUR_BASE):len(OUR_BASE) + 2].lower() for p in STAGE.iterdir()}
    kept = []
    for p in sorted(CRIT.glob(f"{OUR_BASE}*")):
        shutil.copy2(p, backup / p.name)
        if p.name[len(OUR_BASE):len(OUR_BASE) + 2].lower() in new_codes:
            p.unlink()
        else:
            kept.append(p.name)
    for p in sorted(STAGE.iterdir()):
        shutil.copy2(p, CRIT / p.name)
    print(f"  hfpcot replaced with {n} {SRC_BASE} files; kept {kept or 'nothing'}; "
          f"old set backed up to {backup.relative_to(ROOT)}")
    row = port.ledger_row(SOURCE, "art", f"art\\critters\\{SRC_BASE}*", SRC_BASE,
                          f"mod/data/art/critters/{OUR_BASE}*", OUR_BASE,
                          "female player sprite: Fallout: Olympus nflife, unchanged (pc_female.py)")
    have = {(r["source"], r["dest_path"]) for r in port.read_ledger()}
    if (row["source"], row["dest_path"]) not in have:
        port.append_ledger([row])
    port.regen_ledger_md()
    return subprocess.run([sys.executable, str(ROOT / "tools" / "deploy.py")], cwd=ROOT).returncode


if __name__ == "__main__":
    sys.exit(main())
