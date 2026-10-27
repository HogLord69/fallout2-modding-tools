"""RWFAC1.MAP, Redwell's buried municipal waterworks (the Facility Below,
foc_fac.h). Designed room by room; nothing copied. Fallout 2's concrete
interior walls (dv, as in Vault 15 and the Gecko power plant), its plank,
steel and vault floors, its own props.

elev 0, the well-head level: the stair niche from the colonists' dig, the
pump hall with its valve room, the intake shaft with the railed pit and
the winch over it, the staff lockers, and the sewer that still holds the
plant's chlorine.
elev 1, the treatment level under it: the control room at the foot of the
shaft, a long service corridor, the settling basins and the filter gallery
to the west, the machine room (breaker), maintenance office and shift
quarters to the east, the service lift down to the annex at the south.

    python tools/designs/rwfac1.py && python tools/compose_map.py mod/maps_src/rwfac1.compose.json --write --force
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sitekit import Site  # noqa: E402


def hx(r):
    """square rect -> its hex rect"""
    return (r[0] * 2, r[1] * 2, r[2] * 2 + 1, r[3] * 2 + 1)


def inside(r, m=1):
    a = hx(r)
    return (a[0] + m, a[1] + m, a[2] - m, a[3] - m)


S = Site("RWFAC1", 214, 214)
S.script = "SCRIPT_RWFAC1"

# ===================================================================== elev 0
S.layout([10, 10, 90, 90], base=None)
NICHE = (46, 62, 51, 67)
CORR = (47, 52, 50, 61)
HALL = (38, 40, 60, 51)
SHAFT = (40, 28, 54, 39)
PIT = (44, 31, 49, 36)
SEWER = (22, 43, 37, 48)
SUMP = (22, 36, 29, 55)
LOCK = (51, 55, 56, 60)
S.complex("well-head level", [NICHE, CORR, HALL, SHAFT, SEWER, SUMP, LOCK], "dv",
          inner=[(76, 80, 121, 80),      # shaft room / pump hall
                 (108, 81, 108, 103),    # valve room
                 (94, 103, 101, 103),    # pump hall / corridor
                 (76, 86, 76, 97),       # pump hall / sewer
                 (102, 110, 102, 121)],  # corridor / lockers
          doors=[(94, 80), (108, 92), (97, 103), (76, 91), (102, 115)])
S.L.floor(NICHE, "plank"); S.L.floor(CORR, "plank"); S.L.floor(LOCK, "plank")
S.L.floor(HALL, "metal"); S.L.floor(SHAFT, "metal")
S.L.floor(SEWER, "metal"); S.L.floor(SUMP, "metal")
S.L.floor((54, 40, 60, 51), "vault")                  # valve room
pit = {(x, y) for y in range(PIT[1], PIT[3] + 1) for x in range(PIT[0], PIT[2] + 1)}
S.L.clear(pit)                                        # the shaft: open to the level below
px0, py0, px1, py1 = hx(PIT)
S.fence("pit rail", [(px0 - 1, py0 - 1), (px1 + 1, py0 - 1), (px1 + 1, py1 + 1), (px0 - 1, py1 + 1), (px0 - 1, py0 - 1)],
        "rl", gates=[(94, py1 + 1), (95, py1 + 1)])
S.taken |= {(x, y) for x in range(px0, px1 + 1) for y in range(py0, py1 + 1)}
S.solve_layout()

# furnishing
for x in range(80, 106, 6):                           # the pumps in a row
    S.put("waterpump", x, 90)
S.put("pumpctl", 100, 84)
S.row("pipes", 78, 82, 6, dx=4, dy=0)
S.furnish("machine", (110, 82, 120, 102))             # valve room
S.furnish("store", inside(LOCK))
S.row("pipes", 82, 58, 5, dx=5, dy=0)                 # shaft room
S.put("crate", 104, 62); S.put("barrel", 104, 66)
for x, y in ((50, 88), (58, 94), (66, 90), (48, 78), (52, 104)):   # sewer
    S.put("puddle", x, y)
S.put("drain", 70, 88); S.put("drain", 46, 98)
# stories
S.put("bones", 56, 96); S.put("crate", 54, 96)       # a worker caught by the gas
S.put("table", 114, 96); S.put("pot", 116, 96)        # the last shift's coffee
S.scene("collapse", 96, 126)                          # the dig broke through here

# exit up the stair to Redwell (RWCORE2, the dig)
S.exit([94, 133, 101, 134], to=201, tile=16506, elev=0, rot=2)
S.start = (97, 128, 0, 2)

# ===================================================================== elev 1
S.new_level(1)
S.layout([10, 10, 90, 90], base=None)
CTRL = (42, 28, 52, 38)
COR1 = (45, 39, 48, 64)
LIFT = (44, 65, 49, 70)
BASIN = (28, 40, 44, 52)
FILTER = (28, 54, 44, 64)
MACH = (49, 40, 60, 48)
OFFICE = (49, 50, 58, 56)
QUART = (49, 58, 58, 64)
S.complex("treatment level", [CTRL, COR1, LIFT, BASIN, FILTER, MACH, OFFICE, QUART], "dv",
          inner=[(90, 78, 97, 78), (88, 130, 99, 130), (90, 80, 90, 129), (97, 80, 97, 129)],
          doors=[(93, 78), (93, 130), (90, 92), (90, 118), (97, 88), (97, 106), (97, 122)])
S.L.floor(CTRL, "metal"); S.L.floor(COR1, "plank"); S.L.floor(LIFT, "metal")
S.L.floor(BASIN, "metal"); S.L.floor(FILTER, "vault")
S.L.floor(MACH, "metal"); S.L.floor(OFFICE, "plank"); S.L.floor(QUART, "plank")
S.solve_layout()

S.furnish("lab", (86, 58, 104, 76))                   # control room consoles
for x in range(60, 86, 6):                            # settling basins
    S.put("drain", x, 88)
    S.put("drain", x, 98)
S.row("pipes", 58, 82, 6, dx=5, dy=0)
S.row("barrel", 84, 84, 3, dx=0, dy=3)
S.row("watertank_s", 62, 112, 4, dx=6, dy=0)          # filter gallery
S.row("pipes", 60, 124, 5, dx=6, dy=0)
S.furnish("machine", inside(MACH))
S.furnish("office", inside(OFFICE))
S.furnish("quarters", inside(QUART))
S.put("crate", 92, 138); S.put("barrel", 96, 138)
S.scene("collapse", 66, 104)                          # basin wall cracked

S.exit([0, 0, 0, 0], to=-2) if False else None
S.save()
