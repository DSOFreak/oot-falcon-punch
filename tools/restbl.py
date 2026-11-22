"""TotK-style RESTBL (System/Resource/ResourceSizeTable.*.rsizetable.zs): read, query, set entries.
Layout: "RESTBL" magic, u32 version, u32 string size (0xA0), u32 crc count, u32 name count;
crc entries (u32 crc32(path), u32 size) sorted by crc; name entries (char[str_size], u32 size).
Usage: restbl.py [path ...]   (prints the size entry for each romfs path, without .zs)"""
import struct, sys, zlib
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
import zs

REL = "System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs"


class Restbl:
    def __init__(self, data):
        assert data[:6] == b"RESTBL", data[:8]
        self.version, self.str_size, nc, nn = struct.unpack_from("<IIII", data, 6)
        o = 22
        self.crc = {}
        for _ in range(nc):
            c, s = struct.unpack_from("<II", data, o); self.crc[c] = s; o += 8
        self.names = {}
        for _ in range(nn):
            n = data[o:o + self.str_size].split(b"\0")[0].decode(); s = struct.unpack_from("<I", data, o + self.str_size)[0]
            self.names[n] = s; o += self.str_size + 4
        assert o == len(data), (o, len(data))

    def get(self, path):
        if path in self.names:
            return self.names[path]
        return self.crc.get(zlib.crc32(path.encode()))

    def set(self, path, size):
        if path in self.names:
            self.names[path] = size
        else:
            self.crc[zlib.crc32(path.encode())] = size

    def to_bytes(self):
        out = bytearray(b"RESTBL") + struct.pack("<IIII", self.version, self.str_size, len(self.crc), len(self.names))
        for c in sorted(self.crc):
            out += struct.pack("<II", c, self.crc[c])
        for n in sorted(self.names):
            out += n.encode().ljust(self.str_size, b"\0") + struct.pack("<I", self.names[n])
        return bytes(out)


def load(romfs=zs.ROMFS):
    p = Path(romfs) / REL
    return Restbl(zs.decompress(p.read_bytes(), p.name))


def save(t, out_path):
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    import zstandard
    # the game reads this table without a dictionary (the original frame has dict id 0)
    Path(out_path).write_bytes(zstandard.ZstdCompressor(level=19).compress(t.to_bytes()))


if __name__ == "__main__":
    t = load()
    print("version", t.version, "crc", len(t.crc), "names", len(t.names))
    assert t.to_bytes() == zs.decompress((zs.ROMFS / REL).read_bytes()), "round trip"
    for p in sys.argv[1:]:
        print(p, t.get(p))
