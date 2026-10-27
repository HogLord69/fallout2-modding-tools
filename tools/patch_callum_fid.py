#!/usr/bin/env python3
"""Patch Callum's critter FID on REDWELL.MAP to the NCR Ranger art (NMRANG, idx 250)."""
import sys, struct
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from foclib import MapFile, GameIndex, pid_type, OBJ_TYPE_CRITTER

ROOT = Path(__file__).resolve().parent.parent
MAP = ROOT / "mod" / "data" / "maps" / "REDWELL.MAP"
NEW_FID = (1 << 24) | 249   # line 250 NMRANG,11 -> FID 0x010000F9
SCRIPT_RWELDER = 1602       # 0-based script index for Callum/rwelder

gi = GameIndex()
raw = bytearray(MAP.read_bytes())
m = MapFile.parse(bytes(raw), gi.proto)

patched = 0
for o in m.objects:
    if pid_type(o.pid) != OBJ_TYPE_CRITTER:
        continue
    if o.script_index != SCRIPT_RWELDER:
        continue
    sq = ((o.tile % 200) // 2, (o.tile // 200) // 2)
    old_fid = o.fid
    # object FID is a u32 at fid_offset (offset into the raw map object record)
    off = o.fid_offset
    struct.pack_into(">I", raw, off, NEW_FID)
    patched += 1
    print(f"patched critter at sq={sq} script_idx={o.script_index} "
          f"fid 0x{old_fid:08X} -> 0x{NEW_FID:08X} (off={off})")

print(f"total patched: {patched}")
if patched == 0:
    sys.exit("ERROR: no RWELDER critter found")
MAP.write_bytes(bytes(raw))
# verify round-trip
chk = MapFile.parse(MAP.read_bytes(), gi.proto)
for o in chk.objects:
    if o.script_index == SCRIPT_RWELDER:
        print(f"verify: sq={((o.tile%200)//2,(o.tile//200)//2)} fid=0x{o.fid:08X}")
        assert o.fid == NEW_FID, "FID not persisted!"
print(f"verified. wrote {MAP.relative_to(ROOT)}")
