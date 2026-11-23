"""Player_Adult.root.asb (+ its AsNode BAEV) for the Falcon Punch item.

    uv run python tools/build_asb.py [--value 51] [--replace-hammer] [--src ...] [--out ...]

1. Every IntSelector on bb:UsingItem with a branch for 7 (Hammer) gets the same branch for VALUE (the item's
   stored AssignableItem value): the item equips, holds, moves and attacks like the hammer, through the hammer's own
   nodes, so the attack keeps the hammer's AS events (AtCollision 14-24, sounds, cancels: Event node #16179).
2. Overlays: each hammer attack state (commands CutJumpSt/Ed/Land, CutHammerAfter, and the ground and step
   attacks' UsingItem selectors) keeps its own nodes for VALUE, with their Event nodes (hit, sounds, the events that
   end the state). Its VALUE branch goes to a new BoneBlender (upper-body mask, from #3851): base = the hammer's
   node (shared, not copied), overlay = a punch leaf. Learned in game (2026-11-23): copying a node that owns Event
   nodes crashes; a selector inside a OneDimensionalBlender or a Sequential stalls the state (the hammer's too).
--replace-hammer: test mode, the overlays also on the hammer's own branch (7): no code change needed.
"""
import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
from asb_edit import Editor, check  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MASK_FROM = 3851   # an event-free BoneBlender with the plain upper-body mask (上半身【サブで使う用】)
OVERLAY_COMMANDS = {   # hammer attack states (their root is a UsingItem selector, or gets one) -> punch overlay
    "CutJumpSt": "FalconPunch",
    "CutJumpEd": "FalconPunch",
    "CutJumpLand": "FalconPunch",
    "CutHammerAfter": "FalconPunch_After",
}
OVERLAY_GROUND = "FalconPunch"


def _leaves(nodes, i, depth):
    out, todo = [], [(i, 0)]
    while todo:
        j, d = todo.pop()
        if j >= len(nodes):   # (a node added by this script)
            continue
        out.append(j)
        if d < depth:
            todo += [(c, d + 1) for c in nodes[j]["children"]]
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=os.path.join(ROOT, "unpacked/Player_Adult.root.asb"))
    ap.add_argument("--value", type=int, default=51)
    ap.add_argument("--replace-hammer", action="store_true")
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

    tprefix, _ = e.parse_body(template)

    # 2. overlays: the hammer's attack states stay as they are for VALUE (their nodes own the Event nodes that hit,
    #    sound and end the states, and a selector inside a blender or a Sequential stalls the state: the hammer's
    #    own attack too). The VALUE branch of each attack state's UsingItem selector gets a new BoneBlender: base = the
    #    hammer's node (shared, not copied), overlay = a punch leaf on the upper body (mask of #MASK_FROM).
    bb_prefix, _ = e.parse_body(MASK_FROM)
    leaf_tpl = next(n["index"] for n in nodes if n["type"] == 3 and n.get("anim") == "Hammer_Attack_Vertical_Advance")
    punch_leaf = {}

    def overlay(base, anim):
        if anim not in punch_leaf:
            punch_leaf[anim] = e.clone_node(leaf_tpl, anim=anim, events="drop")
        bb = e.clone_node(MASK_FROM, events="drop")
        e.set_body(bb, bb_prefix, {"child": [struct.pack("<I", base), struct.pack("<I", punch_leaf[anim])]})
        return bb

    def retarget(sel, anim, values):
        prefix, slots = e.parse_body(sel)
        for k, ent in enumerate(slots["child"]):
            flags, v, tgt = struct.unpack("<iiI", ent)
            if k < len(slots["child"]) - 1 and v in values:
                slots["child"][k] = struct.pack("<iiI", flags, v, overlay(tgt, anim))
        e.set_body(sel, prefix, slots)

    vals = (a.value, 7) if a.replace_hammer else (a.value,)
    done = []
    for cmd, anim in OVERLAY_COMMANDS.items():
        root = e.command_root(cmd)
        if nodes[root]["type"] == 8 and nodes[root]["sel"] == "bb:UsingItem":
            retarget(root, anim, vals)
        else:   # (root without a UsingItem selector: a new one above it)
            s = e.clone_node(template, events="drop")
            default = overlay(root, anim) if a.replace_hammer else root
            e.set_body(s, tprefix, {"child": [struct.pack("<iiI", 0, a.value, overlay(root, anim)),
                                              struct.pack("<iiI", 0, 0, default)]})
            e.set_command_root(cmd, s)
        done.append(cmd)
    # the ground attack (command CutS1): the UsingItem selector whose hammer branch leads to the vertical attack
    for n in sel:
        br = dict(e.int_branches(n["index"]))
        t7 = br.get(7)
        if t7 is not None and any(nodes[c].get("anim", "").startswith("Hammer_Attack_Vertical_Advance")
                                  for c in _leaves(nodes, t7, 3)):
            retarget(n["index"], OVERLAY_GROUND, vals)
            done.append(f"#{n['index']}")
    print(f"overlays (BoneBlender, mask #{MASK_FROM}) on: {', '.join(done)}")

    data = e.build()
    b = check(data)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    open(a.out, "wb").write(data)
    print(f"{added} UsingItem selectors got [{a.value}]; {len(data)} bytes ({len(data) - len(e.d):+d}); "
          f"nodes {len(b.nodes)}")
    # (no copied Event nodes: the AsNode BAEV stays as it is)
    if os.path.exists(a.baev_src):
        open(a.baev_out, "wb").write(open(a.baev_src, "rb").read())


if __name__ == "__main__":
    main()
