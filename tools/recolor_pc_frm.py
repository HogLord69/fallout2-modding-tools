#!/usr/bin/env python3
"""recolor_pc_frm.py - build hmpcot/hfpcot from the vanilla HMJMPS/HFJMPS
FRMs. Palette-index swap only - nothing moves.

Method (from the flood-fill-from-collar / belt-sentinel idea):

  1. NORMALISE per frame. Rewrite the "13"/zip pixels to fabric (each takes
     the median suit shade around it, so it leaves no patch). Rewrite the belt
     band to a sentinel index - an unbroken divider.

  2. SPLIT. Everything above the belt row is torso/upper-body -> shirt. Below
     it, flood-fill the suit from the collar with the sentinel belt as a dam:
     whatever the fill reaches is shirt (a lowered sleeve connects up to the
     shoulder), the rest is trousers. Fallbacks: belt gone / fill leaks ->
     torso-column split; frame wider than tall -> X-cut for prone.

  3. RECOLOUR. suit blue -> dusty-white shirt ramp / warm brown trouser ramp;
     the distal third of each sleeve -> bare forearm (skin); sentinel -> belt.
"""
from __future__ import annotations

import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import numpy as np
from scipy import ndimage
from foclib import GameIndex
from foclib.dat2 import Dat2

ROOT = Path(__file__).resolve().parent.parent
CRIT_DIR = ROOT / "mod" / "data" / "art" / "critters"

_raw = GameIndex().vfs.read("color.pal")
PAL = np.array([[(_raw[i * 3] << 2) | (_raw[i * 3] >> 4),
                 (_raw[i * 3 + 1] << 2) | (_raw[i * 3 + 1] >> 4),
                 (_raw[i * 3 + 2] << 2) | (_raw[i * 3 + 2] >> 4)]
                for i in range(256)], float)

SUIT = [101, 102, 103, 104, 115, 105, 106, 113, 107, 108, 116, 109, 110, 111]
SUIT_MID = 108
GOLD = list(range(56, 65)) + [79, 80, 81, 82, 83]
EDGE = [72, 73, 74, 75, 87, 88, 89, 90, 91, 93, 94]
TAN = [119, 120, 121, 122, 123, 144, 158, 159, 160, 161, 162, 173]
SENT = 254

SHIRT = [1, 2, 2, 3, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12]   # dusty white
PANTS = [223, 223, 222, 205, 224, 224, 203, 225, 225, 206, 206, 226, 226, 204]
SKIN = [157, 159, 158, 121, 122, 122, 123, 124, 124, 125, 125, 227, 227, 227]
BELT_C = 225

SHIRT_T = {ix: SHIRT[round(k / (len(SUIT) - 1) * (len(SHIRT) - 1))]
           for k, ix in enumerate(SUIT)}
PANTS_T = {ix: PANTS[round(k / (len(SUIT) - 1) * (len(PANTS) - 1))]
           for k, ix in enumerate(SUIT)}
SKIN_T = {ix: SKIN[round(k / (len(SUIT) - 1) * (len(SKIN) - 1))]
          for k, ix in enumerate(SUIT)}
_RANK = {ix: k for k, ix in enumerate(SUIT)}


def normalise(a):
    a = a.copy()
    suit = np.isin(a, SUIT)
    if not suit.any():
        return a, None
    ys, xs = np.where(suit | np.isin(a, GOLD + EDGE))
    y0, y1 = ys.min(), ys.max()
    span = max(y1 - y0, 1)

    gold = np.isin(a, GOLD)
    rows = np.arange(a.shape[0])[:, None]
    band = gold & (rows >= y0 + 0.30 * span) & (rows <= y0 + 0.66 * span)
    belt_row = int(np.argmax(band.sum(axis=1))) if band.any() else None

    logo = np.isin(a, GOLD + EDGE)
    a[logo] = SUIT_MID
    if logo.any():
        pend = list(zip(*np.where(logo)))
        for _ in range(4):
            nxt = []
            for y, x in pend:
                v = [_RANK[a[y + dy, x + dx]]
                     for dy in (-2, -1, 0, 1, 2) for dx in (-2, -1, 0, 1, 2)
                     if 0 <= y + dy < a.shape[0] and 0 <= x + dx < a.shape[1]
                     and a[y + dy, x + dx] in _RANK and not logo[y + dy, x + dx]]
                if v:
                    v.sort(); a[y, x] = SUIT[v[len(v) // 2]]
                else:
                    nxt.append((y, x))
            pend = nxt
            if not pend:
                break

    if belt_row is not None:
        suitish = np.isin(a, SUIT + [SUIT_MID])
        belt = np.zeros_like(suit)
        for y in range(max(belt_row - 1, 0), min(belt_row + 2, a.shape[0])):
            belt[y, gold[y]] = True
            for x in np.where(np.isin(a[y], TAN))[0]:
                if suitish[y, max(x - 4, 0):x].any() and suitish[y, x + 1:x + 5].any():
                    belt[y, x] = True
        belt = ndimage.binary_dilation(belt, np.array([[0, 0, 0], [1, 1, 1],
                                                       [0, 0, 0]]))
        belt &= np.isin(a, SUIT + [SUIT_MID] + GOLD + TAN)
        a[belt] = SENT
    return a, belt_row


def split_shirt(a, belt_row):
    garment = np.isin(a, SUIT + [SENT])
    ys, xs = np.where(garment)
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    span = max(y1 - y0, 1)
    prone = (x1 - x0) > span + 4

    closed = ndimage.binary_closing(garment, np.ones((2, 2)))
    barrier = closed & (a != SENT) & ~ndimage.binary_dilation(a == SENT)
    rows = np.arange(a.shape[0])[:, None]
    seed = np.isin(a, SUIT) & (rows <= y0 + 0.15 * span)
    shirt = ndimage.binary_propagation(seed, mask=barrier) & garment

    if belt_row is not None and not prone:
        shirt = shirt | (garment & (rows <= belt_row) & (a != SENT))

    frac = shirt.sum() / max(garment.sum(), 1)
    if belt_row is None or frac > 0.88 or frac < 0.12 or prone:
        yy, xx = np.indices(a.shape)
        if prone:
            hx = np.where(np.isin(a, TAN).any(axis=0))[0]
            headL = (hx.mean() < (x0 + x1) / 2) if len(hx) else True
            sx = x0 + 0.42 * (x1 - x0)
            shirt = garment & ((xx <= sx) if headL else (xx > sx))
        else:
            sr = belt_row if belt_row is not None else int(y0 + 0.45 * span)
            rx = np.where(garment[sr])[0]
            cx = (rx.min() + rx.max()) / 2 if len(rx) else a.shape[1] / 2
            hw = (max((rx.max() - rx.min()) / 2, 3) if len(rx) else span) * 1.8
            shirt = garment & ((yy <= sr) | (np.abs(xx - cx) > hw))
    return shirt, garment


def recolor_frame(a):
    a, belt_row = normalise(a)
    if not np.isin(a, SUIT).any():
        return a
    shirt, garment = split_shirt(a, belt_row)
    pants = garment & ~shirt

    forearm = np.zeros_like(shirt)
    core = ndimage.binary_dilation(ndimage.binary_erosion(shirt, iterations=2),
                                   iterations=2) & shirt
    if core.sum() > 12 and (shirt & ~core).sum() > 6:
        dist = ndimage.distance_transform_edt(~core)
        forearm = shirt & (dist > 5.0)
        shirt = shirt & ~forearm

    out = a.copy()
    for src in SUIT:
        m = a == src
        out[m & shirt] = SHIRT_T[src]
        out[m & pants] = PANTS_T[src]
        out[m & forearm] = SKIN_T[src]
    out[a == SENT] = BELT_C

    leftover = np.isin(out, GOLD + EDGE + TAN)
    if leftover.any():
        deep = ndimage.binary_erosion(shirt, iterations=1)
        out[leftover & deep] = SHIRT[len(SHIRT) // 2]
        out[leftover & ~deep] = PANTS[len(PANTS) // 2 + 1]
    return out


def process_frm(raw: bytes) -> bytes:
    data = bytearray(raw)
    fpd = struct.unpack_from(">H", data, 8)[0]
    diroff = struct.unpack_from(">6I", data, 0x22)
    end_body = 0x3E + struct.unpack_from(">I", data, 0x3A)[0]
    for d in range(6):
        pos = 0x3E + diroff[d]
        stop = 0x3E + diroff[d + 1] if d < 5 else end_body
        f = 0
        while pos + 12 <= len(data) and pos < stop and f < fpd:
            w, h, size, fx, fy = struct.unpack_from(">HHIhh", data, pos)
            if w == 0 or h == 0 or size == 0 or size > 0x1000000:
                break
            s = pos + 12
            arr = np.frombuffer(bytes(data[s:s + w * h]), np.uint8).reshape(h, w)
            data[s:s + w * h] = recolor_frame(arr).astype(np.uint8).tobytes()
            pos = s + size
            f += 1
    return bytes(data)


def main() -> int:
    dat = Dat2(str(ROOT / "base" / "critter.dat"))
    exts = (".FRM", ".FR0", ".FR1", ".FR2", ".FR3", ".FR4", ".FR5")
    done = 0
    for name in dat.names():
        b = name.split("\\")[-1].upper()
        if not (b.startswith(("HMJMPS", "HFJMPS")) and b.endswith(exts)):
            continue
        dst = ("hmpcot" if b.startswith("HM") else "hfpcot") + b[6:].lower()
        (CRIT_DIR / dst).write_bytes(process_frm(dat.read(name)))
        done += 1
    print(f"recoloured {done} FRM files -> {CRIT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
