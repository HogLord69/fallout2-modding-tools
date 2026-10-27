#!/usr/bin/env python3
"""
How expensive is it to place a fragment?

Fragments store tile / proto / art NAMES so they survive crossing installs. The
practical question is what fraction of those names already exist in OUR base:
those cost nothing, and the rest have to be ported and allocated first.

Sampled across sources so the answer is per-source, which is what decides where
to shop for a given room.
"""

import collections
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from foclib import TYPE_NAME, GameIndex, parse_lst  # noqa: E402

CORPUS = Path(__file__).resolve().parent.parent.parent / "corpus" / "fragments.jsonl"


def main() -> int:
    gi = GameIndex()
    tiles = {n.lower() for n in parse_lst(gi.vfs.read("art\\tiles\\tiles.lst")) if n}
    art = {}
    for d in ("scenery", "walls", "items", "critters", "misc"):
        try:
            art[d] = {n.lower() for n in parse_lst(gi.vfs.read(f"art\\{d}\\{d}.lst")) if n}
        except FileNotFoundError:
            art[d] = set()
    # A proto FILENAME is "00001417.pro" - the index with an extension. It
    # collides across installs while naming a completely different object, so
    # matching on it is worthless (it reports ~99% and means nothing). The
    # meaningful identity is the proto's ART: match (type, art name) instead.
    from foclib import parse_pro
    proto_art = {}
    for ot in TYPE_NAME:
        names = set()
        lst = gi.proto_lst(ot)
        for i, fn in enumerate(lst):
            if not fn:
                continue
            pid = (ot << 24) | (i + 1)
            pr = gi.proto(pid)
            if pr is None:
                continue
            a = gi.vfs
            an = None
            try:
                d = TYPE_NAME[ot]
                alist = art.get(d)
                # resolve the proto's own fid to an art name via the full list
                al = parse_lst(gi.vfs.read(f"art\{d}\{d}.lst"))
                idx = pr.fid & 0xFFF
                if 0 <= idx < len(al) and al[idx]:
                    an = al[idx].lower()
            except FileNotFoundError:
                pass
            if an:
                names.add(an)
        proto_art[ot] = names

    by_src = collections.defaultdict(lambda: collections.Counter())
    rows = []
    with CORPUS.open(encoding="utf-8") as f:
        for line in f:
            rows.append(line)
    random.seed(7)
    sample = random.sample(rows, min(1200, len(rows)))

    for line in sample:
        fr = json.loads(line)
        s = fr["source"]
        c = by_src[s]
        c["fragments"] += 1
        for n in fr["palette"]:
            c["tiles"] += 1
            if n.lower() in tiles:
                c["tiles_ok"] += 1
        for o in fr["objects"]:
            d = TYPE_NAME.get(o["t"])
            if o["art"]:
                c["art"] += 1
                if d and o["art"].lower() in art.get(d, ()):
                    c["art_ok"] += 1
            if o["proto"]:
                c["protos"] += 1
                if o["art"] and o["art"].lower() in proto_art.get(o["t"], ()):
                    c["protos_ok"] += 1

    print(f"sampled {len(sample)} fragments; resolving names against our base\n")
    print(f"{'source':14s} {'frags':>6s} {'tiles':>16s} {'art':>16s} {'protos(by art)':>16s}")
    for s in sorted(by_src):
        c = by_src[s]
        def pct(a, b):
            return f"{c[a]}/{c[b]} {c[a]/c[b]:.0%}" if c[b] else "-"
        print(f"{s:14s} {c['fragments']:6d} {pct('tiles_ok','tiles'):>16s} "
              f"{pct('art_ok','art'):>16s} {pct('protos_ok','protos'):>16s}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
