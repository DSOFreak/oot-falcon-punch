"""Falcon Punch: our changes to the lifted C, applied by our copy of the builder (nx2/chunks.py edit_c, after
oot_patches.apply). Same idea as nx2/oot_patches.py: find the lift's exact text in a function and replace it.

Install into a builder copy: tools/fp_builder.sh (copies this file and fp_item_functions.txt into
<builder>/usr/share/hookshot/nx2/ and adds the hook). All of nx2/ is in the lift key, so a change here lifts again.

The item takes over Pouch_Amiibo, stored AssignableItem value 51 (the wheel and the HUD show it as Falcon Punch).
Design: the game logic gets the real Hammer, only the AS knows it is the punch.
1. GETTER: f_8019b6e0 reads the equipped item from GameData (PlayerStatus.AssignableItem). In the game-logic
   callers (GETTER_CALLERS; not the UI ones at 0x833.../0x834..., so the HUD keeps 51) its result goes through
   fp_item(): 51 -> 7. The item component, the use handler and player+0x7d8 then hold 7: the hammer, in full.
   f_830350a0 (the player's per-frame item update, current button) also records fp_punch_equipped.
2. AS: the writes of bb:UsingItem give 7 back as 51 while the punch is equipped, so tools/build_asb.py's [51]
   branches (hammer nodes, punch leaves) play. By name ("UsingItem") in f_82e57c30 and f_8305faa0, by its index
   (player+0x1334) in f_826d02e0 and f_826d05c0: all four read player+0x7d8 (AS_WRITERS). And f_83035be0, the
   item component's setter (equip/draw), passes the item itself to the blackboard (vtable +0x70, index
   player+0x1334): its value goes through fp_as() before that call (AS_SETTER).
3. LOAD (first attempt, kept): in the functions of fp_item_functions.txt (tools/find_item_sites.py) every load of
   player+0x7d8 goes through fp_item(). With 1. the field no longer holds 51, so this is a fallback only.
"""
import glob
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
FP_VALUE, HAMMER = 51, 7
HELPER = ("\n/* (fp_patches) Falcon Punch: the item value 51 behaves as the Hammer (7) in the game logic */\n"
          "__attribute__((weak)) volatile int fp_punch_equipped;\n"
          "static inline uint64_t fp_item(uint64_t v) { return (uint32_t)v == %du ? %du : v; }\n"
          "static inline uint64_t fp_as(uint64_t v) { return ((uint32_t)v == %du && fp_punch_equipped) ? %du : v; }\n"
          % (FP_VALUE, HAMMER, HAMMER, FP_VALUE))
LOAD = re.compile(r"recomp_load32\(c,(c->x\[\d+\]) \+ 2008\)")
GETTER_CALL = re.compile(r"(c->x\[30\] = 0x[0-9a-f]+ULL; f_8019b6e0\(c\);)")
GETTER_CALLERS = """f_802ebd20 f_80609d00 f_80a8e0d0 f_80a8ef20 f_80a913b0 f_80a93060 f_80a95ef0 f_80a96770 f_80bcd7d0
    f_80c225d0 f_8112d570 f_81153f80 f_81231c00 f_828e2ca0 f_829364c0 f_82a3d940 f_830350a0""".split()
FLAG_SETTER = "f_830350a0"
AS_WRITERS = ["f_82e57c30", "f_8305faa0", "f_826d02e0", "f_826d05c0"]
AS_SETTER = ("f_83035be0", "A64_IJUMP(c, c->x[3]); return;")


def _func_span(src, name):
    m = re.search(r"^void %s\(Ctx \*__restrict A64_NOESC c\) \{$" % re.escape(name), src, re.M)
    if not m:
        return None
    end = src.index("\n}\n", m.end())
    return m.start(), end + 3


def _functions():
    p = os.path.join(HERE, "fp_item_functions.txt")
    return [l.strip() for l in open(p) if l.strip() and not l.startswith("#")]


def _edit(name, body):
    """-> (new body, {kind: count})"""
    n = {}
    if name in LOAD_FUNCS:
        body, n["load"] = LOAD.subn(r"fp_item(recomp_load32(c,\1 + 2008))", body)
    if name in GETTER_CALLERS:
        rep = r"\1 fp_punch_equipped = ((uint32_t)c->x[0] == %du); c->x[0] = fp_item(c->x[0]);" % FP_VALUE \
            if name == FLAG_SETTER else r"\1 c->x[0] = fp_item(c->x[0]);"
        body, n["getter"] = GETTER_CALL.subn(rep, body)
    if name in AS_WRITERS:
        body, n["as"] = LOAD.subn(r"fp_as(recomp_load32(c,\1 + 2008))", body)
    if name == AS_SETTER[0]:
        n["as_setter"] = body.count(AS_SETTER[1])
        body = body.replace(AS_SETTER[1], "c->x[2] = fp_as(c->x[2]); " + AS_SETTER[1])
    return body, n


LOAD_FUNCS = set()


def apply(gen):
    LOAD_FUNCS.update(_functions())
    wanted = LOAD_FUNCS | set(GETTER_CALLERS) | set(AS_WRITERS) | {AS_SETTER[0]}
    found, total = set(), {}
    per_func = {}
    for path in sorted(glob.glob(os.path.join(gen, "code_*.c"))):
        src = open(path, encoding="utf-8").read()
        names = [n for n in wanted if ("void %s(Ctx *__restrict" % n) in src]
        if not names:
            continue
        changed = False
        for name in names:
            span = _func_span(src, name)
            if not span:
                continue
            new, n = _edit(name, src[span[0]:span[1]])
            if any(n.values()):
                src = src[:span[0]] + new + src[span[1]:]
                changed = True
                for k, v in n.items():
                    total[k] = total.get(k, 0) + v
                    per_func.setdefault((name, k), v)
            found.add(name)
        if changed:
            if "fp_item(uint64_t v)" not in src:
                inc = src.index('#include "a64.h"\n') + len('#include "a64.h"\n')
                src = src[:inc] + HELPER + src[inc:]
            open(path, "w", encoding="utf-8").write(src)
    missing = wanted - found
    if missing:
        raise RuntimeError(f"fp_patches: {len(missing)} functions not found, e.g. {sorted(missing)[:5]}")
    for name in GETTER_CALLERS:
        if not per_func.get((name, "getter")):
            raise RuntimeError(f"fp_patches: no f_8019b6e0 call found in {name}")
    for name in AS_WRITERS:
        if per_func.get((name, "as")) != 1:
            raise RuntimeError(f"fp_patches: expected one player+0x7d8 load in {name}")
    if per_func.get((AS_SETTER[0], "as_setter")) != 1:
        raise RuntimeError(f"fp_patches: expected one indirect call in {AS_SETTER[0]}")
    print(f"fp_patches: {total} (load: player+0x7d8 loads, getter: f_8019b6e0 calls, as: UsingItem writes)", flush=True)
