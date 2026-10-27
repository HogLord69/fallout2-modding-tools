#!/usr/bin/env python3
"""
quest_survey.py - measure how the quests of Fallout 1, Fallout 2 and the
total conversions are built, so FOC's quests can follow the same habits.

    python tools/quest_survey.py                  # every source -> build/quest_survey/
    python tools/quest_survey.py --sources fo2,nevada
    python tools/quest_survey.py --show fo2 "Rescue Smoke"   # one quest in full

Every script is decompiled with int2ssl (build/int2ssl, from
reference/int2ssl) so the vanilla game and the TCs are read the same way,
from the compiled .int the engine actually runs. Decompiled sources and the
dialogue .msg files are cached under build/quest_survey/<source>/.

WHAT IS MEASURED
  quest list   the Pip-Boy quest log: quests.txt + quests.msg (Fallout 2 and
               the TCs), or the table compiled into Fallout 1's exe (taken
               from fallout1-ce pipboy.cc: shown at 1, struck through at 2+).
  per quest    the quest gvar's writers: which scripts and procedures set it
               and to what. The start (lowest value >= the display
               threshold), the stages (distinct values set), the endings
               (distinct values >= the completed threshold), who gives it and
               who closes it, and whether those happen in dialogue or through
               a hook (killing, using an item, entering a map, a timer).
               XP, karma, caps and items handed over in the procedures that
               close it. Skill and SPECIAL checks in the giver's dialogue.
               The giver's offer line and the player's answers to it.
  per script   dialogue shape: nodes, options per node, low-INT options
               (giq_option with a negative IQ test), smart options, skill and
               stat gated options, line lengths.

Writes build/quest_survey/<source>/quests.json, build/quest_survey/summary.json
and corpus/quests.jsonl. Findings are written up in docs/QUEST_DESIGN_GUIDE.md.
"""

from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from foclib import GameIndex  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "quest_survey"
INT2SSL = ROOT / "build" / "int2ssl" / "int2ssl.exe"
SOURCES = ["fo1", "fo2", "sonora", "nevada", "olympus", "resurrection", "sotj", "yesterday"]
SEP = "\\"

# Fallout 1's Pip-Boy quest table (fallout1-ce src/game/pipboy.cc, sthreads):
# location i is pipboy.msg 700+10i, quest j is 701+10i+j
FO1_THREADS = [
    ["CALM_REBELS", "DESTROY_MASTER_5", "DESTROY_MASTER_4", "FIND_WATER_CHIP", "WATER_THIEF"],
    [],
    ["CURE_JARVIS", "MAKE_ANTIDOTE", "RESCUE_TANDI", "RADSCORPION_SEED"],
    ["SAUL_QUEST", "KILL_KILLIAN", "SAVE_SINTHIA", "TRISH_QUEST", "CAPTURE_GIZMO", "BUST_SKULZ"],
    [],
    ["NECROP_MUTANTS_KILLED", "NECROP_WATER_PUMP_FIXED"],
    ["KILL_DEATHCLAW", "KILL_JAIN", "KILL_MERCHANT", "MISSING_CARAVAN", "STEAL_NECKLACE"],
    ["BECOME_AN_INITIATE", "FIND_LOST_INITIATE"],
    [],
    ["WEAPONS_ARMED", "START_POWER"],
    ["BECOME_BLADE", "ROMEO_JULIET", "DESTROY_FOLLOWERS", "FIND_AGENT", "FIX_FARM", "LOST_BROTHER", "GANG_WAR"],
    [],
]

SKILLS = ["small guns", "big guns", "energy weapons", "unarmed", "melee", "throwing", "first aid",
          "doctor", "sneak", "lockpick", "steal", "traps", "science", "repair", "speech", "barter",
          "gambling", "outdoorsman"]
SPECIAL = ["ST", "PE", "EN", "CH", "IN", "AG", "LK"]

HOOKS = {"destroy_p_proc": "kill", "use_obj_on_p_proc": "use item on", "use_p_proc": "use",
         "use_skill_on_p_proc": "skill on", "map_enter_p_proc": "enter map", "map_exit_p_proc": "leave map",
         "timed_event_p_proc": "timer", "pickup_p_proc": "pick up", "spatial_p_proc": "walk into",
         "critter_p_proc": "critter tick", "damage_p_proc": "damage", "map_update_p_proc": "map update",
         "combat_p_proc": "combat", "push_p_proc": "push", "look_at_p_proc": "look",
         "description_p_proc": "examine", "barter_p_proc": "barter", "start": "start"}

KIND_WORDS = [
    ("kill", r"\b(kill|destroy|eliminate|assassinat|wipe out|exterminat|get rid of|dispose|take out|deal with|clear|hunt)"),
    ("fetch", r"\b(find|retrieve|get|obtain|bring|recover|collect|gather|acquire|steal|buy|return)"),
    ("deliver", r"\b(deliver|take .* to|give .* to|bring .* to|carry)"),
    ("rescue", r"\b(rescue|save|free|release|cure|heal)"),
    ("escort", r"\b(escort|guide|protect|guard|defend|accompany)"),
    ("repair", r"\b(fix|repair|restore|turn on|power|install|build)"),
    ("talk", r"\b(talk|convince|persuade|negotiate|speak|ask|tell|warn|reconcile|make peace|calm|mediat)"),
    ("investigate", r"\b(find out|investigate|learn|discover|figure out|who|why|what happened|spy)"),
    ("join", r"\b(become|join|initiat|member|recruit)"),
]


# ------------------------------------------------------------------ reading

def open_game(src: str) -> GameIndex:
    if src == "fo2":
        return GameIndex(pristine=True)            # Fallout 2 + RPU, as the base
    cfg = json.loads((ROOT / "tools" / "sources.json").read_text(encoding="utf-8"))
    path = Path(cfg[src]["path"])
    extra = [path / "data"] if (path / "data").is_dir() else None
    return GameIndex(path, extra_dirs=extra, pristine=False)


def read_text(gi, path) -> str | None:
    try:
        return gi.vfs.read(path).decode("cp1252", errors="replace")
    except (FileNotFoundError, KeyError):
        return None


MSG_RE = re.compile(r"\{(\d+)\}\{[^}]*\}\{(.*?)\}", re.S)


def parse_msg(text: str | None) -> dict[int, str]:
    if not text:
        return {}
    out = {}
    for m in MSG_RE.finditer(text):
        out[int(m.group(1))] = " ".join(m.group(2).split())
    return out


def gvar_names(gi) -> list[str]:
    t = read_text(gi, f"data{SEP}vault13.gam") or ""
    names = []
    for line in t.splitlines():
        m = re.match(r"\s*([A-Za-z_][A-Za-z0-9_]*)\s*:=", line)
        if m:
            names.append(re.sub(r"^GVAR_", "", m.group(1)))
    return names


def quest_table(src, gi, gnames):
    """[(location text, description, gvar, display, completed)]"""
    maps = parse_msg(read_text(gi, f"text{SEP}english{SEP}game{SEP}map.msg"))
    if src == "fo1":
        pip = parse_msg(read_text(gi, f"text{SEP}english{SEP}game{SEP}pipboy.msg"))
        out = []
        for i, row in enumerate(FO1_THREADS):
            for j, name in enumerate(row):
                gv = gnames.index(name) if name in gnames else -1
                out.append((pip.get(700 + 10 * i, "?"), pip.get(701 + 10 * i + j, "?"), gv, 1, 2))
        return out
    qm = parse_msg(read_text(gi, f"text{SEP}english{SEP}game{SEP}quests.msg"))
    out = []
    for line in (read_text(gi, f"data{SEP}quests.txt") or "").splitlines():
        s = line.split("#")[0].strip()
        if not s:
            continue
        parts = [p.strip() for p in s.split(",")]
        if len(parts) < 5 or not all(re.match(r"^-?\d+$", p) for p in parts[:5]):
            continue
        loc, desc, gv, disp, comp = (int(p) for p in parts[:5])
        out.append((maps.get(loc, f"map.msg {loc}"), qm.get(desc, f"quests.msg {desc}"), gv, disp, comp))
    return out


# ----------------------------------------------------------- decompiling

def decompile_all(src, gi) -> Path:
    d = OUT / src
    (d / "int").mkdir(parents=True, exist_ok=True)
    (d / "ssl").mkdir(parents=True, exist_ok=True)
    (d / "msg").mkdir(parents=True, exist_ok=True)
    jobs = []
    for line, name in enumerate(gi.scripts, 1):
        stem = name.strip().split()[0].rsplit(".", 1)[0].lower() if name.strip() else ""
        if not stem:
            continue
        ssl = d / "ssl" / f"{stem}.ssl"
        msgf = d / "msg" / f"{stem}.msg"
        if not msgf.exists():
            t = read_text(gi, f"text{SEP}english{SEP}dialog{SEP}{stem}.msg")
            if t is not None:
                msgf.write_text(t, encoding="utf-8")
        if ssl.exists():
            continue
        try:
            b = gi.vfs.read(f"scripts{SEP}{stem}.int")
        except (FileNotFoundError, KeyError):
            continue
        ip = d / "int" / f"{stem}.int"
        ip.write_bytes(b)
        jobs.append((ip, ssl))

    def run(job):
        ip, ssl = job
        args = [str(INT2SSL), "-a", "-b", "-s2"] + (["-1"] if src == "fo1" else []) + [str(ip), str(ssl)]
        subprocess.run(args, capture_output=True, timeout=120)
        return ssl.exists()
    with ThreadPoolExecutor(8) as ex:
        ok = sum(ex.map(run, jobs))
    if jobs:
        print(f"  {src}: decompiled {ok}/{len(jobs)} scripts")
    return d


PROC_RE = re.compile(r"^procedure (\w+)\s*\nbegin\n(.*?)^end\s*$", re.M | re.S)
SET_RE = re.compile(r"set_global_var\((\d+), (.+?)\);\s*$", re.M)
XP_RE = re.compile(r"give_exp_points\((-?\d+)\)")
CAPS_RE = re.compile(r"item_caps_adjust\(dude_obj, (-?\d+)\)")
SKILL_RE = re.compile(r"(?:has_skill|roll_vs_skill)\(dude_obj, (\d+)")
STAT_RE = re.compile(r"(?:get_critter_stat\(dude_obj, ([0-6])\)|do_check\(dude_obj, ([0-6]))")
OPT_RE = re.compile(r"giq_option\((-?\d+), (\d+), (\d+|\"[^\"]*\"), (\w+), (-?\d+)\)")
GOPT_RE = re.compile(r"gsay_option\((\d+), (\d+|\"[^\"]*\"), (\w+), (-?\d+)\)")
REPLY_RE = re.compile(r"gsay_(?:reply|message)\((\d+), (\d+|\"[^\"]*\")")
FLOAT_RE = re.compile(r"float_msg\(")
GIVE_RE = re.compile(r"add_(?:mult_)?objs?_to_inven\(dude_obj")
TAKE_RE = re.compile(r"(?:rm_obj_from_inven\(dude_obj|rm_mult_objs_from_inven\(dude_obj|remove_pid_qty\(dude_obj)")
CARRY_RE = re.compile(r"obj_is_carrying_obj_pid\(dude_obj, (\d+)\)")


def parse_script(text: str):
    procs = {}
    for m in PROC_RE.finditer(text):
        procs[m.group(1)] = m.group(2)
    return procs


def cond_before(body: str, pos: int) -> str:
    """The if-condition lines leading to a statement (for 'why was this set')."""
    lines = body[:pos].splitlines()
    conds = [l.strip() for l in lines[-6:] if l.strip().startswith(("if ", "else"))]
    return " / ".join(conds[-2:])


# ------------------------------------------------------------ the survey

def survey(src: str) -> dict:
    gi = open_game(src)
    gnames = gvar_names(gi)
    quests = quest_table(src, gi, gnames)
    d = decompile_all(src, gi)
    karma = next((i for i, n in enumerate(gnames) if n in ("PLAYER_REPUTATION", "KARMA", "PLAYER_KARMA")), 0)
    # message list id -> msg stem (the list id is the script's scripts.lst line)
    lst = [(n.strip().split()[0].rsplit(".", 1)[0].lower() if n.strip() else "") for n in gi.scripts]
    msgs_cache = {}

    def msg(list_id: int, num) -> str:
        if isinstance(num, str) and num.startswith('"'):
            return num.strip('"')
        for stem in (lst[list_id - 1] if 0 < list_id <= len(lst) else "",
                     lst[list_id] if 0 <= list_id < len(lst) else ""):
            if not stem:
                continue
            if stem not in msgs_cache:
                f = d / "msg" / f"{stem}.msg"
                msgs_cache[stem] = parse_msg(f.read_text(encoding="utf-8")) if f.exists() else {}
            t = msgs_cache[stem].get(int(num))
            if t is not None:
                return t
        return f"<{list_id}:{num}>"

    scripts = {}
    writes = defaultdict(list)       # gvar -> [(script, proc, value, cond)]
    dialogue = Counter()
    per_node_opts = []
    reply_words, option_words = [], []
    for f in sorted((d / "ssl").glob("*.ssl")):
        text = f.read_text(encoding="cp1252", errors="replace")
        procs = parse_script(text)
        facts = {"nodes": 0, "options": 0, "dumb": 0, "smart": 0, "skill_opts": 0, "stat_opts": 0,
                 "floats": len(FLOAT_RE.findall(text))}
        for pname, body in procs.items():
            replies = REPLY_RE.findall(body)
            opts = OPT_RE.findall(body)
            gopts = GOPT_RE.findall(body)
            if replies:
                facts["nodes"] += 1
                n = len(opts) + len(gopts)
                if n:
                    per_node_opts.append(n)
                facts["options"] += n
                facts["dumb"] += sum(1 for o in opts if int(o[0]) < 0)
                facts["smart"] += sum(1 for o in opts if int(o[0]) > 4)
                # options sitting under a skill/stat test in this node
                for line in body.splitlines():
                    if "_option(" in line:
                        pass
                for m in re.finditer(r"if \((.*?)\) then begin\n(\s+)(g\w*_option)", body):
                    if SKILL_RE.search(m.group(1)):
                        facts["skill_opts"] += 1
                    if STAT_RE.search(m.group(1)):
                        facts["stat_opts"] += 1
                for lid, num in replies[:1]:
                    t = msg(int(lid), num)
                    if not t.startswith("<"):
                        reply_words.append(len(t.split()))
                for o in opts:
                    t = msg(int(o[1]), o[2])
                    if not t.startswith("<"):
                        option_words.append(len(t.split()))
            for m in SET_RE.finditer(body):
                gv, val = int(m.group(1)), m.group(2).strip()
                v = int(val) if re.match(r"^-?\d+$", val) else val
                writes[gv].append((f.stem, pname, v, cond_before(body, m.start())))
        scripts[f.stem] = facts
        for k in ("nodes", "options", "dumb", "smart", "skill_opts", "stat_opts"):
            dialogue[k] += facts[k]

    parsed = {}

    def procs_of(script):
        if script not in parsed:
            f = d / "ssl" / f"{script}.ssl"
            parsed[script] = parse_script(f.read_text(encoding="cp1252", errors="replace"))
        return parsed[script]

    def proc_body(script, pname):
        return procs_of(script).get(pname, "")

    def targets(body):
        t = [o[3] for o in OPT_RE.findall(body)] + [o[2] for o in GOPT_RE.findall(body)]
        return t + re.findall(r"\bcall (\w+)", body)

    def is_dialogue(script, pname):
        """A node, or a helper reached from one (an option's target or a call)."""
        procs = procs_of(script)
        body = procs.get(pname, "")
        if REPLY_RE.search(body) or pname.lower().startswith("node"):
            return True
        return any(pname in targets(b) and (REPLY_RE.search(b) or p.lower().startswith("node"))
                   for p, b in procs.items())

    def via(script, pname):
        if pname in HOOKS and pname != "start":
            return HOOKS[pname]
        return "dialogue" if is_dialogue(script, pname) else f"other:{pname}"

    def context(script, pname):
        """What was said around a write: the NPC line before it, the player's
        choice that led there, and the NPC's answer."""
        procs = procs_of(script)
        body = procs.get(pname, "")
        ctx = {"npc": "", "player": "", "answer": ""}
        r = REPLY_RE.findall(body)
        if r:
            ctx["answer"] = msg(int(r[0][0]), r[0][1])
        for p, b in procs.items():
            for o in OPT_RE.findall(b):
                if o[3] == pname:
                    ctx["player"] = msg(int(o[1]), o[2])
                    rr = REPLY_RE.findall(b)
                    ctx["npc"] = msg(int(rr[0][0]), rr[0][1]) if rr else ""
                    break
            for o in GOPT_RE.findall(b):
                if o[2] == pname and not ctx["player"]:
                    ctx["player"] = msg(int(o[0]), o[1])
                    rr = REPLY_RE.findall(b)
                    ctx["npc"] = msg(int(rr[0][0]), rr[0][1]) if rr else ""
            if ctx["player"]:
                break
        if not ctx["answer"]:
            for c in re.findall(r"\bcall (\w+)", body):
                rr = REPLY_RE.findall(procs.get(c, ""))
                if rr:
                    ctx["answer"] = msg(int(rr[0][0]), rr[0][1])
                    break
        return ctx

    def rewards(body):
        xp = [int(x) for x in XP_RE.findall(body)]
        # Olympus scales a base amount by INT and Luck: floor(N / 5) + ...
        xp += [int(x) for x in re.findall(r"give_exp_points\(floor\((\d+) / 5\)", body)]
        # Sonora stages the amount in a gvar first: set_global_var(28, N) ... give_exp_points(global_var(28))
        for g in set(re.findall(r"give_exp_points\(global_var\((\d+)\)\)", body)):
            xp += [int(x) for x in re.findall(rf"set_global_var\({g}, (?:global_var\({g}\) \+ )?(\d+)\)", body)
                   if int(x) > 0]
        kar = []
        for sign, n in re.findall(rf"set_global_var\({karma}, global_var\({karma}\) ([+-]) \(?(-?\d+)", body):
            kar.append(int(n) if sign == "+" else -int(n))
        kar = [k for k in kar if k]
        # town reputation: a named *REP* gvar, or one clamped to +-100 (Sonora)
        rep = []
        for g, sign, n in re.findall(r"set_global_var\((\d+), global_var\(\1\) ([+-]) \(?(-?\d+)", body):
            g = int(g)
            name = gnames[g] if g < len(gnames) else ""
            if g != karma and (re.search(r"REP|RESPECT|TRUST|FAME", name) or
                               re.search(rf"if \(global_var\({g}\) > 100\)", body)):
                rep.append(int(n) if sign == "+" else -int(n))
        caps = [int(x) for x in CAPS_RE.findall(body)]
        return {"xp": xp, "karma": kar, "rep": rep, "caps": caps, "gives_item": len(GIVE_RE.findall(body)),
                "takes_item": len(TAKE_RE.findall(body))}

    def node_text(script, pname, body):
        r = REPLY_RE.findall(body)
        reply = msg(int(r[0][0]), r[0][1]) if r else ""
        opts = []
        for o in OPT_RE.findall(body):
            opts.append({"iq": int(o[0]), "text": msg(int(o[1]), o[2]), "to": o[3]})
        for o in GOPT_RE.findall(body):
            opts.append({"iq": None, "text": msg(int(o[0]), o[1]), "to": o[2]})
        return reply, opts

    out = []
    for loc, desc, gv, disp, comp in quests:
        w = writes.get(gv, [])
        lits = sorted({v for _s, _p, v, _c in w if isinstance(v, int)})
        exprs = sorted({v for _s, _p, v, _c in w if not isinstance(v, int)})
        start_vals = [v for v in lits if v >= disp]
        start = start_vals[0] if start_vals else None
        ends = [v for v in lits if v >= comp]
        stages = [v for v in lits if v >= disp]
        q = {"source": src, "location": loc, "quest": desc, "gvar": gv,
             "gvar_name": gnames[gv] if 0 <= gv < len(gnames) else "?",
             "display": disp, "completed": comp, "values": lits, "exprs": exprs[:6],
             "stages": len(stages), "endings": len(ends), "writers": sorted({s for s, *_ in w}),
             "start": [], "finish": [], "hooks": sorted({via(s_, p) for s_, p, _v, _c in w}),
             "kinds": [k for k, rx in KIND_WORDS if re.search(rx, desc, re.I)]}
        for s, p, v, c in w:
            if v == start:
                body = proc_body(s, p)
                reply, opts = node_text(s, p, body)
                q["start"].append({"script": s, "proc": p, "via": via(s, p), **context(s, p),
                                   "options": opts[:6], "cond": c})
            if isinstance(v, int) and v >= comp:
                body = proc_body(s, p)
                q["finish"].append({"script": s, "proc": p, "value": v, "cond": c, "via": via(s, p),
                                    **context(s, p), **rewards(body)})
        givers = {x["script"] for x in q["start"]}
        g = Counter()
        for s in givers:
            for k, v in scripts.get(s, {}).items():
                g[k] += v
        q["giver_dialogue"] = dict(g)
        out.append(q)

    summary = {
        "source": src, "quests": len(out), "scripts": len(scripts),
        "dialogue_nodes": dialogue["nodes"],
        "options_per_node_median": statistics.median(per_node_opts) if per_node_opts else 0,
        "options_per_node_hist": dict(sorted(Counter(min(n, 8) for n in per_node_opts).items())),
        "dumb_option_share": round(dialogue["dumb"] / max(1, dialogue["options"]), 3),
        "smart_option_share": round(dialogue["smart"] / max(1, dialogue["options"]), 3),
        "skill_gated_share": round(dialogue["skill_opts"] / max(1, dialogue["options"]), 3),
        "stat_gated_share": round(dialogue["stat_opts"] / max(1, dialogue["options"]), 3),
        "reply_words_median": statistics.median(reply_words) if reply_words else 0,
        "option_words_median": statistics.median(option_words) if option_words else 0,
    }
    (d / "quests.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    return {"summary": summary, "quests": out}


def aggregate(res: dict) -> dict:
    s = dict(res["summary"])
    qs = res["quests"]
    found = [q for q in qs if q["writers"]]
    s["quests_linked"] = len(found)
    by_loc = Counter(q["location"] for q in qs)
    s["quests_per_location_median"] = statistics.median(by_loc.values()) if by_loc else 0
    s["stages_hist"] = dict(sorted(Counter(min(q["stages"], 8) for q in found).items()))
    s["endings_hist"] = dict(sorted(Counter(min(q["endings"], 5) for q in found).items()))
    s["start_via"] = dict(Counter(x["via"] for q in found for x in q["start"][:1]).most_common())
    s["finish_via"] = dict(Counter(x["via"] for q in found for x in q["finish"]).most_common(8))
    xp = [sum(x["xp"]) for q in found for x in q["finish"] if x["xp"]]
    s["finish_xp_median"] = statistics.median(xp) if xp else 0
    s["finish_xp_quartiles"] = statistics.quantiles(xp, n=4) if len(xp) >= 4 else xp
    s["finish_with_xp_share"] = round(sum(1 for q in found if any(x["xp"] for x in q["finish"])) / max(1, len(found)), 2)
    s["finish_with_karma_share"] = round(sum(1 for q in found if any(x["karma"] for x in q["finish"])) / max(1, len(found)), 2)
    s["finish_with_rep_share"] = round(sum(1 for q in found if any(x["rep"] for x in q["finish"])) / max(1, len(found)), 2)
    s["finish_with_caps_share"] = round(sum(1 for q in found if any(x["caps"] for x in q["finish"])) / max(1, len(found)), 2)
    s["finish_with_item_share"] = round(sum(1 for q in found if any(x["gives_item"] for x in q["finish"])) / max(1, len(found)), 2)
    s["giver_has_skill_gate_share"] = round(sum(1 for q in found if q["giver_dialogue"].get("skill_opts")) / max(1, len(found)), 2)
    s["giver_has_stat_gate_share"] = round(sum(1 for q in found if q["giver_dialogue"].get("stat_opts")) / max(1, len(found)), 2)
    s["giver_has_dumb_share"] = round(sum(1 for q in found if q["giver_dialogue"].get("dumb")) / max(1, len(found)), 2)
    s["multi_writer_share"] = round(sum(1 for q in found if len(q["writers"]) > 1) / max(1, len(found)), 2)
    s["kinds"] = dict(Counter(k for q in qs for k in (q["kinds"] or ["other"])).most_common())
    s["desc_words_median"] = statistics.median(len(q["quest"].split()) for q in qs) if qs else 0
    return s


def show(src: str, needle: str):
    qs = json.loads((OUT / src / "quests.json").read_text(encoding="utf-8"))
    for q in qs:
        if needle.lower() in q["quest"].lower():
            print(json.dumps(q, indent=1, ensure_ascii=False))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--sources", default=",".join(SOURCES))
    ap.add_argument("--show", nargs=2, metavar=("SOURCE", "TEXT"))
    args = ap.parse_args()
    if args.show:
        show(*args.show)
        return 0
    if not INT2SSL.exists():
        sys.exit(f"{INT2SSL} missing: build reference/int2ssl with CMake first")
    summary, corpus = {}, []
    for src in args.sources.split(","):
        res = survey(src)
        summary[src] = aggregate(res)
        corpus += res["quests"]
        print(f"  {src}: {summary[src]['quests']} quests, {summary[src]['quests_linked']} linked to scripts")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1, ensure_ascii=False), encoding="utf-8")
    with open(ROOT / "corpus" / "quests.jsonl", "w", encoding="utf-8") as fh:
        for q in corpus:
            slim = {k: q[k] for k in ("source", "location", "quest", "gvar_name", "display", "completed",
                                      "values", "stages", "endings", "hooks", "kinds", "writers")}
            slim["start"] = [{k: x[k] for k in ("script", "via", "npc", "player", "answer")} for x in q["start"][:1]]
            slim["finish"] = [{k: x[k] for k in ("script", "via", "value", "player", "answer", "xp", "karma", "rep", "caps", "gives_item")}
                              for x in q["finish"]]
            fh.write(json.dumps(slim, ensure_ascii=False) + "\n")
    print(f"wrote {OUT / 'summary.json'} and corpus/quests.jsonl")
    return 0


if __name__ == "__main__":
    sys.exit(main())
