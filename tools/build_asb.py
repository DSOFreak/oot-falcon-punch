"""Player_Adult.root.asb (+ its AsNode BAEV) for the Falcon Punch item.

    uv run python tools/build_asb.py [--value 51] [--replace-hammer] [--src ...] [--out ...]

1. Every IntSelector on bb:UsingItem with a branch for 7 (Hammer) gets the same branch for VALUE (the item's
   stored AssignableItem value): the item equips, holds, moves and attacks like the hammer, through the hammer's own
   nodes, so the attack keeps the hammer's AS events (AtCollision 14-24, sounds, cancels: Event node #16179).
2. Each SkeletalAnimation that plays a hammer vertical attack (ANIM_MAP) is replaced, in its parents, by a new
   IntSelector on bb:UsingItem: VALUE -> a copy of the leaf playing the punch, default -> the original leaf.
   (Copying a node that owns Event nodes crashes the game, whether the Event nodes are shared or copied, so only
   leaves without events are copied.)
3. The follow-through (command CutHammerAfter): each slope leaf of its blender gets a UsingItem selector,
   VALUE -> FalconPunch_After, default -> the leaf (the blender keeps the events that end the state).
--replace-hammer: test mode, the new selectors play the punch for every item (the hammer too), no code change needed.
"""
import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
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
    ap.add_argument("--no-after", dest="after", action="store_false", help="keep the hammer's follow-through")
    ap.add_argument("--out", default=os.path.join(ROOT, "out/mod/work/Player_Adult.root.asb"))
    ap.add_argument("--baev-src", default=os.path.join(ROOT, "unpacked/Player_Adult.root.baev"))
    ap.add_argument("--baev-out", default=os.path.join(ROOT, "out/mod/work/Player_Adult.root.baev"))
    a = ap.parse_args()
    e = Editor(open(a.src, "rb").read())
    nodes = e.a.nodes

    # 1. [VALUE] next to every UsingItem [7]
    sel = [n for n in nodes if n["type"] == 8 and n["sel"] == "bb:UsingItem"]
    template = None
    added = 0
    for n in sel:
        br = e.int_branches(n["index"])
        vals = [v for v, _ in br]
        if template is None and not n["events"]:
            template = n["index"]
        if 7 not in vals or a.value in vals:
            continue
        e.add_int_branch(n["index"], a.value, dict((v, t) for v, t in br if v is not None)[7])
        added += 1

    # 2. the attack leaves: a UsingItem selector in front of each
    tprefix, _ = e.parse_body(template)
    wrapped = []
    for leaf in [n for n in nodes if n["type"] == 3 and n.get("anim") in ANIM_MAP]:
        i = leaf["index"]
        assert not leaf["events"], f"leaf #{i} owns Event nodes"
        punch = e.clone_node(i, anim=ANIM_MAP[leaf["anim"]], events="drop")
        s = e.clone_node(template, events="drop")
        default = punch if a.replace_hammer else i
        e.set_body(s, tprefix, {"child": [struct.pack("<iiI", 0, a.value, punch), struct.pack("<iiI", 0, 0, default)]})
        for p in e.a.parents.get(i, []):
            for k, c in enumerate(nodes[p]["children"]):
                if c == i:
                    e.set_child(p, k, s)
        wrapped.append((i, s, punch))

    # 3. the follow-through (command CutHammerAfter): its slope blender owns the events that end the state
    #    (AnmSeqCancel at 44, cancels, FootIK), so it stays; each of its leaves gets a UsingItem selector:
    #    VALUE -> FalconPunch_After (a recovery, long enough to reach frame 44), default -> the slope leaf
    if a.after:
        blender = e.command_root("CutHammerAfter")
        rec = e.clone_node(wrapped[0][2], anim="FalconPunch_After", events="drop")
        for k, leaf in enumerate(nodes[blender]["children"]):
            s = e.clone_node(template, events="drop")
            default = rec if a.replace_hammer else leaf
            e.set_body(s, tprefix, {"child": [struct.pack("<iiI", 0, a.value, rec), struct.pack("<iiI", 0, 0, default)]})
            e.set_child(blender, k, s)
        print(f"CutHammerAfter: {len(nodes[blender]['children'])} slope leaves of #{blender} wrapped "
              f"([{a.value}] -> FalconPunch_After #{rec})")

    data = e.build()
    b = check(data)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    open(a.out, "wb").write(data)
    print(f"{added} UsingItem selectors got [{a.value}]; {len(wrapped)} attack leaves wrapped; "
          f"{len(data)} bytes ({len(data) - len(e.d):+d}); nodes {len(b.nodes)}")
    for i, s, punch in wrapped:
        print(f"   #{i} -> {b.describe(s)} {b.nodes[s]['conds']} -> {[b.describe(c) for c in b.nodes[s]['children']]}")
    # (no copied Event nodes: the AsNode BAEV stays as it is)
    if os.path.exists(a.baev_src):
        open(a.baev_out, "wb").write(open(a.baev_src, "rb").read())


if __name__ == "__main__":
    main()
