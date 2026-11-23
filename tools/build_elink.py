"""The punch's flames: the effect link file (ELink2/elink2.Product.*.belnk) with the punch's animations.

    uv run python tools/build_elink.py SRC.belnk OUT.belnk

The game starts an effect when an animation starts: the player's user (Player_Adult) has, per slot (Skl[Lower]: the
body's animation), a list of actions, an animation's name each, with triggers: an asset call of the user from a
frame on (the hammer's swing has its blur this way). The punch's animations get actions of their own, with the
flame of "Link is burning" (the asset call of his right upper arm, emitter set Ply_Fire_Burn_M_00): once on the
fist (the trigger's own Bone parameter: the hand's weapon bone), and from the thrust on, on the arm itself.

Nothing of the file is rewritten: the new actions, triggers, the Bone parameter set and the names are inserted,
and what points behind an insert is moved (the header's positions, the users' offsets, the slots' indices).
"""
import random
import struct
import sys

from xlnk import User, Xlnk, asset_params

USER = "Player_Adult"
SLOT = "Skl[Lower]"
FLAME_PART = "右上腕"            # the burning player's right upper arm
FLAME_ESET = "Ply_Fire_Burn_M_00"
FIST_BONE = "Weapon_R"
# animation -> (action flag, as the hammer's animation in its place has it; [(first frame, on the fist?)])
ACTIONS = {
    "FalconPunch_Ground": (1, [(6, True), (38, False)]),       # (the fist goes out at 42: tools/make_phases.py)
    "FalconPunch_GroundZero": (1, [(6, True), (38, False)]),
    "FalconPunch_Pre": (0, [(6, True)]),
    "FalconPunch_St": (0, [(0, True), (0, False)]),
    "FalconPunch_Jump": (0, [(0, True), (0, False)]),
    "FalconPunch_Land": (0, [(0, True), (0, False)]),
}
TRIGGER_END = 0x7FFFFFFF
TRIGGER_TAG = 0x4C8D   # (every trigger of the file has it)


def insert(x, at, blob):
    """blob into the file at `at`; what the header and the user table hold of positions at or behind it moves"""
    n = len(blob)
    x.d[at:at] = blob
    struct.pack_into("<I", x.d, 4, x.u32(4) + n)
    for o in (0x18, 0x20, 0x40, 0x50, 0x58):
        if x.u64(o) >= at:
            struct.pack_into("<Q", x.d, o, x.u64(o) + n)
    for i in range(x.nuser):
        o = x.off_at + 8 * i
        if x.u64(o) >= at:
            struct.pack_into("<Q", x.d, o, x.u64(o) + n)
    x.names = x.u64(0x58)


def add_name(x, s):
    off = len(x.d) - x.names
    x.d += s.encode() + b"\0"
    struct.pack_into("<I", x.d, 4, len(x.d))
    return off


def find_name(x, s):
    i = bytes(x.d).find(b"\0" + s.encode() + b"\0", x.names)
    assert i > 0, s
    return i + 1 - x.names


def overwrite_sets(x):
    """The trigger parameter sets: [(position from the table, mask, values)]"""
    at, end, out = x.u64(0x18), x.u64(0x20), []
    o = at
    while o < end:
        mask = x.u32(o)
        n = bin(mask).count("1")
        out.append((o - at, mask, struct.unpack_from("<%dI" % n, x.d, o + 4)))
        o += 4 + 4 * n
    assert o == end
    return out


def build(data):
    x = Xlnk(data)
    u = x.user(USER)
    part = None
    # the table starts after the header, the local properties, the user parameters and the sorted ids (u16 each)
    nu = struct.unpack_from("<I", x.d, x.off_at + 8 * x.nuser + 4)[0]
    base = u.at + 0x38 + 8 * u.nlocal + 4 * nu + 2 * u.ncall
    base = (base + 3) & ~3
    for i in range(u.ncall):
        k, aid, flag, _, parent, _, _, _, params, _ = struct.unpack_from("<QhHiiIIIQi", x.d, base + 0x30 * i)
        if x.name(k) == FLAME_PART and not flag & 1:
            p = asset_params(x, params)
            assert p.get("RuntimeAssetName") == FLAME_ESET, p
            part = i
            break
    assert part is not None, FLAME_PART

    # 1. the names (the name table is the file's end)
    assert x.u32(4) == len(x.d)
    names = {a: add_name(x, a) for a in ACTIONS}

    # 2. the triggers and the actions, into the user's trigger table
    slots = u.slots()
    si = [s[0] for s in slots].index(SLOT)
    _, s_first, s_last = slots[si]
    acts = u.actions()
    assert not set(ACTIONS) & {a[0] for a in acts[s_first:s_last + 1]}
    have = [a[0] for a in acts[s_first:s_last + 1]]
    assert have == sorted(have), "the slot's actions are not sorted by name"
    sets = overwrite_sets(x)
    fist_pos = x.u64(0x20) - x.u64(0x18)   # (the new set goes to the table's end)
    trig = b""
    rng = random.Random(0xFA1C0)
    new_actions = []
    nt = u.ntrigger
    for name in sorted(ACTIONS):
        flag, trs = ACTIONS[name]
        first_t = nt
        for frame, fist in trs:
            trig += struct.pack("<IIQiIiHHQ", rng.getrandbits(32), 0, part * 0x30, frame, 0, TRIGGER_END, 0,
                                TRIGGER_TAG, fist_pos if fist else 0xFFFFFFFF)
            nt += 1
        new_actions.append((name, struct.pack("<QHHI", names[name], first_t, flag, nt - 1)))
    props_at, actions_at = u.props_at, u.actions_at
    insert(x, props_at, trig)
    # (sorted into the slot)
    order = sorted(have + [n for n, _ in new_actions])
    added = 0
    for name, rec in new_actions:
        idx = s_first + order.index(name)
        insert(x, actions_at + 0x10 * idx, rec)
        added += 1
    struct.pack_into("<II", x.d, u.at + 0x18, u.naction + added, nt)
    for k in range(u.nslot):
        o = u.slots_at + 0x10 * k
        a, b = struct.unpack_from("<hh", x.d, o + 8)
        if k == si:
            b += added
        elif a > s_last:
            a, b = a + added, b + added
        struct.pack_into("<hh", x.d, o + 8, a, b)

    # 3. the trigger parameter set: Bone alone (mask bit 1; a text value is 1 << 24 | the name's offset)
    bone = find_name(x, FIST_BONE)
    assert all(v >> 24 == 1 for _, m, vals in sets if m & 2 for v in vals[bin(m & 1).count("1"):][:1])
    count = x.u32(0x14)
    assert count in (len(sets), sum(len(v) for _, _, v in sets)), (count, len(sets))
    insert(x, x.u64(0x20), struct.pack("<II", 2, 1 << 24 | bone))
    struct.pack_into("<I", x.d, 0x14, count + 1)
    x.d += b"\0" * (-len(x.d) % 8)   # (the names are the file's end: its size stays a multiple of 8)
    struct.pack_into("<I", x.d, 4, len(x.d))
    return bytes(x.d)


def describe(data):
    x = Xlnk(data)
    u = x.user(USER)
    acts, tr = u.actions(), u.triggers()
    out = []
    for name, a, b in u.slots():
        if name == SLOT:
            for n, first, flag, last in acts[a:b + 1]:
                out.append((n, flag, [(t[3], t[2] // 0x30, t[8]) for t in tr[first:last + 1]]))
    return out


def checked(old):
    """build(old), read again: the punch's actions are there, and nothing else of the file reads differently"""
    new = build(old)
    before, after = describe(old), describe(new)
    assert [a for a in after if a[0] not in ACTIONS] == before, "the slot's other actions changed"
    # (every other user reads as before)
    xo, xn = Xlnk(old), Xlnk(new)
    for i in range(xo.nuser):
        a, b = User(xo, xo.u64(xo.off_at + 8 * i)), User(xn, xn.u64(xn.off_at + 8 * i))
        if a.at != xo.user(USER).at:
            assert bytes(xo.d[a.at:a.end]) == bytes(xn.d[b.at:b.end]), i
    assert bytes(xo.d[xo.u64(0x50):xo.names]) == bytes(xn.d[xn.u64(0x50):xn.names])
    return new


def main():
    src, dst = sys.argv[1:3]
    old = open(src, "rb").read()
    new = checked(old)
    open(dst, "wb").write(new)
    for a in describe(new):
        if a[0] in ACTIONS:
            print(" ", a)
    print(f"{dst}: {len(old)} -> {len(new)} bytes, {len(ACTIONS)} actions for the punch")


if __name__ == "__main__":
    main()
