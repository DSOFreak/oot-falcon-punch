"""(Triforce) Code hooks: a mod's own C, built into the game, and the places of the game's code that call it.

A patch file (.ips, .pchtxt: nx2/code_mods.py) can change the game's instructions but cannot add code: a code cave is
refused, the translator has not been tried on one. A hook is the other way to the same end, and the one this port
uses for its own additions (nx2/oot_patches.py and host/oot_sprint.c): the new code is C beside the translated game,
and the translated C calls it at a named place. A mod carries both in a folder of its own:

    <game folder>/mods/<name>/code/hooks.txt    where the game's code calls the mod (below)
    <game folder>/mods/<name>/code/*.c, *.h     the mod's C: compiled as the runtime's own files are, linked into the game

Like a patch file, a hook is built in, not loaded: a build reads the mods folder (make_game.py: stage), applies the
hooks to the C the lift wrote (chunks.py edit_c: apply) and compiles the mod's files (build.py: sources). The hooks are
part of the lift key (make_game.py lift_key: key_files), so a mod added, taken out, switched off or edited makes the
next build translate the game again, and nothing else does. A hook that finds no place stops the build with a line
that names it: switch the mod off (a '-' or '_' before its folder's name) and build again.

hooks.txt, one hook a line ('#' starts a comment; a function is its address in the game, 0x80953270, as the lift names
it: f_80953270):

    game <build id>                              the build the addresses are for: the first 16 hex digits of its
                                                 id or more (as a cheat file is named). Needed, once, before the hooks
    before <function> <hook>                     int hook(Ctx *c): first thing in the function, with its arguments in
                                                 c->x[0..7]. A return other than 0 skips the function (the hook has
                                                 then put its result in c->x[0])
    after <function> <hook>                      void hook(Ctx *c): when the function has returned, however it did
                                                 (a tail call's result included), with its result in c->x[0]
    after-call <callee> <hook> in <function>...  void hook(Ctx *c): after each call of <callee> in the named functions
                                                 only (what one caller gets, where others must see the game's own)
    before-icall <function> <hook>               void hook(Ctx *c): before each indirect call or jump of the function
                                                 (a virtual call: its arguments are in c->x[0..7])
    load32 <offset> <hook> in <function>...      uint64_t hook(Ctx *c, uint64_t value, uint64_t address): each
                                                 32-bit load from <register> + <offset> in the named functions
                                                 gives the hook's value (address: where it was loaded from)

A hook's name is a C identifier that one of the mod's .c files defines. The mod's C sees the game as the runtime does
(host/mod_api.h: the registers, the game's memory, the log, sounds); it is trusted code, as the runtime is: a mod with
a code folder can do on the player's machine what any program can, which a patch file or a RomFS mod cannot. The build
names every mod whose code it builds in, and the game's log does at each start (host/mod_api.c).

Standard library only. The lift imports it (chunks.py), so it is part of the lift key like the rest of nx2/; the
mods' hooks are too, by the staged hooks.json (key_files).
"""
import json
import os
import re
import shutil

import code_mods

FOLDER = "code"
HOOKS = "hooks.txt"
STAGE = "mod_code"           # <work>/mod_code: the active mods' code folders as this build reads them
STAGED = "hooks.json"        # <work>/mod_code/hooks.json: their hooks, parsed
TABLE = "mod_code_table.c"   # <work>/mod_code/mod_code_table.c: the mods built in, for the game's log
KINDS = ("before", "after", "after-call", "before-icall", "load32")
IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ADDRESS = re.compile(r"^0x([0-9a-fA-F]{1,16})$")
DEFINITION = "void %s(Ctx *__restrict A64_NOESC c) {"
INCLUDE = '#include "a64.h"\n'


class Refused(ValueError):
    """A hooks.txt that is not built in, or a hook without a place; the text says why"""


def function_name(word, where):
    m = ADDRESS.match(word)
    if not m:
        raise Refused("%s: %r is not a function's address (0x...)" % (where, word))
    return "f_%08x" % int(m.group(1), 16)


def hook_name(word, where):
    if not IDENT.match(word) or word.startswith("f_"):
        raise Refused("%s: %r is not a hook's name (a C identifier of the mod's, not f_...)" % (where, word))
    return word


def parse(text, where=HOOKS):
    """-> (build id or None, [hook]). A hook: {"kind", "hook", "functions": [...], and "callee" or "offset"}"""
    build, hooks = None, []
    for n, line in enumerate(text.splitlines(), 1):
        w = line.split("#", 1)[0].split()
        if not w:
            continue
        at = "%s line %d" % (where, n)
        if w[0] == "game":
            if len(w) != 2 or not re.match(r"^[0-9a-fA-F]{16,64}$", w[1]):
                raise Refused("%s: game <build id> (hex, 16 digits or more)" % at)
            if build is not None:
                raise Refused("%s: a second game line" % at)
            build = w[1].upper()
            continue
        if w[0] not in KINDS:
            raise Refused("%s: %r is not a kind of hook (%s)" % (at, w[0], ", ".join(KINDS)))
        if build is None:
            raise Refused("%s: no game <build id> line before the first hook" % at)
        kind = w[0]
        if kind in ("before", "after", "before-icall"):
            if len(w) != 3:
                raise Refused("%s: %s <function> <hook>" % (at, kind))
            hooks.append({"kind": kind, "hook": hook_name(w[2], at), "functions": [function_name(w[1], at)]})
            continue
        if len(w) < 5 or w[3] != "in":
            raise Refused("%s: %s <%s> <hook> in <function>..." % (at, kind, "callee" if kind == "after-call" else "offset"))
        h = {"kind": kind, "hook": hook_name(w[2], at), "functions": [function_name(x, at) for x in w[4:]]}
        if kind == "after-call":
            h["callee"] = function_name(w[1], at)
        else:
            try:
                h["offset"] = int(w[1], 0)
            except ValueError:
                raise Refused("%s: %r is not an offset" % (at, w[1])) from None
            if h["offset"] < 0:
                raise Refused("%s: a negative offset" % at)
        hooks.append(h)
    return build, hooks


def code_folders(root):
    """[(the mod's path under the mods folder with '/', its code folder)] of the active mods, in the mods' order"""
    out = []
    for rel, path in code_mods.find_mods(root):
        d = os.path.join(path, FOLDER)
        if os.path.isfile(os.path.join(d, HOOKS)):
            out.append((rel, d))
    return out


def stage_name(k, rel):
    return "%02d_%s" % (k, re.sub(r"[^A-Za-z0-9]+", "_", rel).strip("_") or "mod")


def stage(mods_root, work, build_ids, say=print):
    """make_game.py, before the lift's key is taken: the active mods' code folders copied to <work>/mod_code (what the
    lift and the compile read: the mods folder may change while a build runs), their hooks parsed into hooks.json.
    build_ids: the game's modules' build ids (hex); a mod for another build is refused, with a line, as a patch file
    is. Returns [{"mod", "state": "built in" | "refused", "note", "hooks", "files"}] in the mods' order"""
    top = os.path.join(work, STAGE)
    shutil.rmtree(top, ignore_errors=True)
    entries, staged = [], []
    for k, (rel, folder) in enumerate(code_folders(mods_root)):
        entry = {"mod": rel, "state": "refused", "note": "", "hooks": 0, "files": 0}
        entries.append(entry)
        try:
            with open(os.path.join(folder, HOOKS), encoding="utf-8") as f:
                build, hooks = parse(f.read(), "%s/%s/%s" % (rel, FOLDER, HOOKS))
            if build is None:
                raise Refused("%s/%s/%s: no game <build id> line" % (rel, FOLDER, HOOKS))
            if not any(b.upper().startswith(build) for b in build_ids):   # (its first 16 digits or more, as a cheat file's name)
                raise Refused("for another build of the game (%s)" % build)
            sources = sorted(f for f in os.listdir(folder) if f.endswith(".c"))
            if hooks and not sources:
                raise Refused("hooks, but no .c file that could define them")
        except (Refused, OSError, UnicodeDecodeError) as e:
            entry["note"] = str(e)
            say("code hooks: %s: refused: %s" % (rel, e))
            continue
        name = stage_name(k, rel)
        dst = os.path.join(top, name)
        os.makedirs(dst)
        files = sorted(f for f in os.listdir(folder) if f.endswith((".c", ".h")) or f == HOOKS)
        for f in files:
            shutil.copyfile(os.path.join(folder, f), os.path.join(dst, f))
        staged.append({"mod": rel, "folder": name, "sources": sources, "hooks": hooks})
        entry.update(state="built in", hooks=len(hooks), files=len(files) - 1)
        say("code hooks: %s: %d hooks, %d files of C: built into the game (a mod's code can do what any program can)"
            % (rel, len(hooks), len(files) - 1))
    if staged:
        with open(os.path.join(top, STAGED), "w", encoding="utf-8") as f:
            json.dump(staged, f, indent=1, sort_keys=True)
        with open(os.path.join(top, TABLE), "w", encoding="utf-8") as f:
            f.write("/* (nx2/code_hooks.py) The mods whose code this game is built with, for the log (host/mod_api.c) */\n"
                    "const char *const hos_mod_code_built[] = {\n%s    0 };\n"
                    % "".join('    "%s (%d hooks)",\n' % (s["mod"].replace("\\", "/").replace('"', "'"), len(s["hooks"]))
                              for s in staged))
    return entries


def staged(work):
    p = os.path.join(work, STAGE, STAGED)
    if not os.path.isfile(p):
        return []
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def key_files(work):
    """The files the lift key hashes for the hooks (make_game.py lift_key): what apply() reads. The mods' C is not
    among them: it is compiled after the lift, and its objects are keyed by their own source (build.py)"""
    p = os.path.join(work, STAGE, STAGED)
    return [p] if os.path.isfile(p) else []


def sources(work):
    """build.py: [(a name for the object file, the .c file, its folder)] of the staged mods, the table last"""
    out = []
    for s in staged(work):
        d = os.path.join(work, STAGE, s["folder"])
        out += [("%s_%s" % (s["folder"], f[:-2]), os.path.join(d, f), d) for f in s["sources"]]
    table = os.path.join(work, STAGE, TABLE)
    if os.path.isfile(table):
        out.append(("table", table, os.path.dirname(table)))
    return out


def headers(folder):
    """The bytes of a staged mod's headers: its objects' dependencies beside the runtime's own"""
    return b"".join(open(os.path.join(folder, f), "rb").read() for f in sorted(os.listdir(folder)) if f.endswith(".h"))


# ---- the edits of the lifted C

def span(src, name):
    """(start, end) of a function's definition in a file's text, or None"""
    at = src.find("\n" + DEFINITION % name + "\n")
    if at < 0:
        return None
    return at + 1, src.index("\n}\n", at) + 3


CALL = r"(c->x\[30\] = 0x[0-9a-f]+ULL; %s\(c\);)"
ICALL = re.compile(r"(\{ uint64_t _t = c->x\[\d+\]; c->x\[30\] = 0x[0-9a-f]+ULL; A64_ICALL\(c, _t\); \}"
                   r"|A64_IJUMP\(c, c->x\[\d+\]\); return;)")
LOAD32 = r"recomp_load32\(c,(c->x\[\d+\]) \+ %d\)"


def edit(body, name, hook):
    """One hook on one function's text -> (the text, the places it found)"""
    kind, fn = hook["kind"], hook["hook"]
    if kind == "after-call":
        return re.subn(CALL % re.escape(hook["callee"]), lambda m: "%s %s(c);" % (m.group(1), fn), body)
    if kind == "before-icall":
        return ICALL.subn(lambda m: "{ %s(c); %s }" % (fn, m.group(1)), body)
    if kind == "load32":
        return re.subn(LOAD32 % hook["offset"],
                       lambda m: "%s(c, %s, %s + %d)" % (fn, m.group(0), m.group(1), hook["offset"]), body)
    raise AssertionError(kind)


def wrap(body, name, before, after):
    """The function under another name, and one of its own name that calls the hooks around it. Whoever calls the
    function, by name or through the function table, calls this one"""
    inner = "mod_hooked_" + name
    head = DEFINITION % name
    assert body.startswith(head)
    calls = "".join("    if (%s(c)) return;\n" % h for h in before) + "    %s(c);\n" % inner + \
        "".join("    %s(c);\n" % h for h in after)
    return "%s%s\n%s\n%s}\n" % (DEFINITION % inner, body[len(head):].rstrip("\n"), head, calls)


def declarations(hooks):
    out, seen = [], set()
    for h in hooks:
        if h["hook"] in seen:
            continue
        seen.add(h["hook"])
        out.append({"before": "extern int %s(Ctx *c);", "load32": "extern uint64_t %s(Ctx *c, uint64_t value, uint64_t address);"}
                   .get(h["kind"], "extern void %s(Ctx *c);") % h["hook"])
    return "/* (nx2/code_hooks.py) the mods' hooks this file calls */\n" + "\n".join(out) + "\n"


def apply(gen, work, say=print):
    """chunks.py edit_c, after the port's own patches: the staged hooks on the lifted C. Raises Refused where a hook
    finds no place (a function the lift did not write, a call or a load that is not in it): the build stops there"""
    mods = staged(work)
    if not mods:
        return 0
    by_function = {}
    for m in mods:
        for h in m["hooks"]:
            for f in h["functions"]:
                by_function.setdefault(f, []).append((m["mod"], h))
    found, places = set(), 0
    for path in sorted(f for f in os.listdir(gen) if f.startswith("code_") and f.endswith(".c")):
        path = os.path.join(gen, path)
        with open(path, encoding="utf-8") as f:
            src = f.read()
        used = []
        for name in sorted(by_function):
            if (DEFINITION % name) not in src:
                continue
            at = span(src, name)
            if not at:
                continue
            found.add(name)
            body = src[at[0]:at[1]]
            before, after = [], []
            for mod, h in by_function[name]:
                if h["kind"] == "before":
                    before.append(h["hook"])
                elif h["kind"] == "after":
                    after.append(h["hook"])
                else:
                    body, n = edit(body, name, h)
                    if not n:
                        raise Refused("code hooks: %s: %s %s finds no place in %s"
                                      % (mod, h["kind"], h.get("callee", h.get("offset", "")), name))
                    places += n
                used.append(h)
            if before or after:
                body = wrap(body, name, before, after)
                places += len(before) + len(after)
            src = src[:at[0]] + body + src[at[1]:]
        if used:
            inc = src.index(INCLUDE) + len(INCLUDE)
            src = src[:inc] + declarations(used) + src[inc:]
            with open(path, "w", encoding="utf-8") as f:
                f.write(src)
    missing = sorted(set(by_function) - found)
    if missing:
        mod = by_function[missing[0]][0][0]
        raise Refused("code hooks: %s: the game has no function %s (%d of its hooks' functions are not in the "
                      "translated code)" % (mod, missing[0], len(missing)))
    say("code hooks: %d mods, %d functions, %d places in the translated code" % (len(mods), len(by_function), places))
    return places
