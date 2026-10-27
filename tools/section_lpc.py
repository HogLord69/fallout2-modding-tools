#!/usr/bin/env python3
"""
section_lpc.py - Split the Universal LPC Spritesheet into per-animation PNGs.

Input:  a single PNG containing the full LPC sheet (3933x9128 typical).
Output: one PNG per magenta-bordered animation group, named
        <out_dir>/anim_<NN>.png in raster order (top-to-bottom, left-to-right).

Detection strategy:
    The viewer renders each animation as a magenta-bordered rectangle on a
    dark-purple background. Borders are exactly RGB(255,0,255). For each
    pair of consecutive horizontal border lines we get a horizontal "strip"
    of the sheet; inside that strip we look for vertical border lines that
    divide the strip into individual group boxes. The intersection of a
    horizontal strip and a vertical strip is one group.

    Because viewer fonts use the same magenta color as borders, label text
    creates short magenta runs that we filter out by minimum-length
    thresholds.

Usage:
    python tools/section_lpc.py <input.png> <out_dir> [--prefix anim_]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
from PIL import Image


# Tunables (matched against the canonical LPC sheet)
H_MIN_LEN = 500   # horizontal border min length in px (filters label noise)
V_MIN_LEN = 500   # vertical border min length in px
MAGENTA = (255, 0, 255)
MIN_BOX_AREA = 50_000   # skip boxes smaller than this (filters label-only artifacts)


def longest_run(row: np.ndarray) -> tuple[int, int]:
    """Return (start_x, length) of the longest contiguous True run in row."""
    best_start, best_len = -1, 0
    cur_start, cur_len = -1, 0
    for x, v in enumerate(row):
        if v:
            if cur_start == -1:
                cur_start = x
                cur_len = 1
            else:
                cur_len += 1
        else:
            if cur_len > best_len:
                best_start, best_len = cur_start, cur_len
            cur_start = -1
            cur_len = 0
    if cur_len > best_len:
        best_start, best_len = cur_start, cur_len
    return best_start, best_len


def find_horizontal_borders(mag: np.ndarray, min_len: int) -> list[tuple[int, int, int]]:
    """Return list of (y, x_start, x_end) for horizontal border lines."""
    H, _ = mag.shape
    out = []
    for y in range(H):
        s, l = longest_run(mag[y])
        if l >= min_len:
            out.append((y, s, s + l))
    return out


def find_vertical_borders(mag: np.ndarray, min_len: int) -> list[tuple[int, int, int]]:
    """Return list of (x, y_start, y_end) for vertical border lines."""
    _, W = mag.shape
    out = []
    for x in range(W):
        col = mag[:, x]
        s, l = longest_run(col)
        if l >= min_len:
            out.append((x, s, s + l))
    return out


def cluster_lines(lines: list[tuple[int, int, int]], axis: str,
                  max_gap: int = 6) -> list[tuple[int, int, int, int]]:
    """Coalesce consecutive border lines (within max_gap px) into single
    rectangle-defining ranges. Returns (axis_pos, start, end, length).
    For horizontal borders, axis_pos is y; for vertical, axis_pos is x."""
    if not lines:
        return []
    out = []
    cur_axis = lines[0][0]
    cur_starts = [lines[0][1]]
    cur_ends = [lines[0][2]]
    for pos, s, e in lines[1:]:
        if pos - cur_axis <= max_gap:
            cur_axis = pos
            cur_starts.append(s)
            cur_ends.append(e)
        else:
            start = min(cur_starts)
            end = max(cur_ends)
            out.append((cur_axis, start, end, end - start))
            cur_axis = pos
            cur_starts = [s]
            cur_ends = [e]
    start = min(cur_starts)
    end = max(cur_ends)
    out.append((cur_axis, start, end, end - start))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("input", type=Path)
    ap.add_argument("out_dir", type=Path)
    ap.add_argument("--prefix", default="anim_")
    args = ap.parse_args()

    img = Image.open(args.input).convert("RGB")
    arr = np.array(img)
    H, W = arr.shape[:2]
    r, g, b = arr[:, :, 0], arr[:, :, 1], arr[:, :, 2]
    mag = (r == MAGENTA[0]) & (g == MAGENTA[1]) & (b == MAGENTA[2])

    h_lines = find_horizontal_borders(mag, H_MIN_LEN)
    v_lines = find_vertical_borders(mag, V_MIN_LEN)
    print(f"Found {len(h_lines)} horizontal border runs, "
          f"{len(v_lines)} vertical border runs", file=sys.stderr)

    # Coalesce into single border segments
    h_borders = cluster_lines(h_lines, "h")
    v_borders = cluster_lines(v_lines, "v")
    print(f"After coalescing: {len(h_borders)} horizontal segments, "
          f"{len(v_borders)} vertical segments", file=sys.stderr)

    # Build horizontal strips: ranges between consecutive horizontal borders.
    # Sort borders by y, include implicit edges at y=0 and y=H.
    h_borders.sort()
    h_y = [0] + [b[0] for b in h_borders] + [H]
    # For each horizontal strip, find vertical borders that fall inside it.
    v_borders.sort()

    # A group = (x0, y0, x1, y1) where:
    #   y0, y1 = top and bottom of a horizontal strip
    #   x0, x1 = left and right of a vertical strip
    args.out_dir.mkdir(parents=True, exist_ok=True)
    saved = 0
    manifest = []

    for i in range(len(h_y) - 1):
        y0, y1 = h_y[i], h_y[i + 1]
        if y1 - y0 < 50:  # skip very thin strips
            continue

        # Find vertical borders that intersect this horizontal strip
        strip_vs = []
        for vx, vy0, vy1, vlen in v_borders:
            # Does this vertical border cross through the strip?
            if vy0 <= y0 + 5 and vy1 >= y1 - 5:
                strip_vs.append(vx)
            elif vy0 < y1 and vy1 > y0:
                # partial overlap - skip to be safe
                pass

        # Add implicit left/right edges
        x_edges = [0] + strip_vs + [W]

        for j in range(len(x_edges) - 1):
            x0, x1 = x_edges[j], x_edges[j + 1]
            if x1 - x0 < 50:
                continue
            area = (x1 - x0) * (y1 - y0)
            if area < MIN_BOX_AREA:
                continue
            # Crop with a 2-pixel margin to keep the border
            crop_x0 = max(0, x0 - 1)
            crop_y0 = max(0, y0 - 1)
            crop_x1 = min(W, x1 + 1)
            crop_y1 = min(H, y1 + 1)
            crop = img.crop((crop_x0, crop_y0, crop_x1, crop_y1))
            out_name = f"{args.prefix}{saved:02d}.png"
            crop.save(args.out_dir / out_name)
            manifest.append((out_name, crop_x0, crop_y0, crop_x1, crop_y1,
                             crop_x1 - crop_x0, crop_y1 - crop_y0))
            saved += 1

    # Write manifest
    (args.out_dir / "_manifest.txt").write_text(
        "name\tx0\ty0\tx1\ty1\tw\th\n" +
        "\n".join(f"{n}\t{x0}\t{y0}\t{x1}\t{y1}\t{w}\t{h}"
                  for n, x0, y0, x1, y1, w, h in manifest) + "\n",
        encoding="utf-8"
    )

    print(f"Saved {saved} groups to {args.out_dir}", file=sys.stderr)
    print(f"Manifest at {args.out_dir / '_manifest.txt'}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
