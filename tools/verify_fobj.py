#!/usr/bin/env python3
"""Cross-check of the fobj.c state-machine port in melee_anim.py against an
independent "decode all keys, then evaluate" implementation of the same
format. Reports max abs difference per action over all tracks and frames."""

import math
import struct
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hsd_archive  # noqa: E402
import melee_anim as M  # noqa: E402


def read_val(ad, pos, frac):
    if frac == M.FRAC_FLOAT:
        return struct.unpack_from("<f", ad, pos)[0], pos + 4
    kind, sh = frac & 0xE0, frac & 0x1F
    if kind == M.FRAC_S8:
        return struct.unpack_from("<b", ad, pos)[0] / (1 << sh), pos + 1
    if kind == M.FRAC_U8:
        return ad[pos] / (1 << sh), pos + 1
    if kind == M.FRAC_S16:
        return struct.unpack_from("<h", ad, pos)[0] / (1 << sh), pos + 2
    if kind == M.FRAC_U16:
        return struct.unpack_from("<H", ad, pos)[0] / (1 << sh), pos + 2
    raise ValueError(frac)


def varint(ad, pos):
    v = sh = 0
    while True:
        d = ad[pos]; pos += 1
        v |= (d & 0x7F) << sh; sh += 7
        if not d & 0x80:
            return v, pos


def decode_segments(tr):
    """Walk the whole byte stream once, applying the register updates of
    fobj.c FObjAnim{CON,Linear,SPL0,SPL,SLP,Key} (p0/p1/d0/d1/op_intrp), and
    emit one segment per key interval: (start, T, interp, p0, p1, d0, d1)."""
    ad, n = tr["ad"], tr["length"]
    pos = 0
    op = 0
    p0 = p1 = d0 = d1 = 0.0
    frame = 0
    segs = []
    pending = None  # segment waiting for its end key: (start, T)
    first = True
    while pos < n:
        b = ad[pos]; pos += 1
        rec_op = b & 0xF
        cnt = ((b >> 4) & 7) + 1
        if b & 0x80:
            extra = sh = 0
            while True:
                d = ad[pos]; pos += 1
                extra += (d & 0x7F) << (3 + sh); sh += 7
                if not d & 0x80:
                    break
            cnt += extra
        for _ in range(cnt):
            op_intrp = op
            op = rec_op
            if op in (M.OP_CON, M.OP_LIN):
                p0 = p1
                p1, pos = read_val(ad, pos, tr["frac_value"])
                if op_intrp != M.OP_SLP:
                    d0 = d1; d1 = 0.0
            elif op == M.OP_SPL0:
                p0 = p1; d0 = d1
                p1, pos = read_val(ad, pos, tr["frac_value"]); d1 = 0.0
            elif op == M.OP_SPL:
                p0 = p1
                p1, pos = read_val(ad, pos, tr["frac_value"])
                d0 = d1
                d1, pos = read_val(ad, pos, tr["frac_slope"])
            elif op == M.OP_SLP:
                d0 = d1
                d1, pos = read_val(ad, pos, tr["frac_slope"])
                continue  # no wait after a slope record
            else:
                raise ValueError(op)
            if pending is not None:
                segs.append((pending[0], pending[1], op_intrp, p0, p1, d0, d1))
            elif first:
                first = False
            if pos < n:
                w, pos = varint(ad, pos)
                pending = (frame, w)
                frame += w
            else:
                pending = None
                segs.append((frame, None, None, p1, p1, 0, 0))
    return segs


def eval_segs(segs, t, start):
    t = t + start
    if t < 0 or not segs:
        return None
    for (f0, T, it, p0, p1, d0, d1) in segs:
        if T is None:
            return p1
        if f0 <= t < f0 + T:
            u = t - f0
            if it == M.OP_CON:
                return p0
            if it == M.OP_LIN:
                return p0 + (p1 - p0) * u / T
            return float(M.spl_get_helmite(1.0 / T, u, p0, p1, d0, d1))
    # past the last key interval without a terminating key: hold the end value
    return segs[-1][4]


def main():
    plca = hsd_archive.load(M.MELEE / "PlCa.dat")
    plnr = hsd_archive.load(M.MELEE / "PlCaNr.dat")
    plco = hsd_archive.load(M.MELEE / "PlCo.dat")
    aj = (M.MELEE / "PlCaAJ.dat").read_bytes()
    joints = M.load_joints(plnr)
    parts = M.load_parts_table(plco)
    M.name_joints(joints, parts)
    acts = M.load_actions(plca)
    for idx in (M.FTCA_SM_SPECIALN, M.FTCA_SM_SPECIALAIRN):
        tree = M.load_figatree(aj, acts[idx])
        frames, jmap = M.evaluate(joints, tree, parts)
        worst = (0, None)
        ops_seen = set()
        fracs = set()
        for ji, tids in jmap.items():
            for t in tids:
                tr = tree["tracks"][t]
                keys = decode_segments(tr)
                ops_seen |= {k[2] for k in keys if k[2] is not None}
                fracs.add((tr["frac_value"] & 0xE0, tr["frac_slope"] & 0xE0))
                ty = tr["obj_type"]
                for f in range(len(frames)):
                    ref = eval_segs(keys, f, tr["startframe"])
                    if ref is None:
                        continue
                    if ty in (1, 2, 3):
                        got = frames[f][ji]["r"][ty - 1]
                    elif ty in (5, 6, 7):
                        got = frames[f][ji]["t"][ty - 5]
                    elif ty in (8, 9, 10):
                        got = frames[f][ji]["s"][ty - 8]
                    else:
                        continue
                    d = abs(got - ref)
                    if d > worst[0]:
                        worst = (d, (joints[ji]["name"], M.TRACK_TYPE_NAMES[ty], f, got, ref))
        print(acts[idx]["symbol"], "tracks:", sum(len(v) for v in jmap.values()),
              "ops used:", sorted(ops_seen), "frac kinds (value,slope):", sorted(fracs),
              "max |diff|:", worst)


if __name__ == "__main__":
    main()
