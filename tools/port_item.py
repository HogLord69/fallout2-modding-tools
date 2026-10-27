#!/usr/bin/env python3
"""
port_item.py - bring one item proto into FOC under its own name: ported from
another install (with its ground and inventory art), or cloned from a base item.

    python tools/port_item.py --source nevada --pid 0x133 --name "Gunpowder" --desc "..."
    python tools/port_item.py --source base --pid 125 --name "Yuma Hooch" --desc "..."
    python tools/port_item.py --source nevada --pid 0x179 --name "Ammo Press" --desc "..." --script foccraft
    add --dry-run to preview, --no-deploy to skip gen_ids/build/deploy/validate.

Why not port.py proto: that keeps the source's name and never touches the
inventory icon (offset 52, see port_gun.py). An item we rename (Nevada's
"Ammunition remains" becomes our Gunpowder) needs its own name and examine
text, and a misc item without its art/inven icon shows a random base picture.

--source base clones an item from our own base (base + RPU): same art, same
stats, a new FOC pid with its own name. That is how a vanilla item gets a
story-specific twin (Booze -> Yuma Hooch) without renaming every Booze in the
game.

--art-from SOURCE:PID keeps the item (stats, pid, name) but gives it the
ground and inventory art of another source's item proto, ported in the same
way. That is how the Yuma Hooch (a base Booze clone) got Sonora's whiskey
bottle:
    python tools/port_item.py --source base --pid 125 --name "Yuma Hooch" --desc "..." --art-from sonora:123

--script NAME sets the proto's script field to that FOC script (an item
script: type 3, 0-based scripts.lst index), so every copy the engine creates
from this proto carries it (object.cc objectCreateWithPid). Copies placed in
gecko do not; gl_foc.ssl attaches the script to those at runtime.

Re-running with the same --source/--pid reuses the pid it got the first time
(ledger lookup) and rewrites the proto in place.
"""

from __future__ import annotations

import argparse
import struct
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import port  # noqa: E402
import port_gun  # noqa: E402
from foclib import GameIndex  # noqa: E402
from ids import ART_KEY  # noqa: E402

ROOT, MOD, IDS, FOC_START = port.ROOT, port.MOD, port.IDS, port.FOC_START
FID_OFF, SID_OFF, INVFID_OFF = 8, 28, 52
SCRIPT_TYPE_ITEM = 3


def read_lst(gi: GameIndex, path: str) -> list[str]:
    return [l.strip() for l in gi.vfs.read(path).decode("cp1252", "replace").splitlines()]


def ground_fid(src_name: str, src: GameIndex, base: GameIndex, fid: int, ledger: list, pid: int, dry: bool) -> int:
    """Keep the ground sprite when base has the same-named FRM (reuse base's
    index); otherwise copy the FRM in under an engine-safe name."""
    idx = fid & 0xFFFFFF
    s = read_lst(src, "art\\items\\items.lst")
    name = s[idx]
    b = [n.lower() for n in read_lst(base, "art\\items\\items.lst")]
    if name.lower() in b:
        return (fid & ~0xFFFFFF) | b.index(name.lower())
    data = src.vfs.read(f"art\\items\\{name}")
    lst_entry = port.engine_art_name(src_name, name, port.art_names_taken("items"))
    port.check_art_name("items", lst_entry)
    key = ART_KEY["items"]
    if dry:
        print(f"  ground art {name} -> {lst_entry} (not written, dry run)")
        return fid
    dst = port.dest_for(f"art\\items\\{lst_entry}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(data)
    a_idx = port.allocate(IDS / f"{key}.txt", lst_entry, FOC_START[key] - 1)
    port.check_art_index(a_idx, "items", lst_entry)
    ledger.append(port.ledger_row(src_name, "art", f"art\\items\\{name}", idx,
                                  f"mod/data/art/items/{lst_entry}", a_idx,
                                  f"ground art for proto 0x{pid:08X}"))
    return (fid & ~0xFFFFFF) | a_idx


def script_sid(name: str) -> int:
    entries = port.registry_entries(IDS / "scripts.txt")
    want = name.lower() if name.lower().endswith(".int") else name.lower() + ".int"
    for i, e in enumerate(entries):
        if e.lower() == want:
            line = FOC_START["script"] + i          # 1-based scripts.lst line
            return (SCRIPT_TYPE_ITEM << 24) | (line - 1)
    raise SystemExit(f"{want} is not in mod/ids/scripts.txt")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--source", required=True, help="a sources.json name, or 'base' to clone")
    ap.add_argument("--pid", required=True, type=lambda s: int(s, 0))
    ap.add_argument("--name", required=True)
    ap.add_argument("--desc", required=True)
    ap.add_argument("--script", help="FOC script to put in the proto's script field")
    ap.add_argument("--art-from", help="SOURCE:PID whose ground and inventory art to use instead")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-deploy", action="store_true")
    args = ap.parse_args()

    base = GameIndex(ROOT / "base", pristine=False)
    cloning = args.source == "base"
    src = base if cloning else port.open_source(args.source)
    sp = src.proto_path(args.pid)
    if sp is None or not src.vfs.exists(sp):
        sys.exit(f"no item proto 0x{args.pid:08X} in {args.source}")
    data = bytearray(src.vfs.read(sp))
    ledger: list[dict] = []

    key = port.PROTO_KEY[0]                               # proto_items
    reg = IDS / f"{key}.txt"
    already = next((r for r in port.read_ledger()
                    if r["source"] == args.source and r["kind"] == "proto"
                    and r["source_id"].lower() == f"0x{args.pid:08x}"), None)
    if already:
        new_index = int(already["dest_id"], 16) & 0xFFFFFF
    else:
        new_index = len(port.registry_entries(reg)) + FOC_START[key]
        if not args.dry_run:
            new_index = port.allocate(reg, f"{new_index:08d}.pro", FOC_START[key])
    new_pid = new_index                                   # items: type 0

    art_name, art_src, art_pid, art_data = args.source, src, args.pid, data
    if args.art_from:
        art_name, _, pid_text = args.art_from.partition(":")
        art_pid = int(pid_text, 0)
        art_src = base if art_name == "base" else port.open_source(art_name)
        ap_path = art_src.proto_path(art_pid)
        if ap_path is None or not art_src.vfs.exists(ap_path):
            sys.exit(f"no item proto 0x{art_pid:08X} in {art_name}")
        art_data = art_src.vfs.read(ap_path)

    if art_name == "base":
        new_fid = struct.unpack_from(">I", art_data, FID_OFF)[0]
        new_inv = struct.unpack_from(">I", art_data, INVFID_OFF)[0]
    else:
        new_fid = ground_fid(art_name, art_src, base, struct.unpack_from(">I", art_data, FID_OFF)[0],
                             ledger, art_pid, args.dry_run)
        # The foc-layer inven.lst, when present, is base + every icon already
        # added and may not be deployed yet; reading only the deployed base
        # handed two items ported in a row the same slot.
        mod_inven = MOD / "data" / "art" / "inven" / "inven.lst"
        if mod_inven.is_file():
            base_inven = [l.strip() for l in mod_inven.read_text(encoding="cp1252").splitlines() if l.strip()]
        else:
            base_inven = port_gun.read_inven_lst(base)
        foc_added: list[str] = []
        new_inv = port_gun.port_inven_art(art_name, art_src, base_inven, foc_added,
                                          struct.unpack_from(">I", art_data, INVFID_OFF)[0],
                                          ledger, art_pid, args.dry_run)
        port_gun.write_inven_lst(base_inven, foc_added, args.dry_run)

    sid = script_sid(args.script) if args.script else 0xFFFFFFFF

    if args.dry_run:
        print(f"dry run: 0x{args.pid:08X} -> index {new_index} '{args.name}' fid=0x{new_fid:08X} "
              f"inv=0x{new_inv:08X} sid=0x{sid:08X}")
        return 0

    idx = port.allocate(port.msg_registry_path("items"), args.name, 0)
    port.record_msg_desc("items", args.name, args.desc)
    port.write_merged_msg("items")
    msg_id = port.msg_id_for_index(idx)

    struct.pack_into(">I", data, 0, new_pid)
    struct.pack_into(">I", data, 4, msg_id)
    struct.pack_into(">I", data, FID_OFF, new_fid)
    struct.pack_into(">I", data, SID_OFF, sid)
    struct.pack_into(">I", data, INVFID_OFF, new_inv)
    out = MOD / "data" / "proto" / "items" / f"{new_index:08d}.pro"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(bytes(data))
    if not already:
        ledger.append(port.ledger_row(args.source, "proto", sp, f"0x{args.pid:08X}",
                                      str(out.relative_to(ROOT)), f"0x{new_pid:08X}",
                                      f"port_item.py as '{args.name}'"))
    port.append_ledger(ledger)
    port.regen_ledger_md()
    print(f"  0x{args.pid:08X} ({args.source}) -> '{args.name}' index {new_index} "
          f"(PID_FOC_{new_index:08d}) msg {msg_id} fid=0x{new_fid:08X} inv=0x{new_inv:08X} sid=0x{sid:08X}")

    if not args.no_deploy:
        for t in ("gen_ids.py", "build.py", "deploy.py", "validate.py"):
            rc = subprocess.run([sys.executable, str(ROOT / "tools" / t)], cwd=ROOT).returncode
            if rc:
                return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
