"""RWFAC2.MAP, the sealed military annex under the waterworks (foc_fac.h).
Designed room by room; nothing copied. Fallout 2's military wall set (mmb,
as in the EPA complex) with vault doors, steel and vault floors; the
aquifer galleries in its cave set (ca).

elev 0: the lift lobby, the checkpoint hall and guard post, the tunnel with
the sealed fire door, the stair room beyond it.
elev 1: one long corridor; barracks, mess, command office, power room to
the north; officers, armory, stores and the stair down to the south.
elev 2: the trial station's labs (alga tanks, samples, cold store, the
station log) and the natural galleries they opened into, down to the
Root Chamber.

    python tools/designs/rwfac2.py && python tools/compose_map.py mod/maps_src/rwfac2.compose.json --write --force
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sitekit import Site  # noqa: E402


def hx(r):
    return (r[0] * 2, r[1] * 2, r[2] * 2 + 1, r[3] * 2 + 1)


def inside(r, m=1):
    a = hx(r)
    return (a[0] + m, a[1] + m, a[2] - m, a[3] - m)


S = Site("RWFAC2", 215, 215)
S.script = "SCRIPT_RWFAC2"

# ===================================================================== elev 0
S.layout([4, 4, 95, 95], base=None)
LOBBY = (44, 60, 53, 68)
CHECK = (40, 44, 57, 59)
GUARD = (58, 46, 64, 54)
TUNNEL = (20, 49, 39, 53)
STAIR0 = (12, 46, 19, 56)
S.complex("checkpoint", [LOBBY, CHECK, GUARD, TUNNEL, STAIR0], "mmb",
          inner=[(88, 120, 107, 120), (116, 92, 116, 109)],
          doors=[(97, 120), (116, 100)])
S.L.floor(LOBBY, "metal"); S.L.floor(CHECK, "metal"); S.L.floor(GUARD, "vault")
S.L.floor(TUNNEL, "cave"); S.L.floor(STAIR0, "metal")
S.solve_layout()
S.furnish("office", inside(GUARD))
S.row("crate", 84, 92, 4, dx=0, dy=4)                 # checkpoint: the guards' barricade
S.put("barrel", 110, 112); S.put("crate", 112, 112)
S.put("body", 92, 104); S.put("blood", 93, 105)       # a guard who never got out
S.put("bones", 70, 101); S.put("junk", 72, 104)       # someone tried the door
S.put("pipes", 30, 94); S.put("crate", 34, 110)
S.exit([26, 100, 28, 105], to=215, tile=99 * 200 + 24, elev=1, rot=2)
S.start = (97, 130, 0, 2)

# ===================================================================== elev 1
S.new_level(1)
S.layout([4, 4, 95, 95], base=None)
COR = (14, 48, 70, 51)
ARR1 = (8, 44, 13, 56)
BAR = (16, 36, 30, 47)
MESS = (32, 36, 42, 47)
CMD = (44, 36, 54, 47)
POW = (56, 36, 68, 47)
OFF = (16, 52, 26, 63)
ARM = (28, 52, 38, 63)
STO = (40, 52, 50, 63)
DOWN = (60, 52, 68, 63)
S.complex("annex", [COR, ARR1, BAR, MESS, CMD, POW, OFF, ARM, STO, DOWN], "mmb",
          inner=[(28, 96, 141, 96), (28, 103, 141, 103), (28, 96, 28, 103)],
          doors=[(46, 96), (74, 96), (98, 96), (124, 96), (42, 103), (66, 103), (90, 103), (128, 103), (28, 99)])
for r, f in ((COR, "metal"), (ARR1, "metal"), (BAR, "vault"), (MESS, "vault"), (CMD, "vault"), (POW, "metal"),
             (OFF, "vault"), (ARM, "metal"), (STO, "metal"), (DOWN, "metal")):
    S.L.floor(r, f)
S.solve_layout()
S.furnish("barracks", inside(BAR))
S.furnish("mess", inside(MESS))
S.furnish("office", inside(CMD))
S.furnish("machine", inside(POW))
S.furnish("quarters", inside(OFF))
S.furnish("armory", inside(ARM))
S.furnish("store", inside(STO))
S.put("goo", 60, 86); S.put("goo", 62, 88)            # the mould has reached the barracks
S.put("bones", 58, 84)
S.put("body", 100, 99)                                # corridor: the last patrol
S.exit([18, 98, 20, 103], to=215, tile=103 * 200 + 32, elev=0, rot=2)
S.exit([130, 122, 135, 125], to=215, tile=90 * 200 + 128, elev=2, rot=2)

# ===================================================================== elev 2
S.new_level(2)
S.layout([4, 4, 95, 95], base=None)
ARR2 = (60, 40, 68, 48)
LCOR = (40, 44, 59, 47)
LAB1 = (40, 32, 50, 43)
LAB2 = (52, 32, 59, 43)
COLD = (40, 48, 50, 56)
TRIAL = (52, 48, 59, 56)
labs = S.complex("trial station", [ARR2, LCOR, LAB1, LAB2, COLD, TRIAL], "mmb",
                 inner=[(80, 88, 119, 88), (80, 95, 119, 95), (120, 88, 120, 95)],
                 doors=[(90, 88), (110, 88), (90, 95), (110, 95), (120, 91), (80, 91)])
for r, f in ((ARR2, "metal"), (LCOR, "metal"), (LAB1, "vault"), (LAB2, "vault"), (COLD, "metal"), (TRIAL, "vault")):
    S.L.floor(r, f)
gal = S.cave("galleries", [(36, 45, 3), (31, 50, 4), (26, 57, 5), (22, 65, 4), (28, 70, 4), (18, 73, 3), (35, 62, 3)], 2,
             floor=None)
S.lines_last_open = None
# no cave wall where the galleries meet the station's west door
S.level["lines"].pop()
gal |= {(x, y) for x in range(31, 40) for y in range(44, 48)}       # the station's breach into the rock
S.wall_squares("galleries", gal, "ca", floor="cave", open_to=labs)
S.solve_layout()
S.row("suspension_tank", 84, 68, 4, dx=4, dy=0)       # the alga tanks
S.row("suspension_tank", 84, 78, 4, dx=4, dy=0)
S.furnish("lab", inside(LAB2))
S.furnish("store", inside(COLD))
S.furnish("lab", inside(TRIAL))
for i in range(70):                                   # the mould thickening toward the Root Chamber
    gx, gy = S.rng.randint(30, 80), S.rng.randint(84, 150)
    if (gx // 2, gy // 2) in gal and S.rng.random() < (gy - 80) / 80:
        S.put(S.rng.choice(["goo", "goo", "mushroom"]), gx, gy)
S.put("bones", 52, 116); S.put("crate", 54, 118)      # the survey team's cache
S.exit([130, 82, 135, 84], to=215, tile=112 * 200 + 128, elev=1, rot=2)
S.exit([34, 144, 39, 147], to=216, tile=118 * 200 + 96, elev=0, rot=2)
S.save()
