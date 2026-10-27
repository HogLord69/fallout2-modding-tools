#!/usr/bin/env python3
"""restyle_local.py - restyle the vanilla PC animation sheets into the colonist
look with FLUX.1-Kontext running LOCALLY through stable-diffusion.cpp (Vulkan).

Same job and same quality gate as restyle_sheets.py (which used the paid Gemini
API); the only difference is where the image comes from. Free and unmetered, so
it retries as much as it likes - the limit is wall-clock, not dollars.

Why this stack on this machine: the GPU is an AMD RX 6650 XT (gfx1032), which
ROCm/HIP does not officially support on Windows, and Python here is 3.13 which
torch-directml does not cover. stable-diffusion.cpp talks to the card through
the Vulkan driver instead, so no PyTorch and no ROCm are involved. 8 GB of VRAM
means the 12B model runs quantized (Q4_K_S) with --offload-to-cpu.

Source sheets are build/pc_anims/male/hmjmps_*.png, green-backed - the SAME
layout replace_pc_from_ref.py expects back. Results land in art/pc_grids/<CODE>.png
only if they key green AND register against the vanilla silhouettes at
--min-iou (mean) and --min-floor (worst single frame, catches dropped frames).

Run:  python tools/restyle_local.py --only AA           # one family, to tune
      python tools/restyle_local.py --all --overwrite   # the lot, overnight
      python tools/restyle_local.py --only AA --keep-raw # leave the sd.cpp output
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from foclib import GameIndex
from PIL import Image

import replace_pc_from_ref as R
import restyle_sheets as RS

ROOT = Path(__file__).resolve().parent.parent
SD = Path("F:/sdcpp")
MODELS = SD / "models"
WORK = ROOT / "build" / "restyle_local"
GRID_DIR = ROOT / "art" / "pc_grids"

# The first pass ("dusty white t-shirt and brown pants") gave long sleeves to
# the wrist, a blown-out flat pure white, and maroon trousers. Every clause
# below fixes one of those: sleeve length, shirt value, trouser hue, and the
# explicit demand for shading, since the model defaults to flat fills.
# Better still, pass --style-ref: the 48 hand-made sheets in the Green folder
# ARE the target look, and matching by example beats describing it in words.
# Keep this SHORT. The owner's own one-line prompt produced the 48 sheets that
# look right, and a one-line variant scored 0.92 here. A ~100-word rewrite with
# shouty negations ("NOT pure white", "not maroon") went the other way: Kontext
# is an EDIT model, and a heavy prompt pushes it to regenerate the sheet rather
# than recolour it, which is how we got smeared faces and lost poses.
PROMPT = (
    "Give this character a dusty white short-sleeved t-shirt with bare arms, "
    "brown pants and a dark brown belt. "
    "Remove the yellow numbers from his back. "
    "Keep every pose, the layout and the green background exactly as they are.")

STYLE_PROMPT = (
    " The second image shows the exact character design and colour palette to "
    "match: copy its shirt, skin, trousers, belt and boot colours and its "
    "light-and-shadow treatment faithfully onto the poses in the first image.")

# Style exemplar for --style-ref: ONE frame cropped from the hand-made AA idle
# sheet, not the whole sheet. A second full sheet roughly doubles the image
# tokens and pushed a single family past 60 minutes on this card; one frame
# carries the same colour/design information for ~6% of the bytes.
STYLE_REF = ROOT / "art" / "pc_grids" / "_style_ref.png"


def sd_cmd(ref: Path, out: Path, prompt: str, seed: int, a) -> list[str]:
    """FLUX.1-Kontext edit: the sheet goes in as --ref-image, not --init-img."""
    return [
        str(SD / "sd-cli.exe"),
        "-M", "img_gen",
        "--diffusion-model", str(MODELS / "flux1-kontext-Q4_K_S.gguf"),
        "--clip_l", str(MODELS / "clip_l.safetensors"),
        "--t5xxl", str(MODELS / "t5xxl_fp8.safetensors"),
        "--vae", str(MODELS / "flux_vae.safetensors"),
        "-r", str(ref),
        "-p", prompt,
        "-o", str(out),
        "--steps", str(a.steps),
        "--cfg-scale", str(a.cfg),
        "--seed", str(seed),
        "--sampling-method", a.sampler,
        # 8 GB card: keep weights in RAM and stream them, tile the VAE, and use
        # flash attention in the diffusion model. Without these it OOMs.
        "--offload-to-cpu",
        "--vae-tiling",
        "--diffusion-fa",
    ]


def call_server(ref: Path, prompt: str, seed: int, a) -> bytes | None:
    """POST to a resident sd-server instead of spawning sd-cli.

    sd-cli reloads all 12 GB of weights on every invocation; over 126 families
    that dwarfs the sampling time. Start the server once with:
      sd-server.exe --diffusion-model ... --offload-to-cpu --vae-tiling --diffusion-fa
    """
    import base64
    import requests
    files = [("image", ("ref.png", ref.read_bytes(), "image/png"))]
    if a.style_ref:
        p = Path(a.style_ref)
        files.append(("image", ("style.png", p.read_bytes(), "image/png")))
    r = requests.post(f"http://127.0.0.1:{a.port}/v1/images/edits",
                      files=files,
                      data={"prompt": prompt, "sample_steps": a.steps,
                            "cfg_scale": a.cfg, "seed": seed, "n": 1},
                      timeout=a.timeout)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    for item in r.json().get("data", []):
        if item.get("b64_json"):
            return base64.b64decode(item["b64_json"])
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", help="comma list of family codes")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--min-iou", type=float, default=0.70)
    ap.add_argument("--min-floor", type=float, default=0.40)
    ap.add_argument("--prompt", default=PROMPT)
    ap.add_argument("--steps", type=int, default=20)
    ap.add_argument("--cfg", type=float, default=1.0, help="Kontext wants ~1.0")
    ap.add_argument("--sampler", default="euler")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--timeout", type=int, default=3600, help="per image, seconds")
    ap.add_argument("--keep-raw", action="store_true", help="keep sd.cpp output alongside")
    ap.add_argument("--server", action="store_true",
                    help="POST to a resident sd-server (no 12GB reload per family)")
    ap.add_argument("--port", type=int, default=1234)
    ap.add_argument("--max-side", type=int, default=1024,
                    help="longest edge of the sheet sent to the model. Activation "
                         "memory scales with pixel count, so trimming this is the "
                         "lever that decides whether the graph fits in VRAM. 768 "
                         "visibly destroys the sprites; 960 is a mild trim.")
    ap.add_argument("--style-ref", nargs="?", const=str(STYLE_REF), default=None,
                    help="second reference image showing the target look; the bare "
                         "flag uses the hand-made AA sheet from the Green folder")
    args = ap.parse_args()

    missing = [p.name for p in (MODELS / "flux1-kontext-Q4_K_S.gguf",
                                MODELS / "clip_l.safetensors",
                                MODELS / "t5xxl_fp8.safetensors",
                                MODELS / "flux_vae.safetensors") if not p.exists()]
    if missing and not args.list:
        sys.exit(f"models not downloaded yet: {', '.join(missing)}\n"
                 f"  run: sh /f/sdcpp/get_models.sh")

    src_of = {p.stem.split("_")[1].upper(): p
              for p in sorted(RS.VAN_DIR.glob("hmjmps_*.png")) if len(p.stem.split("_")) > 2}
    codes = sorted(src_of)
    if args.only:
        want = {c.strip().upper() for c in args.only.split(",")}
        codes = [c for c in codes if c in want]
    elif not args.all and not args.list:
        sys.exit("pass --only CODES or --all")
    if not args.overwrite:
        codes = [c for c in codes if not (GRID_DIR / f"{c}.png").exists()]
    if args.list:
        print(f"{len(codes)} families: {' '.join(codes)}")
        return 0

    gi = GameIndex()
    pal = R.load_8bit_palette(gi)
    table, levels = R.make_index_table(pal)
    (WORK / "rejected").mkdir(parents=True, exist_ok=True)
    (WORK / "backup").mkdir(parents=True, exist_ok=True)

    ok_list, fail_list = [], []
    t_all = time.time()
    for n, code in enumerate(codes, 1):
        try:
            van = gi.vfs.read(f"art\\critters\\HMJMPS{code}.FRM")
        except Exception:
            print(f"[{n}/{len(codes)}] {code}: no vanilla .FRM (split family) - skipped")
            continue
        ref = WORK / f"_ref_{code}.png"
        RS.UPSCALE_TO = args.max_side
        blob = RS.to_green(src_of[code])
        if args.max_side:                      # to_green only upscales; also trim down
            import io as _io
            _im = Image.open(_io.BytesIO(blob)).convert("RGB")
            _f = args.max_side / max(_im.size)
            if _f < 1:
                _im = _im.resize((round(_im.width * _f), round(_im.height * _f)), Image.LANCZOS)
                _b = _io.BytesIO(); _im.save(_b, "PNG"); blob = _b.getvalue()
        ref.write_bytes(blob)
        w, h = Image.open(ref).size
        print(f"[{n}/{len(codes)}] {code} ({w}x{h}): ", end="", flush=True)

        kept = False
        for attempt in range(1, args.retries + 2):
            out = WORK / f"_out_{code}.png"
            out.unlink(missing_ok=True)
            t0 = time.time()
            full = args.prompt + (STYLE_PROMPT if args.style_ref else "")
            if args.server:
                try:
                    blob = call_server(ref, full, args.seed + attempt - 1, args)
                except Exception as e:
                    print(f"\n    attempt {attempt}: server error - {e}")
                    continue
                dt = time.time() - t0
                if blob is None:
                    print(f"\n    attempt {attempt}: server returned no image in {dt:.0f}s")
                    continue
                out.write_bytes(blob)
            else:
                cmd = sd_cmd(ref, out, full, args.seed + attempt - 1, args)
                proc = subprocess.run(cmd, capture_output=True, text=True,
                                      timeout=args.timeout, cwd=str(SD))
                dt = time.time() - t0
                if not out.exists():
                    tail = (proc.stderr or proc.stdout or "")[-400:].replace("\n", " ")
                    print(f"\n    attempt {attempt}: sd.cpp produced nothing in {dt:.0f}s - {tail}")
                    continue
            good, note = RS.check(code, out.read_bytes(), van, table, levels,
                                  args.min_iou, args.min_floor)
            if good:
                dst = GRID_DIR / f"{code}.png"
                if dst.exists():
                    (WORK / "backup" / f"{code}.png").write_bytes(dst.read_bytes())
                dst.write_bytes(out.read_bytes())
                print(f"kept in {dt:.0f}s  ({note})")
                ok_list.append(code)
                kept = True
                break
            (WORK / "rejected" / f"{code}_{attempt}.png").write_bytes(out.read_bytes())
            print(f"\n    attempt {attempt} ({dt:.0f}s) rejected: {note}")
        if not kept:
            fail_list.append(code)
            print(f"    {code}: kept nothing, existing grid untouched")
        if not args.keep_raw:
            ref.unlink(missing_ok=True)

    mins = (time.time() - t_all) / 60
    (WORK / "last_run.json").write_text(json.dumps(
        {"kept": ok_list, "failed": fail_list, "minutes": round(mins, 1),
         "prompt": args.prompt, "steps": args.steps, "cfg": args.cfg}, indent=1))
    print(f"\nkept {len(ok_list)}, failed {len(fail_list)}"
          f"{': ' + ' '.join(fail_list) if fail_list else ''}  in {mins:.0f} min")
    if ok_list:
        print("next: python tools/replace_pc_from_ref.py --preview && python tools/deploy.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
