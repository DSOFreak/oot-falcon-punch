"""Minimal MSBT (MsgStdBn) reader/editor: labels (LBL1) and texts (TXT2), little endian, UTF-8 (this game) or UTF-16.

    uv run python tools/msbt.py Mals/USen.Product.110.sarc.zs ActorMsg/PouchContent.msbt [label-substring]

Texts are kept as raw bytes, so control tags (0x0E ...) survive untouched. set_text() replaces a whole
entry with plain text. Other sections (ATR1, NLI1, ...) are copied as they are.
"""
import struct
import sys


class Msbt:
    def __init__(self, data):
        d = bytes(data)
        assert d[:8] == b"MsgStdBn", d[:8]
        assert d[8:10] == b"\xff\xfe", "big endian not supported"
        self.head = bytearray(d[:0x20])
        self.utf8 = d[0x0C] == 0       # (header byte 0x0C: 0 = UTF-8, 1 = UTF-16)
        nsec = struct.unpack_from("<H", d, 0x0E)[0]
        self.sections = []          # [(magic, bytes body)]
        p = 0x20
        for _ in range(nsec):
            magic = d[p:p + 4]
            size = struct.unpack_from("<I", d, p + 4)[0]
            body = d[p + 0x10:p + 0x10 + size]
            self.sections.append([magic, bytearray(body)])
            p += 0x10 + size
            p += -p % 16
        self.labels = self._labels()
        self.texts = self._texts()

    def _sec(self, magic):
        for s in self.sections:
            if s[0] == magic:
                return s
        raise KeyError(magic)

    def _labels(self):
        b = self._sec(b"LBL1")[1]
        n = struct.unpack_from("<I", b, 0)[0]
        out = {}
        for k in range(n):
            cnt, off = struct.unpack_from("<II", b, 4 + 8 * k)
            p = off
            for _ in range(cnt):
                ln = b[p]
                name = b[p + 1:p + 1 + ln].decode()
                idx = struct.unpack_from("<I", b, p + 1 + ln)[0]
                out[name] = idx
                p += 1 + ln + 4
        return out

    def _texts(self):
        b = self._sec(b"TXT2")[1]
        n = struct.unpack_from("<I", b, 0)[0]
        offs = [struct.unpack_from("<I", b, 4 + 4 * k)[0] for k in range(n)] + [len(b)]
        return [bytes(b[offs[k]:offs[k + 1]]) for k in range(n)]

    def plain(self, raw):
        """Readable text: control tags shown as {group.type}"""
        if self.utf8:
            return raw.split(b"\0")[0].decode("utf-8", "replace").replace("\x0e", "{tag}")
        u = [struct.unpack_from("<H", raw, i)[0] for i in range(0, len(raw) - 1, 2)]
        out, i = [], 0
        while i < len(u):
            c = u[i]
            if c == 0:
                break
            if c == 0x0E:   # tag: group, type, param size, params
                size = u[i + 3]
                out.append(f"{{{u[i + 1]}.{u[i + 2]}}}")
                i += 4 + size // 2
                continue
            if c == 0x0F:
                out.append("{/}")
                i += 3
                continue
            out.append(chr(c))
            i += 1
        return "".join(out)

    def text(self, label):
        return self.plain(self.texts[self.labels[label]])

    def set_text(self, label, s):
        self.texts[self.labels[label]] = s.encode("utf-8") + b"\0" if self.utf8 else s.encode("utf-16-le") + b"\0\0"

    def to_bytes(self):
        txt = self._sec(b"TXT2")
        n = len(self.texts)
        body = bytearray(struct.pack("<I", n))
        off = 4 + 4 * n
        for t in self.texts:
            body += struct.pack("<I", off)
            off += len(t)
        for t in self.texts:
            body += t
        txt[1] = body
        out = bytearray(self.head)
        for magic, b in self.sections:
            out += magic + struct.pack("<I", len(b)) + b"\0" * 8 + b
            out += b"\xab" * (-len(out) % 16)
        struct.pack_into("<I", out, 0x12, len(out))
        return bytes(out)


def main():
    sys.path.insert(0, __file__.rsplit("/", 1)[0])
    import oead
    import zs
    s = oead.Sarc(zs.load(sys.argv[1]))
    m = Msbt(bytes(s.get_file(sys.argv[2]).data))
    sub = sys.argv[3] if len(sys.argv) > 3 else ""
    for name, idx in sorted(m.labels.items(), key=lambda x: x[1]):
        if sub in name:
            print(f"{idx:4d} {name}: {m.plain(m.texts[idx])!r}")


if __name__ == "__main__":
    main()
