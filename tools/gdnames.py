"""Collect candidate GameData names from strings in romfs files, match to GameDataList hashes."""
import re, sys, mmh3, json
from pathlib import Path
sys.path.insert(0, 'tools'); import zs, byml7
ROM = zs.ROMFS
cands = set(l.strip() for l in open('/tmp/opencode/main_strings.txt', errors='ignore'))
pat = re.compile(rb'[A-Za-z_][A-Za-z0-9_.%]{3,120}')
files = list(ROM.glob('Logic/*')) + list(ROM.glob('AI/*')) + list(ROM.glob('AS/*')) + list(ROM.glob('Sequence/*')) + list(ROM.glob('Event/**/*'))
for p in files:
    if not p.is_file(): continue
    try:
        data = zs.decompress(p.read_bytes(), p.name) if p.name.endswith('.zs') else p.read_bytes()
    except Exception:
        continue
    if data[:4] == b'SARC':
        import oead
        try:
            for f in oead.Sarc(data).get_files(): cands.update(m.decode() for m in pat.findall(bytes(f.data)))
        except Exception: pass
    cands.update(m.decode() for m in pat.findall(data))
h = {mmh3.hash(s, signed=False): s for s in cands}
d = byml7.load(zs.load('GameData/GameDataList.Product.110.byml.zs'))['Data']
out = {}
for k in d:
    for e in d[k]:
        hh = int(e['Hash'])
        if hh in h: out[f'{hh:08x}'] = [k, h[hh]]
json.dump(out, open('out/gamedata_names.json', 'w'), indent=0)
print(len(cands), len(out))
