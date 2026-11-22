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
        """Give new_anim the same event nodes as existing_anim (same index array). Appends a new EventInfo array"""
        infos = self.infos()
        src = [x for x in infos if x[0] == fnv1a(existing_anim)]
        assert src, existing_anim
        h = fnv1a(new_anim)
        assert all(x[0] != h for x in infos), new_anim + " already has events"
        rows = [(x[0], x[2], len(x[1])) for x in infos] + [(h, src[0][2], len(src[0][1]))]
        rows.sort()
        while len(self.d) % 8:
            self.d += b"\0"
        at = len(self.d)
        for hh, io, n in rows:
            self.d += struct.pack("<IIQII", hh, 0, io, n, 4)
        struct.pack_into("<QII", self.d, self.info_at, at, len(rows), 0x18)
        struct.pack_into("<I", self.d, 8, len(self.d))   # file size
        return self

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
