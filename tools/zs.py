"""zstd helpers for the game's RomFS (.zs files, dictionaries from Pack/ZsDic.pack.zs)."""
import sys
from pathlib import Path

import oead
import zstandard as zstd

ROMFS = Path("/Games/TF-OOT/Hookshot/romfs")
_dicts = None


def dicts():
    global _dicts
    if _dicts is None:
        raw = zstd.ZstdDecompressor().decompress((ROMFS / "Pack/ZsDic.pack.zs").read_bytes())
        sarc = oead.Sarc(raw)
        _dicts = {f.name: zstd.ZstdCompressionDict(bytes(f.data)) for f in sarc.get_files()}
    return _dicts


def dict_for(name):
    if name.endswith(".bcett.byml.zs"):
        return "bcett.byml.zsdic"
    if name.endswith(".pack.zs"):
        return "pack.zsdic"
    return "zs.zsdic"


def decompress(data, name=""):
    d = dicts()
    for key in [dict_for(name)] + list(d):
        try:
            return zstd.ZstdDecompressor(dict_data=d[key]).decompress(data)
        except zstd.ZstdError:
            continue
    return zstd.ZstdDecompressor().decompress(data)


def compress(data, name=""):
    return zstd.ZstdCompressor(level=19, dict_data=dicts()[dict_for(name)]).compress(data)


def load(rel):
    p = ROMFS / rel if not Path(rel).is_absolute() else Path(rel)
    return decompress(p.read_bytes(), p.name)


def sarc(rel):
    return oead.Sarc(load(rel))


if __name__ == "__main__":
    print(list(dicts()))
    for a in sys.argv[1:]:
        data = load(a)
        out = Path("unpacked") / Path(a).name.removesuffix(".zs")
        out.parent.mkdir(exist_ok=True)
        out.write_bytes(data)
        print(out, len(data), data[:8])
