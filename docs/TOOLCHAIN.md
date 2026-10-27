# Toolchain

Everything here was installed and verified on 2026-08-26. Paths are absolute
because this project's tools are invoked from several working directories.

Project root: `F:\FOCMod`

---

## Summary

| Tool | Path | Version | Status |
|---|---|---|---|
| sslc (compiler) | `tools\sslc\compile.exe` | sfall edition **4.5.1**, CI build 2026-08-17 | ✅ verified |
| int2ssl (decompiler) | `tools\int2ssl\int2ssl.exe` | **8.4.9** (sfall edition) | ✅ built from source, verified |
| dat3 (DAT tool) | `tools\dat\dat3.exe` | BGforge **v0.10.1** | ✅ verified |
| dat2 (DAT tool) | `tools\dat\dat2.exe` | TeamX **v2.33b** | ✅ present, unused so far |
| Mapper2 | *(not copied — see below)* | 2002 build | ⚠️ external |
| fallout2-ce | `tools\fallout2-ce\fallout2-ce.exe` | v1.3.0 | ❌ **cannot run our base** |
| MinGW-w64 (g++) | `tools\w64devkit\bin\g++.exe` | GCC **16.2.0** | ✅ verified |

Binary hashes (SHA-256):

```
fd070cc7bfa59dd307c4c79381ee7168da4bfc9e6fc90291227ebc9de0f2fe00  tools/sslc/compile.exe
977c01a5d8d763a34dca1debe3d40f8a0ee341e2714689f9281d5fa294e6e420  tools/sslc/parser.dll
4e8300e20f4a18e00943bd380462749a9be764ad5bd0dc8ce19ef1d9d4ba8d48  tools/sslc/sslc-debug.exe
e84e61d929b6c71f5330cae093df930508ab9c09df648373dab7cfbac30db019  tools/int2ssl/int2ssl.exe
6329df674b32f173c8d50b4e42c538dc90928f262cf1bf4b0f0027f989b8c52f  tools/dat/dat2.exe
0bbcfbb5e2b99ff24822b138e71e6af683bb4d11862a2e2feed0b084c3d1444c  tools/dat/dat3.exe
fbc59df6a4eef2c516b56538db3eb16131efc9ee77d8616faf8328f36979ea01  tools/fallout2-ce/fallout2-ce.exe
```

`dat3.exe` was checked against upstream's published `SHA256SUMS` and matched.

---

## sslc — the script compiler

Downloaded from `sfall-team/sslc`, release tag `2026-08-17-13-40-20`
(`compile.exe`, `parser.dll`, `sslc-debug.exe`). `parser.dll` must sit next to
`compile.exe`.

### Invocation

```
F:\FOCMod\tools\sslc\compile.exe -q -l -n -p -O1 <file>.ssl -o <out>.int
```

| Flag | Why |
|---|---|
| `-p` | **Mandatory.** Runs the mcpp preprocessor. |
| `-q` | Don't block waiting for keypress on error. Required for scripted builds. |
| `-l` | Suppress the logo banner. |
| `-n` | Suppress warnings (mcpp emits noisy but harmless macro-redefinition notes for RPU headers). |
| `-O1` | Default optimisation: strip unreferenced vars/procs. |

### ⚠️ Gotcha 1 — `-p` is not optional

Without `-p`, sslc **silently ignores `#define`** and every macro becomes
`Undefined symbol <NAME> in factor` at the semantic stage. It does *not* warn
that preprocessing was skipped. `#include` still partly works without `-p`,
which makes the failure look like a header problem when it isn't.

Verified: `#define GVAR_X 900` + `global_var(GVAR_X)` fails without `-p`,
compiles with it.

### ⚠️ Gotcha 2 — every script must define `SCRIPT_REALNAME`

`define.h` defines `ndebug(msg)` in terms of `SCRIPT_REALNAME`, and `upu.h`
(pulled in by `define.h`) uses it at file scope. sslc does **not** provide it —
grepping the sslc source for `SCRIPT_REALNAME` returns nothing. It is a
per-script convention from RPU/UPU.

Every `.ssl` in this project must therefore begin:

```c
#define SCRIPT_REALNAME "myscript"

#include "../headers/define.h"
```

Omitting it fails with `Undefined symbol SCRIPT_REALNAME in factor` reported
against `upu.h:17`, which points at the wrong file entirely.

### Exit codes

`0` on success, non-zero on any error. Verified with a deliberate bad script
(`no_such_function(...)` → exit 1). Safe to use as a build gate.

---

## Header layout

```
scripts_src\
  headers\    163 headers — RPU upstream (scripts_src/headers)
  sfall\       11 headers — sfall repo (artifacts/scripting/headers)
  foc\         our scripts
```

This mirrors RPU's own tree exactly, which matters: `define.h` contains
`#include "../sfall/sfall.h"`, and RPU scripts use `#include "../headers/x.h"`.
Because those are relative to the including file, **any RPU script can be
dropped into `scripts_src/foc/` and compiled with no `-I` flags and no edits.**

Header provenance: `reference/rpu-source/scripts_src/headers` @ RPU upstream.
162 of the 163 are byte-identical (modulo CRLF) to the copies in the existing
MDFG project; only `robots.h` differs. RPU's own readme is by killap and asks
for credit in derived work — see `ASSETS.md` when it exists.

---

## int2ssl — the decompiler

**The published binary does not work on this machine.** `falltergeist/int2ssl`
release 8.4.3 is a 32-bit MinGW/GCJ build that imports `libgcc_s_dw2-1.dll` and
`libgcj-16.dll`; neither is present, so it dies with `0xC0000135`
(STATUS_DLL_NOT_FOUND) before printing anything.

Built from source instead, from `sfall-team/int2ssl` (which publishes no
binaries but is the actively maintained fork — version 8.4.9 vs 8.4.3):

```
export PATH="/f/FOCMod/tools/w64devkit/bin:$PATH"
cd /f/FOCMod/reference/int2ssl
g++ -Os -s -o /f/FOCMod/tools/int2ssl/int2ssl.exe *.cpp
```

Compiles with deprecation warnings only. No CMake needed — flat source dir.

### Invocation

```
F:\FOCMod\tools\int2ssl\int2ssl.exe [-a] [-b] <file>.int [<out>.ssl]
```

`-a` ignore wrong argument counts, `-b` insert omitted arguments backward —
both useful on third-party TC scripts. Output defaults to `<file>.ssl`
**next to the input**, so decompile inside a scratch directory.

Verified two ways: round-tripped our own `foctest.int` back to semantically
identical SSL, and decompiled Sonora's `ACBoss.int` (39 KB) into 2557 lines
with all 56 procedure and dialogue-node names intact.

---

## DAT tools

`dat3.exe` (BGforge, Rust) is the primary — `l` list, `x` extract with paths,
`e` extract flat, `a` add, `d` delete. `dat2.exe` (TeamX) is the classic
alternative and can also *build* DAT2 archives with selectable compression.

```
tools\dat\dat3.exe l "F:\GOG Games\Fallout 2\master.dat"
tools\dat\dat3.exe x "F:\GOG Games\Fallout 2\master.dat" maps/artemple.map
```

Verified extracting from both the vanilla and Sonora archives. Source archive
mtimes were re-checked afterwards and were unchanged.

There is also `tools/datlist.py`-style read-only parsing available if a pure
Python path is wanted; the DAT2 trailer layout was confirmed empirically
against nine archives (trailer = `<u32 treeSize><u32 totalFileSize>`, tree =
`<u32 count>` then per entry `<u32 nameLen><name><u8 compressed><u32 real><u32 packed><u32 offset>`).

---

## fallout2-ce — reference only, NOT a test runtime

Cloned to `reference/fallout2-ce` and the v1.3.0 Windows x64 binary is in
`tools/fallout2-ce/`. Its C++ is the intended ground truth for file formats and
opcode behaviour — grep it before trusting any wiki page.

**It cannot run our base.** From its own README:

> Fallout 2 Restoration Project ... not yet supported.

Our base is FO2 + RPU 2.4.33, so fallout2-ce is out as the fast test loop. It
does carry partial sfall support (18 `sfall_*.cc` files, ~269 references, reads
`ddraw.ini`) but not enough for RPU. Testing happens on the original
`fallout2.exe` + sfall 4.4.6.1.

---

## Mapper2

`mapper2.exe` (2002) exists at:

```
F:\Fallout Sonora (Extended Release) - Copy\mods\mapper2.exe
```

alongside `mapper2.cfg` and `Fallout_Editor.pdf` / `.doc`. **Not copied into the
project yet** — Mapper2 must run against a game install with the right
`master.dat`/`critter.dat`, so it belongs with the working base copy, not in
`tools/`. That happens in Phase 3.

---

## MinGW-w64 (w64devkit)

`skeeto/w64devkit` v2.9.1, x64, extracted to `tools/w64devkit/`. GCC 16.2.0
with `make`, `gdb`, `busybox`. Git-ignored (58 MB); re-extract with:

```
tools\w64devkit-sfx.exe -oF:\FOCMod\tools -y
```

Installed specifically to build int2ssl, but it's the general C/C++ toolchain
for this project. No CMake is installed (`pip install cmake` if ever needed).

---

## Format specs

`docs/specs/` holds the fodev.net-era format documentation, retrieved
2026-08-26 as MediaWiki source from `falloutmods.fandom.com` (which hosts those
specs today):

`MAP`, `PRO`, `FRM`, `GAM`, `LST`, plus `DAT`, `MSG`, `INT`.

### ⚠️ Gotcha 3 — `.map` is big-endian and the spec doesn't say so

The MAP spec's header table gives offsets and sizes but not byte order.
Verified empirically against `artemple.map` (vanilla), `MDFGEXT.MAP` and
`MDFGFAC.MAP`: all are **big-endian**, version 20.

Read back correctly this way, `MDFGEXT.MAP` reports `startHex=20100` and
`MDFGFAC.MAP` reports `startHex=26705` — which match the numbers written in the
existing MDFG `BUILD_NOTES.md` independently, so both the spec reading and the
tooling agree.

Header, big-endian, from offset 0:
`u32 version(=20)`, `char[16] filename`, `i32 defaultPlayerHex`,
`i32 defaultElevation`, `i32 defaultOrientation`, `i32 numLocalVars`,
`i32 mapScriptId`, `i32 flags`, `i32 darkness`, `i32 numGlobalVars`,
`i32 mapId`, `u32 timeTicks`, then `44 * i32` unknown/zero.
