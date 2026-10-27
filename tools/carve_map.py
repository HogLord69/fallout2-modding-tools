#!/usr/bin/env python3
"""
carve_map.py - hunt a raw NTFS volume for Fallout 2 .map files that are no
longer in the file system (overwritten / deleted), and save every parseable
hit to build/carve/.

    # MUST run from an elevated (Administrator) PowerShell - raw volume reads:
    python tools/carve_map.py F: [--start GB] [--end GB] [--want-objects 1964]

READ-ONLY. It opens \\\\.\\F: for reading, never writes to the volume, and only
creates files under build/carve/.

WHY IT EXISTS
    2026-09-19: a gecko-saved RWCORE2.MAP (222,452 bytes, 1,964 objects, header
    name still "RWCORE.MAP") was overwritten by map_crop.py. NTFS frees the old
    clusters on truncate and the new data may or may not land on the same ones;
    if it did not, the old file's bytes are still on disk until something else
    reuses them. A .map is easy to carve: it starts with version 20 big-endian
    (00 00 00 14) followed by its own name, and the parser tells us exactly
    where it ends.

WHAT IT DOES
    Streams the volume in 64 MiB chunks, regex-scans each chunk for a map
    header, and for every hit tries MapFile.parse on the following 512 KiB.
    Hits that parse are written to build/carve/<offset>_<name>_<objects>.map
    and compared against the maps currently in the tree so you can ignore the
    live copies. --want-objects highlights the one you are looking for.

    Full scan of a 1 TB volume takes roughly as long as reading it once
    (an hour or two on a hard disk, minutes on NVMe). Use --start/--end (in GB)
    to scan a window first; `fsutil file queryextents <a recently written
    file>` (also elevated) gives the LCN neighbourhood recent writes went to,
    and the lost clusters are usually close to it.
"""

from __future__ import annotations

import argparse
import re
import struct
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foclib import GameIndex, MapFile  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "carve"
CHUNK = 64 * 1024 * 1024
OVERLAP = 64                       # a header is at most 20 bytes; keep more
WINDOW = 512 * 1024                # a Redwell map is ~220-310 KB
HEADER_RE = re.compile(rb"\x00\x00\x00\x14([A-Za-z0-9_\-]{1,12}\.[Mm][Aa][Pp])\x00")


def map_length(data: bytes, proto) -> tuple[int, int] | None:
    """(byte length, object count) if `data` starts with a complete map."""
    try:
        m = MapFile.parse(data, proto)
    except Exception:
        return None
    if not m.objects:
        return None
    p = m.objects[0].off - 8
    try:
        total, n0 = struct.unpack_from(">2i", data, p)
        if total != len(m.objects) or total <= 0 or total > 20000:
            return None
        p += 8
        for _ in range(n0):
            _obj, p = MapFile._read_object(data, p, proto)
        # two remaining elevation counts (0) for a single-level map
        end = p + 8
        if end > len(data):
            return None
        return end, len(m.objects)
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("volume", help="drive letter, e.g. F:")
    ap.add_argument("--start", type=float, default=0.0, help="start offset in GB")
    ap.add_argument("--end", type=float, default=None, help="end offset in GB (default: whole volume)")
    ap.add_argument("--want-objects", type=int, default=1964)
    ap.add_argument("--want-name", default="RWCORE.MAP")
    args = ap.parse_args()

    vol = args.volume.rstrip("\\/")
    if not vol.endswith(":"):
        vol += ":"
    dev = r"\\.\{}".format(vol)

    gi = GameIndex(pristine=False)
    live = {}
    for d in (ROOT / "mod" / "data" / "maps", ROOT / "base" / "mods" / "foc" / "maps"):
        for p in d.glob("*.MAP"):
            live[p.read_bytes()] = p.name
    OUT.mkdir(parents=True, exist_ok=True)

    try:
        f = open(dev, "rb", buffering=0)
    except PermissionError:
        sys.exit(f"cannot open {dev}: run this from an elevated (Administrator) PowerShell")

    # volume size: seek to end is not allowed on raw devices; probe by reading
    start = int(args.start * (1 << 30))
    end = int(args.end * (1 << 30)) if args.end else None
    pos = start - (start % 4096)
    f.seek(pos)
    t0 = time.time()
    seen_hits = set()
    found = []
    carry = b""
    total_read = 0
    print(f"scanning {dev} from {pos / (1 << 30):.1f} GB"
          + (f" to {end / (1 << 30):.1f} GB" if end else " to the end") + " ...")
    while True:
        if end is not None and pos >= end:
            break
        try:
            chunk = f.read(CHUNK)
        except OSError:
            break
        if not chunk:
            break
        buf = carry + chunk
        base = pos - len(carry)
        for hm in HEADER_RE.finditer(buf):
            off = base + hm.start()
            if off in seen_hits:
                continue
            seen_hits.add(off)
            name = hm.group(1).decode("ascii", "replace")
            # read a full window from the hit (may extend past this chunk)
            cur = f.tell()
            f.seek(off)
            window = f.read(WINDOW)
            f.seek(cur)
            info = map_length(window, gi.proto)
            if info is None:
                continue
            length, nobj = info
            data = window[:length]
            tag = live.get(data)
            star = " <== WANTED" if (nobj == args.want_objects and name.upper() == args.want_name.upper()) else ""
            label = f"{off:016x}_{name}_{nobj}obj.map"
            if tag:
                print(f"  hit @ {off / (1 << 30):9.3f} GB  {name:14s} {length:7d} B {nobj:5d} objects  = live {tag}")
            else:
                (OUT / label).write_bytes(data)
                print(f"  hit @ {off / (1 << 30):9.3f} GB  {name:14s} {length:7d} B {nobj:5d} objects  -> build/carve/{label}{star}")
                found.append((off, name, length, nobj))
        carry = buf[-OVERLAP:]
        pos += len(chunk)
        total_read += len(chunk)
        if total_read % (CHUNK * 16) == 0:
            el = time.time() - t0
            rate = total_read / el / (1 << 20) if el else 0
            print(f"  ... {pos / (1 << 30):8.1f} GB  ({rate:.0f} MB/s)", flush=True)
    f.close()
    print(f"done: {len(found)} non-live map(s) carved into {OUT.relative_to(ROOT)} "
          f"in {(time.time() - t0) / 60:.1f} min")
    wanted = [x for x in found if x[3] == args.want_objects]
    if wanted:
        print("WANTED candidates:", wanted)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
