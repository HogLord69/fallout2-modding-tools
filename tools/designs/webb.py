"""Webb Airbase (WEBB.MAP): Governor Thorne's forward camp on the old Big
Spring airfield. Drawn from docs/plans/webb.png (mod/maps_src/plans/
webb.plan.json); nothing copied from another map. The bombers are Sonora's
aircraft art (TSGRAVE and RNDBOMB), lifted as single objects onto drawn
ground, at the owner's request.

    python tools/designs/webb.py && python tools/compose_map.py mod/maps_src/webb.compose.json --write --force
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sitekit import Site  # noqa: E402


def inner(rect):
    sx0, sy0, sx1, sy1 = rect
    return (sx0 * 2 + 1, sy0 * 2 + 1, sx1 * 2, sy1 * 2)


S = Site("WEBB", 218, 218)
S.script = "SCRIPT_WEBB"

# --- ground: the airfield's bands, laid with Fallout 2's tile grammar ------
L = S.layout([4, 4, 95, 97], wear=0.32)
L.runway_x(8, 6, 93, width=7)            # main runway, centre line on row 11
L.apron([26, 16, 70, 25])                # apron
L.runway_x(27, 22, 78, width=3)          # Front Avenue
L.sidewalk([22, 30, 27, 31])
L.road_y(53, 30, 97, width=3)            # gate road
L.apron([55, 52, 66, 62])                # parade ground

ROOF = ["tp153.frm", "tp154.frm", "tp155.frm", "tp156.frm"]
#CONC = ["crbm004.frm", "crbm007.frm"]

# --- flightline: Hangar 25 and the tower on Front Avenue --------------------
hang = (28, 30, 40, 39)
S.building("Hangar 25", hang, "ware", doors=[("N", 10), ("N", 11), ("N", 12), ("N", 13)],
           roof=["wroof06.frm"],
           rooms=[("workshop", inner(hang))])
tower = (43, 30, 47, 34)
S.building("Control tower", tower, "nec", doors=[("N", 5)], roof=ROOF,
           rooms=[("office", inner(tower))])

# --- the cantonment, fenced -------------------------------------------------
# chain-link round [40,42]-[76,79] squares, gate on the gate road
fx0, fy0, fx1, fy1 = 80, 84, 153, 159
S.fence("cantonment fence", [(fx0, fy0), (fx1, fy0), (fx1, fy1), (fx0, fy1), (fx0, fy0)], "fence",
        gates=[(x, fy1) for x in range(101, 109)])
hq = (42, 48, 49, 58)
S.building("HQ", hq, "nec", doors=[("E", 9), ("E", 10), (92, 106)], inner=[(85, 106, 99, 106)],
           roof=ROOF,
           rooms=[("office", (85, 97, 98, 105)), ("armory", (85, 107, 98, 117))])
bar = (55, 44, 70, 49)
S.building("Barracks", bar, "nec", doors=[("S", 14), ("S", 15)], roof=ROOF,
           rooms=[("barracks", inner(bar))])
mess = (55, 64, 68, 69)
S.building("Mess hall", mess, "nec", doors=[("N", 12), ("N", 13), (126, 134)], inner=[(126, 129, 126, 139)],
           roof=ROOF,
           rooms=[("kitchen", (111, 129, 125, 138)), ("mess", (127, 129, 136, 138))])

# --- the safety corner: fuel, powder, the teamsters -------------------------
S.fence("barrier", [(44, 124), (74, 124)], "carw")
powder = (26, 66, 31, 70)
S.building("Powder store", powder, "nec", doors=[("N", 6)], roof=ROOF,
           rooms=[("store", inner(powder))])
shed = (26, 73, 31, 78)
S.building("Teamsters' shed", shed, "dv", doors=[("E", 4)],
           roof=["plk2000.frm"], rooms=[("squat", inner(shed))])

# fuel tanks at the east end of Front Avenue
for i, (x, y) in enumerate([(128, 62), (134, 62), (140, 62), (128, 70), (134, 70)]):
    S.put("tanks", x, y, force=True)
S.put("gaspump", 124, 66)
S.put("gaspump", 124, 70)

# --- the aircraft: Sonora's bombers on the apron, the crash past it ---------
K = ["^tsun5", "^tsun6", "^bibl01", "^block"]
S.level["lift"] = [
    {"source": "sonora", "map": "TSGRAVE", "elev": 1, "rect": [29, 21, 39, 31], "shift": [-2, -6], "no_floor": True, "keep": K},
    {"source": "sonora", "map": "TSGRAVE", "elev": 1, "rect": [29, 32, 39, 42], "shift": [9, -17], "no_floor": True, "keep": K},
    {"source": "sonora", "map": "TSGRAVE", "elev": 1, "rect": [69, 42, 76, 51], "shift": [-19, -26], "no_floor": True, "keep": K},
    {"source": "sonora", "map": "RNDBOMB", "elev": 0, "rect": [37, 40, 44, 47], "shift": [25, -25], "no_floor": True, "keep": K},
]

# --- stories (docs/plans/webb.png S1-S8) -------------------------------------
S.scene("firebarrel_crowd", 112, 164)                     # S1 the checkpoint, outside the gate
S.fence("gate post west", [(96, 162), (99, 162)], "carw")
S.fence("gate post east", [(110, 162), (113, 162)], "carw")
S.scene("ambush", 130, 40)                                # S2 cutting up the crashed bomber
S.put("cart", 126, 44)
S.put("bones", 132, 34)
S.scene("salvage", 64, 50)                                 # S3 stripping the B-25s
S.put("firebarrel", 70, 50)
S.put("flagpole", 122, 110, force=True)                    # S4 the punishment post
S.put("pot", 124, 111)
S.put("blood", 123, 112)
S.scene("camp", 144, 108)                                  # S5 the troopers' camp
S.scene("camp", 146, 122)
S.row("barrel", 62, 140, 6, dx=3, dy=0)                    # S6 the teamsters' fuel line
S.put("cart", 82, 140)
S.scene("driver", 150, 64)                                 # S7 the base that died
S.graves(144, 150, 1, 3, "cross")                          # S8 the march's dead
S.put("grave", 150, 154)

for r, fam in ((hang, "cmt"), (tower, "tp"), (hq, "tp"), (bar, "tp"), (mess, "tp"), (powder, "cmt"), (shed, "carpet")):
    L.floor(r, fam)
S.solve_layout()

# --- clutter -----------------------------------------------------------------
S.clutter_walls(["scrub", "scrub", "scrub", "junk", "trash", "tires", "barrel", "tumbleweed"], chance=0.22)
S.sprinkle(["scrub", "scrub", "tumbleweed", "cactus", "junk"], (44, 12, 156, 190), density=0.04)

# --- exits, start ------------------------------------------------------------
S.exit([102, 186, 107, 188])
S.start = (104, 172, 0, 0)
S.save(scroll=[36, 8, 162, 194])
