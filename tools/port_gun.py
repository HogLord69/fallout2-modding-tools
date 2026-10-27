#!/usr/bin/env python3
"""
port_gun.py - port a weapon (and its ammo) from another install into FOC,
including the custom inventory art the other TCs keep in art/inven/.

    python tools/port_gun.py --source yesterday --ammo 731 --weapon 862
    python tools/port_gun.py --source yesterday --ammo 731 --weapon 862 --dry-run

Why a dedicated tool and not `port.py proto`: cmd_proto re-points only a proto's
world sprite (fid, in art/items). A weapon's *inventory* icon is a separate FID
- offset 52, type nibble 0x07 - that indexes art/inven/inven.lst, which cmd_proto
never touches. Left alone, the ported weapon shows a random base icon (or none)
in the inventory/loot window. This ports the art/inven FRM too, appends it to a
foc-layer inven.lst override, and re-points inventoryFid; it also fixes the
weapon's ammoTypePid to the newly-ported ammo so the two link up in our ID space.

Item proto layout (proto.cc protoRead + protoItemDataRead, big-endian int32):
  0 pid  4 messageId  8 fid  12 lightDist  16 lightInt  20 flags  24 extFlags
  28 sid  32 type  36 material  40 size  44 weight  48 cost  52 inventoryFid
  56 field_80(u8)  57 <item data>
weapon data @57: 57 anim 61 minDmg 65 maxDmg 69 dmgType 73 rng1 77 rng2
  81 projPid 85 minST 89 AP1 93 AP2 97 critFail 101 perk 105 rounds 109 caliber
  113 ammoTypePid 117 ammoCapacity 121 soundCode(u8)
inventoryFid = 0x07000000 | index-into-art/inven/inven.lst.

Ground art (fid) is kept as-is when the same-named FRM exists in our base at the
same index (the TCs reuse vanilla rifle.frm / ammo.frm); otherwise the tool
refuses rather than leave a dangling world sprite - port that art separately.

Caliber is a bare matching key (weapon.caliber == ammo.caliber lets it reload);
a non-vanilla value like 22 is carried across verbatim and cannot collide with
base ammo, so the ported pair is self-contained.
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

ROOT = port.ROOT
MOD = port.MOD
IDS = port.IDS
FOC_START = port.FOC_START

FID_OFF, TYPE_OFF, INVFID_OFF = 8, 32, 52
W_CALIBER_OFF, W_AMMOPID_OFF = 109, 113
INVEN_LST = "art\\inven\\inven.lst"
INVEN_TYPE_BITS = 0x07000000          # inventoryFid type nibble (art/inven)


def read_inven_lst(gi: GameIndex) -> list[str]:
    return [l.strip() for l in gi.vfs.read(INVEN_LST).decode("cp1252", "replace").splitlines() if l.strip()]


def port_inven_art(src_name, src, base_inven, foc_added, src_inv_fid, ledger, src_pid, dry):
    """Copy the source's art/inven FRM for src_inv_fid into the foc layer and
    return the new inventoryFid (0x07... | index). Idempotent by filename."""
    idx = src_inv_fid & 0xFFFFFF
    src_names = read_inven_lst(src)
    name = src_names[idx]                      # e.g. "22rifle.FRM"
    lname = name.lower()
    lower_base = [n.lower() for n in base_inven]
    if lname in lower_base:                    # already in base: reuse its slot
        return INVEN_TYPE_BITS | lower_base.index(lname)
    if lname in [n.lower() for n in foc_added]:
        return INVEN_TYPE_BITS | (len(base_inven) + [n.lower() for n in foc_added].index(lname))
    data = src.vfs.read(f"art\\inven\\{name}")
    dst = MOD / "data" / "art" / "inven" / lname
    if not dry:
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(data)
    new_idx = len(base_inven) + len(foc_added)
    foc_added.append(lname)
    ledger.append(port.ledger_row(src_name, "art", f"art\\inven\\{name}", idx,
                                  f"mod/data/art/inven/{lname}", new_idx,
                                  f"inventory icon for proto 0x{src_pid:08X}"))
    return INVEN_TYPE_BITS | new_idx


def keep_or_refuse_fid(base: GameIndex, src: GameIndex, fid: int) -> int:
    """Ground sprite: keep fid if base has the identically-named art/items FRM
    at the same index; else refuse (needs a separate art port)."""
    idx = fid & 0xFFFFFF
    b = [l.strip() for l in base.vfs.read("art\\items\\items.lst").decode("cp1252", "replace").splitlines()]
    s = [l.strip() for l in src.vfs.read("art\\items\\items.lst").decode("cp1252", "replace").splitlines()]
    if idx < len(b) and idx < len(s) and b[idx].lower() == s[idx].lower():
        return fid
    raise SystemExit(f"ground art mismatch at items idx {idx}: base has "
                     f"{b[idx] if idx < len(b) else '<oor>'!r}, source has "
                     f"{s[idx] if idx < len(s) else '<oor>'!r}; port that FRM separately")


def port_one(src_name, src, base, pid, base_inven, foc_added, ammo_new_pid, dry, dry_alloc, ledger):
    t = port.pid_type(pid)
    sp = src.proto_path(pid)
    data = bytearray(src.vfs.read(sp))
    proto = port.parse_pro(bytes(data))
    key = port.PROTO_KEY[t]                     # "proto_items"
    # Same idempotent pattern as port.cmd_proto: the prospective index is the
    # current registry length + FOC start; forming its filename and allocating
    # that appends it and returns the index (reused on a re-run). In dry-run the
    # registry is not written, so dry_alloc counts protos already staged so the
    # preview shows the real, distinct indices.
    reg = IDS / f"{key}.txt"
    new_index = len(port.registry_entries(reg)) + FOC_START[key]
    if dry:
        new_index += dry_alloc.count(key)
        dry_alloc.append(key)
    else:
        new_index = port.allocate(reg, f"{new_index:08d}.pro", FOC_START[key])
    new_pid = (t << 24) | new_index

    new_msg = port.ensure_message_id(src_name, src, "items", proto.message_id) if not dry else 0
    new_fid = keep_or_refuse_fid(base, src, proto.fid)
    new_invfid = port_inven_art(src_name, src, base_inven, foc_added,
                                struct.unpack_from(">I", data, INVFID_OFF)[0], ledger, pid, dry)

    struct.pack_into(">I", data, 0, new_pid)
    if not dry:
        struct.pack_into(">I", data, 4, new_msg)
    struct.pack_into(">I", data, FID_OFF, new_fid)
    struct.pack_into(">I", data, INVFID_OFF, new_invfid)
    itype = struct.unpack_from(">i", data, TYPE_OFF)[0]
    if itype == 3 and ammo_new_pid is not None:   # weapon: link to ported ammo
        struct.pack_into(">i", data, W_AMMOPID_OFF, ammo_new_pid)

    out = MOD / "data" / "proto" / "items" / f"{new_index:08d}.pro"
    if not dry:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(bytes(data))
        ledger.append(port.ledger_row(src_name, "proto", sp, f"0x{pid:08X}",
                                      str(out.relative_to(ROOT)), f"0x{new_pid:08X}",
                                      "ported by port_gun.py"))
    cal = struct.unpack_from(">i", data, W_CALIBER_OFF)[0] if itype == 3 else struct.unpack_from(">i", data, 57)[0]
    print(f"  {'weapon' if itype==3 else 'ammo':6} 0x{pid:08X} -> FOC #{new_index} (pid 0x{new_pid:08X}) "
          f"fid=0x{new_fid:08X} invFid=0x{new_invfid:08X} caliber={cal}"
          + (f" ammoPid=0x{ammo_new_pid:08X}" if itype == 3 and ammo_new_pid else ""))
    return new_pid, new_index


def write_inven_lst(base_inven, foc_added, dry):
    if not foc_added:
        return
    full = base_inven + foc_added
    out = MOD / "data" / "art" / "inven" / "inven.lst"
    text = "\r\n".join(full) + "\r\n"
    if not dry:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(text.encode("cp1252"))
    print(f"  art/inven: appended {foc_added} at indices "
          f"{list(range(len(base_inven), len(full)))}; inven.lst now {len(full)} lines")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--source", required=True)
    ap.add_argument("--weapon", required=True, type=lambda s: int(s, 0))
    ap.add_argument("--ammo", type=lambda s: int(s, 0))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-deploy", action="store_true")
    args = ap.parse_args()

    src = port.open_source(args.source)
    base = GameIndex(ROOT / "base", pristine=False)
    base_inven = read_inven_lst(base)
    foc_added: list[str] = []

    print(f"porting from {args.source} (base art/inven has {len(base_inven)} entries):")
    dry_alloc: list[str] = []
    ledger: list[dict] = []
    ammo_pid = None
    if args.ammo is not None:
        ammo_pid, _ = port_one(args.source, src, base, args.ammo, base_inven, foc_added, None, args.dry_run, dry_alloc, ledger)
    port_one(args.source, src, base, args.weapon, base_inven, foc_added, ammo_pid, args.dry_run, dry_alloc, ledger)
    write_inven_lst(base_inven, foc_added, args.dry_run)

    if args.dry_run:
        print("dry run: nothing written")
        return 0
    port.append_ledger(ledger)
    port.regen_ledger_md()
    if not args.no_deploy:
        for t in ("gen_ids.py", "build.py", "deploy.py", "validate.py"):
            print(f"\n$ python tools/{t}")
            rc = subprocess.run([sys.executable, str(ROOT / "tools" / t)], cwd=ROOT).returncode
            if rc:
                return rc
    return 0


if __name__ == "__main__":
    sys.exit(main())
