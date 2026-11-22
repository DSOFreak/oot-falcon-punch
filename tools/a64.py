"""Quick static helpers over the game's Eden-layout image (Hookshot/image.bin, based at 0x80000000)."""
import struct
import sys

import capstone
import numpy as np

BASE = 0x80000000
IMG = "/Games/TF-OOT/Hookshot/image.bin"
_data = None
_words = None


def data():
    global _data
    if _data is None:
        _data = open(IMG, "rb").read()
    return _data


def words():
    global _words
    if _words is None:
        _words = np.frombuffer(data()[: len(data()) & ~3], dtype="<u4")
    return _words


def u32(a):
    return struct.unpack_from("<I", data(), a - BASE)[0]


def u64(a):
    return struct.unpack_from("<Q", data(), a - BASE)[0]


def cstr(a):
    d = data()
    o = a - BASE
    return d[o:d.index(b"\0", o)].decode("utf-8", "replace")


def find_bytes(b):
    d = data()
    out, i = [], -1
    while True:
        i = d.find(b, i + 1)
        if i < 0:
            return out
        out.append(BASE + i)


def find_str(s):
    return [a + 1 for a in find_bytes(b"\0" + s.encode() + b"\0")]


def adrp_add_refs(target, lo=None, hi=None):
    """Sites of ADRP Xn,page ; (ADD|LDR) .., Xn, #off resolving to target (the next few instructions)."""
    w = words()
    page = target & ~0xFFF
    off = target & 0xFFF
    idx = np.nonzero((w & 0x9F000000) == 0x90000000)[0]
    out = []
    for i in idx:
        pc = BASE + int(i) * 4
        if lo and pc < lo or hi and pc >= hi:
            continue
        ins = int(w[i])
        immlo = (ins >> 29) & 3
        immhi = (ins >> 5) & 0x7FFFF
        imm = (immhi << 2) | immlo
        if imm & (1 << 20):
            imm -= 1 << 21
        if (pc & ~0xFFF) + (imm << 12) != page:
            continue
        rd = ins & 31
        for j in range(1, 6):
            if i + j >= len(w):
                break
            n = int(w[i + j])
            if (n & 0xFFC00000) == 0x91000000 and ((n >> 5) & 31) == rd:      # ADD imm (64-bit)
                if ((n >> 10) & 0xFFF) == off:
                    out.append(pc + j * 4)
                break
            if (n & 0xBFC00000) == 0xB9400000 and ((n >> 5) & 31) == rd:      # LDR Wt/Xt [Xn,#imm]
                scale = 8 if n & 0x40000000 else 4
                if ((n >> 10) & 0xFFF) * scale == off:
                    out.append(pc + j * 4)
                break
    return out


def ptr_refs(target):
    d = data()
    b = struct.pack("<Q", target)
    return [a for a in find_bytes(b) if (a - BASE) % 8 == 0]


def bl_refs(target):
    w = words()
    idx = np.nonzero((w & 0xFC000000) == 0x94000000)[0]
    pcs = BASE + idx.astype(np.int64) * 4
    imm = (w[idx] & 0x3FFFFFF).astype(np.int64)
    imm = np.where(imm & (1 << 25), imm - (1 << 26), imm)
    return [int(p) for p in pcs[pcs + imm * 4 == target]]


_md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)


def dis(lo, hi):
    for ins in _md.disasm(data()[lo - BASE:hi - BASE], lo):
        print(f"  {ins.address:#x}: {ins.mnemonic} {ins.op_str}")


def func_start(pc, limit=0x4000):
    """Heuristic: walk back to a likely prologue (stp x29,x30 / sub sp) after a ret/b."""
    a = pc
    while a > pc - limit:
        a -= 4
        prev = u32(a - 4)
        if prev == 0xD65F03C0 or (prev & 0xFC000000) == 0x14000000:   # ret / b
            ins = u32(a)
            if (ins & 0xFF8003FF) == 0xD10003FF or (ins & 0xFFC07FFF) in (0xA9807BFD, 0xA9BF7BFD) or (ins & 0x7FC00000) == 0x29800000 or (ins & 0xFFC003E0) == 0xA98003E0:
                return a
    return None


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "str":
        for s in sys.argv[2:]:
            for a in find_str(s):
                print(s, hex(a), "adrp:", [hex(x) for x in adrp_add_refs(a)], "ptr:", [hex(x) for x in ptr_refs(a)])
    elif cmd == "dis":
        dis(int(sys.argv[2], 0), int(sys.argv[3], 0))
    elif cmd == "bl":
        print([hex(x) for x in bl_refs(int(sys.argv[2], 0))])
