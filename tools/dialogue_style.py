#!/usr/bin/env python3
"""
dialogue_style.py - measure how the Fallout games and TCs write dialogue, and
how FOC's own lines compare.

    python tools/dialogue_style.py            # every source + foc
    python tools/dialogue_style.py --samples  # also write close-reading samples

Lines are sorted by role from the decompiled scripts quest_survey.py cached:
NPC replies (gsay_reply / gsay_message), player options (giq_option /
gsay_option) and barks (float_msg). FOC's lines come from its own source
(Reply / NOption / mstr in scripts_src/foc) and mod/data/text/english/dialog.

Writes build/quest_survey/style.json and style.md, and with --samples
build/quest_survey/style_samples.md (a fixed random sample per source).
"""

from __future__ import annotations

import argparse
import json
import random
import re
import statistics
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import quest_survey as qs  # noqa: E402

FOC_SRC = qs.ROOT / "scripts_src" / "foc"
FOC_MSG = qs.ROOT / "mod" / "data" / "text" / "english" / "dialog"

MSG_CALL = re.compile(r"message_str\((\d+), (\d+)\)")
FLOAT_CALL = re.compile(r"float_msg\([^,]+, message_str\((\d+), (\d+)\)")
DASH = re.compile(r"\s-\s|--|—|–")
STAGE = re.compile(r"\[[^\]]+\]|::[^:]+::|\*[^*]+\*")
WORD = re.compile(r"[A-Za-z']+")
SENT = re.compile(r"[^.!?]+[.!?]*")
CONTR = re.compile(r"\b\w+'(s|t|re|ve|ll|d|m)\b", re.I)
SWEAR = re.compile(r"\b(fuck\w*|shit\w*|damn\w*|hell|bitch\w*|ass(hole)?|bastard\w*|crap)\b", re.I)


def clean(t: str) -> str:
    # gendered pairs "<male^female>" -> male text; drop {} codes
    t = re.sub(r"<([^<>^]*)\^[^<>]*>", r"\1", t)
    return t.strip()


def stats(lines: list[str]) -> dict:
    lines = [clean(l) for l in lines if l and l.strip()]
    if not lines:
        return {"n": 0}
    words, sents, frag, short_close, contr, wtot = [], [], 0, 0, 0, 0
    nsent = 0
    for l in lines:
        body = STAGE.sub(" ", l)
        w = WORD.findall(body)
        words.append(len(w))
        wtot += len(w)
        contr += len(CONTR.findall(body))
        ss = [s.strip() for s in SENT.findall(body) if WORD.search(s)]
        sents.append(len(ss))
        nsent += len(ss)
        frag += sum(1 for s in ss if len(WORD.findall(s)) <= 3)
        if len(ss) >= 2 and len(WORD.findall(ss[-1])) <= 4:
            short_close += 1
    n = len(lines)
    pct = lambda k: round(100 * k / n, 1)  # noqa: E731
    multi = sum(1 for s in sents if s >= 2) or 1
    return {
        "n": n,
        "words_median": statistics.median(words),
        "words_p90": sorted(words)[int(0.9 * (n - 1))],
        "sentences_median": statistics.median(sents),
        "dash_pct": pct(sum(1 for l in lines if DASH.search(STAGE.sub(" ", l)))),
        "ellipsis_pct": pct(sum(1 for l in lines if "..." in l)),
        "exclaim_pct": pct(sum(1 for l in lines if "!" in l)),
        "question_pct": pct(sum(1 for l in lines if "?" in l)),
        "stage_pct": pct(sum(1 for l in lines if STAGE.search(l))),
        "swear_pct": pct(sum(1 for l in lines if SWEAR.search(l))),
        "fragment_sent_pct": round(100 * frag / max(nsent, 1), 1),
        "short_closer_pct": round(100 * short_close / multi, 1),
        "contractions_per_100w": round(100 * contr / max(wtot, 1), 1),
    }


def openers(lines: list[str], k: int = 12) -> list[tuple[str, int]]:
    c = Counter()
    for l in lines:
        w = WORD.findall(STAGE.sub(" ", clean(l)))
        if w:
            c[" ".join(w[:2]).lower()] += 1
    return c.most_common(k)


def collect_source(src: str) -> dict[str, list[str]]:
    d = qs.OUT / src
    gi = qs.open_game(src)
    lst = [(n.strip().split()[0].rsplit(".", 1)[0].lower() if n.strip() else "") for n in gi.scripts]
    msgs: dict[str, dict[int, str]] = {}

    def text(list_id: int, num: int) -> str | None:
        for stem in (lst[list_id - 1] if 0 < list_id <= len(lst) else "",
                     lst[list_id] if 0 <= list_id < len(lst) else ""):
            if not stem:
                continue
            if stem not in msgs:
                f = d / "msg" / f"{stem}.msg"
                msgs[stem] = qs.parse_msg(f.read_text(encoding="utf-8")) if f.exists() else {}
            t = msgs[stem].get(num)
            if t is not None:
                return t
        return None

    out = {"npc": [], "player": [], "player_dumb": [], "bark": []}
    seen = set()
    for f in sorted((d / "ssl").glob("*.ssl")):
        s = f.read_text(encoding="cp1252", errors="replace")
        for m in qs.REPLY_RE.finditer(s):
            if m.group(2).startswith('"'):
                continue
            key = ("npc", m.group(1), m.group(2))
            if key in seen:
                continue
            seen.add(key)
            t = text(int(m.group(1)), int(m.group(2)))
            if t:
                out["npc"].append(t)
        for m in qs.OPT_RE.finditer(s):
            if m.group(3).startswith('"'):
                continue
            role = "player_dumb" if int(m.group(1)) < 0 else "player"
            key = (role, m.group(2), m.group(3))
            if key in seen:
                continue
            seen.add(key)
            t = text(int(m.group(2)), int(m.group(3)))
            if t:
                out[role].append(t)
        for m in FLOAT_CALL.finditer(s):
            key = ("bark", m.group(1), m.group(2))
            if key in seen:
                continue
            seen.add(key)
            t = text(int(m.group(1)), int(m.group(2)))
            if t:
                out["bark"].append(t)
    return out


def collect_foc() -> dict[str, list[str]]:
    out = {"npc": [], "player": [], "player_dumb": [], "bark": []}
    for f in sorted(FOC_SRC.glob("*.ssl")):
        mf = FOC_MSG / f"{f.stem}.msg"
        if not mf.exists():
            continue
        msg = qs.parse_msg(mf.read_text(encoding="cp1252", errors="replace"))
        s = f.read_text(encoding="cp1252", errors="replace")
        for n in sorted(set(int(x) for x in re.findall(r"\bReply\((\d+)\)", s))):
            if n in msg:
                out["npc"].append(msg[n])
        for m in re.finditer(r"\b[NGB](Low)?Option\((\d+),\s*\w+,\s*(-?\d+)\)", s):
            n, iq = int(m.group(2)), int(m.group(3))
            if n in msg:
                out["player_dumb" if (m.group(1) or iq < 0) else "player"].append(msg[n])
        for n in sorted(set(int(x) for x in re.findall(r"\bmstr\((\d+)\)", s))):
            if n in msg:
                out["bark"].append(msg[n])
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--samples", action="store_true")
    args = ap.parse_args()
    res, data = {}, {}
    for src in qs.SOURCES + ["foc"]:
        lines = collect_foc() if src == "foc" else collect_source(src)
        data[src] = lines
        res[src] = {role: stats(v) for role, v in lines.items()}
        res[src]["npc_openers"] = openers(lines["npc"])
        res[src]["player_openers"] = openers(lines["player"])
        print(f"  {src}: npc {len(lines['npc'])}, player {len(lines['player'])}, "
              f"dumb {len(lines['player_dumb'])}, bark {len(lines['bark'])}")
    (qs.OUT / "style.json").write_text(json.dumps(res, indent=1), encoding="utf-8")

    keys = ["n", "words_median", "words_p90", "sentences_median", "dash_pct", "ellipsis_pct",
            "exclaim_pct", "question_pct", "stage_pct", "swear_pct", "fragment_sent_pct",
            "short_closer_pct", "contractions_per_100w"]
    md = ["# Dialogue style by source", ""]
    for role in ("npc", "player", "player_dumb", "bark"):
        md += [f"## {role}", "", "| source | " + " | ".join(keys) + " |",
               "|" + "---|" * (len(keys) + 1)]
        for src in res:
            r = res[src][role]
            md.append(f"| {src} | " + " | ".join(str(r.get(k, "")) for k in keys) + " |")
        md.append("")
    md += ["## Common openers (NPC)", ""]
    for src in res:
        md.append(f"- {src}: " + ", ".join(f"{w} ({c})" for w, c in res[src]["npc_openers"]))
    md += ["", "## Common openers (player)", ""]
    for src in res:
        md.append(f"- {src}: " + ", ".join(f"{w} ({c})" for w, c in res[src]["player_openers"]))
    (qs.OUT / "style.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print(f"  wrote {(qs.OUT / 'style.md').relative_to(qs.ROOT)}")

    if args.samples:
        rnd = random.Random(2026)
        sm = ["# Dialogue close-reading samples (seed 2026)", ""]
        for src in qs.SOURCES:
            sm.append(f"## {src}")
            for role, k in (("npc", 45), ("player", 25), ("player_dumb", 10), ("bark", 20)):
                pool = [clean(l) for l in data[src][role] if len(WORD.findall(l)) >= 3]
                sm.append(f"### {role}")
                for l in rnd.sample(pool, min(k, len(pool))):
                    sm.append(f"- {l}")
            sm.append("")
        (qs.OUT / "style_samples.md").write_text("\n".join(sm) + "\n", encoding="utf-8")
        print(f"  wrote {(qs.OUT / 'style_samples.md').relative_to(qs.ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
