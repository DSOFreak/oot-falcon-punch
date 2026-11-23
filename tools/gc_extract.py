"""Extract files from a GameCube CISO image by name (reads the FST)."""
import struct
import sys
from pathlib import Path


class Ciso:
    def __init__(self, path):
        self.f = open(path, "rb")
        hdr = self.f.read(0x8000)
        assert hdr[:4] == b"CISO", "not a CISO image"
        self.bs = struct.unpack_from("<I", hdr, 4)[0]
        self.map = []
        n = 0
        for b in hdr[8:]:
            self.map.append(n if b else None)
            n += b

    def read(self, off, size):
        out = bytearray()
        while size > 0:
            blk, inner = divmod(off, self.bs)
            take = min(size, self.bs - inner)
            idx = self.map[blk]
            if idx is None:
                out += b"\0" * take
            else:
                self.f.seek(0x8000 + idx * self.bs + inner)
                out += self.f.read(take)
            off += take
            size -= take
        return bytes(out)


def fst_entries(disc):
    fst_off, fst_size = struct.unpack(">II", disc.read(0x424, 8))
    fst = disc.read(fst_off, fst_size)
    count = struct.unpack_from(">I", fst, 8)[0]
    names = fst[count * 12:]
    out = {}
    stack = [(count, "")]
    for i in range(1, count):
        while stack and i >= stack[-1][0]:
            stack.pop()
        flags_name, a, b = struct.unpack_from(">III", fst, i * 12)
        is_dir = flags_name >> 24
        noff = flags_name & 0xFFFFFF
        name = names[noff:names.index(b"\0", noff)].decode("shift_jis", "replace")
        prefix = stack[-1][1] if stack else ""
        path = prefix + name
        if is_dir:
            stack.append((b, path + "/"))
        else:
            out[path] = (a, b)
    return out


if __name__ == "__main__":
    disc = Ciso(sys.argv[1])
    outdir = Path(sys.argv[2])
    files = fst_entries(disc)
    wanted = sys.argv[3:]
    if not wanted:
        for k in sorted(files):
            print(k, files[k][1])
        sys.exit()
    outdir.mkdir(parents=True, exist_ok=True)
    for w in wanted:
        off, size = files[w]
        (outdir / w).parent.mkdir(parents=True, exist_ok=True)
        (outdir / w).write_bytes(disc.read(off, size))
        print("wrote", w, size)
