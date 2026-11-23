"""Animation event files (AnimationEvent/Animation/<anim file>.anim.baev, magic BFFH): reader and append-only editor.

Our own code; layout per dt-12345/asb's baev.py (format reference only). Events are keyed by FNV-1a-32 of the
animation name (anim files) or of a node GUID (AsNode files).

    uv run python tools/baev.py FILE.baev[.zs] [anim name ...]     # list the events of those animations

Layout used here: header BFFH (magic, u32 offset, u32 file size, u32 align), section array (u64 off, u32 n, u32 sz),
u64 container offset. Container: u64 head, u32 version, u32 ?, u64 string pool, array EventInfo (0x18 each: u32
hash, u32 pad, u64 index array, u32 n, u32 4), array of event nodes (0x18 each: u64 events, u32 n, u32 0x30, u32
hash, u32 ?). Event (0x30): u64 name, array triggers (0x18: params array, f32 frame, f32 pad), array holds (0x18:
params, f32 start, f32 end), u32 is_hold, u32 id.
"""
import struct
import sys


def fnv1a(s):
    h = 0x811C9DC5
    for c in s.encode():
        h = ((h ^ c) * 0x01000193) & 0xFFFFFFFF
    return h


class Baev:
    def __init__(self, data):
        self.d = bytearray(data)
        assert self.d[:4] == b"BFFH"
        self.cont = self.u64(0x20)
        c = self.cont
        self.pool = self.u64(c + 0x10)
        self.info_at = c + 0x18
        self.nodes_at = c + 0x28

    def u32(self, o): return struct.unpack_from("<I", self.d, o)[0]
    def u64(self, o): return struct.unpack_from("<Q", self.d, o)[0]
    def f32(self, o): return struct.unpack_from("<f", self.d, o)[0]

    def arr(self, o):
        return self.u64(o), self.u32(o + 8), self.u32(o + 12)

    def string(self, off):
        return self.d[off:self.d.index(b"\0", off)].decode("utf-8", "replace")

    def infos(self):
        off, n, sz = self.arr(self.info_at)
        out = []
        for k in range(n):
            e = off + sz * k
            io, ic, _ = self.arr(e + 8)
            out.append((self.u32(e), [self.u32(io + 4 * j) for j in range(ic)], io))
        return out

    def node_events(self, idx):
        off, n, sz = self.arr(self.nodes_at)
        e = off + sz * idx
        eo, ec, esz = self.arr(e)
        out = []
        for k in range(ec):
            ev = eo + esz * k
            name = self.string(self.u64(ev))
            to, tc, tsz = self.arr(ev + 8)
            ho, hc, hsz = self.arr(ev + 0x18)
            trig = [self.f32(to + tsz * j + 0x10) for j in range(tc)]
            hold = [(self.f32(ho + hsz * j + 0x10), self.f32(ho + hsz * j + 0x14)) for j in range(hc)]
            out.append((name, trig, hold))
        return out

    def events_of(self, anim):
        h = fnv1a(anim)
        for hh, idxs, _ in self.infos():
            if hh == h:
                return [(i, self.node_events(i)) for i in idxs]
        return None

    def alias(self, new_anim, existing_anim):
        """Give new_anim the same event nodes as existing_anim (same index array)"""
        return self.alias_hashes([(fnv1a(new_anim), fnv1a(existing_anim))])

    def _append(self, blob):
        while len(self.d) % 8:
            self.d += b"\0"
        at = len(self.d)
        self.d += blob
        return at

    def _copy_params(self, po, pc, psz):
        """A copy of a parameter array (pointers to 16-byte parameters: u64 type, u64 value; a text value points
        into the string pool, which stays shared) -> its offset"""
        if not pc:
            return po
        assert psz == 8, psz
        ptrs = [self._append(bytes(self.d[self.u64(po + 8 * i):self.u64(po + 8 * i) + 16])) for i in range(pc)]
        return self._append(struct.pack("<%dQ" % pc, *ptrs))

    def edited_node(self, idx, edits):
        """A copy of event node idx with other times and values: edits {event name: {"trigger": [frame, ...],
        "hold": [(start, end), ...]}} (as many as the event has), and "trigger_params" / "hold_params": {(entry,
        parameter): value} for a parameter's value (a parameter is u64 type, u64 value). The copy is whole (its events, their trigger and hold
        arrays, their parameters): no structure with a pointer in it is reachable twice, as in the game's own file
        (the game turns the offsets into pointers in place when it loads the file; a shared array hung the load).
        Appended; returns the 24-byte node entry of the copy (for the node array)"""
        off, _, sz = self.arr(self.nodes_at)
        entry = bytearray(self.d[off + sz * idx:off + sz * idx + sz])
        eo, ec, esz = self.arr(off + sz * idx)
        events = bytearray(self.d[eo:eo + ec * esz])
        seen = set()
        for k in range(ec):
            name = self.string(struct.unpack_from("<Q", events, k * esz)[0])
            e = edits.get(name, {})
            if name in edits:
                seen.add(name)
            for key, at, width in (("trigger", 8, 1), ("hold", 0x18, 2)):
                ao, ac, asz = struct.unpack_from("<QII", events, k * esz + at)
                if not ac:
                    assert key not in e and key + "_params" not in e, (name, key)
                    continue
                arr = bytearray(self.d[ao:ao + ac * asz])
                for j in range(ac):
                    po, pc, psz = struct.unpack_from("<QII", arr, j * asz)
                    struct.pack_into("<Q", arr, j * asz, self._copy_params(po, pc, psz))
                for (j, i), value in e.get(key + "_params", {}).items():   # (entry j's parameter i: its value)
                    po, pc, _ = struct.unpack_from("<QII", arr, j * asz)
                    assert i < pc, (name, key, j, i)
                    struct.pack_into("<Q", self.d, self.u64(po + 8 * i) + 8, value)
                if key in e:
                    vals = [v if isinstance(v, (tuple, list)) else (v,) for v in e[key]]
                    assert len(vals) == ac and all(len(v) == width for v in vals), (name, key, ac)
                    for j, v in enumerate(vals):
                        struct.pack_into("<%df" % width, arr, j * asz + 0x10, *v)
                struct.pack_into("<Q", events, k * esz + at, self._append(arr))
        assert seen == set(edits), f"events not on node {idx}: {set(edits) - seen}"
        struct.pack_into("<Q", entry, 0, self._append(events))
        return bytes(entry)

    def alias_hashes(self, pairs, edits=None):
        """[(new hash, existing hash)]: each new key gets the existing key's event nodes (shared index array), or,
        with edits[new hash] (see edited_node), copies of them with other times. Existing keys without events are
        skipped. Appends one new, sorted EventInfo array (and the node array, when nodes were copied). Returns the
        count added"""
        edits = edits or {}
        infos = self.infos()
        have = {x[0]: (x[2], len(x[1])) for x in infos}
        idxs = {x[0]: x[1] for x in infos}
        rows = [(x[0], x[2], len(x[1])) for x in infos]
        noff, ncount, nsz = self.arr(self.nodes_at)
        new_nodes = []
        added = 0
        for new_h, old_h in pairs:
            if old_h not in have:
                assert new_h not in edits, "edits for a node without events"
                continue
            assert new_h not in have, hex(new_h)
            if new_h in edits:
                mine = []
                for i in idxs[old_h]:
                    new_nodes.append(self.edited_node(i, edits[new_h]))
                    mine.append(ncount + len(new_nodes) - 1)
                have[new_h] = (self._append(struct.pack("<%dI" % len(mine), *mine)), len(mine))
            else:
                have[new_h] = have[old_h]
            rows.append((new_h,) + have[new_h])
            added += 1
        if new_nodes:   # (the node array, with the copies after it)
            at = self._append(bytes(self.d[noff:noff + ncount * nsz]) + b"".join(new_nodes))
            struct.pack_into("<QII", self.d, self.nodes_at, at, ncount + len(new_nodes), nsz)
        rows.sort()
        at = self._append(b"".join(struct.pack("<IIQII", hh, 0, io, n, 4) for hh, io, n in rows))
        struct.pack_into("<QII", self.d, self.info_at, at, len(rows), 0x18)
        struct.pack_into("<I", self.d, 8, len(self.d))   # file size
        return added

    def to_bytes(self):
        return bytes(self.d)


def main():
    sys.path.insert(0, __file__.rsplit("/", 1)[0])
    import zs
    p = sys.argv[1]
    data = zs.decompress(open(p, "rb").read()) if p.endswith(".zs") else open(p, "rb").read()
    b = Baev(data)
    print(len(b.infos()), "animations with events")
    for anim in sys.argv[2:]:
        ev = b.events_of(anim)
        print("==", anim, "none" if ev is None else "")
        for i, evs in ev or []:
            for name, trig, hold in evs:
                print(f"   node {i}: {name} trigger {trig} hold {hold}")


if __name__ == "__main__":
    main()
