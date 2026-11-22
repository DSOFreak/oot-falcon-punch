"""Reader for the AS files (`AS/*.root.asb`) of this game: ASB version 0x41b.

Our own code. Layout notes come from comparing the file with dt-12345's description of TotK's ASB 0x417
(https://github.com/dt-12345/asb, used as a format reference only).

Differences found between 0x41b and 0x417:
- The header is 0x80 bytes. The counts are paired with offsets: (commands, 0x80), (nodes, node table),
  (event nodes, first body), (partials, ...), (sync controls, ...).
- One new field at 0x68. The tail moves down by 4: string-pool size 0x60, transitions 0x64, valid tags 0x6c,
  AS markings 0x70, EXB 0x74, command groups 0x78, material blend 0x7c.
- Commands (0x30) and nodes (0x24) have the same records as 0x417. The blackboard (at 0x38) has the same format.
- Node types 26 and 27 are new.

    uv run python tools/asb.py unpacked/Player_Adult.root.asb [substring]   # node paths to matching anims
"""
import struct
import sys
from collections import defaultdict

H = {  # header field -> offset (0x41b)
    "cmd_count": 0x0c, "cmd_off": 0x10, "node_count": 0x14, "node_off": 0x18, "event_count": 0x1c,
    "body_off": 0x20, "partial_count": 0x24, "partial_off": 0x28, "sync_count": 0x2c, "sync_off": 0x30,
    "sync_idx_off": 0x34, "blackboard_off": 0x38, "string_pool_off": 0x3c, "enum_off": 0x40,
    "state_transition_off": 0x44, "calc_ctrl_off": 0x48, "string_pool_size": 0x60, "transitions_off": 0x64,
    "unk68_off": 0x68, "valid_tags_off": 0x6c, "as_markings_off": 0x70, "expression_off": 0x74,
    "command_groups_off": 0x78, "material_blend_off": 0x7c,
}
TYPES = {1: "FloatSelector", 2: "StringSelector", 3: "SkeletalAnimation", 4: "State", 5: "Unknown2",
         6: "OneDimensionalBlender", 7: "Sequential", 8: "IntSelector", 9: "Simultaneous", 10: "Event",
         11: "MaterialAnimation", 12: "FrameController", 13: "DummyAnimation", 14: "RandomSelector",
         15: "Unknown4", 16: "PreviousTagSelector", 17: "BonePositionSelector", 18: "BoneAnimation",
         19: "InitialFrame", 20: "BoneBlender", 21: "BoolSelector", 22: "Alert", 23: "SubtractAnimation",
         24: "ShapeAnimation", 25: "Unknown7", 26: "Type26", 27: "Type27"}
# body bytes before the connection block, and where the node index sits in one child entry
PREFIX = {1: 20, 2: 20, 3: 32, 4: 0, 6: 12, 7: 24, 8: 20, 9: 4, 10: 4, 11: 20, 12: 120, 13: 16, 14: 32, 16: 4,
          17: 32, 18: 32, 19: 52, 20: 28, 21: 20, 22: 8, 23: 0, 24: 8, 25: 0, 26: 24, 27: 24}
CHILD_IDX = {1: 16, 2: 8, 6: 16, 8: 8, 14: 8, 16: 4, 17: 16}
BB_TYPES = ["string", "int", "unk2", "float", "bool", "vec3f", "ptr"]  # 0x41b: 7 types (0x417: 6, no unk2)
PARAM_TYPE = {1: "float", 2: "string", 8: "int", 21: "bool"}


class ASB:
    def __init__(self, data):
        self.d = d = bytes(data)
        assert d[:4] == b"ASB " and self.u32(4) == 0x41b, "not an ASB 0x41b file"
        self.h = {k: self.u32(o) for k, o in H.items()}
        self.sp = self.h["string_pool_off"]
        self.read_blackboard()
        self.nodes = [self.read_node(i) for i in range(self.h["node_count"])]
        self.parents = defaultdict(list)
        for n in self.nodes:
            for c in n["children"] + n.get("states", []) + n.get("transitions", []):
                self.parents[c].append(n["index"])
        self.commands = [self.read_command(i) for i in range(self.h["cmd_count"])]

    # -- primitives
    def u32(self, o): return struct.unpack_from("<I", self.d, o)[0]
    def s32(self, o): return struct.unpack_from("<i", self.d, o)[0]
    def f32(self, o): return struct.unpack_from("<f", self.d, o)[0]
    def u16(self, o): return struct.unpack_from("<H", self.d, o)[0]

    def string(self, off):
        a = self.sp + off
        return self.d[a:self.d.index(b"\0", a)].decode("utf-8", "replace")

    def tags(self, off):
        if not off or off == 0xFFFFFFFF:
            return []
        return [self.string(self.u32(off + 4 + 4 * i)) for i in range(self.u32(off))]

    def read_blackboard(self):
        o = self.h["blackboard_off"]
        heads = [struct.unpack_from("<HHH", self.d, o + 8 * i) for i in range(len(BB_TYPES))]
        p = o + 8 * len(BB_TYPES)
        self.bb = {}
        for t, (count, _idx, _off) in zip(BB_TYPES, heads):
            self.bb[t] = [self.string(self.u32(p + 4 * i) & 0x3FFFFF) for i in range(count)]
            p += 4 * count

    def param(self, o, typ):
        """A parameter: (flags, value). Returns a readable value or a blackboard reference"""
        flags = self.s32(o)
        if typ == "string":
            v = self.string(self.u32(o + 4))
        elif typ == "int":
            v = self.s32(o + 4)
        elif typ == "float":
            v = self.f32(o + 4)
        else:
            v = bool(self.u32(o + 4))
        if flags < 0:
            f = flags & 0xFFFFFFFF
            idx = f & 0xFFFF
            if f & 0x81000000 == 0x81000000:
                return f"expr#{idx}"
            if typ == "float" and f & (1 << 30):
                return f"calc#{idx}"
            if f & (1 << 25):
                return f"cmd#{idx}"
            names = self.bb.get(typ, [])
            return f"bb:{names[idx] if idx < len(names) else idx}"
        return v

    # -- records
    def read_command(self, i):
        o = self.h["cmd_off"] + 0x30 * i
        return {"name": self.string(self.u32(o)), "tags": self.tags(self.u32(o + 4)), "node": self.u16(o + 0x2c)}

    def connections(self, o):
        c = self.d[o:o + 12]
        counts = c[0::2]
        p = o + 12
        out = []
        for n in counts:
            out.append([self.u32(p + 4 * k) for k in range(n)])
            p += 4 * n
        return dict(zip(("state", "unk", "child", "transition", "event", "frame"), out))

    def read_node(self, i):
        o = self.h["node_off"] + 36 * i
        t, sync_count, no_st, tag_off, body = struct.unpack_from("<HBBII", self.d, o)
        n = {"index": i, "type": t, "name": TYPES.get(t, t), "tags": self.tags(tag_off), "body": body,
             "children": [], "sel": None}
        if t not in PREFIX:
            return n
        con = self.connections(body + PREFIX[t])
        n["children"] = [self.u32(c + CHILD_IDX.get(t, 0)) for c in con["child"]]
        n["transitions"] = [self.u32(c + 4) for c in con["transition"]]   # (state transition index, node)
        n["states"] = [self.u32(c) for c in con["state"]]   # State nodes keep their children here
        n["events"] = [self.u32(c) for c in con["event"]]
        n["frames"] = [self.u32(c) for c in con["frame"]]
        if t in (3, 11, 18, 24):  # animation name first (MaterialAnimation: after a u32)
            n["anim"] = self.param(body + (4 if t == 11 else 0), "string")
        if t in PARAM_TYPE:
            typ = PARAM_TYPE[t]
            n["sel"] = self.param(body, typ)
            conds = []
            for k, c in enumerate(con["child"]):
                if t == 21:
                    conds.append("true" if k == 0 else "false")
                elif t == 1:
                    conds.append("default" if k == len(con["child"]) - 1 else
                                 f"{self.param(c, 'float')}..{self.param(c + 8, 'float')}")
                else:
                    conds.append(("default:" if k == len(con["child"]) - 1 else "") + str(self.param(c, typ)))
            n["conds"] = conds
        return n

    # -- queries
    def describe(self, i):
        n = self.nodes[i]
        s = f"#{i} {n['name']}"
        if n.get("anim") is not None:
            s += f" anim={n['anim']}"
        if n["sel"] is not None:
            s += f" on {n['sel']}"
        if n["tags"]:
            s += f" tags={n['tags']}"
        return s

    def paths_up(self, i, limit=12):
        """Chains from node i up to a command's root node (or a node without parents)"""
        roots = {c["node"]: c["name"] for c in self.commands}
        out = []

        def walk(j, chain):
            if len(out) > limit:
                return
            chain = chain + [j]
            ps = self.parents.get(j, [])
            if j in roots or not ps or len(chain) > 40:
                out.append((roots.get(j), chain))
                return
            for p in ps:
                if p not in chain:
                    walk(p, chain)
        walk(i, [])
        return out


def main():
    a = ASB(open(sys.argv[1], "rb").read())
    sub = sys.argv[2] if len(sys.argv) > 2 else None
    bad = sum(1 for n in a.nodes for c in n["children"] if c >= len(a.nodes))
    print(f"{len(a.nodes)} nodes, {len(a.commands)} commands, bad child refs {bad}")
    print("blackboard:", {k: len(v) for k, v in a.bb.items()})
    if not sub:
        return
    for n in a.nodes:
        if isinstance(n.get("anim"), str) and sub in n["anim"]:
            print("==", a.describe(n["index"]))
            for root, chain in a.paths_up(n["index"]):
                print("   cmd", root)
                for j in chain[1:]:
                    p = a.nodes[j]
                    prev = chain[chain.index(j) - 1]
                    k = p["children"].index(prev) if prev in p["children"] else None
                    cond = f"  [{p['conds'][k]}]" if p.get("conds") and k is not None else ""
                    print("     <-", a.describe(j) + cond)


if __name__ == "__main__":
    main()
