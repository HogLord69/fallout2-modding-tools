#!/usr/bin/env python3
"""
scenery_text.py - give scenery protos their own name and examine text, from
mod/ids/scenery_text.tsv.

    python tools/scenery_text.py --dry-run
    python tools/scenery_text.py             # write protos + pro_scen.msg, deploy, validate

A proto's name is message <id> and its examine text <id>+1 in pro_scen.msg
(proto.cc protoGetMessage). Vanilla protos share ids ("Plant" / "A mutated
cornstalk." covers every corn stalk AND the marijuana bushes), so changing a
vanilla line in place would change unrelated objects. Instead each listed
proto is pointed at an FOC entry: its name is allocated in
mod/ids/msg_scenery.txt (idempotent by name), its description is set for that
name in msg_scenery_desc.txt (replacing any earlier one), and the proto's
message id at offset 4 is rewritten. A vanilla-range proto gets a foc-layer
override copy in mod/data/proto/scenery, like the item overrides we ship.

Descriptions are keyed by name, so rows sharing a name must share the text;
the tool refuses a table that disagrees with itself.
"""

from __future__ import annotations

import argparse
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import port  # noqa: E402
from foclib import GameIndex  # noqa: E402

ROOT, MOD, IDS = port.ROOT, port.MOD, port.IDS
TABLE = IDS / "scenery_text.tsv"
OUT = MOD / "data" / "proto" / "scenery"


def read_table() -> list[tuple[int, str, str]]:
    rows = []
    for n, line in enumerate(TABLE.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip() or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            sys.exit(f"{TABLE.name}:{n}: need pid<TAB>name<TAB>description")
        rows.append((int(parts[0], 0), parts[1].strip(), parts[2].strip()))
    descs: dict[str, str] = {}
    for pid, name, desc in rows:
        if descs.setdefault(name.lower(), desc) != desc:
            sys.exit(f"{name!r} has two different descriptions in {TABLE.name}")
    return rows


def set_desc(name: str, desc: str) -> None:
    """Set (replace) the examine text for a name in msg_scenery_desc.txt."""
    p = port.msg_desc_path("scenery")
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    out, done = [], False
    for l in lines:
        if "\t" in l and not l.startswith("#") and l.split("\t", 1)[0].strip().lower() == name.lower():
            if not done:
                out.append(f"{name}\t{desc}")
                done = True
            continue
        out.append(l)
    if not done:
        out.append(f"{name}\t{desc}")
    p.write_text("\n".join(out) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-deploy", action="store_true")
    args = ap.parse_args()

    rows = read_table()
    base = GameIndex()                        # pristine: vanilla/RPU protos
    full = GameIndex(pristine=False)
    for pid, name, desc in rows:
        sp = full.proto_path(pid)
        if sp is None:
            sys.exit(f"0x{pid:08X}: no such scenery proto")
        fname = sp.replace("/", "\\").split("\\")[-1]
        dst = OUT / fname
        data = bytearray(dst.read_bytes() if dst.exists() else base.vfs.read(sp))
        old = struct.unpack_from(">I", data, 4)[0]
        if args.dry_run:
            print(f"  0x{pid:08X} {fname}  msg {old} -> '{name}'" + ("" if dst.exists() else "  (new override)"))
            continue
        reg = port.msg_registry_path("scenery")
        idx = port.allocate(reg, name, 0)
        # allocate matches names case-insensitively: an older "corn" would
        # otherwise keep its lowercase spelling for our "Corn"
        entries = port.registry_entries(reg)
        if entries[idx] != name:
            lines = port.registry_lines(reg)
            k = [i for i, l in enumerate(lines) if not l.strip().startswith("#")][idx]
            lines[k] = name
            reg.write_text("\n".join(lines) + "\n", encoding="utf-8")
        set_desc(name, desc)
        struct.pack_into(">I", data, 4, port.msg_id_for_index(idx))
        OUT.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(bytes(data))
    if args.dry_run:
        print(f"{len(rows)} protos (dry run)")
        return 0
    port.write_merged_msg("scenery")
    print(f"{len(rows)} protos given their own name and examine text")
    if args.no_deploy:
        return 0
    for t in ("deploy.py", "validate.py"):
        rc = subprocess.run([sys.executable, str(ROOT / "tools" / t)], cwd=ROOT).returncode
        if rc:
            return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
