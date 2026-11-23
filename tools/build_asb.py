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
COMMANDS = ("CutJumpSt", "CutJumpEd", "CutJumpLand", "CutHammerAfter")   # the hammer's attack: the jump slam
ANIMS = (   # (hammer animation name prefix -> the punch's, tools/make_phases.py; first match)
    ("Hammer_Attack_Jump_Pre", "FalconPunch_Pre"),
    ("Hammer_Attack_Jump_St", "FalconPunch_St"),
    ("Hammer_Attack_Jump", "FalconPunch_Jump"),
    ("Hammer_Attack_Vertical_Jump_Land", "FalconPunch_Land"),
    ("Hammer_Attack_Vertical_After", "FalconPunch_After"),
)

PRE_GO = 40   # the wind-up's length: the frame of FalconPunch_Pre at which the state goes on to the thrust
EVENT_EDITS = {   # hammer Event node -> other times for its copy (tools/baev.py edited_node)
    # CutJumpSt's selector: NoChangeAS 0-9, CanChangeAS 17 (the wind-up ends there)
    16388: {"NoChangeAS": {"hold": [(0.0, float(PRE_GO - 8))]}, "CanChangeAS": {"trigger": [float(PRE_GO)]}},
}


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

    # 2. the punch's own nodes: the VALUE branch of each attack state goes to a copy of the hammer's nodes, with
    #    the punch's animations and copies of the Event nodes (new GUIDs; the AsNode BAEV gives each copy its
    #    original's events, edited by EVENT_EDITS).
    def deep(i):
        n = nodes[i]
        anim = None
        if n["type"] == 3 and isinstance(n.get("anim"), str):
            anim = next((v for k, v in ANIMS if n["anim"].startswith(k)), None)
        before = len(e.records)
        j = e.clone_node(i, anim=anim, events="clone")
        clones.setdefault(i, []).append(j)
        for k, ev in enumerate(n.get("events") or []):   # (clone_node copied the Event nodes right after j)
            clones.setdefault(ev, []).append(before + 1 + k)
        prefix, slots = e.parse_body(j)
        slots["child"] = [ent[:-4] + struct.pack("<I", deep(struct.unpack("<I", ent[-4:])[0]))
                          for ent in slots["child"]]
        e.set_body(j, prefix, slots)
        return j

    clones = {}
    vals = (a.value, 7) if a.replace_hammer else (a.value,)
    done = []
    for cmd in COMMANDS:
        # a new root above the command's: VALUE -> the punch's copy, everything else -> the command's own root. A root
        # that is a UsingItem selector is copied for it (its tags stay), and its own Event nodes, which the copy of
        # its hammer branch would no longer pass, go onto that copy
        root = e.command_root(cmd)
        is_sel = nodes[root]["type"] == 8 and nodes[root]["sel"] == "bb:UsingItem"
        base = dict(e.int_branches(root))[7] if is_sel else root
        c = deep(base)
        if is_sel and nodes[root].get("events"):
            prefix, slots = e.parse_body(c)
            for ev in nodes[root]["events"]:
                k = e.clone_node(ev)
                clones.setdefault(ev, []).append(k)
                slots["event"] = slots.get("event", []) + [struct.pack("<I", k)]
            e.set_body(c, prefix, slots)
        s = e.clone_node(root if is_sel else template, events="drop")
        sprefix = e.parse_body(root)[0] if is_sel else tprefix
        e.set_body(s, sprefix, {"child": [struct.pack("<iiI", 0, v, c) for v in vals] + [struct.pack("<iiI", 0, 0, root)]})
        e.set_command_root(cmd, s)
        done.append(cmd)
    print(f"punch nodes for: {', '.join(done)} ({sum(len(v) for v in clones.values())} copies)")

    data = e.build()
    b = check(data)
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    open(a.out, "wb").write(data)
    print(f"{added} UsingItem selectors got [{a.value}]; {len(data)} bytes ({len(data) - len(e.d):+d}); "
          f"nodes {len(b.nodes)}")
    # the copies' events: each copied node's GUID gets its original's events in the AsNode BAEV
    from baev import Baev, fnv1a
    bv = Baev(open(a.baev_src, "rb").read())
    old_of = {new: old for new, old in e.guid_aliases}
    edits = {}
    for node, ev in EVENT_EDITS.items():   # (a hammer Event node -> its copies' times)
        for c in clones.get(node, []):
            edits[fnv1a(e.guid(c))] = ev
    assert len(edits) == len(EVENT_EDITS), "an Event node of EVENT_EDITS was not copied"
    n = bv.alias_hashes([(fnv1a(new), fnv1a(old)) for new, old in e.guid_aliases], edits)
    open(a.baev_out, "wb").write(bv.to_bytes())
    print(f"BAEV: {n} copied nodes with events")

if __name__ == "__main__":
    main()
