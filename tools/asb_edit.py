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

    def clone_node(self, i, anim=None):
        """A copy of node i (same children); anim: another animation name (SkeletalAnimation). Returns its index"""
        rec = bytearray(self.records[i])
        self.guid_seed += 1
        struct.pack_into("<I", rec, 20, self.guid_seed)   # GUID's first word: unique
        j = len(self.records)
        self.records.append(rec)
        prefix, slots = self.parse_body(i)
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
        # 3. bodies first in a temp layout so the records know their offsets: records go before them
        node_off = len(out)
        bodies_at = node_off + 36 * len(self.records)
        bodies_at += -bodies_at % 16
        blob = bytearray()
        for i in sorted(self.bodies):
            prefix, slots = self.bodies[i]
            at = bodies_at + len(blob)
            struct.pack_into("<I", self.records[i], 8, at)
            blob += self.body_bytes(prefix, slots, at)
        for r in self.records:
            out += r
        out += b"\0" * (bodies_at - len(out))
        out += blob
        struct.pack_into("<I", out, hdr["node_off"], node_off)
        struct.pack_into("<I", out, hdr["node_count"], len(self.records))
        return bytes(out)


def check(data):
    """Re-read an edited file with tools/asb.py and return the parsed ASB"""
    a = A.ASB(data)
    bad = sum(1 for n in a.nodes for c in n["children"] if c >= len(a.nodes))
    assert bad == 0, f"{bad} bad child references"
    return a
