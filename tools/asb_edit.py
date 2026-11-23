"""Append-only editor for ASB 0x41b (see tools/asb.py for the layout).

Nothing already in the file moves, so no existing offset has to be fixed. Edits are appended:
  1. new strings at the end of the string pool (the pool is the last section; its size field 0x60 grows),
  2. a copy of the node table with the new nodes after it (header node_off 0x18 and node_count 0x14 change),
  3. the new or rebuilt node bodies; node records point at them.

    from asb_edit import Editor
    e = Editor(open(path, 'rb').read())
    e.add_int_branch(node_index, 51, target_node)       # IntSelector: one more condition before the default
    new = e.clone_node(16178, anim="FalconPunch")         # a copy of a node (new GUID), optionally another animation
    data = e.build()
"""
import os
import struct
import sys

sys.path.insert(0, os.path.dirname(__file__))
import asb as A  # noqa: E402

SLOTS = ("state", "unk", "child", "transition", "event", "frame")


def child_entry_size(t, is_last):
    if t in (1, 6, 17):
        return 20
    if t in (2, 8, 14):
        return 12
    if t == 16:
        return 8
    return 4


class Editor:
    def __init__(self, data):
        self.a = A.ASB(data)
        self.d = bytes(data)
        self.records = [bytearray(self.d[self.a.h["node_off"] + 36 * i:self.a.h["node_off"] + 36 * (i + 1)])
                        for i in range(self.a.h["node_count"])]
        self.new_strings = {}            # string -> offset in the pool
        self.pool_end = self.a.h["string_pool_size"]
        self.bodies = {}                 # node index -> (prefix bytes, {slot: [entry bytes]})
        self.guid_seed = 0x46504e00      # 'FPN\0'
        self.guid_aliases = []           # (GUID of a copy, GUID of its original)
        self.command_roots = {}          # command index -> new root node

    # -- strings
    def string(self, s):
        """Offset in the string pool of s (an existing one if present, else appended)"""
        pool = self.d[self.a.sp:self.a.sp + self.a.h["string_pool_size"]]
        b = s.encode() + b"\0"
        i = pool.find(b)
        while i > 0 and pool[i - 1] != 0:
            i = pool.find(b, i + 1)
        if i >= 0:
            return i
        if s not in self.new_strings:
            self.new_strings[s] = self.pool_end
            self.pool_end += len(b)
        return self.new_strings[s]

    # -- bodies
    def parse_body(self, i):
        """(prefix bytes, {slot: [entry bytes]}) of node i, as it is now (edited or original)"""
        if i in self.bodies:
            p, s = self.bodies[i]
            return bytearray(p), {k: list(v) for k, v in s.items()}
        t = struct.unpack_from("<H", self.records[i], 0)[0]
        body = struct.unpack_from("<I", self.records[i], 8)[0]
        pre = A.PREFIX[t]
        h = body + pre
        counts = self.d[h:h + 12:2]
        p = h + 12
        slots = {}
        for name, n in zip(SLOTS, counts):
            offs = [struct.unpack_from("<I", self.d, p + 4 * k)[0] for k in range(n)]
            p += 4 * n
            if name == "child":
                sizes = [child_entry_size(t, k == n - 1) for k in range(n)]
            elif name == "transition":
                sizes = [8] * n
            else:
                sizes = [4] * n
            slots[name] = [self.d[o:o + sz] for o, sz in zip(offs, sizes)]
        return bytearray(self.d[body:body + pre]), slots

    def set_body(self, i, prefix, slots):
        self.bodies[i] = (bytes(prefix), {k: [bytes(e) for e in v] for k, v in slots.items()})

    @staticmethod
    def body_bytes(prefix, slots, at):
        """The body laid out at absolute offset `at`: prefix, connection header, offsets, entries"""
        counts = [len(slots.get(n, [])) for n in SLOTS]
        head, base = bytearray(), 0
        for c in counts:
            head += bytes((c, base))
            base += c
        n_total = sum(counts)
        entries_at = at + len(prefix) + 12 + 4 * n_total
        offs, blob = bytearray(), bytearray()
        for n in SLOTS:
            for e in slots.get(n, []):
                offs += struct.pack("<I", entries_at + len(blob))
                blob += e
        out = bytes(prefix) + bytes(head) + bytes(offs) + bytes(blob)
        return out + b"\0" * (-len(out) % 4)

    # -- edits
    def add_int_branch(self, i, value, target):
        """IntSelector i: a child `value -> target` before the default (the last child)"""
        assert struct.unpack_from("<H", self.records[i], 0)[0] == 8
        prefix, slots = self.parse_body(i)
        entry = struct.pack("<iiI", 0, value, target)
        slots["child"].insert(len(slots["child"]) - 1, entry)
        self.set_body(i, prefix, slots)

    def int_branches(self, i):
        """[(value or None for default, target)] of IntSelector i"""
        prefix, slots = self.parse_body(i)
        out = []
        for k, e in enumerate(slots["child"]):
            flags, v, tgt = struct.unpack("<iiI", e)
            out.append((None if k == len(slots["child"]) - 1 else v, tgt))
        return out

    def set_child(self, i, k, target):
        """Point child k of node i at another node (the node index is the entry's last u32)"""
        prefix, slots = self.parse_body(i)
        e = bytearray(slots["child"][k])
        struct.pack_into("<I", e, len(e) - 4, target)
        slots["child"][k] = bytes(e)
        self.set_body(i, prefix, slots)

    def swap_nodes(self, i, j):
        """Exchange two nodes' places in the node table (records and bodies): what referred to index i now gets
        j's node and the other way round. A command's root is replaced this way: the game does not follow a
        changed root index in the command table (seen in game, 2026-11-23), so the new root takes the old one's
        index"""
        self.records[i], self.records[j] = self.records[j], self.records[i]
        bi, bj = self.bodies.pop(i, None), self.bodies.pop(j, None)
        if bj is not None:
            self.bodies[i] = bj
        if bi is not None:
            self.bodies[j] = bi

    def set_command_root(self, name, node):
        """Make `node` the root node of command `name` (u16 at +0x2c of its 0x30-byte record)"""
        idx = [k for k, c in enumerate(self.a.commands) if c["name"] == name]
        assert len(idx) == 1, name
        self.command_roots[idx[0]] = node

    def command_root(self, name):
        return [c["node"] for c in self.a.commands if c["name"] == name][0]

    def guid(self, i):
        """GUID string of node i as BAEV AsNode files hash it (FNV-1a of this text)"""
        w = struct.unpack_from("<IHH8B", self.records[i], 20)
        return "%08x-%04x-%04x-%02x%02x-%02x%02x%02x%02x%02x%02x" % w

    def clone_node(self, i, anim=None, events="clone"):
        """A copy of node i (same children); anim: another animation name (SkeletalAnimation). Returns its index.
        events: what the copy does with the Event nodes in its event slot: 'clone' copies them too (new GUIDs;
        self.guid_aliases gets (new GUID, old GUID) so the AsNode BAEV can give the copies the same events, or
        edited ones: tools/baev.py) and 'drop' leaves them out. (The game's own file shares Event nodes between
        parents, e.g. #17400; the crashes first put down to copies were the resource size table: tools/build_mod.py
        SLACK.)"""
        rec = bytearray(self.records[i])
        self.guid_seed += 1
        struct.pack_into("<I", rec, 20, self.guid_seed)   # GUID's first word: unique
        j = len(self.records)
        self.records.append(rec)
        self.guid_aliases.append((self.guid(j), self.guid(i)))
        prefix, slots = self.parse_body(i)
        if events == "drop":
            slots["event"] = []
        else:
            slots["event"] = [struct.pack("<I", self.clone_node(struct.unpack("<I", ev)[0]))
                              for ev in slots["event"]]
        if anim is not None:
            t = struct.unpack_from("<H", rec, 0)[0]
            assert t == 3, "anim= only for SkeletalAnimation"
            flags = struct.unpack_from("<i", prefix, 0)[0]
            assert flags >= 0, "animation name comes from the blackboard"
            struct.pack_into("<I", prefix, 4, self.string(anim))
        self.set_body(j, prefix, slots)
        return j

    # -- output
    def build(self):
        out = bytearray(self.d)
        hdr = A.H
        # 1. strings (the pool ends the original file)
        assert self.a.sp + self.a.h["string_pool_size"] == len(self.d), "string pool is not the last section"
        for s, off in sorted(self.new_strings.items(), key=lambda x: x[1]):
            assert len(out) == self.a.sp + off
            out += s.encode() + b"\0"
        struct.pack_into("<I", out, hdr["string_pool_size"], len(out) - self.a.sp)
        out += b"\0" * (-len(out) % 16)
        # 2./3. the node table moves to the end only when nodes were added (records first, then the bodies)
        n_orig = self.a.h["node_count"]
        relocate = len(self.records) != n_orig or getattr(self, "force_relocate", False)
        node_off = len(out) if relocate else self.a.h["node_off"]
        bodies_at = (node_off + 36 * len(self.records)) if relocate else len(out)
        bodies_at += -bodies_at % 16
        blob = bytearray()
        for i in sorted(self.bodies):
            prefix, slots = self.bodies[i]
            at = bodies_at + len(blob)
            struct.pack_into("<I", self.records[i], 8, at)
            blob += self.body_bytes(prefix, slots, at)
        if relocate:
            for r in self.records:
                out += r
        else:
            for i, r in enumerate(self.records):
                out[node_off + 36 * i:node_off + 36 * (i + 1)] = r
        out += b"\0" * (bodies_at - len(out))
        out += blob
        for k, node in self.command_roots.items():
            struct.pack_into("<H", out, self.a.h["cmd_off"] + 0x30 * k + 0x2c, node)
        struct.pack_into("<I", out, hdr["node_off"], node_off)
        struct.pack_into("<I", out, hdr["node_count"], len(self.records))
        struct.pack_into("<I", out, hdr["event_count"],
                         sum(1 for r in self.records if struct.unpack_from("<H", r, 0)[0] == 10))
        return bytes(out)


def check(data):
    """Re-read an edited file with tools/asb.py and return the parsed ASB"""
    a = A.ASB(data)
    bad = sum(1 for n in a.nodes for c in n["children"] if c >= len(a.nodes))
    assert bad == 0, f"{bad} bad child references"
    return a
