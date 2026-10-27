#!/usr/bin/env python3
"""
build_gecko_browsers.py - generate tools/gecko_browse/, one launcher per TC.

    python tools/build_gecko_browsers.py

Regenerate here rather than hand-editing the .bat/.ps1 files if a TC's
install path changes or a new one is added (edit TCS below).

WHY A SEPARATE LAUNCHER PER GAME, NOT ONE MERGED VIEW.
Gecko keeps exactly one settings.json with one flat list of mounted data
paths - there is no per-session profile. Nine different Fallout games each
ship a full master.dat/critter.dat that reuses Fallout 2's own filenames
(art/tiles/edg5000.frm, art/critters/hmjmps*.frm, ...) for DIFFERENT pixel
content. Merging them all into one mount list means a name collision
silently picks whichever game mounted last - Redwell's own tiles or
critters could start rendering as some other game's art, with no error.
There is no priority ordering that avoids this when the "TCs" are unrelated
games, not overlays of the same one. So each launcher swaps the whole
settings.json out, runs gecko against ONE game only, and restores the FOC
editing profile when that window closes - see _swap_and_launch.ps1.

WHY SOME TCS ALSO GET A _clean/<name> OVERRIDE FOLDER.
Several community TCs ship LST files with Cyrillic (CP1251) comments after
the ';' on a line - harmless to the real game, which stops reading at the
comma-separated fields before it. gecko is stricter: it checks the first 64
bytes of an LST file for pure ASCII and throws on the first high byte,
which a Cyrillic comment on line 1 hits immediately (confirmed against
Sonora's art/intrface/intrface.lst). clean_lst_for_gecko.py scans every .lst
in that install's own .dat archives, scrubs non-ASCII bytes to spaces (field
data before ';' is untouched, only comment text is blanked), and writes
them to gecko_browse/_clean/<install folder name>/. The matching launcher
mounts that folder LAST (highest priority) so gecko reads the scrubbed
copies for those files and the game's own dat archives for everything
else - no file in the actual install is ever touched.

WHY _fallback_art/ IS ITS OWN TINY FOLDER, NOT gecko's build/resources.
A map with a tile id outside a game's own tiles.lst needs SOME art
(blank.frm) or gecko hard-fails outright instead of degrading - confirmed
against gecko.log, this is not automatic despite what the app's own
ensureFallbackDataPath naming implies. reference/gecko/build/resources
LOOKS like gecko's small bundled placeholder set but is not: this project
copied master.dat (333MB) and critter.dat (166MB) into gecko's *source*
resources/ early on for FOC's own convenience (harmless there - same
vanilla FO2 data), and its maps/ later picked up saved copies of Redwell.
Mounting that whole folder into a TC session leaked Redwell's own
REDWELL.MAP into what was meant to be an isolated Nevada Mod (Extended)
browse - confirmed live via `resource list`. _fallback_art/ is copied fresh
each run from gecko's actual bundled set (the 6 small .frm files under
reference/gecko/resources/art/ in the SOURCE tree) and nothing else.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "gecko_browse"
CLEAN_ROOT = OUT / "_clean"
FALLBACK_ART_SRC = HERE.parent / "reference" / "gecko" / "resources" / "art"
FALLBACK_ART_OUT = OUT / "_fallback_art" / "art"

# name -> (install directory, extra dat filenames beyond master.dat/critter.dat,
#          in the order they should be mounted - lowest priority first)
TCS: dict[str, tuple[str, list[str]]] = {
    "Fallout 2 - vanilla (no RPU)": (r"F:\GOG Games\Fallout 2", []),
    "Fallout Sonora":               (r"C:\Fallout Sonora (Extended Release)", []),
    "Fallout Nevada":               (r"C:\Fallout Nevada (Expansion Version)", []),
    "Fallout Olympus 2207":         (r"C:\Olympus 2207 (FE)", []),
    "Fallout Resurrection":         (r"C:\Fallout Resurrection (FE)", ["fores.dat"]),
    "Fallout Story of the Jackal":  (r"C:\Fallout-SotJ", []),
    "Fallout Yesterday":            (r"F:\Fallout yesterday", ["patch001.dat", "patch002.dat"]),
}
# Nevada Mod (Extended) has no master.dat/critter.dat of its own and is NOT a
# standalone game - confirmed missing color.pal (the engine's core palette)
# anywhere in its own Patch000.dat/Patch001.dat/loose data. It's a true overlay
# mod, expecting a base Fallout Nevada install underneath for the engine-level
# files it doesn't ship. underlay is that base game's own dat files, mounted
# BELOW everything else (lowest priority) so Nevada Mod's own content still
# wins wherever the two overlap - the same layering our own FOC mod uses over
# vanilla FO2 + RPU.
OVERLAY_TCS: dict[str, tuple[str, list[str], list[str]]] = {
    "Nevada Mod Extended": (
        r"C:\Nevada Mod (Extended)", ["Patch000.dat", "Patch001.dat"],
        [r"C:\Fallout Nevada (Expansion Version)\master.dat",
         r"C:\Fallout Nevada (Expansion Version)\critter.dat"],
    ),
}

# Sources this project GENERATES (tools/sources.json "derived"). They are not games:
# their lists are the FOC base's entries followed by the new pieces, so the launcher
# mounts the FOC base's own archives (master, critter, the mods_order.txt .dats; never
# the foc layer) underneath and the generated data folder on top. Unlike the TCs there
# is nothing to isolate from FOC's art - the generated folder holds only names nobody
# else has, which is the point. key -> (label, sources.json key, folder to mount)
FOC_ROOT = HERE.parent
GENERATED_OVERLAYS: dict[str, tuple[str, str, Path]] = {
    "Fallout FOnline 2": ("FOnline 2 (new art only, over the FOC base)", "fonline2",
                          FOC_ROOT / "build" / "fonline2_src" / "data"),
}

SWAP_SCRIPT = HERE.parent / "reference" / "gecko" / "build" / "gecko.exe"  # existence check only


def display_name(key: str, root: str) -> str:
    # Only used for the on-screen "Opening gecko on: X" message.
    return {
        "Fallout 2 - vanilla (no RPU)": "Fallout 2 (vanilla GOG, no RPU)",
        "Fallout Sonora": "Fallout Sonora (Extended Release)",
        "Fallout Nevada": "Fallout Nevada (Expansion Version)",
        "Fallout Olympus 2207": "Olympus 2207 (FE)",
        "Fallout Resurrection": "Fallout Resurrection (FE)",
        "Fallout Story of the Jackal": "Fallout: Story of the Jackal",
        "Fallout Yesterday": "Fallout Yesterday (Van Buren)",
        "Nevada Mod Extended": "Nevada Mod (Extended)",
    }.get(key, key)


def source_key(root: Path) -> str:
    """The tools/sources.json key whose path is this install, or "" - passed to
    the launcher so stamps saved in the session get converted to FOC's IDs when
    gecko closes (tools/port_stamp.py). fo2 is FOC's own base: its stamps
    already match, so it gets no key."""
    raw = json.loads((HERE / "sources.json").read_text(encoding="utf-8"))
    want = str(root).rstrip("\\").lower()
    for key, v in raw.items():
        if key.startswith("_") or key == "fo2" or not isinstance(v, dict):
            continue
        if str(v.get("path", "")).rstrip("\\").lower() == want:
            return key
    return ""


def write_launcher(base: str, label: str, root: Path, extra_dats: list[str],
                    base_dats: list[str] = ("master.dat", "critter.dat"),
                    underlay: list[str] = ()) -> None:
    # base_dats defaults to the normal pair; standalone patch-based installs
    # (no master.dat/critter.dat of their own - Nevada Mod Extended is built
    # entirely on Patch000/001.dat) must pass base_dats=[] or gecko is handed
    # two data-path entries that don't exist on disk. Confirmed that broke
    # more than those two entries: gecko reported art/intrface/intrface.lst
    # and art/inven/inven.lst as "missing" even though Patch000.dat genuinely
    # contains both - the bogus master.dat/critter.dat paths ahead of it in
    # the list appear to abort the mount sequence before Patch000.dat's own
    # files are ever read, not just skip the two paths that don't exist.
    #
    # underlay (full paths, not relative to root) is for a genuine OVERLAY
    # mod - one missing engine-level files (color.pal, confirmed for Nevada
    # Mod Extended) because it expects a base game underneath. Mounted FIRST
    # (lowest priority) so the overlay's own content still wins on overlap.
    paths = list(underlay)
    paths += [str(root / d) for d in base_dats]
    for d in extra_dats:
        paths.append(str(root / d))
    paths.append(str(root))  # loose data folder, mounted last among the real install paths

    # " [clean]" suffix is load-bearing: gecko silently drops a mounted
    # folder whose basename matches another mounted folder's basename
    # (reproduced live - 4 of 5 configured paths mounted, the clean override
    # dropped with no log line at all, the game's own broken LST used
    # instead). Must match clean_lst_for_gecko.py's own out_dir naming.
    clean_dir = CLEAN_ROOT / f"{root.name} [clean]"
    if clean_dir.is_dir() and any(clean_dir.rglob("*.lst")):
        paths.append(str(clean_dir))  # highest priority: shadows only the scrubbed LSTs

    ps1_lines = ", ".join(f"'{p}'" for p in paths)
    ps1 = OUT / f"{base}.ps1"
    ps1.write_text(
        f'# Launches gecko on "{label}" only. Generated by tools/build_gecko_browsers.py -\n'
        f"# regenerate there rather than hand-editing.\n"
        f'& "$PSScriptRoot\\_swap_and_launch.ps1" -Name "{label}" -DataPaths @({ps1_lines})'
        f' -Source "{source_key(root)}"\n',
        encoding="utf-8",
    )
    bat = OUT / f"{base}.bat"
    bat.write_text(
        "@echo off\r\n"
        f'powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0{base}.ps1"\r\n',
        encoding="utf-8",
    )


def foc_base_mounts() -> list[str]:
    """The FOC base's archives in load order, lowest priority first - what gecko's
    FOC profile mounts, minus the foc layer and the loose base folders."""
    base = FOC_ROOT / "base"
    paths = [base / "master.dat", base / "critter.dat"]
    order = base / "mods" / "mods_order.txt"
    if order.is_file():
        for raw in order.read_text(encoding="cp1252", errors="replace").splitlines():
            n = raw.strip()
            if n and not n.startswith((";", "#")) and n.lower() != "foc":
                paths.append(base / "mods" / n)
    return [str(p) for p in paths]


def write_overlay_launcher(base: str, label: str, source: str, data: Path) -> None:
    paths = foc_base_mounts() + [str(data)]
    ps1_lines = ", ".join(f"'{p}'" for p in paths)
    (OUT / f"{base}.ps1").write_text(
        f'# Launches gecko on "{label}". Generated by tools/build_gecko_browsers.py -\n'
        f"# regenerate there rather than hand-editing.\n"
        f'& "$PSScriptRoot\\_swap_and_launch.ps1" -Name "{label}" -DataPaths @({ps1_lines})'
        f' -Source "{source}"\n',
        encoding="utf-8",
    )
    (OUT / f"{base}.bat").write_text(
        "@echo off\r\n"
        f'powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0{base}.ps1"\r\n',
        encoding="utf-8",
    )


def rebuild_fallback_art() -> None:
    """Fresh copy of gecko's real bundled fallback art from its SOURCE tree -
    never from build/resources, which has grown far beyond that (see the
    module docstring's WHY _fallback_art/ section)."""
    if FALLBACK_ART_OUT.exists():
        shutil.rmtree(FALLBACK_ART_OUT)
    if not FALLBACK_ART_SRC.is_dir():
        print(f"  note: {FALLBACK_ART_SRC} not found - gecko source tree missing?")
        return
    shutil.copytree(FALLBACK_ART_SRC, FALLBACK_ART_OUT)
    n = sum(1 for _ in FALLBACK_ART_OUT.rglob("*") if _.is_file())
    print(f"  _fallback_art/: {n} file(s) copied from gecko's source resources/art/")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if not SWAP_SCRIPT.is_file():
        print(f"  note: {SWAP_SCRIPT} not found yet - build gecko before using these launchers")
    rebuild_fallback_art()

    made = 0
    for key, root_str, extras, base_dats, underlay in (
        [(k, r, e, ["master.dat", "critter.dat"], []) for k, (r, e) in TCS.items()]
        + [(k, r, e, [], u) for k, (r, e, u) in OVERLAY_TCS.items()]
    ):
        root = Path(root_str)
        if not root.is_dir():
            print(f"  SKIP {key}: {root} not found on this machine")
            continue
        if any(not Path(p).is_file() for p in underlay):
            print(f"  SKIP {key}: its base-game underlay is missing on this machine: {underlay}")
            continue
        # scrub this install's essential LSTs if it hasn't been done yet
        clean_script = OUT / "clean_lst_for_gecko.py"
        result = subprocess.run(
            [sys.executable, str(clean_script), str(root)],
            capture_output=True, text=True,
        )
        for line in result.stdout.splitlines():
            print(f"  {line}")
        write_launcher(key, display_name(key, root_str), root, extras, base_dats, underlay)
        made += 1

    for key, (label, source, data) in GENERATED_OVERLAYS.items():
        if not data.is_dir():
            print(f"  SKIP {key}: {data} not generated yet - run tools/fonline2_source.py build")
            continue
        write_overlay_launcher(key, label, source, data)
        made += 1

    print(f"\n{made} launcher(s) written to {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
