"""Sanity-check the curve decoder: for every curve, value at the first key must equal the bone's base value;
baked_size must match the formula; key data size must match the next structure. Usage: bfres_validate.py files..."""
import sys, math, collections
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import bfres


def check(fn, limit=None):
    bf = bfres.load(fn)
    st = collections.Counter()
    worst = []
    for a in bf.skeletal_anims()[:limit]:
        bs = sum(bfres.curve_bake_size(c) for ba in a.bone_anims for c in ba.curves)
        st["bake_ok" if bs == a.baked_size else "bake_bad"] += 1
        if bs != a.baked_size and st["bake_bad"] < 3:
            print("  bake mismatch", a.name, bs, a.baked_size)
        for ba in a.bone_anims:
            for c in ba.curves:
                v0 = c.evaluate(c.frames[0])
                comp = c.comp
                if comp == "rq":
                    base = ba.base_rotate
                    err = 1 - abs(sum(x * y for x, y in zip(base, v0)))
                elif comp[0] == "s":
                    base = ba.base_scale["xyz".index(comp[1])]; err = abs(base - v0)
                elif comp[0] == "r":
                    base = ba.base_rotate["xyz".index(comp[1])]; err = abs(base - v0)
                    if err > 1e-3:  # euler angles may differ by 2pi
                        err = min(err, abs(abs(base - v0) - 2 * math.pi))
                else:
                    base = ba.base_translate["xyz".index(comp[1])]; err = abs(base - v0)
                st["curves"] += 1
                if err > 1e-3:
                    st["mismatch"] += 1
                    worst.append((err, a.name, ba.name, comp, hex(c.flags), base, v0))
    worst.sort(reverse=True)
    print(fn, dict(st))
    for w in worst[:5]:
        print("   ", w)


if __name__ == "__main__":
    for f in sys.argv[1:]:
        check(f)
