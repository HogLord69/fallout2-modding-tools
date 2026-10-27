#!/usr/bin/env python3
"""
endings.py - write FOC's ending slideshow: mod/data/data/endgame.txt and the
narration (subtitle) files in mod/data/text/english/cuts/.

    python tools/endings.py           # write
    python tools/endings.py --check   # list, write nothing

The slides are shown in the order below, each when its global equals the
value (fc_endings in scripts_src/foc/foc_end.h sets them just before
endgame_slideshow). The art is FOC's own, made by tools/make_slide.py into
the vanilla ending slots (EG_*.FRM, intrface.lst lines 440-473); 327 is the
panning desert. There is no recorded voice: endgame.cc shows the subtitles
for 0.08 s a character when no speech file loads (fallout2.cfg
subtitles=1). FOC's endgame.txt replaces the base's, so no vanilla ending
can ever show.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
IDS_H = ROOT / "scripts_src" / "foc" / "foc_ids.h"
OUT_TXT = ROOT / "mod" / "data" / "data" / "endgame.txt"
OUT_CUTS = ROOT / "mod" / "data" / "text" / "english" / "cuts"

ART = {"EG_ARO01": 440, "EG_BRO01": 441, "EG_DEN01": 442, "EG_GCK01": 443, "EG_GCK02": 444,
       "EG_MOD01": 445, "EG_MOD02": 446, "EG_SAN01": 447, "EG_SAN02": 448, "EG_V1501": 449,
       "EG_DEN02": 454, "EG_NCR01": 455, "DESERT": 327}

# (gvar, value, art, narration name (8 chars max), lines)
ENDINGS = [
    ("GVAR_FOC_END_REDWELL", 1, "EG_ARO01", "fcrw1", [
        "Governor Thorne fell at the well in Redwell, and his legionaries scattered back toward Fort Stockton with no one left to hold them together.",
        "The colony buried its dead on the rise above the corn, and the next morning it went back to work."]),
    ("GVAR_FOC_END_REDWELL", 2, "EG_BRO01", "fcrw2", [
        "Governor Thorne kept his word, which surprised everyone except the Ranger who made the deal.",
        "Water went west by the wagon at Redwell's price, and his riders kept off Redwell's roads. It was not quite peace, but it held."]),
    ("GVAR_FOC_END_WELL", 1, "EG_DEN01", "fcwl1", [
        "Redwell lived with what grew beneath it. The colonists never spoke of it to outsiders, and the water stayed clean and dark.",
        "People who came to stay found they never wanted to leave, and nobody thought that strange."]),
    ("GVAR_FOC_END_WELL", 2, "EG_DEN01", "fcwl2", [
        "Redwell grew. Drifters, refugees and caravan hands came for the water and stayed for reasons they could not quite name.",
        "Within ten years it was the largest town between Lamesa and Odessa, and it moved and fought as one."]),
    ("GVAR_FOC_END_WELL", 3, "EG_GCK02", "fcwl3", [
        "Using Vault 39's old filter designs, Redwell dug shallow wells and built tanks to clean its water another way.",
        "Year by year the colonists drank less from the deep well. The dreams faded, and so did something else that was harder to name."]),
    ("GVAR_FOC_END_WELL", 4, "EG_GCK01", "fcwl4", [
        "Callum carried the charges down himself. The Root Chamber burned for three days.",
        "When the smoke cleared, the well water ran bitter and hot, like water everywhere else. Redwell dug deeper, rationed for the first time, and endured on its own terms."]),
    ("GVAR_FOC_END_WELL", 5, "EG_SAN02", "fcwl5", [
        "The broadcast from the relay station went out across the wasteland.",
        "Within a year, men in power armor came asking about the well under Redwell. What they wanted with it, and what the colony gave them, is a story for another time."]),
    ("GVAR_FOC_END_CLAIRE", 1, "EG_MOD01", "fccl1", [
        "Clairemont's posse rode beside the water wagons for years. The town never got its own well back, but it never went thirsty again.",
        "Its children grew up drinking water that did not make them sick."]),
    ("GVAR_FOC_END_CLAIRE", 2, "EG_V1501", "fccl2", [
        "Without Redwell's water, Clairemont dried out one family at a time.",
        "By the next summer, the drive-in screen stood over an empty town."]),
    ("GVAR_FOC_END_LAMESA", 1, "EG_MOD02", "fclm1", [
        "The Loosing went home to its reliquary, and the Church of Plutonius kept its covenant with Redwell.",
        "Their brahmin carried Redwell's water to every town on the circuit, and the flock sang the Ranger's name in their liturgy, which was a mixed blessing."]),
    ("GVAR_FOC_END_LAMESA", 2, "EG_MOD02", "fclm2", [
        "Brother Gamma's word carried the flock. Lamesa closed its gate to smoothskins and went on tending the casks, alone and content."]),
    ("GVAR_FOC_END_LAMESA", 3, "EG_MOD02", "fclm3", [
        "To the flock at Lamesa, Redwell became the second brotherhood.",
        "The caravans stopped coming, and the ghouls told the story of the Ranger who stole from Plutonius until the story outlived them."]),
    ("GVAR_FOC_END_LAMESA", 4, "EG_MOD02", "fclm4", [
        "The flock at Lamesa traded with Redwell when it suited them and kept to themselves when it did not, waiting with their casks as they always had."]),
    ("GVAR_FOC_END_BAND", 1, "EG_SAN01", "fcmb1", [
        "The band from Midland never raided another caravan. Hollis read to them in the evenings, and the Odessa road grew quiet."]),
    ("GVAR_FOC_END_BAND", 2, "EG_SAN01", "fcmb2", [
        "The Midland ruins fell silent. The caravans rolled through safely, and few of the drivers knew or cared what had become of the old monsters who used to live there."]),
    ("GVAR_FOC_END_BAND", 3, "EG_SAN01", "fcmb3", [
        "The lost one went home to Midland, and Hollis never let him out of his sight again.",
        "When Redwell needed them the band came, and when it did not, they sat by their fire and read."]),
    ("GVAR_FOC_END_BAND", 4, "EG_SAN01", "fcmb4", [
        "The raids on the Odessa road went on. Nobody ever learned who did them, and the flock at Lamesa took the blame for years."]),
    ("GVAR_FOC_END_CALLUM", 1, "EG_DEN02", "fcca1", [
        "With the parts from the annex, Callum's charging station came to life.",
        "Redwell charged its own cells, and towns that had never heard of it began to trade with it."]),
    ("GVAR_FOC_END_CALLUM", 2, "EG_NCR01", "fcca2", [
        "Callum never finished his charging station. He kept the well, tended the corn, and told the new colonists about the advance team until they could tell it back to him."]),
    ("GVAR_FOC_END_RANGER", 1, "DESERT", "fcend", [
        "As for the Ranger, the road never quite let go.",
        "But wherever the trail led, there was always a well to come home to."]),
]


def gvar_numbers() -> dict[str, int]:
    text = IDS_H.read_text(encoding="utf-8")
    return {m.group(1): int(m.group(2)) for m in re.finditer(r"#define\s+(GVAR_FOC_\w+)\s+\((\d+)\)", text)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    nums = gvar_numbers()
    lines = ["# endgame.txt - FOC's ending slides, written by tools/endings.py. Edit there.",
             "#   gvar, value, art (intrface.lst line), narration [, pan direction]"]
    for gvar, value, art, nar, text in ENDINGS:
        if gvar not in nums:
            sys.exit(f"{gvar} is not in foc_ids.h; run gen_ids.py")
        if len(nar) > 8:
            sys.exit(f"narration name {nar} is longer than 8 characters")
        for t in text:
            if " - " in t or "—" in t:
                sys.exit(f"no dashes in narration: {t!r}")
        idx = ART[art]
        tail = ", 1" if art == "DESERT" else ""
        lines.append(f"# {gvar} = {value}")
        lines.append(f"{nums[gvar]}, {value}, {idx}, {nar}{tail}")
        if not args.check:
            OUT_CUTS.mkdir(parents=True, exist_ok=True)
            (OUT_CUTS / f"{nar}.txt").write_text(
                "\n".join(f"{i}:{t}" for i, t in enumerate(text, 1)) + "\n", encoding="cp1252", newline="\r\n")
    if args.check:
        print("\n".join(lines))
        return 0
    OUT_TXT.parent.mkdir(parents=True, exist_ok=True)
    OUT_TXT.write_text("\n".join(lines) + "\n", encoding="cp1252", newline="\r\n")
    print(f"wrote {OUT_TXT.relative_to(ROOT)} ({len(ENDINGS)} slides) and {len(ENDINGS)} narration files")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
