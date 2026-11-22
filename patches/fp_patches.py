"""Falcon Punch: our changes to the lifted C, applied by our copy of the builder (nx2/chunks.py edit_c, after
oot_patches.apply). The same idea as nx2/oot_patches.py: find the lift's exact text in a function and replace it.

Install into a builder copy: tools/fp_builder.sh (it copies this file into <builder>/usr/share/hookshot/nx2/ and adds
the hook). Every change here is in the lift key (all of nx2/ is), so the next build lifts again.
"""
import glob
import os
import re

MARK = "/* (fp_patches) */"


def _func_span(src, name):
    m = re.search(r"^void %s\(Ctx \*__restrict A64_NOESC c\) \{$" % re.escape(name), src, re.M)
    if not m:
        return None
    end = src.index("\n}\n", m.end())
    return m.start(), end + 3


def patch_function(gen, name, old, new, count=1):
    """Replace `old` by `new` inside lifted function `name` (exactly `count` times). Returns the file changed"""
    for path in sorted(glob.glob(os.path.join(gen, "code_*.c"))):
        src = open(path, encoding="utf-8").read()
        span = _func_span(src, name)
        if not span:
            continue
        body = src[span[0]:span[1]]
        n = body.count(old)
        if n != count:
            raise RuntimeError(f"fp_patches: {name}: expected {count} of {old!r}, found {n}")
        body = body.replace(old, new)
        open(path, "w", encoding="utf-8").write(src[:span[0]] + body + src[span[1]:])
        return path
    raise RuntimeError(f"fp_patches: function {name} not found")


def apply(gen):
    # Marker only (pipeline check): a comment at the top of one function.
    patch_function(gen, "f_83036730", "{\n", "{ " + MARK + "\n")
    print("fp_patches: applied", flush=True)
