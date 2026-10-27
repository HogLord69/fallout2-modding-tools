#!/usr/bin/env python3
"""
port_head.py - import one talking head from a heads add-on (a .dat, or an
unpacked data folder) under a new FOC head name.

    python tools/port_head.py --dat PATH\\talking_heads.dat --head cat --name rwdoz --credit rpu_talking_heads
    python tools/port_head.py --dat PATH\\patch001.dat --head parmr --name rwarn --credit yesterday --replace
    add --dry-run to preview.

A talking head is a set of FRMs named <head><mood><kind>[n].frm (e.g.
catgf1.frm, catgn.frm, catgp.frm - good/neutral/bad x fidget/neutral/phoneme)
plus one heads.lst line "<head>,g,n,b" giving the fidget count per mood. The
files are copied to mod/data/art/heads under the new name and the line is
appended to mod/ids/art_heads.txt with the add-on's own counts. The printed
index is the number a script passes to start_gdialog() as the head.

New names are 5 characters, like the vanilla ones (mrcus, haku2), so they can
never collide with a vanilla or add-on head.

--dat may be a folder: an unpacked .dat holding art\\heads\\heads.lst (e.g.
extracted from an archive).

--replace puts a different head into a slot that already exists: the old
<name>* files are deleted and the heads.lst line is rewritten in place, so
the index - and every script's HEAD_ define - stays the same.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import port  # noqa: E402
from foclib.dat2 import Dat2  # noqa: E402

IDS, FOC_START = port.IDS, port.FOC_START
KEY = "art_heads"
LST = "art\\heads\\heads.lst"


def open_heads(path: str):
    """(file names as art\\heads\\x, reader) for a .dat or an unpacked folder."""
    root = Path(path)
    if root.is_dir():
        for d in (root / "art" / "heads", root):
            by_name = {q.name.lower(): q for q in d.iterdir()} if d.is_dir() else {}
            if "heads.lst" in by_name:
                names = ["art\\heads\\" + n for n in by_name]
                return names, lambda n: by_name[n.split("\\")[-1].lower()].read_bytes()
        sys.exit(f"no {LST} under {root}")
    dat = Dat2(path)
    return list(dat.names()), dat.read


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dat", required=True, help="heads .dat, or an unpacked data folder")
    ap.add_argument("--head", required=True, help="head name in the source's heads.lst")
    ap.add_argument("--name", required=True, help="new 5-character head name")
    ap.add_argument("--credit", required=True, help="sources.json name to credit in the ledger")
    ap.add_argument("--replace", action="store_true",
                    help="swap the head in an existing slot (same index)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    head, name = args.head.lower(), args.name.lower()
    if len(name) != 5 or not name.isalnum():
        sys.exit(f"--name must be 5 letters/digits, got {name!r}")

    names, read = open_heads(args.dat)
    lst = read(LST).decode("cp1252", "replace").splitlines()
    line = next((l.split(";")[0].strip() for l in lst
                 if l.split(",")[0].strip().lower() == head), None)
    if line is None:
        sys.exit(f"{head} is not in the source's heads.lst")
    entry = name + line[len(line.split(",")[0]):]

    rx = re.compile(re.escape(head) + r"([gnb][bfgnp]\d?\.frm)$")
    files = [(n, rx.match(n.split("\\")[-1].lower())) for n in names
             if n.lower().startswith("art\\heads\\")]
    files = [(n, m.group(1)) for n, m in files if m]
    if not files:
        sys.exit(f"no art\\heads\\{head}*.frm in {args.dat}")

    reg = IDS / f"{KEY}.txt"
    lines = port.registry_lines(reg)
    slot = next((k for k, l in enumerate(lines)
                 if l.strip() and not l.startswith("#")
                 and l.split(",")[0].strip().lower() == name), None)
    if slot is not None and not args.replace:
        sys.exit(f"{name} already has a slot; pass --replace to swap its head")

    print(f"{len(files)} files {head}* -> {name}*  (heads.lst entry {entry!r})"
          + ("  [replacing]" if slot is not None else ""))
    if args.dry_run:
        return 0

    out = port.MOD / "data" / "art" / "heads"
    out.mkdir(parents=True, exist_ok=True)
    if slot is not None:
        for old in out.glob(f"{name}*"):
            old.unlink()
        lines[slot] = entry
        reg.write_text("\n".join(lines) + "\n", encoding="utf-8")
    for n, suffix in files:
        (out / (name + suffix)).write_bytes(read(n))
    idx = port.allocate(reg, entry, FOC_START[KEY] - 1)
    port.append_ledger([port.ledger_row(
        args.credit, "art", f"{Path(args.dat).name}:art\\heads\\{head}*", head,
        f"mod/data/art/heads/{name}*", idx, f"talking head, {len(files)} files (port_head.py)")])
    port.regen_ledger_md()
    print(f"  head index {idx}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
