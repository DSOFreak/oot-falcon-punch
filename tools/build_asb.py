"""Player_Adult.root.asb (+ its AsNode BAEV) for the Falcon Punch item.

    uv run python tools/build_asb.py [--value 51] [--replace-hammer] [--src ...] [--out ...]

1. Every IntSelector on bb:UsingItem with a branch for 7 (Hammer) gets the same branch for VALUE (the item's
   stored AssignableItem value): the item is held, carried and put away like the hammer, through the hammer's nodes.
2. The attack. The hammer's hit is a jump slam, four commands: CutJumpSt (wind-up), CutJumpEd (leap), CutJumpLand
   (hit), CutHammerAfter. Each gets a new root in its old root's place (the same node index: the game does not
   follow a changed index), a UsingItem selector: VALUE -> a copy of the hammer's nodes with the
   punch's animations (punch_anim) and copies of their Event nodes, everything else -> the command's own root. The AsNode
   BAEV gives each copied Event node its original's events, or edited ones (EVENT_EDITS): the wind-up's length, the
   punch's attack type.
3. The swing on the ground (inside the command CutS1, and after a side step): the UsingItem selectors whose
   hammer branch leads to the hammer's swings give VALUE a copy of them with the punch's animation, their events
   later by the punch's wind-up (GROUND_SHIFT).
--replace-hammer: test mode, the hammer's own value (7) takes the punch's branch too.

Learned in game (2026-11-23): the animation system has the value once Link's own field (the item in his hand) and
the blackboard's UsingItem both hold it (mod/FalconPunch/code/falcon_punch.c). An IntSelector inside a
OneDimensionalBlender or a Sequential stalls the state. A BAEV structure that holds a pointer must not be reachable
twice (tools/baev.py edited_node).
"""
import argparse
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
from asb_edit import Editor, check  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMMANDS = ("CutJumpSt", "CutJumpEd", "CutJumpLand", "CutHammerAfter")   # the hammer's attack: the jump slam
def punch_anim(name):
    """A hammer animation's name -> the punch's (tools/make_phases.py), or None"""
    if name.startswith(("Hammer_Attack_Left", "Hammer_Attack_Right", "Hammer_Attack_Vertical_Advance")):
        return "FalconPunch_GroundZero" if name.endswith("AdvanceZero") else "FalconPunch_Ground"
    for k, v in (("Hammer_Attack_Jump_Pre", "FalconPunch_Pre"), ("Hammer_Attack_Jump_St", "FalconPunch_St"),
                 ("Hammer_Attack_Jump", "FalconPunch_Jump"), ("Hammer_Attack_Vertical_Jump_Land", "FalconPunch_Land"),
                 ("Hammer_Attack_Vertical_After", "FalconPunch_After")):
        if name.startswith(k):
            return v
    return None


GROUND_SHIFT = 28   # the ground punch's wind-up over the hammer's swing, in frames (the hammer hits at 14, the punch
                    # at 42: tools/make_phases.py GROUND_HIT)
PRE_GO = 40   # the wind-up's length: the frame of FalconPunch_Pre at which the state goes on to the thrust
# The punch's attack: the AtCollision events' second parameter is the attack type (an index of the game's enum; the
# player's GameBalance/AttackParam table has its damage). The hammer's are 108 (the jump slam) and 117 (its shock
# wave). The punch takes the burning Deku Stick's two, which adult Link never uses: 104 and 103, whose table entries
# tools/build_mod.py turns into the punch's (fire, and a multiplier nothing survives).
ATTACK = {"hold_params": {(0, 1): 104, (1, 1): 103}}
D = float(GROUND_SHIFT)
GROUND_HIT = {"hold": [(14.0 + D, 24.0 + D), (14.0 + D, 24.0 + D)], **ATTACK}
EVENT_EDITS = {   # hammer Event node -> other times and values for its copy (tools/baev.py edited_node)
    # CutJumpSt's selector: NoChangeAS 0-9, CanChangeAS 17 (the wind-up ends there)
    16388: {"NoChangeAS": {"hold": [(0.0, float(PRE_GO - 8))]}, "CanChangeAS": {"trigger": [float(PRE_GO)]}},
    16354: {"AtCollision": ATTACK},   # Hammer_Attack_Jump_St
    16356: {"AtCollision": ATTACK},   # Hammer_Attack_Jump
    16404: {"AtCollision": ATTACK},   # the landing
    # the ground swings (CutS1): everything later by the wind-up
    16179: {"AtSound": {"trigger": [10.0 + D]}, "AtCollision": GROUND_HIT, "SwordCancel": {"hold": [(40.0 + D, -1.0)]},
            "AnmSeqCancel": {"hold": [(40.0 + D, -1.0)]}, "EmitEffect": {"trigger": [20.0 + D]},
            "NoChangeAS": {"hold": [(0.0, 14.0 + D)]}},
    16167: {"AtSound": {"trigger": [10.0 + D]}, "AtCollision": GROUND_HIT, "SwordCancel": {"hold": [(40.0 + D, -1.0)]},
            "AnmSeqCancel": {"hold": [(40.0 + D, -1.0)]}},
    16175: {"AtSound": {"trigger": [10.0 + D]}, "AtCollision": GROUND_HIT, "SwordCancel": {"hold": [(40.0 + D, -1.0)]},
            "AnmSeqCancel": {"hold": [(40.0 + D, -1.0)]}},
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
    ap.add_argument("--no-hold", action="store_true", help="test: step 1 left out (VALUE has no branch but the attack's)")
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
        if 7 not in vals or a.value in vals or a.no_hold:
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
            anim = punch_anim(n["anim"])
            if anim and os.environ.get("FP_TEST_ANIM"):   # (test: an animation of the game's that cannot be mistaken)
                anim = os.environ["FP_TEST_ANIM"]
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
        # (the new selector takes the root's index, the root's own node the selector's: tools/asb_edit.py swap_nodes)
        e.set_body(s, sprefix, {"child": [struct.pack("<iiI", 0, v, c) for v in vals] + [struct.pack("<iiI", 0, 0, s)]})
        e.swap_nodes(root, s)
        done.append(cmd)
    # the ground swings (inside the command CutS1 and the step attack): the UsingItem selectors whose hammer branch
    # leads to the hammer's swing animations. Their VALUE branch (step 1 gave it the hammer's nodes) goes to a copy
    for n in sel:
        br = dict(e.int_branches(n["index"]))
        t7 = br.get(7)
        if t7 is None or n["index"] in [e.command_root(c) for c in COMMANDS]:
            continue
        if any(str(nodes[c].get("anim", "")).startswith("Hammer_Attack_Vertical_Advance") for c in _leaves(nodes, t7, 3)):
            c = deep(t7)
            prefix, slots = e.parse_body(n["index"])
            for k, ent in enumerate(slots["child"][:-1]):
                flags, v, tgt = struct.unpack("<iiI", ent)
                if v in vals:
                    slots["child"][k] = struct.pack("<iiI", flags, v, c)
            e.set_body(n["index"], prefix, slots)
            done.append(f"#{n['index']}")
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
    assert all(clones.get(node) for node in EVENT_EDITS), "an Event node of EVENT_EDITS was not copied"
    n = bv.alias_hashes([(fnv1a(new), fnv1a(old)) for new, old in e.guid_aliases], edits)
    open(a.baev_out, "wb").write(bv.to_bytes())
    print(f"BAEV: {n} copied nodes with events")

if __name__ == "__main__":
    main()
