#!/usr/bin/env python3
"""
dlg.py - compile a character's dialogue file (mod/dialog_src/<name>.dlg) into
its script (scripts_src/foc/<name>.ssl) and message file
(mod/data/text/english/dialog/<name>.msg).

    python tools/dlg.py                    # every .dlg
    python tools/dlg.py lamzero lamrem     # just these
    python tools/dlg.py --check            # parse only, write nothing

One file holds everything a talking NPC needs: the look and description text,
barks, and the conversation as nodes in the AI_WRITING_BRIEF format (» for
the NPC, → for the player). Message numbers are assigned here, so text and
script can never drift apart. The script is registered in mod/ids/scripts.txt
if it is new (run gen_ids.py after, as build.py does).

FORMAT  (one directive per line; # starts a comment line)

  script lamzero              the script name (8 chars at most)
  about <text>                a line for the header comment (repeatable)
  include foc_lam.h           extra header after foc_ids.h (repeatable)
  head <n> [<bg>]             talking head (default -1: the plain dialogue box)
  trigger use                 open the conversation from use_p_proc (a terminal,
                              a sign) instead of talk_p_proc
  look <text>                 look-at line (msg 100)
  desc <text>                 description line (msg 101)
  lvar <NAME>                 a local variable: #define LVAR_<NAME> (1..7)
  bark <min> <max>            bark timer in seconds (default 25 50)
  bark [<cond>] <text>        a bark; the first condition that holds picks
                              its group, and a group with several lines picks
                              one at random. No barks, no timer.
  refuse [<cond>] <text>      when talked to and <cond> holds (or always),
                              float this instead of opening the dialogue
  on <event> {                raw SSL, until a line that is just }
     enter     map_enter_p_proc (not on a save-load)
     heartbeat critter_p_proc
     death     destroy_p_proc
     hurt      damage_p_proc
     skill     use_skill_on_p_proc (action_being_used)
     timer     timed_event_p_proc (fixed_param; barks use 9)
     after     talk_p_proc, after the dialogue closes
     top       file scope: defines, variables, procedures (declare them too)
  }

  node <name>                 a dialogue node; the conversation enters at `start`
    goto [<cond>] <node>      route: if <cond> holds, go there instead
    do <ssl>                  run on entering the node (or `do {` ... `}`)
    » <text>   / say <text>   the NPC's line; {expr} splices a value in
    → [<cond>] <text> -> <target> [{ <ssl> }]   / opt ...
    low [<cond>] <text> -> <target> [{ <ssl> }]  an option for INT 3 or less

  Targets: a node name, `end` (close), `fight` (close, then attack the
  player), `barter` (trade, then this node again).

  Anywhere in SSL, @"some text" becomes that text's message number, so
  `do display_msg(mstr(@"Arren gives you a Pip-Boy."));` works.

Conditions are SSL; scripts_src/foc/foc_dlg.h has the shorthands (skill(),
stat(), has(), gv(), lv(), give(), take(), xp(), caps()). sslc's and/or
evaluate both sides.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "mod" / "dialog_src"
SSL_OUT = ROOT / "scripts_src" / "foc"
MSG_OUT = ROOT / "mod" / "data" / "text" / "english" / "dialog"
SCRIPTS_TXT = ROOT / "mod" / "ids" / "scripts.txt"

EVENTS = {"enter", "heartbeat", "death", "hurt", "skill", "timer", "after", "top"}
BARK_EVENT = 9
OPT_RE = re.compile(r"^(?:\[(?P<cond>.*?)\]\s*)?(?P<text>.+?)\s*->\s*(?P<target>[A-Za-z_][\w]*)"
                    r"\s*(?:\{(?P<act>.*)\})?\s*$")
COND_RE = re.compile(r"^\[(?P<cond>.*?)\]\s*(?P<rest>.*)$")
AT_RE = re.compile(r'@"((?:[^"\\]|\\.)*)"')


class DlgError(Exception):
    pass


class Messages:
    def __init__(self):
        self.ids: dict[str, int] = {}
        self.order: list[tuple[int, str, str]] = []
        self.next = 102

    def add(self, text: str, note: str = "", fixed: int | None = None, keep_space: bool = False) -> int:
        text = clean(text, keep_space)
        if fixed is not None:
            self.order.append((fixed, text, note))
            return fixed
        if text in self.ids:
            return self.ids[text]
        n = self.next
        self.next += 1
        self.ids[text] = n
        self.order.append((n, text, note))
        return n


def clean(text: str, keep_space: bool = False) -> str:
    if not keep_space:
        text = text.strip()
    if "{" in text or "}" in text:
        raise DlgError(f"braces are not allowed in message text: {text!r}")
    if " - " in text or " -- " in text or "—" in text or "–" in text:
        raise DlgError(f"no dashes in dialogue (owner rule): {text!r}")
    return text


class Option:
    def __init__(self, cond, text, target, act, low, line):
        self.cond, self.text, self.target, self.act, self.low, self.line = cond, text, target, act, low, line


class Node:
    def __init__(self, name, line):
        self.name, self.line = name, line
        self.gotos: list[tuple[str | None, str]] = []
        self.do: list[str] = []
        self.say: str | None = None
        self.opts: list[Option] = []


class Dialogue:
    def __init__(self, path: Path):
        self.path = path
        self.script = ""
        self.about: list[str] = []
        self.includes: list[str] = []
        self.head, self.bg = "-1", "-1"
        self.trigger = "talk"
        self.look = self.desc = None
        self.lvars: list[str] = []
        self.bark_timer = (25, 50)
        self.barks: list[tuple[str | None, str]] = []
        self.refuse: list[tuple[str | None, str]] = []
        self.events: dict[str, list[str]] = {}
        self.nodes: dict[str, Node] = {}
        self.node_order: list[str] = []


def parse(path: Path) -> Dialogue:
    d = Dialogue(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    i = 0
    node: Node | None = None

    def block(start: int) -> tuple[list[str], int]:
        body = []
        j = start
        while j < len(lines):
            if lines[j].strip() == "}":
                return body, j + 1
            body.append(lines[j])
            j += 1
        raise DlgError(f"{path.name}:{start}: block never closed with }}")

    while i < len(lines):
        raw = lines[i]
        s = raw.strip()
        ln = i + 1
        i += 1
        if not s or s.startswith("#"):
            continue
        word, _, rest = s.partition(" ")
        rest = rest.strip()
        try:
            if s.startswith("»"):
                word, rest = "say", s[1:].strip()
            elif s.startswith("→"):
                word, rest = "opt", s[1:].strip()
            if word == "script":
                d.script = rest.lower()
                if not re.fullmatch(r"[a-z][a-z0-9_]{0,7}", d.script):
                    raise DlgError("script names are 1-8 letters/digits")
            elif word == "about":
                d.about.append(rest)
            elif word == "include":
                d.includes.append(rest)
            elif word == "head":
                parts = rest.split()
                d.head = parts[0]
                d.bg = parts[1] if len(parts) > 1 else "-1"
            elif word == "trigger":
                if rest not in ("talk", "use"):
                    raise DlgError("trigger is talk or use")
                d.trigger = rest
            elif word == "look":
                d.look = rest
            elif word == "desc":
                d.desc = rest
            elif word == "lvar":
                if len(d.lvars) >= 7:
                    raise DlgError("at most 7 lvars (LVAR 0 stays 0)")
                d.lvars.append(rest.upper())
            elif word in ("bark", "refuse"):
                m = re.fullmatch(r"(\d+)\s+(\d+)", rest)
                if word == "bark" and m:
                    d.bark_timer = (int(m.group(1)), int(m.group(2)))
                else:
                    cm = COND_RE.match(rest)
                    cond, text = (cm.group("cond"), cm.group("rest")) if cm else (None, rest)
                    (d.barks if word == "bark" else d.refuse).append((cond, text))
            elif word == "on":
                ev = rest.rstrip("{").strip()
                if ev not in EVENTS:
                    raise DlgError(f"unknown event {ev!r}")
                body, i = block(i)
                d.events.setdefault(ev, []).extend(body)
            elif word == "node":
                if rest in ("end", "fight", "barter"):
                    raise DlgError(f"`{rest}` is a special option target; name the node something else")
                if rest in d.nodes:
                    raise DlgError(f"node {rest} defined twice")
                node = Node(rest, ln)
                d.nodes[rest] = node
                d.node_order.append(rest)
            elif node is None:
                raise DlgError(f"{word!r} outside a node")
            elif word == "goto":
                cm = COND_RE.match(rest)
                if cm:
                    node.gotos.append((cm.group("cond"), cm.group("rest").strip()))
                else:
                    node.gotos.append((None, rest))
            elif word == "do":
                if rest == "{":
                    body, i = block(i)
                    node.do.extend(body)
                else:
                    node.do.append(rest)
            elif word == "say":
                if node.say is not None:
                    raise DlgError(f"node {node.name} has two NPC lines")
                node.say = rest
            elif word in ("opt", "low"):
                m = OPT_RE.match(rest)
                if not m:
                    raise DlgError(f"bad option (need text -> target): {rest!r}")
                node.opts.append(Option(m.group("cond"), m.group("text"), m.group("target"),
                                        (m.group("act") or "").strip(), word == "low", ln))
            else:
                raise DlgError(f"unknown directive {word!r}")
        except DlgError as e:
            raise DlgError(f"{path.name}:{ln}: {e}") from None
    if not d.script:
        raise DlgError(f"{path.name}: no `script` line")
    for n in d.nodes.values():
        for _c, t in n.gotos:
            if t not in d.nodes:
                raise DlgError(f"{path.name}:{n.line}: goto to unknown node {t!r}")
        for o in n.opts:
            if o.target not in d.nodes and o.target not in ("end", "fight", "barter"):
                raise DlgError(f"{path.name}:{o.line}: option goes to unknown node {o.target!r}")
        if n.say is None and not n.gotos:
            raise DlgError(f"{path.name}:{n.line}: node {n.name} has no NPC line")
    if d.nodes and "start" not in d.nodes:
        raise DlgError(f"{path.name}: the conversation needs a `node start`")
    return d


def sub_at(code: str, msgs: Messages) -> str:
    return AT_RE.sub(lambda m: str(msgs.add(m.group(1).replace('\\"', '"'))), code)


def reply_expr(text: str, msgs: Messages) -> str:
    parts = re.split(r"\{([^{}]*)\}", text)
    if len(parts) == 1:
        return f"Reply({msgs.add(text)});"
    pieces = []
    for k, p in enumerate(parts):
        if k % 2 == 0:
            if p.strip():
                pieces.append(f"mstr({msgs.add(p, keep_space=True)})")
        else:
            pieces.append(f"({p})")
    if pieces and not pieces[0].startswith("mstr"):
        pieces.insert(0, '""')
    return f"gsay_reply(NAME, {' + '.join(pieces)});"


def compile_dlg(d: Dialogue) -> tuple[str, str]:
    msgs = Messages()
    out: list[str] = []
    w = out.append
    name_up = d.script.upper()
    look = msgs.add(d.look or "You see someone.", fixed=100)
    desc = msgs.add(d.desc or d.look or "You see someone.", fixed=101)
    assert (look, desc) == (100, 101)

    w("/*")
    w(f"   {d.script}.ssl - GENERATED by tools/dlg.py from mod/dialog_src/{d.path.name}.")
    w("   Edit the .dlg and recompile; changes made here are overwritten.")
    for a in d.about:
        w(f"   {a}")
    w("*/")
    w("")
    w(f'#define SCRIPT_REALNAME "{d.script}"')
    w("")
    w('#include "../headers/define.h"')
    w('#include "foc_ids.h"')
    for inc in d.includes:
        w(f'#include "{inc}"')
    w("")
    w(f"#define NAME    SCRIPT_{name_up}")
    w("")
    w('#include "../headers/command.h"')
    w('#include "foc_dlg.h"')
    w("")
    for k, lv in enumerate(d.lvars, start=1):
        w(f"#define LVAR_{lv:<14}({k})")
    if d.lvars:
        w("")

    entry = "talk_p_proc" if d.trigger == "talk" else "use_p_proc"
    procs = ["start", "map_enter_p_proc", "timed_event_p_proc", entry,
             "look_at_p_proc", "description_p_proc"]
    ev_proc = {"heartbeat": "critter_p_proc", "death": "destroy_p_proc",
               "hurt": "damage_p_proc", "skill": "use_skill_on_p_proc"}
    for ev, p in ev_proc.items():
        if ev in d.events:
            procs.append(p)
    for p in procs:
        w(f"procedure {p};")
    if d.barks:
        w("procedure dlg_bark;")
    if d.refuse:
        w("procedure dlg_refuse;")

    # option procedures
    opt_procs: list[tuple[str, Node, Option]] = []
    for nname in d.node_order:
        n = d.nodes[nname]
        w(f"procedure N_{nname};")
        for k, o in enumerate(n.opts):
            if o.act or o.target in ("fight", "barter"):
                pn = f"N_{nname}_{k}"
                opt_procs.append((pn, n, o))
                w(f"procedure {pn};")
    w("procedure Node999;")
    w("")
    w("variable dlg_after;")
    w("")
    if "top" in d.events:
        w(sub_at("\n".join(d.events["top"]), msgs))
        w("")

    w("procedure start begin")
    w("end")
    w("")
    w("procedure map_enter_p_proc begin")
    w("   if (is_loading_game == false) then begin")
    for line in d.events.get("enter", []):
        w("   " + sub_at(line, msgs))
    if d.barks:
        lo, hi = d.bark_timer
        w(f"      flush_add_timer_event_sec(self_obj, random({max(3, lo // 3)}, {lo}), {BARK_EVENT});")
    w("   end")
    w("end")
    w("")
    w("procedure timed_event_p_proc begin")
    if d.barks:
        lo, hi = d.bark_timer
        w("   variable b;")
        w(f"   if (fixed_param == {BARK_EVENT}) then begin")
        w("      if ((not combat_is_initialized)")
        w("          and ((critter_state(self_obj) bwand DAM_KNOCKED_DOWN) == 0)")
        w("          and (not (self_can_see_dude and (distance_dude <= 2)))) then begin")
        w("         b := dlg_bark;")
        w("         if (b > 0) then")
        w("            float_msg(self_obj, mstr(b), FLOAT_COLOR_NORMAL);")
        w("      end")
        w(f"      flush_add_timer_event_sec(self_obj, random({lo}, {hi}), {BARK_EVENT});")
        w("   end")
    for line in d.events.get("timer", []):
        w(sub_at(line, msgs))
    w("end")
    w("")
    w("procedure look_at_p_proc begin")
    w("   script_overrides;")
    w("   display_mstr(100);")
    w("end")
    w("")
    w("procedure description_p_proc begin")
    w("   script_overrides;")
    w("   display_mstr(101);")
    w("end")
    w("")

    def grouped(entries):
        groups: list[tuple[str | None, list[int]]] = []
        for cond, text in entries:
            n = msgs.add(text)
            if groups and groups[-1][0] == cond:
                groups[-1][1].append(n)
            else:
                groups.append((cond, [n]))
        return groups

    def pick(ids: list[int]) -> str:
        if len(ids) == 1:
            return str(ids[0])
        if ids == list(range(ids[0], ids[0] + len(ids))):
            return f"random({ids[0]}, {ids[-1]})"
        arr = " ".join(f"if (r == {k}) then return {v};" for k, v in enumerate(ids))
        return None if not arr else f"__RANDARR__{len(ids)}__" + arr

    def emit_chooser(pname, entries):
        w(f"procedure {pname} begin")
        w("   variable r;")
        for cond, ids in grouped(entries):
            p = pick(ids)
            if p.startswith("__RANDARR__"):
                cnt = int(p.split("__")[2])
                body = p.split("__", 3)[3]
                inner = f"r := random(0, {cnt - 1}); {body}"
                line = f"begin {inner} end"
            else:
                line = f"return {p};"
            if cond:
                w(f"   if ({cond}) then {line}")
            else:
                w(f"   {line}")
        w("   return 0;")
        w("end")
        w("")

    if d.barks:
        emit_chooser("dlg_bark", d.barks)
    if d.refuse:
        emit_chooser("dlg_refuse", d.refuse)

    w(f"procedure {entry} begin")
    w("   variable f;")
    w("   script_overrides;")
    if d.refuse:
        w("   f := dlg_refuse;")
        w("   if (f > 0) then begin")
        w("      float_msg(self_obj, mstr(f), FLOAT_COLOR_NORMAL);")
        w("      return;")
        w("   end")
    if d.nodes:
        w("   dlg_after := 0;")
        w(f"   start_gdialog(NAME, self_obj, 4, {d.head}, {d.bg});")
        w("   gsay_start;")
        w("      call N_start;")
        w("   gsay_end;")
        w("   end_dialogue;")
        w("   if (dlg_after == 1) then")
        w("      attack(dude_obj);")
    for line in d.events.get("after", []):
        w(sub_at(line, msgs))
    w("end")
    w("")

    for ev, p in ev_proc.items():
        if ev in d.events:
            w(f"procedure {p} begin")
            for line in d.events[ev]:
                w(sub_at(line, msgs))
            w("end")
            w("")

    for nname in d.node_order:
        n = d.nodes[nname]
        w(f"procedure N_{nname} begin")
        for cond, t in n.gotos:
            if cond:
                w(f"   if ({sub_at(cond, msgs)}) then begin")
                w(f"      call N_{t};")
                w("      return;")
                w("   end")
            else:
                w(f"   call N_{t};")
                w("   return;")
        for line in n.do:
            w("   " + sub_at(line.strip(), msgs))
        if n.say is not None:
            w("   " + reply_expr(n.say, msgs))
        for k, o in enumerate(n.opts):
            pn = f"N_{nname}_{k}" if (o.act or o.target in ("fight", "barter")) else (
                "Node999" if o.target == "end" else f"N_{o.target}")
            mid = msgs.add(o.text)
            call = f"NLowOption({mid}, {pn});" if o.low else f"NOption({mid}, {pn}, 004);"
            if o.cond:
                w(f"   if ({sub_at(o.cond, msgs)}) then")
                w(f"      {call}")
            else:
                w(f"   {call}")
        w("end")
        w("")

    for pn, n, o in opt_procs:
        w(f"procedure {pn} begin")
        if o.act:
            w("   " + sub_at(o.act, msgs))
        if o.target == "fight":
            w("   dlg_after := 1;")
        elif o.target == "barter":
            w("   gdialog_mod_barter(0);")
            w(f"   call N_{n.name};")
        elif o.target != "end":
            w(f"   call N_{o.target};")
        w("end")
        w("")

    w("procedure Node999 begin")
    w("end")
    ssl = "\n".join(out) + "\n"

    msg = [f"# {d.script}.msg - GENERATED by tools/dlg.py from mod/dialog_src/{d.path.name}"]
    for n, text, _note in sorted(msgs.order):
        msg.append(f"{{{n}}}{{}}{{{text}}}")
    return ssl, "\n".join(msg) + "\n"


def register(script: str) -> bool:
    lines = SCRIPTS_TXT.read_text(encoding="utf-8").splitlines()
    names = {l.split("#")[0].strip().lower() for l in lines}
    if f"{script}.int" in names:
        return False
    text = SCRIPTS_TXT.read_text(encoding="utf-8")
    nl = "\r\n" if "\r\n" in text else "\n"
    if not text.endswith(("\n", "\r\n")):
        text += nl
    SCRIPTS_TXT.write_text(text + f"{script}.int" + nl, encoding="utf-8", newline="")
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("names", nargs="*")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    files = ([SRC / f"{n}.dlg" for n in args.names] if args.names
             else sorted(SRC.glob("*.dlg")))
    bad = 0
    for f in files:
        try:
            d = parse(f)
            ssl, msg = compile_dlg(d)
        except DlgError as e:
            print(f"ERROR {e}")
            bad += 1
            continue
        if args.check:
            print(f"ok {f.name}: {len(d.nodes)} nodes")
            continue
        (SSL_OUT / f"{d.script}.ssl").write_text(ssl, encoding="cp1252", newline="\r\n")
        (MSG_OUT / f"{d.script}.msg").write_text(msg, encoding="cp1252", newline="\r\n")
        new = register(d.script)
        print(f"{f.name} -> {d.script}.ssl / .msg ({len(d.nodes)} nodes)"
              + (" [registered in scripts.txt]" if new else ""))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
