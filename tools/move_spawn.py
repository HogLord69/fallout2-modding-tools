#!/usr/bin/env python3
"""Move the player spawn on REDWELL.MAP next to Arren (square 29,49)."""
import struct
from pathlib import Path

MAP = Path(r"F:\FOCMod\mod\data\maps\REDWELL.MAP")
NEW_TILE = 0x2DB2          # square (row 29, col 49) - one hex east of Arren (29,48)
START_ELEV_OFF = 24        # header: u32 start_tile @0x14 (20), u32 start_elevation @0x18 (24)
NEW_ELEV = 0

raw = bytearray(MAP.read_bytes())
old_tile = struct.unpack_from(">I", raw, 20)[0]
old_elev = struct.unpack_from(">I", raw, 24)[0]
struct.pack_into(">I", raw, 20, NEW_TILE)
struct.pack_into(">I", raw, 24, NEW_ELEV)
MAP.write_bytes(bytes(raw))

# verify round-trip
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from foclib import MapFile, GameIndex, hex_xy  # noqa: E402
gi = GameIndex()
m = MapFile.parse(MAP.read_bytes(), gi.proto)
hx, hy = hex_xy(m.default_tile)
print(f"start tile 0x{old_tile:04X} (row {old_tile//200//2} col {(old_tile%200)//2}) "
      f"-> 0x{NEW_TILE:04X} (row {hy//2} col {hx//2}), elev {old_elev} -> {m.default_elevation}")
print("player now spawns one hex east of Arren (29,48)")