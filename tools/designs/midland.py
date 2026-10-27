"""The Midland Ruins (MIDLAND.MAP): the crossing of Wall Street and Main
Street in dead downtown Midland, where Hollis's band lives in the bank.
Drawn from docs/plans/midland.png; nothing copied from another map.

    python tools/designs/midland.py && python tools/compose_map.py mod/maps_src/midland.compose.json --write --force
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sitekit import Site  # noqa: E402


def inner(rect):
    sx0, sy0, sx1, sy1 = rect
    return (sx0 * 2 + 1, sy0 * 2 + 1, sx1 * 2, sy1 * 2)


S = Site("MIDLAND", 217, 217)
S.script = "SCRIPT_MIDLAND"

# --- ground: two crossing streets, Fallout 2's own street sections --------
L = S.layout([4, 4, 95, 95], wear=0.45)
L.sidewalk([12, 44, 90, 46]); L.sidewalk([12, 52, 90, 54])
L.street_x(47, 12, 90)                  # Wall Street
L.sidewalk([42, 6, 45, 94]); L.sidewalk([53, 6, 56, 94])
L.street_y(52, 6, 94)                   # Main Street
L.crossing([46, 47, 52, 51])
L.street_x(73, 12, 90)                  # Front Street
L.apron([57, 56, 72, 70])               # Centennial Plaza

BRICK = ["crbm004.frm", "crbm007.frm"]
TP = ["tp153.frm", "tp154.frm", "tp155.frm", "tp156.frm"]

# --- the bank: the one intact building, the band's home ----------------------
bank = (54, 28, 72, 42)
S.building("First Capital Bank", bank, "adb",
           doors=[("S", 16), ("S", 17), (129, 64), (122, 75)],
           inner=[(129, 57, 129, 85), (109, 75, 128, 75)], roof=["adb029.frm", "adb030.frm"],
           rooms=[("quarters", (110, 57, 127, 74)), ("store", (131, 57, 144, 84)), ("quarters", (110, 77, 127, 84))])

# --- the ruins: shells, rubble, no roofs ---------------------------------------
pet = (26, 18, 42, 42)
S.building("Petroleum Building (ruin)", pet, "nec", broken=0.3, inner=[(53, 60, 84, 60), (68, 37, 68, 60)], rooms=[("ruin", (53, 37, 67, 59)), ("ruin", (69, 37, 84, 59)), ("ruin", (53, 61, 84, 84))])
wil = (28, 55, 42, 70)
S.building("Wilco Building (ruin)", wil, "nec", broken=0.5, inner=[(57, 124, 84, 124)], rooms=[("ruin", (57, 111, 84, 123)), ("ruin", (57, 125, 84, 140))])
for i, r in enumerate([(74, 18, 82, 30), (58, 10, 70, 22), (74, 55, 84, 66), (16, 55, 24, 68), (16, 20, 22, 34)]):
    S.building(f"ruin {i}", r, "nec", broken=0.6, rooms=[("ruin", inner(r))])

# --- stories (docs/plans/midland.png S1-S8) ------------------------------------
S.scene("ambush", 96, 142)                         # S1 the caravan barricade across Main Street
S.scene("ambush", 100, 146)
S.row("cart", 92, 144, 3, dx=4, dy=0)
for x, y in ((116, 64), (114, 66)):                # S2 Hollis's reading corner
    S.put("shelf_books", x, y)
S.put("table", 118, 68)
S.put("chair_any", 120, 68)
S.scene("supply", 136, 62)                         # S3 the loot room
S.scene("supply", 136, 72)
S.scene("camp", 136, 112)                          # S4 Ash's fire on the plaza
S.put("statue", 126, 124, force=True)              # S5 the monument
S.scene("collapse", 66, 56)                        # S6 the grid authority's end
S.put("skeleton", 72, 50)
S.put("desk", 74, 50)
for i, x in enumerate(range(40, 84, 9)):           # S7 the jam on Wall Street
    S.put("car", x, 96 + (i % 2), rot=0 if i % 2 else 2)
S.put("bones", 58, 98)
S.put("chair_any", 64, 112)                        # S8 the lookout on the Wilco rubble
S.put("pole", 66, 112)
S.scene("collapse", 70, 116)

L.floor(bank, "cmt")
for r in (pet, wil):
    L.floor(r, "tp")
S.solve_layout()

# --- clutter -------------------------------------------------------------------
S.clutter_walls(["rubble", "debris", "junk", "trash", "scrub", "scrub", "scrub", "tires"], chance=0.2)
S.sprinkle(["scrub", "tumbleweed", "junk", "trash"], (24, 12, 176, 176), density=0.04)

S.exit([92, 176, 101, 178])                        # south road
S.exit([24, 92, 26, 101])                          # Wall Street east
S.start = (97, 160, 0, 0)
S.save(scroll=[20, 8, 180, 184])
