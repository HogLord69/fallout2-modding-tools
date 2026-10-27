#!/usr/bin/env python3
"""
mirror_scenery.py - add a left-right mirrored copy of a scenery object as a
new FOC piece: its own art and its own proto, the original left as it is.

    python tools/mirror_scenery.py 0x02000664 encl40m.frm --preview build/m.png
    python tools/mirror_scenery.py 0x02000664 encl40m.frm --write

The art is the source proto's current art (the mod's copy when there is one,
so the wooden judge's bench mirrors as wood), flipped: every frame's pixel
rows reversed, and the frame x shift and the header's x offsets negated so
the flipped sprite keeps its foot on the same hex. The proto is a byte copy
of the source with its PID and FID repointed. Both are appended to the ID
registry (mod/ids/art_scenery.txt, proto_scenery.txt), where '#' lines take
no index, and to mod/ids/keep_protos.txt so tools/repack_art.py gives the art
a slot below the engine's 4096 cap. Afterwards run gen_ids.py, deploy.py,
repack_art.py and validate.py.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foclib import GameIndex  # noqa: E402
from ids import FOC_START, check_art_name  # noqa: E402
from replace_pc_from_ref import decode_frm, encode_frm  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
IDS = ROOT / "mod" / "ids"
ART = ROOT / "mod" / "data" / "art" / "scenery"
PROTO = ROOT / "mod" / "data" / "proto" / "scenery"


def next_index(path: Path, start: int) -> int:
    return start + sum(1 for line in path.read_text().splitlines() if not line.startswith("#"))


def mirror(data: bytes) -> bytes:
    meta = decode_frm(data)
    meta["xo"] = [-v for v in meta["xo"]]
    out = {}
    for d, row in meta["frames"].items():
        out[d] = []
        for f in row:
            px = np.frombuffer(f.px, np.uint8).reshape(f.h, f.w)[:, ::-1].tobytes()
            out[d].append((f.w, f.h, -f.sx, f.sy, px))
    return encode_frm(meta, out, split=len(out) == 1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("pid", type=lambda s: int(s, 0))
    ap.add_argument("art_name")
    ap.add_argument("--preview", type=Path)
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    name = args.art_name.lower()
    check_art_name("scenery", name)
    if (ART / name).exists() or name in (IDS / "art_scenery.txt").read_text().lower().split():
        sys.exit(f"{name} already exists")
    gi = GameIndex(pristine=False)
    pr = gi.proto(args.pid)
    if pr is None or (args.pid >> 24) != 2:
        sys.exit(f"no scenery proto 0x{args.pid:08X}")
    from foclib import parse_lst
    lst = parse_lst(gi.vfs.read("art\\scenery\\scenery.lst"))
    art_src = lst[pr.fid & 0xFFFFFF]
    data = gi.vfs.read("art\\scenery\\" + art_src)
    flipped = mirror(data)
    if len(flipped) != len(data):
        sys.exit(f"size changed ({len(data)} -> {len(flipped)}); not writing")

    art_idx = next_index(IDS / "art_scenery.txt", FOC_START["art_scenery"] - 1)   # art is 0-based (port.py cmd_art)
    pid_idx = next_index(IDS / "proto_scenery.txt", FOC_START["proto_scenery"])
    proto_bytes = bytearray(gi.vfs.read(gi.proto_path(args.pid)))
    struct.pack_into(">I", proto_bytes, 0, 0x02000000 | pid_idx)
    struct.pack_into(">I", proto_bytes, 8, 0x02000000 | art_idx)
    proto_file = f"{pid_idx:08d}.pro"
    print(f"{art_src} -> {name} (art {art_idx}); proto 0x{args.pid:08X} -> 0x{0x02000000 | pid_idx:08X} ({proto_file})")

    if args.preview:
        from PIL import Image
        from replace_pc_from_ref import load_8bit_palette
        pal = np.array(load_8bit_palette(gi), dtype=np.uint8)
        f = decode_frm(flipped)["frames"][0][0]
        idx = np.frombuffer(f.px, np.uint8).reshape(f.h, f.w)
        im = Image.fromarray(np.dstack([pal[idx], np.where(idx > 0, 255, 0).astype(np.uint8)]), "RGBA")
        im.resize((im.width * 5, im.height * 5), Image.NEAREST).save(args.preview)
        print(f"preview {args.preview}")
    if args.write:
        if (PROTO / proto_file).exists():
            sys.exit(f"{proto_file} already exists")
        (ART / name).write_bytes(flipped)
        (PROTO / proto_file).write_bytes(bytes(proto_bytes))
        with open(IDS / "art_scenery.txt", "a", newline="\r\n") as fh:     # the registry is CRLF
            fh.write(name + "\n")
        with open(IDS / "proto_scenery.txt", "a", newline="\r\n") as fh:
            fh.write(proto_file + "\n")
        with open(IDS / "keep_protos.txt", "a", newline="\r\n") as fh:   # keep its art under the cap
            fh.write(f"0x{0x02000000 | pid_idx:08X}  # {name}, mirrored from 0x{args.pid:08X}\n")
        print("written; now run tools/gen_ids.py, deploy.py, repack_art.py, validate.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
