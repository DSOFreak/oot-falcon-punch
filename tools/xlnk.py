"""The game's effect link file (ELink2/elink2.Product.*.belnk, magic XLNK, version 0x24): reader.

Our own code, from the file itself. Layout used here: header (u32 magic, size, version, counts; u64 positions:
+0x18 trigger overwrite params, +0x20 local property name refs, +0x40 the users' region, +0x48 user count, +0x50
conditions, +0x58 names), user hashes (crc32 of the name, sorted) at 0x60, user offsets (u64) after them.
A user: +4 u16 local properties, +8 asset calls, +0xc assets, +0x14 action slots, +0x18 actions, +0x1c action
triggers, +0x20 properties, +0x24 property triggers, +0x28 always triggers, +0x30 u64 trigger table (from the user);
the trigger table: slots (0x10: u64 name, s16 first action, s16 last), actions (0x10: u64 name, u16 first trigger,
u16 flag, u32 last trigger), action triggers (0x28: u32 guid, u32 ?, u64 asset call (from the user), s32 start
frame, u32 ?, s32 end frame, u16 flag, u16 overwrite hash, u64 overwrite params or -1), properties, property
triggers. An asset call is 0x30: u64 key name, s16 asset id, u16 flag, s32 duration, s32 parent, u32 guid, u32 key
hash, u32 ?, u64 params, u64 condition.
"""
import struct
import zlib


class Xlnk:
    def __init__(self, data):
        self.d = bytearray(data)
        assert self.d[:4] == b"XLNK" and self.u32(8) == 0x24
        self.nuser = self.u32(0x48)
        self.names = self.u64(0x58)
        self.hash_at = 0x60
        self.off_at = (0x60 + 4 * self.nuser + 7) & ~7

    def u16(self, o): return struct.unpack_from("<H", self.d, o)[0]
    def u32(self, o): return struct.unpack_from("<I", self.d, o)[0]
    def u64(self, o): return struct.unpack_from("<Q", self.d, o)[0]

    def name(self, off):
        a = self.names + off
        return self.d[a:self.d.index(b"\0", a)].decode("utf-8", "replace")

    def user(self, name):
        h = zlib.crc32(name.encode())
        for i in range(self.nuser):
            if self.u32(self.hash_at + 4 * i) == h:
                return User(self, self.u64(self.off_at + 8 * i))
        raise KeyError(name)


class User:
    def __init__(self, x, at):
        self.x, self.at = x, at
        (self.nlocal,) = struct.unpack_from("<H", x.d, at + 4)
        (self.ncall, self.nasset, _, self.nslot, self.naction, self.ntrigger, self.nprop, self.nptrigger,
         self.nalways) = struct.unpack_from("<9I", x.d, at + 8)
        self.table = at + x.u64(at + 0x30)
        self.slots_at = self.table
        self.actions_at = self.slots_at + 0x10 * self.nslot
        self.triggers_at = self.actions_at + 0x10 * self.naction
        self.props_at = self.triggers_at + 0x28 * self.ntrigger
        self.end = self.props_at + 0x10 * self.nprop + 0x28 * self.nptrigger + 0x28 * self.nalways

    def slots(self):
        return [(self.x.name(self.x.u64(o)),) + struct.unpack_from("<hh", self.x.d, o + 8)
                for o in range(self.slots_at, self.actions_at, 0x10)]

    def actions(self):
        return [(self.x.name(self.x.u64(o)),) + struct.unpack_from("<HHI", self.x.d, o + 8)
                for o in range(self.actions_at, self.triggers_at, 0x10)]

    def triggers(self):
        return [struct.unpack_from("<IIQiIiHHq", self.x.d, o) for o in range(self.triggers_at, self.props_at, 0x28)]

    def calls(self):
        """All asset calls: [(position as the triggers give it, key, ...)]"""
        first = min(t[2] for t in self.triggers()) % 0x30
        while self.at + first < self.table - 0x30 * self.ncall - 0x30:
            first += 0x30
        return first

    def call(self, pos):
        """The asset call at pos (from the user): (key, asset id, flag, duration, parent, guid, hash, params, cond)"""
        o = self.at + pos + 8   # (a trigger's position is 8 before the key name)
        k, aid, flag, dur, parent, guid, h, _, params, cond = struct.unpack_from("<QhHiiIIIQi", self.x.d, o)
        return (self.x.name(k), aid, flag, dur, parent, guid, h, params, cond)


PARAM_NAMES = None


def asset_params(x, pos):
    """The asset parameter set at pos (from the asset parameter region, 0x4640 in this file: after the parameter
    definitions): {name: value}. A set is a u64 mask and a u32 per set bit: the top byte the value's kind (0: an
    index of the direct value table; a text parameter holds its name offset), the rest the index"""
    d = x.d
    define = x.off_at + 8 * x.nuser
    size, nu, na, _, nt = struct.unpack_from("<5I", d, define)
    ent = define + 0x18
    st = ent + (nu + na + nt) * 0x18
    base = define + size
    lp = x.u64(0x20)
    dv = lp + 8 * (x.u32(0x28) + x.u32(0x2c))
    o = base + pos
    mask = x.u64(o)
    o += 8
    out = {}
    for b in range(na):
        if not mask >> b & 1:
            continue
        nm, ty = struct.unpack_from("<QI", d, ent + (nu + b) * 0x18)
        name = bytes(d[st + nm:d.index(b"\0", st + nm)]).decode()
        v = x.u32(o)
        o += 4
        kind, i = v >> 24, v & 0xFFFFFF
        if ty == 4:
            out[name] = x.name(i)
        elif kind == 0:
            raw = x.u32(dv + 4 * i)
            out[name] = struct.unpack("<f", struct.pack("<I", raw))[0] if ty == 1 else raw
        else:
            out[name] = f"kind{kind}:{i}"
    return out
