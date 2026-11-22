"""Minimal HSD archive (.dat) reader.

Mirrors sysdolphin/baselib/archive.c:HSD_ArchiveParse:
  header (0x20): file_size, data_size, nb_reloc, nb_public, nb_extern, version, pad[2]
  data block   : header.data_size bytes starting at 0x20
  reloc table  : nb_reloc u32 offsets (into data) of pointer words to relocate
  public table : nb_public (offset, symbol_string_offset)
  extern table : nb_extern (offset, symbol_string_offset)
  symbol strings
All pointers inside the data block are offsets relative to the data block
start (archive.c:Locate adds archive->data to every reloc'd word).
"""

import struct


class HSDArchive:
    def __init__(self, blob: bytes, name: str = "?"):
        self.name = name
        self.blob = blob
        (self.file_size, self.data_size, self.nb_reloc, self.nb_public,
         self.nb_extern) = struct.unpack_from(">5I", blob, 0)
        if self.file_size != len(blob):
            raise ValueError(f"{name}: header file_size {self.file_size:#x} != {len(blob):#x}")
        self.data = blob[0x20:0x20 + self.data_size]
        off = 0x20 + self.data_size
        self.reloc = set(struct.unpack_from(f">{self.nb_reloc}I", blob, off))
        off += 4 * self.nb_reloc
        pub = [struct.unpack_from(">2I", blob, off + 8 * i) for i in range(self.nb_public)]
        off += 8 * self.nb_public
        ext = [struct.unpack_from(">2I", blob, off + 8 * i) for i in range(self.nb_extern)]
        off += 8 * self.nb_extern
        self.symtab_off = off

        def sym(o):
            s = self.symtab_off + o
            e = blob.index(b"\0", s)
            return blob[s:e].decode("ascii")

        self.publics = {sym(s): o for (o, s) in pub}
        self.externs = {sym(s): o for (o, s) in ext}

    # --- primitive readers (big-endian, PowerPC) ---
    def u8(self, o): return self.data[o]
    def s8(self, o): return struct.unpack_from(">b", self.data, o)[0]
    def u16(self, o): return struct.unpack_from(">H", self.data, o)[0]
    def s16(self, o): return struct.unpack_from(">h", self.data, o)[0]
    def u32(self, o): return struct.unpack_from(">I", self.data, o)[0]
    def s32(self, o): return struct.unpack_from(">i", self.data, o)[0]
    def f32(self, o): return struct.unpack_from(">f", self.data, o)[0]
    def vec3(self, o): return list(struct.unpack_from(">3f", self.data, o))

    def ptr(self, o):
        """Pointer at data offset o -> data offset, or None when NULL
        (a word is a pointer only if listed in the relocation table)."""
        if o in self.reloc:
            return self.u32(o)
        return None

    def cstr(self, o):
        e = self.data.index(b"\0", o)
        return self.data[o:e].decode("ascii", "replace")


def load(path):
    with open(path, "rb") as f:
        return HSDArchive(f.read(), str(path))
