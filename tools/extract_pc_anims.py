#!/usr/bin/env python3
"""extract_pc_anims.py - decode the vanilla player-character critter FRMs
(hmjmps = hero male jumpsuit, hfjmps = hero female jumpsuit) out of
base/critter.dat and lay every animation out as a sprite sheet.

One sheet per animation "set" (the 2-letter code at the end of the FRM name,
e.g. HMJMPS**AB** = walk). Layout:

    rows    = the 6 isometric directions  (0 NE, 1 E, 2 SE, 3 SW, 4 W, 5 NW)
    columns = the animation frames, in order

Every cell is the same size across a sheet, and each frame is placed using its
FRM per-frame (x,y) shift accumulated from frame 0, so the sprite is stabilised
exactly the way the engine animates it - the feet stay put, the sheet plays
back cleanly if you flip through the columns.

    python tools/extract_pc_anims.py                 # both sexes -> build/pc_anims/
    python tools/extract_pc_anims.py --sex m --scale 3
    python tools/extract_pc_anims.py --gif           # also write a per-set GIF

The 2-letter code -> animation-name mapping is reversed straight out of the
engine (`_art_get_code` in reference/fallout2-ce/src/art.cc), so the filenames
say what each set actually is (walk, run, punch, fall_back, pistol_fire_single...).
"""
from __future__ import annotations

import argparse
import json
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from PIL import Image
from foclib import GameIndex
from foclib.dat2 import Dat2

ROOT = Path(__file__).resolve().parent.parent
FRX_EXT = (".FRM", ".FR0", ".FR1", ".FR2", ".FR3", ".FR4", ".FR5")
DIR_TAGS = ["NE", "E", "SE", "SW", "W", "NW"]

# ---------------------------------------------------------------- anim naming

# animation.h enum, index -> name (0..64)
ANIM_NAMES = [
    "stand", "walk", "jump_begin", "jump_end", "climb_ladder", "falling",
    "up_stairs_right", "up_stairs_left", "down_stairs_right", "down_stairs_left",
    "magic_hands_ground", "magic_hands_middle", "magic_hands_up", "dodge",
    "hit_from_front", "hit_from_back", "throw_punch", "kick_leg", "throw",
    "running", "fall_back", "fall_front", "bad_landing", "big_hole",
    "charred_body", "chunks_of_flesh", "dancing_autofire", "electrify",
    "sliced_in_half", "burned_to_nothing", "electrified_to_nothing",
    "exploded_to_nothing", "melted_to_nothing", "fire_dance", "fall_back_blood",
    "fall_front_blood", "prone_to_standing", "back_to_standing", "take_out",
    "put_away", "parry", "thrust", "swing", "point", "unpoint", "fire_single",
    "fire_burst", "fire_continuous", "fall_back_sf", "fall_front_sf",
    "bad_landing_sf", "big_hole_sf", "charred_body_sf", "chunks_of_flesh_sf",
    "dancing_autofire_sf", "electrify_sf", "sliced_in_half_sf",
    "burned_to_nothing_sf", "electrified_to_nothing_sf", "exploded_to_nothing_sf",
    "melted_to_nothing_sf", "fire_dance_sf", "fall_back_blood_sf",
    "fall_front_blood_sf", "called_shot_pic",
]
# art.h WEAPON_ANIMATION_* : 0 = none, then 1..10
WEAPON_NAMES = ["none", "knife", "club", "hammer", "spear", "pistol", "smg",
                "shotgun", "laser_rifle", "minigun", "launcher"]


def art_get_code(anim: int, weap: int):
    """Port of _art_get_code(): (anim, weaponType) -> (char7, char8) or None."""
    if weap < 0 or weap >= 11:
        return None
    if 38 <= anim <= 47:                       # TAKE_OUT .. FIRE_CONTINUOUS
        if weap == 0:
            return None
        return chr(ord('d') + weap - 1), chr(ord('c') + anim - 38)
    if anim == 36:
        return 'c', 'h'                        # prone_to_standing
    if anim == 37:
        return 'c', 'j'                        # back_to_standing
    if anim == 64:
        return 'n', 'a'                        # called_shot_pic
    if anim >= 48:                             # single-frame death anims
        return 'r', chr(ord('a') + anim - 48)
    if anim >= 20:                             # knockdown / death anims
        return 'b', chr(ord('a') + anim - 20)
    if anim == 18:                             # throw
        if weap == 1:
            return 'd', 'm'
        if weap == 4:
            return 'g', 'm'
        return 'a', 's'
    if anim == 13:                             # dodge
        if weap <= 0:
            return 'a', 'n'
        return chr(ord('d') + weap - 1), 'e'
    c8 = chr(ord('a') + anim)
    if anim <= 1 and weap > 0:                 # stand/walk with a weapon
        return chr(ord('d') + weap - 1), c8
    return 'a', c8


def build_code_labels() -> dict[str, str]:
    """code -> human label, by running every (anim, weapon) through art_get_code."""
    hits: dict[str, list[tuple[int, int]]] = {}
    for weap in range(11):
        for anim in range(65):
            c = art_get_code(anim, weap)
            if c:
                hits.setdefault(c[0] + c[1], []).append((anim, weap))
    labels = {}
    for code, combos in hits.items():
        weapon_family = code[0] in "defghijklm"
        parts = []
        for anim, weap in combos:
            name = ANIM_NAMES[anim]
            if weapon_family and weap:
                name = f"{WEAPON_NAMES[weap]}_{name}"
            if name not in parts:
                parts.append(name)
        labels[code] = "__".join(parts)
    return labels


CODE_LABELS = build_code_labels()

# ---------------------------------------------------------------- FRM decode


def load_palette(gi: GameIndex) -> np.ndarray:
    raw = gi.vfs.read("color.pal")
    pal = np.zeros((256, 4), np.uint8)
    for i in range(256):
        r, g, b = raw[i * 3], raw[i * 3 + 1], raw[i * 3 + 2]
        pal[i] = (min(255, (r << 2) | (r >> 4)), min(255, (g << 2) | (g >> 4)),
                  min(255, (b << 2) | (b >> 4)), 255)
    pal[0] = (0, 0, 0, 0)                      # index 0 = transparent
    return pal


class Frame:
    __slots__ = ("img", "sx", "sy", "w", "h")

    def __init__(self, img, sx, sy):
        self.img = img
        self.sx = sx
        self.sy = sy
        self.w, self.h = img.size


def _decode_block(data: bytes, pos: int, count: int, pal: np.ndarray):
    """Read `count` sequential frame records starting at absolute offset pos."""
    frames = []
    for _ in range(count):
        if pos + 12 > len(data):
            break
        w, h, size, sx, sy = struct.unpack_from(">HHIhh", data, pos)
        if w == 0 or h == 0 or size == 0 or size > 0x2000000:
            break
        s = pos + 12
        raw = np.frombuffer(data, np.uint8, count=w * h, offset=s)
        if raw.size < w * h:
            break
        rgba = pal[raw].reshape(h, w, 4)
        frames.append(Frame(Image.fromarray(rgba, "RGBA"), sx, sy))
        pos = s + size
    return frames


def decode_frm_all_dirs(data: bytes, pal: np.ndarray):
    """A .FRM file: fpd frames for each of the (up to 6) directions it holds."""
    fpd = struct.unpack_from(">H", data, 0x08)[0] or 1
    offs = struct.unpack_from(">6I", data, 0x22)
    dirs: dict[int, list[Frame]] = {}
    for d in range(6):
        if d > 0 and offs[d] == 0 and offs[0] == 0:
            break                             # single-direction / portrait FRM
        base = 0x3E + offs[d]
        blk = _decode_block(data, base, fpd, pal)
        if blk:
            dirs[d] = blk
    return dirs, fpd


def decode_frx(data: bytes, direction: int, pal: np.ndarray):
    """A .FR0-.FR5 file: fpd frames for the single direction in its extension."""
    fpd = struct.unpack_from(">H", data, 0x08)[0] or 1
    offs = struct.unpack_from(">6I", data, 0x22)
    base = 0x3E + (offs[0] if offs[0] and 0x3E + offs[0] + 12 <= len(data) else 0)
    return {direction: _decode_block(data, base, fpd, pal)}, fpd

# ---------------------------------------------------------------- sheet build


def compose_sheet(dirs: dict[int, list[Frame]], scale: int, anchor: str = "frame",
                  pad: int = 2):
    """dirs[d] = [Frame,...]; rows are directions, columns are frames.

    anchor="frame": each frame centred on its own feet anchor (compact sheet).
    anchor="world": frame shifts accumulated from frame 0, so the sprite tracks
                    the character's actual movement across the animation.
    Either way the anchor point (centre of the bottom edge = the feet) lands at
    the same spot in every cell.
    """
    ncols = max((len(v) for v in dirs.values()), default=0)
    if ncols == 0:
        return None, {}

    # anchor-space bbox of every frame, across every direction
    minx = miny = 10 ** 9
    maxx = maxy = -(10 ** 9)
    placed: dict[int, list[tuple[Frame, int, int, int, int]]] = {}
    for d, frames in dirs.items():
        ax = ay = 0
        row = []
        for fr in frames:
            if anchor == "world":
                ax += fr.sx
                ay += fr.sy
            left = ax - fr.w // 2
            top = ay - fr.h
            row.append((fr, left, top, ax, ay))
            minx, miny = min(minx, left), min(miny, top)
            maxx, maxy = max(maxx, left + fr.w), max(maxy, top + fr.h)
        placed[d] = row

    cell_w = (maxx - minx) + pad * 2
    cell_h = (maxy - miny) + pad * 2
    sheet = Image.new("RGBA", (cell_w * ncols * scale, cell_h * 6 * scale),
                      (0, 0, 0, 0))

    for d in range(6):
        for c, (fr, left, top, ax, ay) in enumerate(placed.get(d, [])):
            x = (c * cell_w + (left - minx) + pad)
            y = (d * cell_h + (top - miny) + pad)
            im = fr.img
            if scale != 1:
                im = im.resize((fr.w * scale, fr.h * scale), Image.NEAREST)
            sheet.alpha_composite(im, (x * scale, y * scale))

    meta = {
        "cols": ncols, "rows": 6, "scale": scale, "anchor": anchor,
        "cell_w": cell_w, "cell_h": cell_h,
        "dirs_present": sorted(dirs),
        "frames_per_dir": {d: len(v) for d, v in dirs.items()},
    }
    return sheet, meta


def make_gif(dirs, scale):
    ncols = max((len(v) for v in dirs.values()), default=0)
    if not ncols:
        return None
    # one strip of all six directions, animated across frames
    per = []
    minx = miny = 10 ** 9
    maxx = maxy = -(10 ** 9)
    walk = {}
    for d, frames in dirs.items():
        ax = ay = 0
        row = []
        for fr in frames:
            ax += fr.sx
            ay += fr.sy
            row.append((fr, ax - fr.w // 2, ay - fr.h))
            minx, miny = min(minx, ax - fr.w // 2), min(miny, ay - fr.h)
            maxx, maxy = max(maxx, ax - fr.w // 2 + fr.w), max(maxy, ay - fr.h + fr.h)
        walk[d] = row
    cw, ch = (maxx - minx) + 4, (maxy - miny) + 4
    for c in range(ncols):
        canvas = Image.new("RGBA", (cw * 6, ch), (0, 0, 0, 0))
        for d in range(6):
            row = walk.get(d, [])
            if not row:
                continue
            fr, l, t = row[min(c, len(row) - 1)]
            canvas.alpha_composite(fr.img, (d * cw + (l - minx) + 2, (t - miny) + 2))
        if scale != 1:
            canvas = canvas.resize((canvas.width * scale, canvas.height * scale),
                                   Image.NEAREST)
        bg = Image.new("RGBA", canvas.size, (30, 30, 36, 255))
        bg.alpha_composite(canvas)
        per.append(bg.convert("P", palette=Image.ADAPTIVE))
    return per

# ---------------------------------------------------------------- driver


def group_files(dat: Dat2, prefix: str):
    """{code: {'.FRM': name} or {0:name,...5:name}} for one hmjmps/hfjmps set."""
    groups: dict[str, dict] = {}
    for name in dat.names():
        b = name.split("\\")[-1].upper()
        if not b.startswith(prefix):
            continue
        stem, _, ext = b.rpartition(".")
        ext = "." + ext
        if ext not in FRX_EXT or len(stem) < 8:
            continue
        code = stem[6:8].lower()
        g = groups.setdefault(code, {})
        if ext == ".FRM":
            g["frm"] = name
        else:
            g[int(ext[-1])] = name
    return groups


def run_sex(dat: Dat2, pal, prefix: str, out_dir: Path, scale: int, want_gif: bool,
            anchor: str = "frame"):
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for code, g in sorted(group_files(dat, prefix).items()):
        if "frm" in g:
            dirs, fpd = decode_frm_all_dirs(dat.read(g["frm"]), pal)
            src = [g["frm"].split("\\")[-1]]
        else:
            dirs, fpd, src = {}, 1, []
            for d in range(6):
                if d in g:
                    dd, fpd = decode_frx(dat.read(g[d]), d, pal)
                    dirs.update(dd)
                    src.append(g[d].split("\\")[-1])
        if not dirs:
            print(f"  {code}: no frames, skipped")
            continue
        sheet, meta = compose_sheet(dirs, scale, anchor)
        label = CODE_LABELS.get(code, "unknown")
        base = f"{prefix.lower()}_{code}_{label}"
        sheet.save(out_dir / f"{base}.png")
        meta.update(code=code, label=label, sources=src, fps=fpd_fps(dat, g))
        (out_dir / f"{base}.json").write_text(json.dumps(meta, indent=2))
        row = f"  {code}  {label:<34} {meta['cols']}f x {len(meta['dirs_present'])}dir"
        if want_gif:
            frames = make_gif(dirs, max(scale, 2))
            if frames:
                fps = meta["fps"] or 8
                frames[0].save(out_dir / f"{base}.gif", save_all=True,
                               append_images=frames[1:], loop=0,
                               duration=int(1000 / fps), disposal=2, transparency=0)
                row += "  +gif"
        print(row)
        manifest.append(meta)
    (out_dir / "_manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"  -> {len(manifest)} sheets in {out_dir}")


def fpd_fps(dat: Dat2, g: dict) -> int:
    name = g.get("frm") or next(iter(v for k, v in g.items() if isinstance(k, int)))
    return struct.unpack_from(">H", dat.read(name), 0x04)[0]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sex", choices=["m", "f", "both"], default="both")
    ap.add_argument("--scale", type=int, default=2, help="nearest-neighbour zoom (default 2)")
    ap.add_argument("--anchor", choices=["frame", "world"], default="frame",
                    help="frame: each frame on its own feet anchor (compact); "
                         "world: accumulate FRM shifts so the sprite tracks movement")
    ap.add_argument("--gif", action="store_true", help="also emit a per-set animated GIF")
    ap.add_argument("--out", default=str(ROOT / "build" / "pc_anims"))
    ap.add_argument("--dat", default=str(ROOT / "base" / "critter.dat"))
    args = ap.parse_args()

    gi = GameIndex()
    pal = load_palette(gi)
    dat = Dat2(args.dat)
    out = Path(args.out)

    targets = []
    if args.sex in ("m", "both"):
        targets.append(("HMJMPS", out / "male"))
    if args.sex in ("f", "both"):
        targets.append(("HFJMPS", out / "female"))

    for prefix, od in targets:
        print(f"{prefix} -> {od}")
        run_sex(dat, pal, prefix, od, args.scale, args.gif, args.anchor)
    return 0


if __name__ == "__main__":
    sys.exit(main())
