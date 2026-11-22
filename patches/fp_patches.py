"""Falcon Punch: our changes to the lifted C, applied by our copy of the builder (nx2/chunks.py edit_c, after
oot_patches.apply). Same idea as nx2/oot_patches.py: find the lift's exact text in a function and replace it.

Install into a builder copy: tools/fp_builder.sh (copies this file and fp_item_functions.txt into
<builder>/usr/share/hookshot/nx2/ and adds the hook). All of nx2/ is in the lift key, so a change here lifts again.

The item: the Falcon Punch takes over Pouch_Amiibo, stored AssignableItem value 51. The game logic must treat it as
the Hammer (7), while the AS still sees 51 (tools/build_asb.py gives 51 the hammer's branches, with punch leaves).
The player's current item is player+0x7d8; in the functions listed in fp_item_functions.txt (tools/find_item_sites.py)
every load of it goes through fp_item(): 51 reads as 7.
"""
import glob
import os
import re

MARK = "/* (fp_patches) */"
HERE = os.path.dirname(os.path.abspath(__file__))
FP_VALUE, HAMMER = 51, 7
HELPER = ("\n/* (fp_patches) Falcon Punch: the item value 51 behaves as the Hammer (7) in the game logic */\n"
          "static inline uint64_t fp_item(uint64_t v) { return (uint32_t)v == %du ? %du : v; }\n" % (FP_VALUE, HAMMER))
LOAD = re.compile(r"recomp_load32\(c,(c->x\[\d+\]) \+ 2008\)")


def _func_span(src, name):
    m = re.search(r"^void %s\(Ctx \*__restrict A64_NOESC c\) \{$" % re.escape(name), src, re.M)
    if not m:
        return None
    end = src.index("\n}\n", m.end())
    return m.start(), end + 3


def _functions():
    p = os.path.join(HERE, "fp_item_functions.txt")
    return [l.strip() for l in open(p) if l.strip() and not l.startswith("#")]


def apply(gen):
    wanted = set(_functions())
    found, loads = set(), 0
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
            body = src[span[0]:span[1]]
            new, n = LOAD.subn(r"fp_item(recomp_load32(c,\1 + 2008))", body)
            if n:
                src = src[:span[0]] + new + src[span[1]:]
                loads += n
                changed = True
            found.add(name)
        if changed:
            if "fp_item(uint64_t v)" not in src:
                inc = src.index('#include "a64.h"\n') + len('#include "a64.h"\n')
                src = src[:inc] + HELPER + src[inc:]
            open(path, "w", encoding="utf-8").write(src)
    missing = wanted - found
    if missing:
        raise RuntimeError(f"fp_patches: {len(missing)} functions not found, e.g. {sorted(missing)[:5]}")
    print(f"fp_patches: fp_item() at {loads} loads of player+0x7d8 in {len(found)} functions", flush=True)
