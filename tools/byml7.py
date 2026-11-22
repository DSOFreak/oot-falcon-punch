"""BYML v7 via oead: the node types the game uses are the v4 ones, so the version field is swapped."""
import struct

import oead


def load(data):
    data = bytearray(data)
    le = data[:2] == b"YB"
    fmt = "<H" if le else ">H"
    struct.pack_into(fmt, data, 2, 4)
    return oead.byml.from_binary(bytes(data))


def dump(node, big_endian=False):
    data = bytearray(oead.byml.to_binary(node, big_endian=big_endian, version=4))
    struct.pack_into(">H" if big_endian else "<H", data, 2, 7)
    return bytes(data)


def text(data):
    return oead.byml.to_text(load(data))
