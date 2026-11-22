"""Player_Adult.root.asb for the Falcon Punch item.

    uv run python tools/build_asb.py [--value 51] [--replace-hammer] [--out out/mod/work/Player_Adult.root.asb]

- every IntSelector on bb:UsingItem with a branch for 7 (Hammer) gets the same branch for VALUE (the item's stored
  AssignableItem value), so the item holds, equips and moves like the hammer;
- where that branch reaches the hammer's vertical attack, VALUE gets a copy of the path whose animations are the
  Falcon Punch ones (ANIM_MAP); untouched subtrees are shared, not copied.
--replace-hammer: test mode, the hammer's own branch (7) is pointed at the punch path too (no code change needed).
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import asb as A  # noqa: E402
from asb_edit import Editor, check  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANIM_MAP = {
    "Hammer_Attack_Vertical_Advance": "FalconPunch",
    "Hammer_Attack_Vertical_AdvanceZero": "FalconPunch_AdvanceZero",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(ROOT, "unpacked/Player_Adult.root.asb"))
    ap.add_argument("--value", type=int, default=51)
    ap.add_argument("--replace-hammer", action="store_true")
    ap.add_argument("--out", default=os.path.join(ROOT, "out/mod/work/Player_Adult.root.asb"))
    a = ap.parse_args()
    e = Editor(open(a.src, "rb").read())
    nodes = e.a.nodes

    contains = {}

    def has_target(i, seen=()):
        if i in contains:
            return contains[i]
        if i in seen:
            return False
        n = nodes[i]
        r = n.get("anim") in ANIM_MAP or any(has_target(c, seen + (i,)) for c in n["children"])
        contains[i] = r
        return r

    clones = {}

    def clone_path(i):
        if not has_target(i):
            return i
        if i in clones:
            return clones[i]
        n = nodes[i]
        j = e.clone_node(i, anim=ANIM_MAP.get(n.get("anim")) if n["type"] == 3 else None)
        clones[i] = j
        for k, c in enumerate(n["children"]):
            cc = clone_path(c)
            if cc != c:
                e.set_child(j, k, cc)
        return j

    sel = [n for n in nodes if n["type"] == 8 and n["sel"] == "bb:UsingItem"]
    added = attack = 0
    for n in sel:
        br = e.int_branches(n["index"])
        vals = [v for v, _ in br]
        if 7 not in vals or a.value in vals:
            continue
        tgt = dict((v, t) for v, t in br if v is not None)[7]
        new = clone_path(tgt)
        if new != tgt:
            attack += 1
            print(f"attack branch: #{n['index']} [7] -> #{tgt}; [{a.value}] -> #{new}")
            if a.replace_hammer:
                k = vals.index(7)
                e.set_child(n["index"], k, new)
        e.add_int_branch(n["index"], a.value, new)
        added += 1
    data = e.build()
    b = check(data)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    open(a.out, "wb").write(data)
    print(f"{added} selectors got [{a.value}] ({attack} to the punch), {len(clones)} nodes cloned, "
          f"{len(e.new_strings)} new strings; {len(data)} bytes ({len(data) - len(e.d):+d}); nodes {len(b.nodes)}")
    for i in clones.values():
        print("  ", b.describe(i))


if __name__ == "__main__":
    main()
