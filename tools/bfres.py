"""BFRES v10.x (Switch, nn::g3d2) reader/writer focused on skeletons and skeletal animations.

Verified against the OoT (Switch) player files, FRES version 10.4.0 (bytes 00 04 0A 00).

Reading: header, relocation table (_RLT), string pool (_STR), ResDic, FMDL -> FSKL bones,
FSKA -> BoneAnim -> AnimCurve, including the v10.4 "hermite value+slope" curve encoding (flag bit 14).
Writing: add a skeletal animation to an existing anim bfres by inserting bytes and shifting every
relocated pointer (the _RLT lists every pointer slot, so this is generic), rebuilding the anim ResDic
(Patricia trie, byte-identical to Nintendo's builder), appending new strings to the _STR pool and
re-encoding the _RLT (encoder reproduces Nintendo's entries exactly for single-section anim files).
"""
from __future__ import annotations

import math
import struct
from bisect import bisect_right
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------------------------------------
# constants

FSKA_SIZE = 0x50
BONEANIM_SIZE = 0x38
CURVE_SIZE = 0x30
BONE_SIZE = 0x58

# FSKA flags
ANIM_BAKED = 1 << 0
ANIM_LOOP = 1 << 2
ANIM_SCALE_MASK = 3 << 8  # 0 none, 1 standard, 2 maya, 3 softimage
ANIM_ROT_EULER = 1 << 12  # whole anim euler (old style, e.g. Player_Adult_1st = 0x1200)
ANIM_ROT_PER_BONE = 1 << 13  # v10.4 player anims (0x2200): euler by default, BONE_QUAT bones use quaternions

# BoneAnim flags
BASE_SCALE = 1 << 3
BASE_ROTATE = 1 << 4
BASE_TRANSLATE = 1 << 5
CURVE_BITS = {"sx": 6, "sy": 7, "sz": 8, "rx": 9, "ry": 10, "rz": 11, "rw": 12, "tx": 13, "ty": 14, "tz": 15}
BONE_QUAT = 1 << 20  # bone rotation is a quaternion (base xyzw + one 0x80 quaternion curve flagged as 'rw')
SEG_SCALE_COMPENSATE = 1 << 23
XF_SCALE_UNIFORM = 1 << 24
XF_SCALE_VOLUME_ONE = 1 << 25
XF_ROTATE_ZERO = 1 << 26
XF_TRANSLATE_ZERO = 1 << 27

# AnimCurve.target (anim_data_offset) -> component
TARGET_OFFSETS = {0x04: "sx", 0x08: "sy", 0x0C: "sz", 0x10: "tx", 0x14: "ty", 0x18: "tz",
                  0x20: "rx", 0x24: "ry", 0x28: "rz", 0x2C: "rw"}
TARGET_BY_NAME = {v: k for k, v in TARGET_OFFSETS.items()}

# AnimCurve flags
FRAME_F32, FRAME_F16, FRAME_U8 = 0, 1, 2  # F16: 16-bit fixed point, frame = raw/32 (or raw*frame_scale)
KEY_F32, KEY_16, KEY_8 = 0, 1 << 2, 2 << 2
CURVE_CUBIC, CURVE_LINEAR, CURVE_BAKED_FLOAT = 0 << 4, 1 << 4, 2 << 4
CURVE_STEP_INT, CURVE_BAKED_INT, CURVE_STEP_BOOL, CURVE_BAKED_BOOL = 4 << 4, 5 << 4, 6 << 4, 7 << 4
CF_QUAT = 1 << 7  # v10.4: key = quaternion xyzw (4 x f32), interpolated spherically
CF_FRAME_SCALE = 1 << 10  # v10.4: header field 0x20 = frame scale (frames = raw * scale)
CF_QUANTIZED = 1 << 11  # v10.4: key data starts with (slope_scale, slope_offset) f32, keys are unsigned ints
CF_HERMITE = 1 << 14  # v10.4: keys are (value, slope-per-frame) pairs (hermite) instead of cubic coefficients
CURVE_TYPE_NAMES = {0x00: "cubic", 0x10: "linear", 0x20: "baked_float", 0x40: "step_int",
                    0x50: "baked_int", 0x60: "step_bool", 0x70: "baked_bool"}


def align(x, a):
    return (x + a - 1) // a * a


def f2u(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


def u2f(u):
    return struct.unpack("<f", struct.pack("<I", u))[0]


# ---------------------------------------------------------------------------------------------------------
# relocation table


@dataclass
class RelocEntry:
    pos: int
    struct_count: int
    offset_count: int
    padding_count: int

    def slots(self):
        p = self.pos
        for _ in range(self.struct_count):
            for _ in range(self.offset_count):
                yield p
                p += 8
            p += 8 * self.padding_count


@dataclass
class RelocSection:
    ptr: int
    pos: int
    size: int
    entry_index: int
    entry_count: int


def encode_reloc_entries(slots):
    """Encoder matching Nintendo's: split pointer slots into maximal runs of consecutive qwords; each
    unassigned run is paired with the next unassigned run of the same length (stride -> padding) and
    repeated while further runs of the same length follow at the same stride."""
    slots = sorted(set(slots))
    runs = []
    i = 0
    while i < len(slots):
        j = i
        while j + 1 < len(slots) and slots[j + 1] == slots[j] + 8 and j + 1 - i < 255:
            j += 1
        runs.append((slots[i], j - i + 1))
        i = j + 1
    by_start = {p: k for k, (p, _) in enumerate(runs)}
    # per length, ordered list of run indices for "next run of same length" queries
    by_len = {}
    for k, (p, n) in enumerate(runs):
        by_len.setdefault(n, []).append(k)
    used = [False] * len(runs)
    ptr_by_len = {n: 0 for n in by_len}
    entries = []
    for k, (p, n) in enumerate(runs):
        if used[k]:
            continue
        used[k] = True
        lst = by_len[n]
        # next unused run of same length after k
        idx = bisect_right(lst, k)
        while idx < len(lst) and used[lst[idx]]:
            idx += 1
        count, pad = 1, 0
        if idx < len(lst):
            k2 = lst[idx]
            stride = (runs[k2][0] - p) // 8
            pad = stride - n
            if 0 <= pad <= 255:
                used[k2] = True
                count = 2
                while count < 0xFFFF:
                    nxt = p + 8 * stride * count
                    k3 = by_start.get(nxt)
                    if k3 is None or used[k3] or runs[k3][1] != n:
                        break
                    used[k3] = True
                    count += 1
            else:
                pad = 0
        entries.append(RelocEntry(p, count, n, pad))
    return entries


# ---------------------------------------------------------------------------------------------------------
# ResDic (Patricia trie), port of the nn::util::ResDic builder used by BfresLibrary / abood's tools


def _bit(n, b):
    if b < 0:
        return 0
    return (n >> b) & 1


def _bit_mismatch(a, b):
    x = a ^ b
    if x == 0:
        return -1
    return (x & -x).bit_length() - 1


def _first_1bit(n):
    return (n & -n).bit_length() - 1


class _Node:
    __slots__ = ("data", "bit", "parent", "child")

    def __init__(self, data, bit, parent):
        self.data = data
        self.bit = bit
        self.parent = parent
        self.child = [self, self]


def build_dict_nodes(keys):
    """Return [(ref, left, right, key)] including the root node (key None)."""
    root = _Node(0, -1, None)
    root.parent = root
    entries = {0: (0, root)}
    order = [root]

    def search(data, prev):
        if root.child[0] is root:
            return root
        node = root.child[0]
        while True:
            prev_node = node
            node = node.child[_bit(data, node.bit)]
            if node.bit <= prev_node.bit:
                break
        return prev_node if prev else node

    def add(data, node):
        if data not in entries:
            order.append(node)
        entries[data] = (len(entries) if data not in entries else entries[data][0], node)

    for key in keys:
        data = int.from_bytes(key.encode("utf-8"), "big")
        cur = search(data, True)
        bit_idx = _bit_mismatch(cur.data, data)
        while bit_idx < cur.parent.bit:
            cur = cur.parent
        if bit_idx < cur.bit:
            nn = _Node(data, bit_idx, cur.parent)
            nn.child[_bit(data, bit_idx) ^ 1] = cur
            cur.parent.child[_bit(data, cur.parent.bit)] = nn
            cur.parent = nn
            add(data, nn)
        elif bit_idx > cur.bit:
            nn = _Node(data, bit_idx, cur)
            if _bit(cur.data, bit_idx) == (_bit(data, bit_idx) ^ 1):
                nn.child[_bit(data, bit_idx) ^ 1] = cur
            else:
                nn.child[_bit(data, bit_idx) ^ 1] = root
            cur.child[_bit(data, cur.bit)] = nn
            add(data, nn)
        else:
            new_bit = _first_1bit(data)
            c = cur.child[_bit(data, bit_idx)]
            if c is not root:
                new_bit = _bit_mismatch(c.data, data)
            nn = _Node(data, new_bit, cur)
            nn.child[_bit(data, new_bit) ^ 1] = cur.child[_bit(data, bit_idx)]
            cur.child[_bit(data, bit_idx)] = nn
            add(data, nn)

    idx = {id(n): i for i, n in enumerate(order)}
    key_by_data = {int.from_bytes(k.encode("utf-8"), "big"): k for k in keys}
    out = []
    for i, n in enumerate(order):
        ref = n.bit & 0xFFFFFFFF
        out.append((ref, idx[id(n.child[0])], idx[id(n.child[1])], None if i == 0 else key_by_data[n.data]))
    return out


def dict_lookup(nodes, name):
    """Standard nn::util::ResDic lookup. nodes: [(ref,left,right,key)] incl. root. Returns value index or -1."""
    b = name.encode("utf-8")

    def bit(ref):
        byte = ref >> 3
        if byte >= len(b):
            return 0
        return (b[len(b) - 1 - byte] >> (ref & 7)) & 1

    prev = nodes[0]
    cur_i = prev[1]
    cur = nodes[cur_i]
    while (prev[0] == 0xFFFFFFFF and cur[0] != 0xFFFFFFFF) or (prev[0] != 0xFFFFFFFF and prev[0] < cur[0] != 0xFFFFFFFF):
        prev = cur
        cur_i = cur[2] if bit(cur[0]) else cur[1]
        cur = nodes[cur_i]
    return cur_i - 1 if cur[3] == name else -1


# ---------------------------------------------------------------------------------------------------------
# data model


def _hermite(v0, s0, v1, s1, h, t):
    t2, t3 = t * t, t * t * t
    return ((2 * t3 - 3 * t2 + 1) * v0 + (t3 - 2 * t2 + t) * h * s0 +
            (-2 * t3 + 3 * t2) * v1 + (t3 - t2) * h * s1)


def _qnorm(q):
    n = math.sqrt(sum(x * x for x in q)) or 1.0
    return tuple(x / n for x in q)


def slerp(q0, q1, t):
    d = sum(a * b for a, b in zip(q0, q1))
    if d < 0:
        q1, d = tuple(-x for x in q1), -d
    if d > 0.9995:
        return _qnorm(tuple(a + (b - a) * t for a, b in zip(q0, q1)))
    th = math.acos(max(-1.0, min(1.0, d)))
    s = math.sin(th)
    w0, w1 = math.sin((1 - t) * th) / s, math.sin(t * th) / s
    return tuple(w0 * a + w1 * b for a, b in zip(q0, q1))


@dataclass
class AnimCurve:
    flags: int
    target: int  # anim_data_offset (byte offset into the bone result struct, see TARGET_OFFSETS)
    start: float
    end: float
    frame_scale: float  # header 0x20 (only meaningful with CF_FRAME_SCALE)
    scale: float  # header 0x24: value = offset + scale * q  (quantized keys)
    offset_raw: int  # header 0x28 (f32 bits)
    frames: list  # decoded frames
    values: list  # decoded key values (float, or xyzw tuple for quaternion curves)
    slopes: list | None  # decoded slopes (per frame) for hermite curves, None for quaternion / legacy
    slope_scale: float = 0.0
    slope_offset: float = 0.0
    raw_frames: bytes = b""
    raw_keys: bytes = b""
    pad: int = 0
    legacy_keys: list | None = None  # legacy (pre-10.4) coefficient keys if CF_HERMITE not set

    @property
    def offset(self):
        return u2f(self.offset_raw)

    @property
    def frame_type(self): return self.flags & 3
    @property
    def key_type(self): return self.flags & 0xC
    @property
    def curve_type(self): return self.flags & 0x70
    @property
    def is_quat(self): return bool(self.flags & CF_QUAT)

    @property
    def type_name(self):
        if self.flags & CF_HERMITE:
            t = "quat_slerp" if self.is_quat else "hermite"
            ft = {0: "f32", 1: "fx16", 2: "u8"}[self.frame_type]
            kt = {0: "f32", 4: "u16q", 8: "u8q"}[self.key_type]
            return f"{t}(frames={ft},keys={kt}{',fscale' if self.flags & CF_FRAME_SCALE else ''})"
        return CURVE_TYPE_NAMES.get(self.curve_type, hex(self.curve_type))

    @property
    def comp(self):
        return "rq" if self.is_quat else TARGET_OFFSETS.get(self.target, hex(self.target))

    def _segment(self, frame):
        fr = self.frames
        n = len(fr)
        if n == 1 or frame <= fr[0]:
            return 0, 0.0, 0.0
        if frame >= fr[-1]:
            return n - 1, 0.0, 0.0
        i = bisect_right(fr, frame) - 1  # last key with frame <= f (handles duplicate frames = tangent breaks)
        h = fr[i + 1] - fr[i]
        return i, (frame - fr[i]) / h if h else 0.0, h

    def evaluate(self, frame):
        if self.legacy_keys is not None:
            return self._evaluate_legacy(frame)
        i, t, h = self._segment(frame)
        if self.is_quat:
            if t == 0.0:
                return tuple(self.values[i])
            return slerp(self.values[i], self.values[i + 1], t)
        if t == 0.0:
            return self.values[i]
        return _hermite(self.values[i], self.slopes[i], self.values[i + 1], self.slopes[i + 1], h, t)

    def _evaluate_legacy(self, frame):
        ct = self.curve_type
        k = self.legacy_keys
        if ct in (CURVE_BAKED_FLOAT, CURVE_BAKED_INT):
            i = max(0, min(len(k) - 1, int(round(frame - self.start))))
            return k[i][0] * self.scale + self.offset
        i, t, h = self._segment(frame)
        c = k[i]
        if ct == CURVE_CUBIC:
            return c[0] * self.scale + self.offset + t * (c[1] + t * (c[2] + t * c[3])) * self.scale
        if ct == CURVE_LINEAR:
            return c[0] * self.scale + self.offset + t * c[1] * self.scale
        return c[0] * self.scale + self.offset


@dataclass
class BoneAnim:
    name: str
    flags: int
    begin_rotate: int
    begin_translate: int
    begin_base_translate: int
    begin_curve: int
    base_scale: tuple | None
    base_rotate: tuple | None
    base_translate: tuple | None
    curves: list
    unk: tuple = (0, 0)
    pad: int = 0

    @property
    def quat(self):
        return bool(self.flags & BONE_QUAT)

    def curve_for(self, comp):
        for c in self.curves:
            if c.comp == comp:
                return c
        return None


@dataclass
class SkeletalAnim:
    name: str
    path: str
    flags: int
    frame_count: int
    baked_size: int
    bone_anims: list
    bind_indices: list
    num_curves: int = 0
    skeleton_ptr: int = 0
    offset: int = 0  # file offset of the FSKA header when read

    def bone_is_quat(self, ba):
        if self.flags & ANIM_ROT_PER_BONE:
            return ba.quat
        return not (self.flags & ANIM_ROT_EULER)

    def sample(self, frame):
        """{bone: {'s':[x,y,z], 'r':[x,y,z] (euler rad) or [x,y,z,w] (quat), 't':[x,y,z], 'rot':'euler'|'quat'}}"""
        out = {}
        for ba in self.bone_anims:
            s = list(ba.base_scale) if ba.base_scale else [1.0, 1.0, 1.0]
            r = list(ba.base_rotate) if ba.base_rotate else [0.0, 0.0, 0.0, 1.0]
            t = list(ba.base_translate) if ba.base_translate else [0.0, 0.0, 0.0]
            for c in ba.curves:
                v = c.evaluate(frame)
                comp = c.comp
                if comp == "rq":
                    r = list(v)
                elif comp[0] == "s":
                    s["xyz".index(comp[1])] = v
                elif comp[0] == "r":
                    r["xyzw".index(comp[1])] = v
                elif comp[0] == "t":
                    t["xyz".index(comp[1])] = v
            q = self.bone_is_quat(ba)
            out[ba.name] = {"s": s, "r": r if q else r[:3], "t": t, "rot": "quat" if q else "euler"}
        return out


@dataclass
class Bone:
    name: str
    index: int
    parent: int
    smooth_index: int
    rigid_index: int
    billboard: int
    flags: int
    scale: tuple
    rotation: tuple
    translation: tuple

    @property
    def euler(self):
        return bool(self.flags & (1 << 12))


# ---------------------------------------------------------------------------------------------------------
# reader


class Bfres:
    def __init__(self, data):
        self.data = bytearray(data)
        d = self.data
        if d[:4] != b"FRES":
            raise ValueError("not FRES")
        self.version = struct.unpack_from("<I", d, 8)[0]
        self.bom, self.align_shift, self.addr_size = struct.unpack_from("<HBB", d, 0xC)
        (self.filename_ofs, self.flag, self.first_block16, self.rlt_ofs,
         self.file_size) = struct.unpack_from("<IHHII", d, 0x10)
        self.name = self.string(self.q(0x20))
        self.read_reloc()

    def u8(self, o): return self.data[o]
    def u16(self, o): return struct.unpack_from("<H", self.data, o)[0]
    def s16(self, o): return struct.unpack_from("<h", self.data, o)[0]
    def u32(self, o): return struct.unpack_from("<I", self.data, o)[0]
    def s32(self, o): return struct.unpack_from("<i", self.data, o)[0]
    def q(self, o): return struct.unpack_from("<Q", self.data, o)[0]
    def f32(self, o): return struct.unpack_from("<f", self.data, o)[0]
    def fs(self, o, n): return struct.unpack_from("<%df" % n, self.data, o)

    def string(self, ptr):
        if ptr == 0:
            return None
        n = self.u16(ptr)  # string pointers point at the u16 length prefix
        return self.data[ptr + 2:ptr + 2 + n].decode("utf-8")

    @property
    def version_str(self):
        v = self.version  # u32 0x000A0400 -> 10.4.0
        return f"{(v >> 16) & 0xFF}.{(v >> 8) & 0xFF}.{v & 0xFF}"

    # header fields (v10)
    @property
    def skel_anim_array(self): return self.q(0x58)
    @property
    def skel_anim_dict(self): return self.q(0x60)
    @property
    def string_pool(self): return self.q(0xD0)
    @property
    def string_pool_size(self): return self.u32(0xD8)
    @property
    def counts(self):
        names = ["model", "unk1", "unk2", "skel_anim", "mat_anim", "bone_vis", "shape_anim", "scene_anim", "external"]
        return dict(zip(names, struct.unpack_from("<9H", self.data, 0xDC)))
    @property
    def external_flags(self): return self.u8(0xEE)

    def read_reloc(self):
        o = self.rlt_ofs
        d = self.data
        assert d[o:o + 4] == b"_RLT", "bad _RLT"
        _, nsec, _ = struct.unpack_from("<III", d, o + 4)
        self.sections = []
        p = o + 0x10
        for _ in range(nsec):
            self.sections.append(RelocSection(*struct.unpack_from("<QIIII", d, p)))
            p += 0x18
        self.reloc_entries = []
        for _ in range(sum(s.entry_count for s in self.sections)):
            self.reloc_entries.append(RelocEntry(*struct.unpack_from("<IHBB", d, p)))
            p += 8
        self.rlt_end = p
        self.slots = sorted(s for e in self.reloc_entries for s in e.slots())

    def read_dict(self, o):
        if o == 0:
            return []
        n = self.s32(o + 4)
        nodes = []
        for i in range(n + 1):
            p = o + 8 + 16 * i
            ref, l, r = struct.unpack_from("<IHH", self.data, p)
            nodes.append((ref, l, r, self.string(self.q(p + 8))))
        return nodes

    def dict_keys(self, o):
        return [n[3] for n in self.read_dict(o)[1:]]

    # models / skeleton
    def model_offsets(self):
        return [self.q(0x28) + i * 0x78 for i in range(self.counts["model"])]  # FMDL v10 = 0x78 bytes

    def model_skeleton_offset(self, model_ofs):
        assert self.data[model_ofs:model_ofs + 4] == b"FMDL"
        return self.q(model_ofs + 0x18)

    def read_skeleton(self, fskl):
        d = self.data
        assert d[fskl:fskl + 4] == b"FSKL", d[fskl:fskl + 4]
        flags = self.u32(fskl + 4)
        bone_dic, bone_arr = self.q(fskl + 8), self.q(fskl + 0x10)
        mirror = self.q(fskl + 0x30)
        nbone, nsmooth, nrigid = struct.unpack_from("<HHH", d, fskl + 0x38)
        names = self.dict_keys(bone_dic)
        bones = []
        for i in range(nbone):
            b = bone_arr + i * BONE_SIZE
            name = self.string(self.q(b))
            idx, parent, smooth, rigid, bb, nud = struct.unpack_from("<HhhhhH", d, b + 0x20)
            assert idx == i, (idx, i, name)
            bones.append(Bone(name, idx, parent, smooth, rigid, bb, self.u32(b + 0x2C),
                              self.fs(b + 0x30, 3), self.fs(b + 0x3C, 4), self.fs(b + 0x4C, 3)))
        assert [b.name for b in bones] == names
        return {"flags": flags, "bones": bones, "num_smooth": nsmooth, "num_rigid": nrigid,
                "mirror_table": list(struct.unpack_from("<%dH" % nbone, d, mirror)) if mirror else None}

    # skeletal animations
    def skel_anim_names(self):
        return self.dict_keys(self.skel_anim_dict)

    def skeletal_anims(self, names_only=False):
        arr = self.skel_anim_array
        return [self.read_fska(arr + i * FSKA_SIZE, names_only) for i in range(self.counts["skel_anim"])]

    def find_anim(self, name):
        i = self.skel_anim_names().index(name)
        return self.read_fska(self.skel_anim_array + i * FSKA_SIZE)

    def read_fska(self, o, names_only=False):
        d = self.data
        assert d[o:o + 4] == b"FSKA", d[o:o + 4]
        flags = self.u32(o + 4)
        name = self.string(self.q(o + 8))
        path = self.string(self.q(o + 0x10))
        skel = self.q(o + 0x18)
        bind_ofs, ba_ofs, ud_arr = self.q(o + 0x20), self.q(o + 0x28), self.q(o + 0x30)
        frame_count, num_curve, baked_size, nba, nud = struct.unpack_from("<iiIHH", d, o + 0x40)
        assert nud == 0 and ud_arr == 0, "user data on FSKA not supported"
        bind = list(struct.unpack_from("<%dH" % nba, d, bind_ofs)) if bind_ofs else []
        bas = [self.read_bone_anim(ba_ofs + i * BONEANIM_SIZE, names_only) for i in range(nba)]
        return SkeletalAnim(name, path, flags, frame_count, baked_size, bas, bind, num_curve, skel, o)

    def read_bone_anim(self, o, names_only=False):
        d = self.data
        name = self.string(self.q(o))
        curve_ofs, base_ofs = self.q(o + 8), self.q(o + 0x10)
        unk = struct.unpack_from("<QQ", d, o + 0x18)
        flags, brot, btr, ncurve, bbtr, bcurve, pad = struct.unpack_from("<IBBBBiI", d, o + 0x28)
        bs = br = bt = None
        p = base_ofs
        if flags & BASE_SCALE:
            bs = self.fs(p, 3); p += 12
        if flags & BASE_ROTATE:
            br = self.fs(p, 4); p += 16
        if flags & BASE_TRANSLATE:
            bt = self.fs(p, 3); p += 12
        curves = [] if names_only else [self.read_curve(curve_ofs + i * CURVE_SIZE) for i in range(ncurve)]
        return BoneAnim(name, flags, brot, btr, bbtr, bcurve, bs, br, bt, curves, unk, pad)

    def read_curve(self, o):
        d = self.data
        fr_ofs, key_ofs = self.q(o), self.q(o + 8)
        flags, nkey, target = struct.unpack_from("<HHI", d, o + 0x10)
        start, end, fscale, scale = struct.unpack_from("<ffff", d, o + 0x18)
        offset_raw, pad = struct.unpack_from("<II", d, o + 0x28)
        ft, kt = flags & 3, flags & 0xC
        # frames
        if ft == FRAME_F32:
            raw_f = bytes(d[fr_ofs:fr_ofs + 4 * nkey]); frames = list(struct.unpack("<%df" % nkey, raw_f))
        elif ft == FRAME_F16:
            raw_f = bytes(d[fr_ofs:fr_ofs + 2 * nkey])
            if flags & CF_FRAME_SCALE:
                frames = [x * fscale for x in struct.unpack("<%dH" % nkey, raw_f)]
            else:
                frames = [x / 32.0 for x in struct.unpack("<%dh" % nkey, raw_f)]
        else:
            raw_f = bytes(d[fr_ofs:fr_ofs + nkey])
            frames = [x * (fscale if flags & CF_FRAME_SCALE else 1.0) for x in raw_f]
        c = AnimCurve(flags, target, start, end, fscale, scale, offset_raw, frames, [], None, pad=pad)
        c.raw_frames = raw_f
        if not flags & CF_HERMITE:
            # legacy (<=10.0) layout: start,end,scale,offset,delta; keys = coefficients
            c.scale, c.offset_raw = fscale, f2u(scale)
            ct = flags & 0x70
            ne = {0x00: 4, 0x10: 2}.get(ct, 1)
            cnt = nkey * ne
            if kt == KEY_F32:
                raw_k = bytes(d[key_ofs:key_ofs + 4 * cnt]); vals = struct.unpack("<%df" % cnt, raw_k)
            elif kt == KEY_16:
                raw_k = bytes(d[key_ofs:key_ofs + 2 * cnt]); vals = struct.unpack("<%dh" % cnt, raw_k)
            else:
                raw_k = bytes(d[key_ofs:key_ofs + cnt]); vals = struct.unpack("<%db" % cnt, raw_k)
            c.legacy_keys = [tuple(vals[i * ne:(i + 1) * ne]) for i in range(nkey)]
            c.raw_keys = raw_k
            return c
        if flags & CF_QUAT:
            assert kt == KEY_F32, hex(flags)
            raw_k = bytes(d[key_ofs:key_ofs + 16 * nkey])
            v = struct.unpack("<%df" % (4 * nkey), raw_k)
            c.values = [tuple(v[i * 4:i * 4 + 4]) for i in range(nkey)]
            c.raw_keys = raw_k
            return c
        p = key_ofs
        if flags & CF_QUANTIZED:
            c.slope_scale, c.slope_offset = struct.unpack_from("<ff", d, p)
            p += 8
        if kt == KEY_F32:
            v = struct.unpack_from("<%df" % (2 * nkey), d, p); p += 8 * nkey
            c.values, c.slopes = list(v[0::2]), list(v[1::2])
        else:
            fmt, sz = ("H", 2) if kt == KEY_16 else ("B", 1)
            v = struct.unpack_from("<%d%s" % (2 * nkey, fmt), d, p); p += 2 * sz * nkey
            off = c.offset
            c.values = [off + scale * x for x in v[0::2]]
            c.slopes = [c.slope_offset + c.slope_scale * x for x in v[1::2]]
        c.raw_keys = bytes(d[key_ofs:p])
        return c


def load(path):
    with open(path, "rb") as f:
        return Bfres(f.read())


# ---------------------------------------------------------------------------------------------------------
# curve construction (v10.4 style, f32 keys -> no quantization; flag combos all observed in game files)


def _frame_encoding(frames):
    """Pick the frame storage like the game does: u8 for integer frames <= 255, else fx16 (1/32 steps)."""
    if all(float(f).is_integer() and 0 <= f <= 255 for f in frames):
        return FRAME_U8, bytes(int(f) for f in frames)
    if all(abs(f * 32 - round(f * 32)) < 1e-6 and -1024 <= f < 1024 for f in frames):
        return FRAME_F16, struct.pack("<%dh" % len(frames), *[int(round(f * 32)) for f in frames])
    return FRAME_F32, struct.pack("<%df" % len(frames), *frames)


def finite_diff_slopes(frames, values):
    n = len(frames)
    if n == 1:
        return [0.0]
    out = []
    for i in range(n):
        a, b = max(0, i - 1), min(n - 1, i + 1)
        out.append((values[b] - values[a]) / (frames[b] - frames[a]))
    return out


def make_hermite_curve(comp, frames, values, slopes=None):
    """Scalar curve for comp in sx..sz, rx..rz (euler radians), tx..tz. Slopes are per frame."""
    frames = [float(f) for f in frames]
    values = [float(v) for v in values]
    slopes = finite_diff_slopes(frames, values) if slopes is None else [float(s) for s in slopes]
    ft, raw_f = _frame_encoding(frames)
    flags = CF_HERMITE | KEY_F32 | ft
    raw_k = struct.pack("<%df" % (2 * len(values)), *[x for vs in zip(values, slopes) for x in vs])
    return AnimCurve(flags, TARGET_BY_NAME[comp], frames[0], frames[-1], 0.0, 0.0, 0, frames, values, slopes,
                     raw_frames=raw_f, raw_keys=raw_k)


def make_quat_curve(frames, quats):
    """Quaternion (x,y,z,w) curve, slerped between keys; must be flagged on a BONE_QUAT bone anim."""
    frames = [float(f) for f in frames]
    qs = []
    for q in quats:
        q = _qnorm(tuple(float(x) for x in q))
        if qs and sum(a * b for a, b in zip(qs[-1], q)) < 0:
            q = tuple(-x for x in q)  # keep hemisphere continuity
        qs.append(q)
    ft, raw_f = _frame_encoding(frames)
    flags = CF_HERMITE | CF_QUAT | KEY_F32 | ft
    raw_k = struct.pack("<%df" % (4 * len(qs)), *[x for q in qs for x in q])
    return AnimCurve(flags, TARGET_BY_NAME["rx"], frames[0], frames[-1], 0.0, 0.0, 0, frames, qs, None,
                     raw_frames=raw_f, raw_keys=raw_k)


def curve_bake_size(c):
    """Matches FSKA.baked_size in the game files (sum over curves)."""
    return align(4 * int(c.end - c.start + 1) + 28, 8)  # same for quaternion curves


def euler_xyz_to_quat(rx, ry, rz):
    """Quaternion for R = Rz*Ry*Rx (nn::g3d euler XYZ)."""
    cx, sx = math.cos(rx / 2), math.sin(rx / 2)
    cy, sy = math.cos(ry / 2), math.sin(ry / 2)
    cz, sz = math.cos(rz / 2), math.sin(rz / 2)
    return (sx * cy * cz - cx * sy * sz,
            cx * sy * cz + sx * cy * sz,
            cx * cy * sz - sx * sy * cz,
            cx * cy * cz + sx * sy * sz)


def build_bone_anim(name, frames, s=None, r=None, t=None, quat=None, seg_scale_compensate=True, eps=1e-6):
    """Build a BoneAnim from per-frame data. frames: list of frame numbers; s/t: list of (x,y,z);
    r: list of euler (x,y,z) radians or quaternions (x,y,z,w) if quat=True. Constant channels become base only."""
    n = len(frames)
    if quat is None:
        quat = bool(r) and len(r[0]) == 4
    base_s = tuple(s[0]) if s else (1.0, 1.0, 1.0)
    base_t = tuple(t[0]) if t else (0.0, 0.0, 0.0)
    if r:
        base_r = tuple(_qnorm(r[0])) if quat else (r[0][0], r[0][1], r[0][2], 1.0)
    else:
        base_r = (0.0, 0.0, 0.0, 1.0)
    curves = []
    if s:
        for k, comp in enumerate(("sx", "sy", "sz")):
            vals = [v[k] for v in s]
            if max(vals) - min(vals) > eps:
                curves.append(make_hermite_curve(comp, frames, vals))
    if r:
        if quat:
            if any(1 - abs(sum(a * b for a, b in zip(_qnorm(q), base_r))) > eps for q in r):
                curves.append(make_quat_curve(frames, r))
        else:
            for k, comp in enumerate(("rx", "ry", "rz")):
                vals = [v[k] for v in r]
                if max(vals) - min(vals) > eps:
                    curves.append(make_hermite_curve(comp, frames, vals))
    if t:
        for k, comp in enumerate(("tx", "ty", "tz")):
            vals = [v[k] for v in t]
            if max(vals) - min(vals) > eps:
                curves.append(make_hermite_curve(comp, frames, vals))
    flags = BASE_SCALE | BASE_ROTATE | BASE_TRANSLATE
    if seg_scale_compensate:
        flags |= SEG_SCALE_COMPENSATE
    if quat:
        flags |= BONE_QUAT
    for c in curves:
        flags |= 1 << CURVE_BITS["rw" if c.is_quat else c.comp]
    comps = {c.comp for c in curves}
    if not comps & {"sx", "sy", "sz"}:
        if base_s[0] == base_s[1] == base_s[2]:
            flags |= XF_SCALE_UNIFORM
            if base_s[0] == 1.0:
                flags |= XF_SCALE_VOLUME_ONE
    if not comps & {"rx", "ry", "rz", "rq"} and all(abs(x) < 1e-9 for x in base_r[:3]):
        flags |= XF_ROTATE_ZERO
    if not comps & {"tx", "ty", "tz"} and all(abs(x) < 1e-9 for x in base_t):
        flags |= XF_TRANSLATE_ZERO
    # order curves like the game: scale, rotate, translate; a quaternion curve first of all (the game's bone sampler,
    # f_814f0620, takes only curve 0 as a quaternion: one further down reaches the scalar sampler and aborts)
    order = {"rq": -1, "sx": 0, "sy": 1, "sz": 2, "rx": 3, "ry": 4, "rz": 5, "tx": 6, "ty": 7, "tz": 8}
    curves.sort(key=lambda c: order[c.comp])
    return BoneAnim(name, flags, 3, 6, 7, 0, base_s, base_r, base_t, curves)


# ---------------------------------------------------------------------------------------------------------
# writer


class _Blob:
    """Byte buffer with pointer slots (local offsets -> local targets or string names)."""

    def __init__(self):
        self.buf = bytearray()
        self.ptrs = []  # (slot_local, (kind, val))

    def tell(self):
        return len(self.buf)

    def align(self, a):
        self.buf += b"\0" * (align(len(self.buf), a) - len(self.buf))


def _curve_header_tail(c):
    if c.flags & CF_HERMITE:
        return struct.pack("<ffffII", c.start, c.end, c.frame_scale, c.scale, c.offset_raw, 0)
    return struct.pack("<fffIfI", c.start, c.end, c.scale, c.offset_raw, 0.0, 0)


def serialize_fska(anim: SkeletalAnim, blob: _Blob):
    """Append everything an FSKA points to (bind table, bone anims, base data, curves, frame/key data) in the
    game's order. Returns write_header(hdr_blob, ofs) which emits the 0x50-byte FSKA header."""
    bas = anim.bone_anims
    blob.align(8)
    bind = blob.tell()
    bi = anim.bind_indices if anim.bind_indices else [0xFFFF] * len(bas)
    blob.buf += struct.pack("<%dH" % len(bi), *bi)
    blob.align(8)
    ba_arr = blob.tell()
    blob.buf += b"\0" * (BONEANIM_SIZE * len(bas))
    curve_index = 0
    for i, ba in enumerate(bas):
        o = ba_arr + i * BONEANIM_SIZE
        # base data
        blob.align(4)
        base = blob.tell()
        flags = ba.flags & ~(BASE_SCALE | BASE_ROTATE | BASE_TRANSLATE | 0xFFC0)
        if ba.base_scale is not None:
            blob.buf += struct.pack("<3f", *ba.base_scale); flags |= BASE_SCALE
        if ba.base_rotate is not None:
            blob.buf += struct.pack("<4f", *ba.base_rotate); flags |= BASE_ROTATE
        if ba.base_translate is not None:
            blob.buf += struct.pack("<3f", *ba.base_translate); flags |= BASE_TRANSLATE
        if blob.tell() == base:
            base = 0
        for c in ba.curves:
            flags |= 1 << CURVE_BITS["rw" if c.is_quat else c.comp]
        # curve headers
        blob.align(8)
        cur_arr = blob.tell() if ba.curves else 0
        blob.buf += b"\0" * (CURVE_SIZE * len(ba.curves))
        for j, c in enumerate(ba.curves):
            blob.align(8)
            fo = blob.tell(); blob.buf += c.raw_frames
            blob.align(8)
            ko = blob.tell(); blob.buf += c.raw_keys
            co = cur_arr + j * CURVE_SIZE
            blob.ptrs.append((co, ("local", fo)))
            blob.ptrs.append((co + 8, ("local", ko)))
            struct.pack_into("<HHI", blob.buf, co + 0x10, c.flags, len(c.frames), c.target)
            blob.buf[co + 0x18:co + 0x30] = _curve_header_tail(c)
        blob.align(8)
        struct.pack_into("<QQQQQ", blob.buf, o, 0, 0, 0, ba.unk[0], ba.unk[1])
        blob.ptrs.append((o, ("str", ba.name)))
        if cur_arr:
            blob.ptrs.append((o + 8, ("local", cur_arr)))
        if base:
            blob.ptrs.append((o + 0x10, ("local", base)))
        struct.pack_into("<IBBBBiI", blob.buf, o + 0x28, flags, ba.begin_rotate, ba.begin_translate,
                         len(ba.curves), ba.begin_base_translate, curve_index, 0)
        curve_index += len(ba.curves)
    blob.align(8)
    num_curves = curve_index
    baked = sum(curve_bake_size(c) for ba in bas for c in ba.curves)

    def write_header(hblob, ho):
        struct.pack_into("<4sI", hblob.buf, ho, b"FSKA", anim.flags)
        hblob.ptrs.append((ho + 0x08, ("str", anim.name)))
        hblob.ptrs.append((ho + 0x10, ("str", anim.path if anim.path is not None else "")))
        hblob.ptrs.append((ho + 0x20, ("blob", bind)))
        hblob.ptrs.append((ho + 0x28, ("blob", ba_arr)))
        struct.pack_into("<iiIHH", hblob.buf, ho + 0x40, anim.frame_count, num_curves, baked, len(bas), 0)

    return write_header, num_curves, baked


class BfresEditor:
    """Edits a Bfres by inserting bytes and shifting relocated pointers."""

    def __init__(self, bf: Bfres):
        self.bf = bf
        self.data = bytearray(bf.data)
        self.slots = list(bf.slots)
        self.str_block = bf.string_pool - 0x14
        assert self.data[self.str_block:self.str_block + 4] == b"_STR"

    def q(self, o): return struct.unpack_from("<Q", self.data, o)[0]

    def insert(self, pos, nbytes):
        """Insert nbytes zero bytes at pos and shift all relocated pointers (+ non-relocated header offsets)."""
        assert nbytes % 8 == 0 and pos % 8 == 0, (pos, nbytes)
        d = self.data
        for s in self.slots:
            v = struct.unpack_from("<Q", d, s)[0]
            if v >= pos:
                struct.pack_into("<Q", d, s, v + nbytes)
        d[pos:pos] = b"\0" * nbytes
        self.slots = [s + nbytes if s >= pos else s for s in self.slots]
        if self.str_block >= pos:
            self.str_block += nbytes
        fn = struct.unpack_from("<I", d, 0x10)[0]
        if fn >= pos:
            struct.pack_into("<I", d, 0x10, fn + nbytes)

    def finalize(self, pending_strings):
        """pending_strings: [(slot, 'str', name)] -> add missing strings to the pool, rebuild _STR/_RLT/header."""
        d = self.data
        sp = self.q(0xD0)
        str_start = self.str_block
        assert sp == str_start + 0x14
        count = struct.unpack_from("<I", d, str_start + 0x10)[0]
        existing = {}
        p = sp
        for _ in range(count + 1):  # count excludes the leading empty string
            n = struct.unpack_from("<H", d, p)[0]
            existing.setdefault(d[p + 2:p + 2 + n].decode("utf-8"), p)
            p = align(p + 2 + n + 1, 2)
        pool_end = p
        new_strings = []
        for _, _, s in pending_strings:
            if s not in existing and s not in new_strings:
                new_strings.append(s)
        add = bytearray()
        new_pos = {}
        for s in new_strings:
            b = s.encode("utf-8")
            new_pos[s] = pool_end + len(add)
            add += struct.pack("<H", len(b)) + b + b"\0"
            if len(add) % 2:
                add += b"\0"
        orig_tail = len(self.bf.data) - self.bf.rlt_end
        del d[pool_end:]
        d += add
        for slot, _, s in pending_strings:
            struct.pack_into("<Q", d, slot, existing[s] if s in existing else new_pos[s])
            self.slots.append(slot)
        struct.pack_into("<I", d, str_start + 0x10, count + len(new_strings))
        sec0_end = len(d)
        while len(d) % 8:
            d += b"\0"
        rlt = len(d)
        struct.pack_into("<II", d, str_start + 4, 0, rlt - str_start)
        struct.pack_into("<I", d, 0xD8, sec0_end - str_start)
        entries = encode_reloc_entries(self.slots)
        nsec = len(self.bf.sections)
        out = bytearray(b"_RLT" + struct.pack("<III", rlt, nsec, 0))
        for i in range(nsec):
            if i == 0:
                out += struct.pack("<QIIII", 0, 0, sec0_end, 0, len(entries))
            else:
                out += struct.pack("<QIIII", 0, sec0_end, 0, len(entries), 0)
        for e in entries:
            out += struct.pack("<IHBB", e.pos, e.struct_count, e.offset_count, e.padding_count)
        d += out
        d += b"\0" * orig_tail
        struct.pack_into("<HII", d, 0x16, str_start & 0xFFFF, rlt, len(d))
        return bytes(d)


def add_skeletal_anim(bf: Bfres, anim: SkeletalAnim) -> bytes:
    """Return new file bytes with `anim` appended as the last skeletal animation (existing indices unchanged)."""
    assert bf.sections and all(s.entry_count == 0 for s in bf.sections[1:]), "multi-section files not supported"
    keys = bf.skel_anim_names()
    if anim.name in keys:
        raise ValueError(f"anim {anim.name} already exists")
    ed = BfresEditor(bf)
    n = bf.counts["skel_anim"]
    pending = []

    def shift_pending(pos, nbytes):
        return [((s + nbytes) if s >= pos else s, k, v) for s, k, v in pending]

    # 1) sub data inserted right before the _STR block (where the game keeps anim data)
    sub = _Blob()
    write_header, num_curves, baked = serialize_fska(anim, sub)
    sub_at = ed.str_block
    ed.insert(sub_at, len(sub.buf))
    ed.data[sub_at:sub_at + len(sub.buf)] = sub.buf
    for slot, (kind, val) in sub.ptrs:
        fs = sub_at + slot
        if kind == "local":
            struct.pack_into("<Q", ed.data, fs, sub_at + val)
            ed.slots.append(fs)
        else:
            pending.append((fs, kind, val))

    # 2) new FSKA header appended to the FSKA array
    arr = ed.q(0x58)
    hdr = _Blob()
    hdr.buf += b"\0" * FSKA_SIZE
    write_header(hdr, 0)
    hdr_at = arr + n * FSKA_SIZE
    ed.insert(hdr_at, FSKA_SIZE)
    pending = shift_pending(hdr_at, FSKA_SIZE)
    if sub_at >= hdr_at:
        sub_at += FSKA_SIZE
    ed.data[hdr_at:hdr_at + FSKA_SIZE] = hdr.buf
    for slot, (kind, val) in hdr.ptrs:
        fs = hdr_at + slot
        if kind == "blob":
            struct.pack_into("<Q", ed.data, fs, sub_at + val)
            ed.slots.append(fs)
        else:
            pending.append((fs, kind, val))

    # 3) rebuild the FSKA ResDic (grows by one 16-byte node)
    dic = ed.q(0x60)
    old_nodes = struct.unpack_from("<i", ed.data, dic + 4)[0] + 1
    end = dic + 8 + 16 * old_nodes
    ed.insert(end, 16)
    pending = shift_pending(end, 16)
    new_keys = keys + [anim.name]
    nodes = build_dict_nodes(new_keys)
    assert [k for *_, k in nodes[1:]] == new_keys
    old_key_ptrs = [ed.q(dic + 8 + 16 * i + 8) for i in range(old_nodes)]
    struct.pack_into("<i", ed.data, dic + 4, len(new_keys))
    slot_set = set(ed.slots)
    for i, (ref, l, r, key) in enumerate(nodes):
        p = dic + 8 + 16 * i
        struct.pack_into("<IHH", ed.data, p, ref, l, r)
        if i == 0:
            struct.pack_into("<Q", ed.data, p + 8, old_key_ptrs[0])
        elif i <= len(keys):
            struct.pack_into("<Q", ed.data, p + 8, old_key_ptrs[i])
        else:
            pending.append((p + 8, "str", key))
            continue
        assert p + 8 in slot_set

    # 4) header count
    struct.pack_into("<H", ed.data, 0xE2, n + 1)
    return ed.finalize(pending)


def rewrite_unchanged(bf: Bfres) -> bytes:
    """Round-trip through the editor without changes (re-encodes _STR header and _RLT)."""
    return BfresEditor(bf).finalize([])


def anim_from_frames(name, frame_count, bones, template: SkeletalAnim | None = None, loop=False):
    """bones: {bone_name: {'s': [[x,y,z]...], 'r': [[x,y,z]|[x,y,z,w]...], 't': [[x,y,z]...]}}, one entry per
    frame 0..frame_count (frame_count+1 samples) or 'frames': [...] explicit key frames."""
    flags = (template.flags if template else 0x2200) & ~ANIM_LOOP
    if loop:
        flags |= ANIM_LOOP
    bas = []
    for bname, ch in bones.items():
        frames = ch.get("frames") or list(range(frame_count + 1))
        r = ch.get("r")
        quat = ch.get("quat")
        if quat is None:
            quat = bool(r) and len(r[0]) == 4
        bas.append(build_bone_anim(bname, frames, ch.get("s"), r, ch.get("t"), quat=quat,
                                   seg_scale_compensate=ch.get("ssc", True)))
    return SkeletalAnim(name, "", flags, frame_count, 0, bas, [0xFFFF] * len(bas))
