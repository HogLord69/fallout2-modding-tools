"""RWFAC3.MAP, the Root Chamber (foc_fac.h; REDWELL_DESIGN §1.3). Designed;
nothing copied. The trial station's observation room (Fallout 2's concrete
interior set, dv) at the mouth of a natural cavern (cave set, ca) that the
Redwell mould has grown through: goo and fruiting bodies thickening toward
the back, where the trial's intake pipe ends; the survey party's last camp.

    python tools/designs/rwfac3.py && python tools/compose_map.py mod/maps_src/rwfac3.compose.json --write --force
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sitekit import Site  # noqa: E402

S = Site("RWFAC3", 216, 216)
S.script = "SCRIPT_RWFAC3"
S.layout([4, 4, 95, 95], base=None)
OBS = (44, 56, 52, 62)
obs = S.complex("observation room", [OBS], "dv", inner=[], doors=[(96, 112)])
S.L.floor(OBS, "metal")
cav = S.cave("root chamber", [(48, 50, 5), (42, 42, 7), (54, 38, 6), (36, 30, 6), (50, 26, 7), (62, 28, 5), (44, 20, 5)], 3,
             floor=None)
S.level["lines"].pop()
S.wall_squares("root chamber", cav, "ca", floor="cave", open_to=obs)
S.solve_layout()
S.furnish("lab", (89, 115, 104, 124))
S.put("pipes", 92, 104); S.put("pipes", 96, 96); S.put("pipes", 100, 86)   # the intake pipe, running in
for x in range(58, 140, 5):                       # the mould: thick at the back, thinning to the mouth
    for y in range(28, 110, 5):
        depth = (110 - y) / 82
        gx, gy = x + S.rng.randint(-2, 2), y + S.rng.randint(-2, 2)
        if (gx // 2, gy // 2) in cav and S.rng.random() < 0.15 + 0.5 * depth:
            S.put(S.rng.choice(["goo", "goo", "mushroom"]), gx, gy)
S.scene("camp", 84, 92)                           # the survey party's last camp
S.put("skeleton", 88, 96); S.put("bones", 80, 90)
S.exit([94, 122, 99, 124], to=215, tile=140 * 200 + 40, elev=2, rot=2)
S.start = (96, 118, 0, 2)
S.save()
