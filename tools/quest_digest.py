#!/usr/bin/env python3
"""
quest_digest.py - render every quest's conversation beats as readable text,
from the decompiled scripts quest_survey.py cached.

    python tools/quest_digest.py                 # every source -> build/quest_survey/<src>/digest.md
    python tools/quest_digest.py --sources fo2

For each quest in the Pip-Boy log it prints the dialogue nodes that read or
write the quest's gvar, in the scripts that write it: the NPC's line, each
player option (with its INT test: -3 is a low-INT line, 4 the normal one,
higher is a smart line) and where it leads, the conditions that pick a node,
and what a node does (quest stage, XP, karma, caps, items). A node that only
acts (no line of its own) is shown with the line that led to it and the line
that answers it.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import quest_survey as qs  # noqa: E402

MAX_NODES = 10
SKILL_NAMES = {i: n for i, n in enumerate(qs.SKILLS)}


def load(src):
    d = qs.OUT / src
    quests = json.loads((d / "quests.json").read_text(encoding="utf-8"))
    gi = qs.open_game(src)
    gnames = qs.gvar_names(gi)
    lst = [(n.strip().split()[0].rsplit(".", 1)[0].lower() if n.strip() else "") for n in gi.scripts]
    return d, quests, gnames, lst


def render_src(src: str) -> str:
    d, quests, gnames, lst = load(src)
    msgs = {}

    def msg(list_id, num):
        if isinstance(num, str) and num.startswith('"'):
            return num.strip('"')
        for stem in (lst[list_id - 1] if 0 < list_id <= len(lst) else "", lst[list_id] if 0 <= list_id < len(lst) else ""):
            if not stem:
                continue
            if stem not in msgs:
                f = d / "msg" / f"{stem}.msg"
                msgs[stem] = qs.parse_msg(f.read_text(encoding="utf-8")) if f.exists() else {}
            t = msgs[stem].get(int(num))
            if t is not None:
                return t
        return f"<{list_id}:{num}>"

    def gname(n):
        n = int(n)
        return gnames[n] if 0 <= n < len(gnames) and not gnames[n].startswith("___") else f"G{n}"

    def readable(expr: str) -> str:
        e = re.sub(r"global_var\((\d+)\)", lambda m: gname(m.group(1)), expr)
        e = re.sub(r"get_critter_stat\(dude_obj, ([0-6])\)", lambda m: qs.SPECIAL[int(m.group(1))], e)
        e = re.sub(r"has_skill\(dude_obj, (\d+)\)", lambda m: SKILL_NAMES.get(int(m.group(1)), "skill" + m.group(1)), e)
        e = re.sub(r"is_success\(roll_vs_skill\(dude_obj, (\d+), ([^)]*)\)\)",
                   lambda m: f"roll {SKILL_NAMES.get(int(m.group(1)), m.group(1))}{'' if m.group(2).strip() == '0' else ' ' + m.group(2)}", e)
        e = re.sub(r"obj_is_carrying_obj_pid\(dude_obj, (\d+)\)", r"has item \1", e)
        e = re.sub(r"local_var\((\d+)\)", r"L\1", e)
        e = re.sub(r"map_var\((\d+)\)", r"M\1", e)
        return e

    def actions(body: str, gv: int) -> list[str]:
        out = []
        for m in re.finditer(r"set_global_var\((\d+), (.+?)\);", body):
            g = int(m.group(1))
            if g == gv:
                out.append(f"QUEST={readable(m.group(2))}")
        for x in qs.XP_RE.findall(body):
            out.append(f"+{x} XP")
        for x in re.findall(r"give_exp_points\(floor\((\d+) / 5\)", body):
            out.append(f"+~{x} XP")
        for sign, n in re.findall(r"set_global_var\(0, global_var\(0\) ([+-]) \(?(-?\d+)", body):
            if n != "0":
                out.append(f"karma {sign}{n}")
        for x in qs.CAPS_RE.findall(body):
            out.append(f"caps {x}")
        if qs.GIVE_RE.search(body):
            out.append("gives item")
        if qs.TAKE_RE.search(body):
            out.append("takes item")
        for m in re.finditer(r"is_success\(roll_vs_skill\(dude_obj, (\d+)", body):
            out.append(f"roll {SKILL_NAMES.get(int(m.group(1)), m.group(1))}")
        if "attack_complex" in body or "attack(" in body:
            out.append("combat")
        if "gdialog_mod_barter" in body or "barter" in body.lower() and "gdialog" in body:
            out.append("barter")
        return out

    def node_lines(body: str) -> tuple[list[str], list[str]]:
        replies, opts = [], []
        for line in body.splitlines():
            m = qs.REPLY_RE.search(line)
            if m:
                replies.append(msg(int(m.group(1)), m.group(2)))
        # options with the condition that guards them
        lines = body.splitlines()
        for i, line in enumerate(lines):
            m = qs.OPT_RE.search(line)
            g = qs.GOPT_RE.search(line)
            if not (m or g):
                continue
            cond = ""
            ind = len(line) - len(line.lstrip())
            for j in range(i - 1, max(-1, i - 8), -1):
                pl = lines[j]
                if pl.strip().startswith("if ") and len(pl) - len(pl.lstrip()) < ind:
                    cond = readable(re.sub(r"^\s*if \((.*)\) then begin\s*$", r"\1", pl))
                    break
                if len(pl) - len(pl.lstrip()) < ind and pl.strip() not in ("begin",):
                    break
            if m:
                iq = int(m.group(1))
                tag = "dumb" if iq < 0 else ("" if iq == 4 else f"IN{iq}")
                text, to = msg(int(m.group(2)), m.group(3)), m.group(4)
            else:
                tag, text, to = "", msg(int(g.group(1)), g.group(2)), g.group(3)
            pre = " ".join(x for x in (f"[{tag}]" if tag else "", f"[if {cond}]" if cond else "") if x)
            opts.append(f"    > {pre + ' ' if pre else ''}\"{text}\" -> {to}")
        return replies, opts

    out = [f"# {src}: quest conversation digest", ""]
    done_gvars = {}
    printed = set()
    for q in quests:
        gv = q["gvar"]
        out.append(f"## {q['location']}: {q['quest']}")
        out.append(f"gvar {q['gvar_name']} (shown at {q['display']}, done at {q['completed']}); "
                   f"values {q['values']}; writers {', '.join(q['writers'])}")
        if gv in done_gvars:
            # a later step of a chain quest: one gvar, several Pip-Boy lines
            out.append(f"(same gvar as \"{done_gvars[gv]}\": a later step of that quest)")
            out.append("")
            continue
        done_gvars[gv] = q["quest"]
        for script in q["writers"]:
            f = d / "ssl" / f"{script}.ssl"
            if not f.exists():
                continue
            procs = qs.parse_script(f.read_text(encoding="cp1252", errors="replace"))
            pat = re.compile(rf"global_var\({gv}\)|set_global_var\({gv},")
            touch = [p for p, b in procs.items() if pat.search(b)]
            chosen = []
            for p in touch:
                b = procs[p]
                if qs.REPLY_RE.search(b) or p in qs.HOOKS:
                    chosen.append(p)
                else:
                    # an action node: show the node(s) that lead to it
                    parents = [pp for pp, bb in procs.items()
                               if re.search(rf"\b{re.escape(p)}\b", bb) and qs.REPLY_RE.search(bb)]
                    chosen += parents[:2] + [p]
            seen, order = set(), []
            for p in chosen:
                if p not in seen:
                    seen.add(p)
                    order.append(p)
            if not order:
                continue
            out.append(f"### {script}")
            shown = 0
            for p in order:
                if shown >= MAX_NODES:
                    out.append(f"  ... {len(order) - shown} more procedures")
                    break
                b = procs[p]
                replies, opts = node_lines(b)
                acts = actions(b, gv)
                calls = re.findall(r"\bcall (\w+)", b)
                if p in qs.HOOKS and p not in ("talk_p_proc",) and not replies:
                    sets = [readable(m.group(0)) for m in re.finditer(rf"set_global_var\({gv}, .+?\);", b)]
                    if sets or acts:
                        out.append(f"  [{p}] {qs.HOOKS.get(p, p)}: {'; '.join(acts) or ''}")
                        shown += 1
                    continue
                if p == "talk_p_proc":
                    # which node the talk starts at, per quest state
                    for m in re.finditer(rf"if \(([^\n]*global_var\({gv}\)[^\n]*)\) then begin\n\s+(?:call )?(\w+)", b):
                        out.append(f"  [talk] when {readable(m.group(1))} -> {m.group(2)}")
                    shown += 1
                    continue
                head = f"  [{p}]"
                if acts:
                    head += " {" + "; ".join(acts) + "}"
                # a line this script already showed (a hub menu under
                # several quests) is printed once per source
                new_r = [r for r in replies[:3] if (script, r) not in printed]
                new_o = [o for o in opts[:8] if (script, o) not in printed]
                if (replies or opts) and not new_r and not new_o and not acts:
                    continue
                out.append(head)
                for r in new_r:
                    out.append(f"    NPC: \"{r}\"")
                    printed.add((script, r))
                if len(new_r) < len(replies[:3]):
                    out.append("    NPC: (lines shown above)")
                if not replies and calls:
                    out.append(f"    (then {', '.join(calls[:3])})")
                for o in new_o:
                    out.append(o)
                    printed.add((script, o))
                shown += 1
        out.append("")
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sources", default=",".join(qs.SOURCES))
    args = ap.parse_args()
    for src in args.sources.split(","):
        text = render_src(src)
        p = qs.OUT / src / "digest.md"
        p.write_text(text, encoding="utf-8")
        print(f"  {src}: {p.relative_to(qs.ROOT)} ({len(text.split())} words)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
