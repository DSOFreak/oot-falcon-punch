"""Read the game's progress.sav (TotK-style GameData save): header 0x20, then (u32 hash, u32 value) pairs grouped by
type, each group introduced by a (0, 0) marker in GameDataList type order. Usage: progress_sav.py SAVE [name|hash ...]"""
import struct, sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))

TYPE_ORDER = None


def load(path):
    b = Path(path).read_bytes()
    magic, ver, data_off = struct.unpack_from("<III", b, 0)
    assert magic == 0x01020304, hex(magic)
    pairs = []
    off, sect = 0x20, -1
    while off < data_off:
        h, v = struct.unpack_from("<II", b, off)
        if h == 0:
            sect += 1
        else:
            pairs.append((sect, off, h, v))
        off += 8
    return b, data_off, pairs


if __name__ == "__main__":
    import mmh3
    b, data_off, pairs = load(sys.argv[1])
    print("data_off", hex(data_off), "entries", len(pairs), "sections", pairs[-1][0] + 1)
    idx = {h: (s, o, v) for s, o, h, v in pairs}
    for q in sys.argv[2:]:
        h = int(q, 16) if q.startswith("0x") else mmh3.hash(q, signed=False)
        print(q, hex(h), idx.get(h))


def patch(path, out, sets):
    """sets: {name_or_hash: u32 value} for entries that exist (bool/int/enum stored inline)."""
    import mmh3
    b, data_off, pairs = load(path)
    b = bytearray(b)
    idx = {h: o for s, o, h, v in pairs}
    for k, v in sets.items():
        h = k if isinstance(k, int) else mmh3.hash(k, signed=False)
        struct.pack_into("<I", b, idx[h] + 4, v & 0xFFFFFFFF)
    Path(out).write_bytes(bytes(b))
