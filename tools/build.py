#!/usr/bin/env python3
"""
build.py - compile every project .ssl to .int.

    python tools/build.py [--clean] [--verbose] [--jobs N] [--file PATH]

Sources live in scripts_src/foc/ (mirroring RPU's layout, so headers/ and
sfall/ are siblings and relative includes just work). Output goes to
build/scripts/.

Fails loudly: any compile error is reported with its full sslc output and the
script exits non-zero. Nothing downstream should ever run on a partial build.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SSLC = ROOT / "tools" / "sslc" / "compile.exe"
SRC = ROOT / "scripts_src" / "foc"
HEADERS = ROOT / "scripts_src" / "headers"
SFALL_HEADERS = ROOT / "scripts_src" / "sfall"
OUT = ROOT / "build" / "scripts"

# -p is MANDATORY: without it sslc silently ignores every #define and you get
# "Undefined symbol" errors that look like header problems. See docs/TOOLCHAIN.md.
SSLC_FLAGS = ["-q", "-l", "-n", "-p", "-O1"]


def newest_header_mtime() -> float:
    """Newest header any script can include - FOC's own (foc_ids.h, foc_rw.h,
    rw_*.h beside the .ssl files) as well as the base and sfall ones."""
    newest = 0.0
    for d in (HEADERS, SFALL_HEADERS, SRC):
        if d.is_dir():
            for h in d.glob("*.h"):
                newest = max(newest, h.stat().st_mtime)
    return newest


def needs_rebuild(src: Path, dst: Path, header_mtime: float) -> bool:
    if not dst.exists():
        return True
    d = dst.stat().st_mtime
    return d < src.stat().st_mtime or d < header_mtime


def lint(src: Path) -> list[str]:
    """Cheap checks that catch the mistakes sslc reports confusingly."""
    import re

    problems = []
    text = src.read_text(encoding="cp1252", errors="replace")

    # command.h's macros (mstr, Reply, display_mstr, NOption...) all expand NAME.
    # Including it before NAME is defined loses every one of them, and sslc then
    # reports "Unknown name identifier display_mstr" at the USE site, pointing
    # nowhere near the real cause. RPU's own scripts always order it
    # define.h -> #define NAME -> command.h.
    m_cmd = re.search(r'^\s*#include\s+"(?:\.\./headers/)?command\.h"', text, re.M)
    m_name = re.search(r"^\s*#define\s+NAME\b", text, re.M)
    if m_cmd:
        if not m_name:
            problems.append(
                "includes command.h but never defines NAME - every message macro "
                "(mstr/Reply/display_mstr/NOption) will expand to nothing"
            )
        elif m_name.start() > m_cmd.start():
            problems.append(
                "defines NAME after including command.h - swap them, or the "
                "message macros expand with an empty NAME"
            )

    if "#define SCRIPT_REALNAME" not in text:
        problems.append(
            "missing `#define SCRIPT_REALNAME \"<name>\"` before the includes - "
            "define.h needs it via ndebug()/upu.h, and sslc reports the failure "
            "against upu.h:17 instead of this file"
        )
    else:
        # the value should match the filename, or debug output lies about origin
        m = re.search(r'#define\s+SCRIPT_REALNAME\s+"([^"]*)"', text)
        if m and m.group(1).lower() != src.stem.lower():
            problems.append(
                f'SCRIPT_REALNAME is "{m.group(1)}" but the file is {src.name} - '
                f"debug messages will name the wrong script"
            )
    return problems


def compile_one(src: Path, header_mtime: float, force: bool):
    dst = OUT / (src.stem + ".int")
    dst.parent.mkdir(parents=True, exist_ok=True)

    problems = lint(src)
    if problems:
        return src, "lint", "\n".join(f"    {p}" for p in problems), 0.0

    if not force and not needs_rebuild(src, dst, header_mtime):
        return src, "skip", "", 0.0

    t0 = time.time()
    proc = subprocess.run(
        [str(SSLC), *SSLC_FLAGS, src.name, "-o", str(dst)],
        cwd=str(src.parent),
        capture_output=True,
        text=True,
        encoding="cp1252",
        errors="replace",
    )
    dt = time.time() - t0
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        # sslc can leave a stale/partial .int behind; don't let it be used
        if dst.exists():
            dst.unlink()
        return src, "fail", out.strip(), dt
    return src, "ok", out.strip(), dt


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--clean", action="store_true", help="wipe build/scripts first")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--jobs", type=int, default=min(8, (os.cpu_count() or 4)))
    ap.add_argument("--file", type=Path, help="compile just this one .ssl")
    args = ap.parse_args()

    if not SSLC.exists():
        sys.exit(f"sslc not found at {SSLC}")
    if not HEADERS.is_dir():
        sys.exit(f"headers not found at {HEADERS}")

    if args.clean and OUT.exists():
        shutil.rmtree(OUT)
        print(f"cleaned {OUT.relative_to(ROOT)}")

    OUT.mkdir(parents=True, exist_ok=True)

    if args.file:
        sources = [args.file.resolve()]
    else:
        sources = sorted(SRC.rglob("*.ssl")) if SRC.is_dir() else []

    if not sources:
        print(f"no .ssl found under {SRC.relative_to(ROOT)} - nothing to do")
        return 0

    hm = newest_header_mtime()
    results = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as ex:
        futs = [ex.submit(compile_one, s, hm, bool(args.clean or args.file))
                for s in sources]
        for f in concurrent.futures.as_completed(futs):
            results.append(f.result())

    results.sort(key=lambda r: r[0].name.lower())
    built = skipped = 0
    failures = []
    for src, status, out, dt in results:
        rel = src.relative_to(ROOT)
        if status == "ok":
            built += 1
            if args.verbose:
                print(f"  built   {rel}  ({dt:.2f}s)")
        elif status == "skip":
            skipped += 1
            if args.verbose:
                print(f"  skip    {rel}  (up to date)")
        else:
            failures.append((rel, status, out))

    print(f"\nbuilt {built}, up-to-date {skipped}, failed {len(failures)}"
          f"  ->  {OUT.relative_to(ROOT)}")

    if failures:
        print("\n" + "=" * 70)
        for rel, status, out in failures:
            head = "LINT" if status == "lint" else "COMPILE ERROR"
            print(f"{head}: {rel}")
            print(out)
            print("-" * 70)
        print(f"BUILD FAILED - {len(failures)} script(s) did not compile.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
