#!/usr/bin/env python3
"""Melee (GALE01 v1.02) Captain Falcon "Falcon Punch" extractor.

Decodes, following the doldecomp/melee sources (paths relative to
/home/lm/projects/decomp/refs/melee/src):

* HSD archives            sysdolphin/baselib/archive.c:HSD_ArchiveParse   (tools/hsd_archive.py)
* ftData action table     melee/ft/types.h:struct ftData (+0xC Fighter_WaitAnimData[])
                          melee/ft/ftdata.c:ftData_80085A14 / ftData_80085CD8
* FigaTree / FigaTrack    melee/lb/lbanim.h, melee/lb/lbanim.c:lbAnim_8001E6D8
* track -> joint mapping  melee/ft/ftanim.c:ftAnim_8006F4C8 + ftparts.c:ftParts_SetupParts
* FObj key decoding/eval  sysdolphin/baselib/fobj.c (ported 1:1 as a state machine)
* AObj stepping           sysdolphin/baselib/aobj.c:HSD_AObjReqAnim / HSD_AObjInterpretAnim
* Hermite                 sysdolphin/baselib/spline.c:splGetHelmite
* JObj values             sysdolphin/baselib/jobj.c:JObjUpdateFunc
* JObj matrix             sysdolphin/baselib/jobj.c:HSD_JObjMakeMatrix + mtx.c:HSD_MtxSRT
* Subaction script        melee/lb/lbcommand.c (opcodes 0-9) + melee/ft/ftaction.c (10+)

Run:  uv run python tools/melee_anim.py
"""

import json
import math
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hsd_archive  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
MELEE = ROOT / "melee"
OUT = ROOT / "out" / "melee"

FT_KIND_CAPTAIN = 2          # melee/ft/forward.h  FighterKind
FTCO_SM_COUNT = 295          # melee/ft/kinds/ftCommon/forward.h ftCo_SM_Count
FTCA_SM_SPECIALN = FTCO_SM_COUNT + 6      # ftCaptain/forward.h ftCa_SM_SpecialN
FTCA_SM_SPECIALAIRN = FTCO_SM_COUNT + 7   # ftCa_SM_SpecialAirN
CAPTAIN_ACTION_COUNT = 318   # ftdata.c ftData_Table_Unk0[Ft_Kind_Captain].count

# Common fighter part names, indexed by "common part" id (PlCo.dat parts table).
# NOTE: doldecomp's melee/ft/forward.h enum Fighter_Part is only correct for
# ids 0..15; from 16 on it is missing WaistN2 and mislabels LHaveN/RHaveN
# (e.g. decomp "FtPart_RThumbNb"(49) is the item-hold bone).  The order below
# is m-ex's MexTK/include/fighter.h enum FtCommonBoneNames, which matches the
# Captain skeleton geometry (JA joints carry the static -90deg offsets,
# wrists have the finger children, ThrowN sits at ground level, ...).
FTPART_NAMES = [
    "TopN", "TransN", "XRotN", "YRotN", "HipN", "WaistN",
    "LLegJA", "LLegJ", "LKneeJ", "LFootJA", "LFootJ",
    "RLegJA", "RLegJ", "RKneeJ", "RFootJA", "RFootJ",
    "WaistN2", "BustN", "LShoulderN", "LShoulderJA", "LShoulderJ", "LArmJ", "LHandN",
    "L1stNa", "L1stNb", "L2ndNa", "L2ndNb", "L3rdNa", "L3rdNb", "L4thNa", "L4thNb",
    "LHaveN", "LThumbNa", "LThumbNb", "NeckN", "HeadN",
    "RShoulderN", "RShoulderJA", "RShoulderJ", "RArmJ", "RHandN",
    "R1stNa", "R1stNb", "R2ndNa", "R2ndNb", "R3rdNa", "R3rdNb", "R4thNa", "R4thNb",
    "RHaveN", "RThumbNa", "RThumbNb", "ThrowN", "Extra",
]
# doldecomp enum Fighter_Part names for the same ids (for cross-referencing code)
DECOMP_FTPART_NAMES = [
    "TopN", "TransN", "XRotN", "YRotN", "HipN", "WaistN",
    "LLegJA", "LLegJ", "LKneeJ", "LFootJA", "LFootJ",
    "RLegJA", "RLegJ", "RKneeJ", "RFootJA", "RFootJ",
    "BustN", "LShoulderN", "LShoulderJA", "LShoulderJ", "LArmJ", "LHandN",
    "L1stNa", "L1stNb", "L2ndNa", "L2ndNb", "L3rdNa", "L3rdNb", "L4thNa", "L4thNb",
    "LThumbNa", "LThumbNb", "LHandNb", "NeckN", "HeadN",
    "RShoulderN", "RShoulderJA", "RShoulderJ", "RArmJ", "RHandN",
    "R1stNa", "R1stNb", "R2ndNa", "R2ndNb", "R3rdNa", "R3rdNb", "R4thNa", "R4thNb",
    "RThumbNa", "RThumbNb", "RHandNb", "ThrowN", "TransN2", "FtPart_53",
]
# Captain-specific joints that have no common part id (descriptive, inferred
# from position/hierarchy only - not official names)
CAPTAIN_EXTRA_NAMES = {
    5: "Ca_HipSideN (belt/holster piece, has mesh)",
    11: "Ca_LToeN", 17: "Ca_RToeN",
    20: "Ca_CollarN (above chest, no children)",
    34: "Ca_LHandAuxN (near left wrist)", 56: "Ca_RHandAuxN (near right wrist)",
    37: "Ca_LShoulderPadN", 60: "Ca_RShoulderPadN",
    40: "Ca_HeadFrontN_a", 41: "Ca_HeadFrontN_b",
    43: "Ca_RShoulderMeshN (has mesh)",
}

# jobj.h flags
JOBJ_CLASSICAL_SCALE = 1 << 3
JOBJ_INSTANCE = 1 << 12
JOBJ_USE_QUATERNION = 1 << 17

# fobj.h
OP_NONE, OP_CON, OP_LIN, OP_SPL0, OP_SPL, OP_SLP, OP_KEY = range(7)
FRAC_FLOAT, FRAC_S16, FRAC_U16, FRAC_S8, FRAC_U8 = (0 << 5, 1 << 5, 2 << 5, 3 << 5, 4 << 5)
# jobj.h HSD_A_J_*
A_J_ROTX, A_J_ROTY, A_J_ROTZ, A_J_PATH, A_J_TRAX, A_J_TRAY, A_J_TRAZ, A_J_SCAX, A_J_SCAY, A_J_SCAZ = range(1, 11)
TRACK_TYPE_NAMES = {1: "ROTX", 2: "ROTY", 3: "ROTZ", 4: "PATH", 5: "TRAX", 6: "TRAY", 7: "TRAZ",
                    8: "SCAX", 9: "SCAY", 10: "SCAZ", 11: "NODE", 12: "BRANCH"}
# aobj.h
AOBJ_FIRST_PLAY = 1 << 27
AOBJ_NO_UPDATE = 1 << 28
AOBJ_LOOP = 1 << 29
AOBJ_NO_ANIM = 1 << 30

f32 = np.float32  # the game computes in single precision


def F(x):
    return float(np.float32(x))


# ---------------------------------------------------------------------------
# Skeleton (PlCaNr.dat: PlyCaptain5K_Share_joint, struct HSD_Joint jobj.h)
# ---------------------------------------------------------------------------

def load_joints(arc, root_sym="PlyCaptain5K_Share_joint"):
    """Depth-first walk identical to ftParts_SetupParts / ftAnim_8006F4C8:
    visit node, then its child (unless JOBJ_INSTANCE), then next sibling."""
    joints = []

    def visit(off, parent):
        while off is not None:
            idx = len(joints)
            flags = arc.u32(off + 0x4)
            j = {
                "index": idx,
                "parent": parent,
                "offset": off,
                "flags": flags,
                "r": arc.vec3(off + 0x14),
                "s": arc.vec3(off + 0x20),
                "t": arc.vec3(off + 0x2C),
            }
            joints.append(j)
            child = arc.ptr(off + 0x8)
            if child is not None and not (flags & JOBJ_INSTANCE):
                visit(child, idx)
            off = arc.ptr(off + 0xC)

    visit(arc.publics[root_sym], None)
    return joints


def load_parts_table(plco, kind=FT_KIND_CAPTAIN):
    """PlCo.dat ftLoadCommonData +0x10: FighterPartsTable*[kind]
    {u8* joint_to_part; u8* part_to_joint; u32 parts_num} (ft/types.h)."""
    root = plco.publics["ftLoadCommonData"]
    tbl = plco.ptr(root + 0x10)
    pt = plco.ptr(tbl + 4 * kind)
    j2p_off = plco.ptr(pt + 0)
    p2j_off = plco.ptr(pt + 4)
    n = plco.u32(pt + 8)
    j2p = [plco.u8(j2p_off + i) for i in range(n)]
    # part_to_joint has one entry per Fighter_Part (common enum)
    p2j = [plco.u8(p2j_off + i) for i in range(len(FTPART_NAMES))]  # ids 0..53
    # +0x14: Fighter_804D6540_t*[kind] {x0*, count} -> parts skipped by ftParts_8007506C
    skip_tbl = plco.ptr(root + 0x14)
    skip = []
    sp = plco.ptr(skip_tbl + 4 * kind) if skip_tbl is not None else None
    if sp is not None:
        cnt = plco.s32(sp + 4)
        arr = plco.ptr(sp)
        for i in range(cnt):
            skip.append(plco.u8(arr + 4 * i))
    return {"parts_num": n, "joint_to_part": j2p, "part_to_joint": p2j, "skip_parts": skip}


def name_joints(joints, parts):
    for j in joints:
        i = j["index"]
        p = parts["joint_to_part"][i] if i < len(parts["joint_to_part"]) else 0xFF
        j["common_part"] = p if p != 0xFF else None
        j["decomp_enum_name"] = DECOMP_FTPART_NAMES[p] if p != 0xFF and p < len(DECOMP_FTPART_NAMES) else None
        if p != 0xFF and p < len(FTPART_NAMES):
            j["name"] = FTPART_NAMES[p]
            j["name_note"] = None
        else:
            desc = CAPTAIN_EXTRA_NAMES.get(i, f"Ca_Joint{i}")
            j["name"] = desc.split(" ")[0]
            j["name_note"] = desc


# ---------------------------------------------------------------------------
# ftData action table (PlCa.dat ftDataCaptain +0xC)
# ---------------------------------------------------------------------------

def load_actions(arc, count=CAPTAIN_ACTION_COUNT):
    root = arc.publics["ftDataCaptain"]
    tbl = arc.ptr(root + 0xC)
    acts = []
    for i in range(count):
        e = tbl + 0x18 * i
        nameptr = arc.ptr(e)
        acts.append({
            "index": i,
            "symbol": arc.cstr(nameptr) if nameptr is not None else None,
            "anim_offset": arc.u32(e + 4),
            "anim_size": arc.u32(e + 8),
            "script": arc.ptr(e + 0xC),
            "flags": arc.u32(e + 0x10),
        })
    return acts


# ---------------------------------------------------------------------------
# FigaTree (lbanim.h)
# ---------------------------------------------------------------------------

def load_figatree(aj_blob, action):
    sub = aj_blob[action["anim_offset"]: action["anim_offset"] + action["anim_size"]]
    arc = hsd_archive.HSDArchive(sub, action["symbol"])
    off = arc.publics[action["symbol"]]
    tree = {
        "type": arc.s32(off + 0),
        "flags": arc.u32(off + 4),
        "frames": arc.f32(off + 8),
    }
    nodes_off = arc.ptr(off + 0xC)
    tracks_off = arc.ptr(off + 0x10)
    nodes = []
    k = 0
    while True:
        v = arc.s8(nodes_off + k)
        if v == -1:
            break
        nodes.append(v)
        k += 1
    tracks = []
    for t in range(sum(nodes)):
        o = tracks_off + 0xC * t
        ad = arc.ptr(o + 8)
        length = arc.u16(o + 0)
        tracks.append({
            "length": length,
            "startframe": arc.u16(o + 2),   # FigaTrack.startframe is u16 -> fobj s16
            "obj_type": arc.u8(o + 4),
            "frac_value": arc.u8(o + 5),
            "frac_slope": arc.u8(o + 6),
            "ad": bytes(arc.data[ad: ad + length]) if ad is not None else b"",
        })
    tree["nodes"] = nodes
    tree["tracks"] = tracks
    return tree


# ---------------------------------------------------------------------------
# FObj: literal port of sysdolphin/baselib/fobj.c
# ---------------------------------------------------------------------------

def spl_get_helmite(fterm, time, p0, p1, d0, d1):
    """spline.c:splGetHelmite (fterm here is 1/T)."""
    fterm, time, p0, p1, d0, d1 = map(f32, (fterm, time, p0, p1, d0, d1))
    _1_T2 = time * time
    t2 = fterm * fterm
    t2_T = _1_T2 * fterm
    t3_T2 = t2 * (_1_T2 * time)
    _2t3_T3 = f32(2.0) * t3_T2 * fterm
    _3t2_T2 = f32(3.0) * _1_T2 * t2
    return f32((d1 * (t3_T2 - t2_T)) + ((d0 * (time + ((t3_T2 - t2_T) - t2_T))) +
               ((p0 * (f32(1.0) + (_2t3_T3 - _3t2_T2))) + (p1 * (-_2t3_T3 + _3t2_T2)))))


class FObj:
    def __init__(self, track):
        self.ad_head = track["ad"]
        self.length = track["length"]
        sf = track["startframe"]
        self.startframe = sf - 0x10000 if sf >= 0x8000 else sf  # stored into s16
        self.obj_type = track["obj_type"]
        self.frac_value = track["frac_value"]
        self.frac_slope = track["frac_slope"]
        self.flags = 0
        self.ad = 0
        self.time = f32(0)
        self.op = 0
        self.op_intrp = 0
        self.nb_pack = 0
        self.fterm = 0
        self.p0 = self.p1 = self.d0 = self.d1 = f32(0)

    # state helpers
    def get_state(self):
        return self.flags & 0xF

    def set_state(self, st):
        self.flags = (st & 0xF) | (self.flags & 0xF0)
        return st

    def req_anim(self, startframe):          # HSD_FObjReqAnim
        self.ad = 0
        self.time = f32(f32(self.startframe) + f32(startframe))
        self.op = 0
        self.op_intrp = 0
        self.flags &= ~0x40
        self.nb_pack = 0
        self.fterm = 0
        self.p0 = self.p1 = self.d0 = self.d1 = f32(0)
        self.set_state(1)

    # --- byte-stream parsing ---
    def _byte(self):
        b = self.ad_head[self.ad]
        self.ad += 1
        return b

    def parse_float(self, frac):            # fobj.c:parseFloat (little-endian!)
        if frac == FRAC_FLOAT:
            raw = bytes(self._byte() for _ in range(4))
            return f32(struct.unpack("<f", raw)[0])
        denom = f32(1 << (frac & 0x1F))
        kind = frac & 0xE0
        if kind == FRAC_S8:
            b = self._byte()
            numer = b - 256 if b >= 128 else b
        elif kind == FRAC_U8:
            numer = self._byte()
        elif kind == FRAC_S16:
            lo = self._byte(); hi = self._byte()
            hi = hi - 256 if hi >= 128 else hi
            numer = (hi << 8) | lo if hi >= 0 else (hi * 256 + lo)
        elif kind == FRAC_U16:
            lo = self._byte(); hi = self._byte()
            numer = (hi << 8) | lo
        else:
            return f32(0.0)
        return f32(f32(numer) / denom)

    def parse_opcode(self):
        return self.ad_head[self.ad] & 0xF

    def parse_pack_info(self):
        d = self._byte()
        nb_pack = ((d >> 4) & 7) + 1
        shift = 3
        if not (d & 0x80):
            return nb_pack
        while True:
            d = self._byte()
            nb_pack += (d & 0x7F) << shift
            shift += 7
            if not (d & 0x80):
                break
        return nb_pack

    def parse_wait(self):
        wait = 0
        shift = 0
        while True:
            d = self._byte()
            wait |= (d & 0x7F) << shift
            shift += 7
            if not (d & 0x80):
                break
        return wait

    def launch_key_data(self):             # FObjLaunchKeyData
        if self.flags & 0x40:
            self.op_intrp = self.op
            self.flags &= ~0x40
            self.flags |= 0x80
            self.p0 = self.p1

    def load_wait(self):                    # FObjLoadWait
        if self.ad >= self.length:
            return 6
        self.fterm = self.parse_wait()
        self.flags |= 0x20
        return self.set_state(2)

    def _ret(self, st):
        return self.set_state(3 if st == 1 else 4)

    def load_data(self):                    # FObjLoadData (+ FObjAnim*)
        if self.ad >= self.length:
            return 6
        self.op_intrp = self.op
        if self.nb_pack == 0:
            self.op = self.parse_opcode()
            self.nb_pack = self.parse_pack_info()
        self.nb_pack -= 1
        st = self.get_state()
        op = self.op
        if op in (OP_CON, OP_LIN):          # FObjAnimCON / FObjAnimLinear
            self.p0 = self.p1
            self.p1 = self.parse_float(self.frac_value)
            if self.op_intrp != OP_SLP:
                self.d0 = self.d1
                self.d1 = f32(0)
            return self._ret(st)
        if op == OP_SPL0:
            self.p0 = self.p1
            self.d0 = self.d1
            self.p1 = self.parse_float(self.frac_value)
            self.d1 = f32(0)
            return self._ret(st)
        if op == OP_SPL:
            self.p0 = self.p1
            self.p1 = self.parse_float(self.frac_value)
            self.d0 = self.d1
            self.d1 = self.parse_float(self.frac_slope)
            return self._ret(st)
        if op == OP_SLP:
            self.d0 = self.d1
            self.d1 = self.parse_float(self.frac_slope)
            return self.get_state()
        if op == OP_KEY:
            self.launch_key_data()
            self.p1 = self.parse_float(self.frac_value)
            self.flags |= 0x40
            return self._ret(st)
        return 0

    def update_anim(self, update):          # FObjUpdateAnim
        if update is None:
            return
        oi = self.op_intrp
        if oi == OP_KEY:
            if self.flags & 0x80:
                v = self.p0
                self.flags &= ~0x80
            else:
                return
        elif oi == OP_CON:
            v = self.p1 if self.time >= self.fterm else self.p0
        elif oi == OP_LIN:
            if self.flags & 0x20:
                self.flags &= ~0x20
                if self.fterm != 0:
                    self.d0 = f32((self.p1 - self.p0) / f32(self.fterm))
                else:
                    self.d0 = f32(0)
                    self.p0 = self.p1
            v = f32(self.d0 * self.time + self.p0)
        elif oi in (OP_SPL0, OP_SPL, OP_SLP):
            if self.fterm != 0:
                v = spl_get_helmite(f32(1.0 / self.fterm), self.time, self.p0, self.p1, self.d0, self.d1)
            else:
                v = self.p1
        else:
            # default: case falls through with an uninitialised value in C;
            # op_intrp NONE only happens before any key is loaded.
            return
        update(self.obj_type, float(v))

    def interpret(self, update, rate):      # HSD_FObjInterpretAnim
        fterm = f32(0)
        state = self.get_state()
        if state == 0:
            return
        self.time = f32(self.time + f32(rate))
        if self.time < 0.0:
            return
        while True:
            if state == 6:
                self.time = f32(self.time + fterm)
                self.launch_key_data()
                self.update_anim(update)
                return
            if state in (1, 2):
                state = self.load_data()
            elif state == 3:
                if self.flags & 0x80:
                    self.update_anim(update)
                state = self.load_wait()
            elif state == 4:
                if self.fterm <= self.time:
                    state = 3
                    fterm = f32(self.fterm)
                    self.time = f32(self.time - f32(self.fterm))
                    self.set_state(state)
                    continue
                self.update_anim(update)
                self.set_state(5)
                return
            elif state == 5:
                state = 4
                self.set_state(state)
            else:  # 0 / unknown
                return

    def stop(self, update, rate):           # HSD_FObjStopAnim
        if self.op_intrp == OP_KEY:
            self.interpret(update, rate)
        self.set_state(0)


class AObj:
    """aobj.c subset used by fighters (lbAnim_8001E6D8 sets flags, rewind 0, end)."""

    def __init__(self, fobjs, tree_flags, end_frame):
        self.fobjs = fobjs
        self.flags = AOBJ_NO_ANIM                      # HSD_AObjAlloc
        self.flags |= tree_flags & (AOBJ_LOOP | AOBJ_NO_UPDATE)  # HSD_AObjSetFlags
        self.framerate = f32(1.0)
        self.rewind_frame = f32(0.0)
        self.end_frame = f32(end_frame)
        self.curr_frame = f32(0)

    def req_anim(self, frame):
        self.curr_frame = f32(frame)
        self.flags = (self.flags & ~AOBJ_NO_ANIM) | AOBJ_FIRST_PLAY
        for fo in self.fobjs:
            fo.req_anim(frame)

    def stop_anim(self, update):
        for fo in self.fobjs:
            fo.stop(update, self.framerate)
        self.flags |= AOBJ_NO_ANIM

    def interpret(self, update):
        if self.flags & AOBJ_NO_ANIM:
            return
        if self.flags & AOBJ_FIRST_PLAY:
            self.flags &= 0xF7FFFFFF
            rate = f32(0)
        else:
            rate = self.framerate
            self.curr_frame = f32(self.curr_frame + self.framerate)
        if (self.flags & AOBJ_LOOP) and self.end_frame <= self.curr_frame:
            if self.rewind_frame < self.end_frame:
                for fo in self.fobjs:
                    fo.stop(update, rate)
                y = self.end_frame - self.rewind_frame
                x = self.curr_frame - self.rewind_frame
                self.curr_frame = f32(math.fmod(x, y) + self.rewind_frame)
                for fo in self.fobjs:
                    fo.req_anim(self.curr_frame)
            else:
                self.curr_frame = self.end_frame
            rate = f32(0)
        upd = None if (self.flags & AOBJ_NO_UPDATE) else update
        for fo in self.fobjs:
            fo.interpret(upd, rate)
        if not (self.flags & AOBJ_LOOP) and self.end_frame <= self.curr_frame:
            self.stop_anim(update)


def make_update(trs):
    """jobj.c:JObjUpdateFunc for TRS channels."""
    def upd(t, v):
        if t == A_J_ROTX: trs["r"][0] = v
        elif t == A_J_ROTY: trs["r"][1] = v
        elif t == A_J_ROTZ: trs["r"][2] = v
        elif t == A_J_TRAX: trs["t"][0] = v
        elif t == A_J_TRAY: trs["t"][1] = v
        elif t == A_J_TRAZ: trs["t"][2] = v
        elif t in (A_J_SCAX, A_J_SCAY, A_J_SCAZ):
            if abs(v) < 1e-3:
                v = F(1e-3)
            trs["s"][t - A_J_SCAX] = v
        # PATH / NODE / BRANCH / SETBYTE... are not TRS; ignored (none expected)
    return upd


def map_tracks_to_joints(joints, tree, parts):
    """ftAnim_8006F4C8: nodes[] is consumed one entry per fighter part i
    (= joint DFS index), skipping parts listed by ftParts_8007506C (none for
    Captain) and parts without a joint (flags_b1==0)."""
    out = {}
    skip = set(parts["skip_parts"])
    i = 0
    ti = 0
    for n in tree["nodes"]:
        while i in skip:
            i += 1
        if i >= len(joints):
            raise ValueError("atree data error: more nodes than joints")
        out[i] = list(range(ti, ti + n))
        ti += n
        i += 1
    return out


def evaluate(joints, tree, parts, nsamples=None):
    """Play the figatree exactly like a fighter state entered with
    anim_start=0, rate=1 (HSD_AObjReqAnim(0) then one InterpretAnim per tick).
    Sample k = pose after the k-th interpret call = animation frame k."""
    jmap = map_tracks_to_joints(joints, tree, parts)
    state = []
    aobjs = []
    for j in joints:
        trs = {"t": [F(x) for x in j["t"]], "r": [F(x) for x in j["r"]], "s": [F(x) for x in j["s"]]}
        state.append(trs)
        tids = jmap.get(j["index"], [])
        if tids:
            fobjs = [FObj(tree["tracks"][t]) for t in tids]
            # lbAnim_JObjSortAnim moves a TYPE_JOBJ(12) fobj to the front
            for k, fo in enumerate(fobjs):
                if fo.obj_type == 12:
                    fobjs.insert(0, fobjs.pop(k))
                    break
            a = AObj(fobjs, tree["flags"], tree["frames"])
            a.req_anim(0.0)
            aobjs.append((a, make_update(trs)))
    end = tree["frames"]
    if nsamples is None:
        nsamples = int(math.floor(end)) + 1
    frames = []
    for _ in range(nsamples):
        for a, upd in aobjs:
            a.interpret(upd)
        frames.append([{"t": list(s["t"]), "r": list(s["r"]), "s": list(s["s"])} for s in state])
    return frames, jmap


# ---------------------------------------------------------------------------
# Matrices: jobj.c:HSD_JObjMakeMatrix + mtx.c:HSD_MtxSRT
# ---------------------------------------------------------------------------

def mtx_srt(s, r, t, pscl=None):
    sx, cx = math.sin(r[0]), math.cos(r[0])
    sy, cy = math.sin(r[1]), math.cos(r[1])
    sz, cz = math.sin(r[2]), math.cos(r[2])
    vx2 = vx1 = vx = s[0]
    vy2 = vy1 = vy = s[1]
    vz2 = vz1 = vz = s[2]
    if pscl is not None:
        t1, t2, t3 = 1.0 / pscl[0], 1.0 / pscl[1], 1.0 / pscl[2]
        vy2 *= pscl[1] * t1; vz2 *= pscl[2] * t1
        vx1 *= pscl[0] * t2; vz1 *= pscl[2] * t2
        vx *= pscl[0] * t3; vy *= pscl[1] * t3
    m = np.eye(4)
    m[0, 0] = cz * (vx2 * cy)
    m[1, 0] = sz * (vx1 * cy)
    m[2, 0] = -vx * sy
    m[0, 1] = vy2 * ((cz * (sx * sy)) - (cx * sz))
    m[1, 1] = vy1 * ((sz * (sx * sy)) + (cx * cz))
    m[2, 1] = cy * (vy * sx)
    m[0, 2] = vz2 * ((cz * (cx * sy)) + (sx * sz))
    m[1, 2] = vz1 * ((sz * (cx * sy)) - (sx * cz))
    m[2, 2] = cy * (vz * cx)
    m[0, 3], m[1, 3], m[2, 3] = t
    return m


def world_matrices(joints, pose, classical_scale=None):
    """pose: list of {t,r,s}; returns list of 4x4 world matrices.
    classical_scale: None -> use each joint's own JOBJ_CLASSICAL_SCALE flag;
    otherwise a dict joint_index -> bool overriding it (lbAnim_8001E6D8 sets
    or clears the flag on every animated joint from FigaTree.type & 1)."""
    mats = [None] * len(joints)
    scl = [None] * len(joints)
    for j in joints:  # DFS order => parents first
        i, p = j["index"], j["parent"]
        trs = pose[i]
        classical = bool(j["flags"] & JOBJ_CLASSICAL_SCALE)
        if classical_scale is not None and i in classical_scale:
            classical = classical_scale[i]
        if classical:
            scl[i] = scl[p] if (p is not None and scl[p] is not None) else None
        else:
            if p is not None and scl[p] is not None:
                scl[i] = [trs["s"][k] * scl[p][k] for k in range(3)]
            else:
                scl[i] = list(trs["s"])
        pscl = scl[p] if (p is not None and scl[p] is not None) else None
        m = mtx_srt(trs["s"], trs["r"], trs["t"], pscl)
        mats[i] = mats[p] @ m if p is not None else m
    return mats


# ---------------------------------------------------------------------------
# Subaction script (lbcommand.c + ftaction.c)
# ---------------------------------------------------------------------------

# ftaction.c:ftAction_803C0870 (command length in words for opcode-10)
FT_CMD_LEN = [5, 5, 1, 1, 1, 1, 1, 3, 1, 1, 1, 1, 1, 1, 1, 1, 1,
              1, 1, 1, 1, 1, 1, 1, 3, 1, 1, 1, 7, 4, 1, 1, 1, 1,
              1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 3, 3, 2, 1, 4]
FT_CMD_NAMES = {  # opcode -> (handler, description) from ftaction.c:ftAction_803C06E8
    10: ("ftAction_80071028", "spawn GFX"),
    11: ("ftAction_8007121C", "create hitbox"),
    12: ("ftAction_8007162C", "adjust hitbox damage"),
    13: ("ftAction_8007169C", "adjust hitbox size"),
    14: ("ftAction_80071708", "set hitbox flags"),
    15: ("ftAction_80071784", "remove hitbox (ftColl_8007AFC8)"),
    16: ("ftAction_800717D8", "clear all hitboxes (ftColl_8007AFF8)"),
    17: ("ftAction_80071B50", "sound effect"),
    18: ("ftAction_80071CCC", "random smash SFX"),
    19: ("ftAction_80071820", "set cmd_var"),
    20: ("ftAction_800718A4", "set throw_flags b3/b4"),
    21: ("ftAction_80071908", "set throw_flags_b1 (fighter-specific trigger)"),
    22: ("ftAction_8007192C", "set throw_flags_b2"),
    23: ("ftAction_80071950", "allow interrupt (IASA)"),
    24: ("ftAction_80071974", "set throw_flags_b0"),
    25: ("ftAction_80071998", "set jump/airborne state"),
    26: ("ftAction_80071A14", "set body collision state"),
    27: ("ftAction_80071A58", "body collision (ftColl_8007B0C0)"),
    28: ("ftAction_80071A9C", "set hurtbox state"),
    29: ("ftAction_80071AE8", "jab combo"),
    30: ("ftAction_80071B28", "rapid jab"),
    31: ("ftAction_80071D40", "set model (dobj) visibility"),
    32: ("ftAction_80071D94", "dobj (ftParts_80074A8C)"),
    33: ("ftAction_80071DCC", "dobj (ftParts_80074ACC)"),
    34: ("ftAction_80071E04", "throw hitbox"),
    35: ("ftAction_80071F34", "ftCommon_8007F5CC"),
    36: ("ftAction_80071F78", "article visibility"),
    37: ("ftAction_80071FA0", "fighter visibility"),
    38: ("ftAction_80071FC8", "pseudo-random SFX"),
    39: ("ftAction_80072320", "positional SFX"),
    40: ("ftAction_800726F4", "texture anim"),
    41: ("ftAction_800727C8", "part anim"),
    42: ("ftAction_80072894", "rumble (ftCommon_8007E83C)"),
    43: ("ftAction_800728F8", "rumble (ftCommon_8007EBAC)"),
    44: ("ftAction_8007297C", "ftCommon_8007ECD4"),
    45: ("ftAction_800729D4", "ftCommon_8007EEC8/EF5C"),
    46: ("ftAction_80072A5C", "color anim (ftCo_800BFFD0)"),
    47: ("ftAction_80072ABC", "ftCo_800C0200"),
    48: ("ftAction_80072B14", "x221E_b1"),
    49: ("ftAction_80072B3C", "x2100"),
    50: ("ftAction_80072B94", "ftCo_8009E318 (animated GFX)"),
    51: ("ftAction_80072BF4", "self damage"),
    52: ("ftAction_80072C6C", "ft_8008A1B8"),
    53: ("ftAction_80072CB0", "x2225_b2"),
    54: ("ftAction_80072CD8", "footstep SFX/GFX"),
    55: ("ftAction_80072E4C", "landing SFX/GFX"),
    56: ("ftAction_80073008", "smash charge"),
    57: ("ftAction_800730B8", "ftCo_800C8B60"),
    58: ("ftAction_80073118", "wind effect"),
}
LB_CMD_NAMES = {0: "end", 1: "sync timer", 2: "async timer", 3: "set loop", 4: "exec loop",
                5: "subroutine", 6: "return", 7: "goto", 8: "set timer (wait anim end)", 9: "bg flash"}
ELEMENTS = ["normal", "fire", "electric", "slash", "coin", "ice", "nap", "sleep", "?8", "catch?",
            "ground?", "cape", "?", "inert", "disable", "dark", "scball", "lipstick", "leadead"]


def bits(w, start, n, signed=False):
    """Big-endian (MSB-first) bitfield, as laid out by the PowerPC compiler."""
    v = (w >> (32 - start - n)) & ((1 << n) - 1)
    if signed and v & (1 << (n - 1)):
        v -= 1 << n
    return v


def decode_command(arc, off, parts, joints):
    w = arc.u32(off)
    op = w >> 26
    d = {"opcode": op, "offset": off}
    if op < 10:
        d["name"] = LB_CMD_NAMES[op]
        d["value"] = bits(w, 6, 26)
        d["words"] = 2 if op in (5, 7) else 1
        if op in (5, 7):
            d["target"] = arc.ptr(off + 4)
        return d
    ln = FT_CMD_LEN[op - 10] if op - 10 < len(FT_CMD_LEN) else 1
    d["words"] = ln
    d["handler"], d["name"] = FT_CMD_NAMES.get(op, ("?", "?"))
    ws = [arc.u32(off + 4 * k) for k in range(ln)]
    d["raw"] = " ".join(f"{x:08X}" for x in ws)

    def bone_name(b, common):
        if common:
            j = parts["part_to_joint"][b] if b < len(parts["part_to_joint"]) else None
            return f"common part {b} ({FTPART_NAMES[b] if b < len(FTPART_NAMES) else '?'}) -> joint {j}"
        return f"joint {b} ({joints[b]['name'] if b < len(joints) else '?'})"

    if op == 10:
        d.update({
            "bone": bits(ws[0], 6, 8), "use_common_bone_ids": bits(ws[0], 14, 1),
            "destroy_on_state_change": bits(ws[0], 15, 1), "use_unk_bone": bits(ws[0], 16, 1),
            "gfx_id": bits(ws[1], 0, 16), "unk_float_raw": bits(ws[1], 16, 16),
            # ftAction_80071028: offset.x=word2.hi/256, offset.y=word2.lo/256, offset.z=word3.hi/256
            "gfx_offset": [bits(ws[2], 0, 16, True) / 256, bits(ws[2], 16, 16, True) / 256, bits(ws[3], 0, 16, True) / 256],
            "gfx_range": [bits(ws[3], 16, 16) / 256, bits(ws[4], 0, 16) / 256, bits(ws[4], 16, 16) / 256],
        })
        d["bone_desc"] = bone_name(d["bone"], d["use_common_bone_ids"])
    elif op == 11:
        d.update({
            "id": bits(ws[0], 6, 3), "hit_group": bits(ws[0], 9, 3),
            "only_hit_grabbed": bits(ws[0], 12, 1), "bone": bits(ws[0], 13, 8),
            "use_common_bone_ids": bits(ws[0], 21, 1), "damage": bits(ws[0], 22, 10),
            "size": bits(ws[1], 0, 16) / 256,
            # ftAction_8007121C: b_offset.x = word1.lo, .y = word2.hi, .z = word2.lo (all /256)
            "b_offset": [bits(ws[1], 16, 16, True) / 256, bits(ws[2], 0, 16, True) / 256, bits(ws[2], 16, 16, True) / 256],
            "angle": bits(ws[3], 0, 9), "kb_growth": bits(ws[3], 9, 9),
            "weight_set_kb": bits(ws[3], 18, 9), "item_hit_interaction": bits(ws[3], 27, 1),
            "ignore_thrown_fighters": bits(ws[3], 28, 1), "ignore_fighter_scale": bits(ws[3], 29, 1),
            "clank": bits(ws[3], 30, 1), "rebound": bits(ws[3], 31, 1),
            "base_kb": bits(ws[4], 0, 9), "element": bits(ws[4], 9, 5),
            "shield_damage": bits(ws[4], 14, 8, True), "hit_sfx_severity": bits(ws[4], 22, 3),
            "hit_sfx_kind": bits(ws[4], 25, 5), "bit30": bits(ws[4], 30, 1), "bit31": bits(ws[4], 31, 1),
        })
        d["element_name"] = ELEMENTS[d["element"]] if d["element"] < len(ELEMENTS) else "?"
        d["bone_desc"] = bone_name(d["bone"], d["use_common_bone_ids"])
    elif op == 12:
        d.update({"id": bits(ws[0], 6, 3), "damage": bits(ws[0], 9, 23)})
    elif op == 13:
        d.update({"id": bits(ws[0], 6, 3), "size": bits(ws[0], 9, 23) / 256})
    elif op == 15:
        d.update({"hit_idx": bits(ws[0], 6, 26)})
    elif op == 17:
        d.update({"behavior": bits(ws[0], 6, 8), "sfx_id": ws[1],
                  "volume": bits(ws[2], 16, 8), "panning": bits(ws[2], 24, 8)})
    elif op == 19:
        d.update({"var": bits(ws[0], 6, 2), "value": bits(ws[0], 8, 24)})
    elif op == 20:
        d.update({"value": bits(ws[0], 6, 26)})
    elif op == 25 or op == 26 or op == 27:
        d.update({"state": bits(ws[0], 6, 26)})
    elif op == 28:
        d.update({"bone": bits(ws[0], 6, 8), "state": bits(ws[0], 14, 18)})
    elif op == 31:
        d.update({"idx": bits(ws[0], 6, 7, True), "value": bits(ws[0], 13, 19, True)})
    elif op == 38:
        d.update({"volume": bits(ws[0], 6, 8), "panning": bits(ws[0], 14, 8),
                  "behavior": bits(ws[0], 22, 4), "random_range": bits(ws[0], 26, 6),
                  "sfx_ids": ws[1:7]})
    elif op == 39:
        d.update({"x": bits(ws[0], 6, 10), "y": bits(ws[0], 16, 8), "pitch_select": bits(ws[0], 24, 8),
                  "sfx_id": ws[1]})
    elif op in (42, 43):
        d.update({"a": bits(ws[0], 6, 13), "b": bits(ws[0], 19, 13)})
    elif op == 46:
        d.update({"a": bits(ws[0], 6, 8), "b": bits(ws[0], 14, 18)})
    elif op == 50:
        d.update({"value": bits(ws[0], 6, 26, True)})
    return d


def run_script(arc, start, parts, joints, max_frame=400, enter_runs_twice=True):
    """Simulate ftAction_80073240 (timer logic) + Command_00..09 to find on
    which animation frame each command executes.  Frame f = the script run
    with cur_anim_frame == f.  ChangeMotionState runs the script at frame 0;
    ftCa_SpecialN_Enter/ftCa_SpecialAirN_Enter then call ftAnim_8006EBA4,
    which advances the anim to frame 1 and runs the script again in the same
    game tick.  So game frame g (1-based, first frame of the action = 1)
    displays anim frame g; events of anim frames 0 and 1 both occur on game
    frame 1."""
    F32_MAX = 3.4028234663852886e38
    pc = start
    timer = 0.0
    stack = []
    events = []
    for frame in range(max_frame):
        frame_count = float(frame)
        if pc is None:
            break
        if timer != F32_MAX:
            timer -= 1.0
        while pc is not None:
            if timer == F32_MAX:
                if frame_count >= 1.0:
                    break
                timer = -frame_count
            elif timer > 0.0:
                break
            cmd = decode_command(arc, pc, parts, joints)
            op = cmd["opcode"]
            cmd["anim_frame"] = frame
            cmd["game_frame"] = max(frame, 1)
            if op not in (1, 2):
                events.append(cmd)
            if op == 0:
                pc = None
            elif op == 1:
                timer += cmd["value"]; pc += 4
            elif op == 2:
                timer = cmd["value"] - frame_count; pc += 4
            elif op == 3:
                stack.append([pc + 4, cmd["value"]]); pc += 4
            elif op == 4:
                stack[-1][1] -= 1
                if stack[-1][1]:
                    pc = stack[-1][0]
                else:
                    stack.pop(); pc += 4
            elif op == 5:
                stack.append([pc + 8, None]); pc = cmd["target"]
            elif op == 6:
                pc = stack.pop()[0]
            elif op == 7:
                pc = cmd["target"]
            elif op == 8:
                pc += 4; timer = F32_MAX
            else:
                pc += 4 * cmd["words"]
    return events


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

def r6(x):
    return round(float(x), 6)


def export_json(path, joints, tree, frames, action, jmap, world_rest):
    doc = {
        "source": {
            "game": "Super Smash Bros. Melee NTSC-U 1.02 (GALE01)",
            "fighter_data": "PlCa.dat ftDataCaptain",
            "action_index": action["index"],
            "symbol": action["symbol"],
            "anim_file": "PlCaAJ.dat",
            "anim_offset": action["anim_offset"],
            "anim_size": action["anim_size"],
            "action_flags": f"{action['flags']:#010x}",
            "figatree_type": tree["type"],
            "figatree_flags": f"{tree['flags']:#x}",
            "anim_end_frame": tree["frames"],
            "skeleton": "PlCaNr.dat PlyCaptain5K_Share_joint",
        },
        "fps": 60,
        "frame_count": len(frames),
        "units": "Melee units (1 unit ~ 1 'meter' in-game; Falcon is ~17 units tall)",
        "rotation": "Euler XYZ radians, R = Rz*Ry*Rx (X applied first), local M = T*R*S",
        "notes": "frames[k] = local TRS after HSD_AObjInterpretAnim call k (anim frame k); "
                 "game frame g of the move displays anim frame g (frame 0 is replaced within the entering tick).",
        "joints": [],
        "frames": [],
    }
    for j in joints:
        doc["joints"].append({
            "index": j["index"], "name": j["name"], "parent": j["parent"],
            "common_part": j["common_part"],
            "decomp_enum_name": j["decomp_enum_name"],
            "name_note": j["name_note"],
            "jobj_flags": f"{j['flags']:#x}",
            "animated_tracks": [TRACK_TYPE_NAMES.get(tree["tracks"][t]["obj_type"], tree["tracks"][t]["obj_type"])
                                for t in jmap.get(j["index"], [])],
            "rest": {"t": [r6(x) for x in j["t"]], "r": [r6(x) for x in j["r"]], "s": [r6(x) for x in j["s"]]},
            "rest_world_pos": [r6(x) for x in world_rest[j["index"]][:3, 3]],
        })
    for fr in frames:
        doc["frames"].append([{"t": [r6(x) for x in p["t"]], "r": [r6(x) for x in p["r"]],
                               "s": [r6(x) for x in p["s"]]} for p in fr])
    path.write_text(json.dumps(doc, indent=1))


def euler_xyz_to_quat(r):
    """quaternion (x,y,z,w) of R = Rz*Ry*Rx."""
    hx, hy, hz = r[0] / 2, r[1] / 2, r[2] / 2
    cx, sx = math.cos(hx), math.sin(hx)
    cy, sy = math.cos(hy), math.sin(hy)
    cz, sz = math.cos(hz), math.sin(hz)
    # q = qz * qy * qx
    w = cz * cy * cx + sz * sy * sx
    x = cz * cy * sx - sz * sy * cx
    y = cz * sy * cx + sz * cy * sx
    z = sz * cy * cx - cz * sy * sx
    return [x, y, z, w]


def export_glb(path, joints, frames, name, scale_to_m=1.0):
    """Skeleton-only glTF: one node per joint (local TRS), animation channels
    for every joint (translation/rotation/scale sampled per frame, LINEAR)."""
    n = len(joints)
    nf = len(frames)
    buf = bytearray()
    accessors, views = [], []

    def add(arr, typ, comp=5126, minmax=False):
        a = np.asarray(arr, dtype=np.float32)
        while len(buf) % 4:
            buf.append(0)
        off = len(buf)
        buf.extend(a.tobytes())
        views.append({"buffer": 0, "byteOffset": off, "byteLength": a.nbytes})
        acc = {"bufferView": len(views) - 1, "componentType": comp, "count": int(a.shape[0]), "type": typ}
        if minmax:
            acc["min"] = [float(a.min())]
            acc["max"] = [float(a.max())]
        accessors.append(acc)
        return len(accessors) - 1

    nodes = []
    for j in joints:
        nodes.append({"name": j["name"],
                      "translation": [x * scale_to_m for x in j["t"]],
                      "rotation": euler_xyz_to_quat(j["r"]),
                      "scale": list(j["s"])})
    for j in joints:
        if j["parent"] is not None:
            nodes[j["parent"]].setdefault("children", []).append(j["index"])
    tin = add(np.arange(nf, dtype=np.float32) / 60.0, "SCALAR", minmax=True)
    samplers, channels = [], []
    for j in joints:
        i = j["index"]
        T = [[x * scale_to_m for x in frames[k][i]["t"]] for k in range(nf)]
        Q = [euler_xyz_to_quat(frames[k][i]["r"]) for k in range(nf)]
        # keep quaternion hemisphere continuous
        for k in range(1, nf):
            if np.dot(Q[k], Q[k - 1]) < 0:
                Q[k] = [-c for c in Q[k]]
        S = [frames[k][i]["s"] for k in range(nf)]
        for path_name, data, typ in (("translation", T, "VEC3"), ("rotation", Q, "VEC4"), ("scale", S, "VEC3")):
            out = add(data, typ)
            samplers.append({"input": tin, "output": out, "interpolation": "LINEAR"})
            channels.append({"sampler": len(samplers) - 1, "target": {"node": i, "path": path_name}})
    # dummy skin so Blender imports the nodes as an armature
    ibm = []
    rest_pose = [{"t": j["t"], "r": j["r"], "s": j["s"]} for j in joints]
    for m in world_matrices(joints, rest_pose):
        m = m.copy()
        m[:3, 3] *= scale_to_m
        ibm.append(np.linalg.inv(m).T.reshape(-1))  # column-major
    ibm_acc = add(np.array(ibm), "MAT4")
    gltf = {
        "asset": {"version": "2.0", "generator": "falconpunch melee_anim.py"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": nodes,
        "skins": [{"joints": list(range(n)), "skeleton": 0, "inverseBindMatrices": ibm_acc, "name": "Captain"}],
        "animations": [{"name": name, "samplers": samplers, "channels": channels}],
        "accessors": accessors,
        "bufferViews": views,
        "buffers": [{"byteLength": len(buf)}],
    }
    js = json.dumps(gltf).encode()
    while len(js) % 4:
        js += b" "
    while len(buf) % 4:
        buf.append(0)
    out = bytearray()
    out += struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(buf))
    out += struct.pack("<II", len(js), 0x4E4F534A) + js
    out += struct.pack("<II", len(buf), 0x004E4942) + bytes(buf)
    path.write_bytes(out)


def render_previews(joints, frames, tag, picks, classical, views=("side", "front")):
    """Stick figure from world-space FK (HSD_JObjMakeMatrix/HSD_MtxSRT).
    Model space: +Y up, character faces +Z, character's right hand is -X.
    Each panel is centred on HipN's horizontal position (the ground move's
    TransN root motion translates the whole body ~12.7 units forward)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    axes_def = {"side": (2, 1, "side: Z (forward) ->, Y up"), "front": (0, 1, "front: X ->, Y up"),
                "top": (0, 2, "top: X ->, Z up")}
    hip = [j["index"] for j in joints if j["name"] == "HipN"][0]
    ncol = len(picks)
    fig = plt.figure(figsize=(3.2 * ncol, 4.2 * len(views)))
    for col, k in enumerate(picks):
        mats = world_matrices(joints, frames[k], classical)
        P = np.array([m[:3, 3] for m in mats])
        for row, v in enumerate(views):
            ax_i, ax_j, title = axes_def[v]
            ax = fig.add_subplot(len(views), ncol, row * ncol + col + 1)
            for j in joints:
                if j["parent"] is None or j["name"] in ("ThrowN", "Extra", "TransN", "XRotN", "YRotN"):
                    continue
                a_, b_ = P[j["parent"]], P[j["index"]]
                nm = j["name"]
                c = "tab:red" if nm.startswith("R") or nm.startswith("Ca_R") else (
                    "tab:blue" if nm.startswith("L") or nm.startswith("Ca_L") else "k")
                ax.plot([a_[ax_i], b_[ax_i]], [a_[ax_j], b_[ax_j]], "-", color=c, lw=1.5)
            for nm, mk in (("RHandN", "r*"), ("LHandN", "b*"), ("HeadN", "ko")):
                idx = [j["index"] for j in joints if j["name"] == nm][0]
                ax.plot(P[idx, ax_i], P[idx, ax_j], mk, ms=9)
            cx = P[hip, ax_i] if ax_i != 1 else 0
            ax.set_xlim(cx - 13, cx + 13)
            ax.set_ylim(-2, 24)
            ax.set_aspect("equal")
            ax.grid(alpha=.3)
            ax.set_title(f"{tag} f{k}\n{title}", fontsize=8)
    fig.suptitle("red = character's right side, blue = left; * = HandN (wrist), o = HeadN", fontsize=9)
    fig.tight_layout()
    p = OUT / f"preview_{tag}.png"
    fig.savefig(p, dpi=70)
    plt.close(fig)
    return p


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    plca = hsd_archive.load(MELEE / "PlCa.dat")
    plnr = hsd_archive.load(MELEE / "PlCaNr.dat")
    plco = hsd_archive.load(MELEE / "PlCo.dat")
    aj = (MELEE / "PlCaAJ.dat").read_bytes()

    joints = load_joints(plnr)
    parts = load_parts_table(plco)
    name_joints(joints, parts)
    assert parts["parts_num"] == len(joints), (parts["parts_num"], len(joints))
    acts = load_actions(plca)

    rest_pose = [{"t": j["t"], "r": j["r"], "s": j["s"]} for j in joints]
    world_rest = world_matrices(joints, rest_pose)

    summary = {"joints": len(joints), "parts_table": parts, "actions": {}}
    for tag, idx in (("ground", FTCA_SM_SPECIALN), ("air", FTCA_SM_SPECIALAIRN)):
        act = acts[idx]
        tree = load_figatree(aj, act)
        assert len(tree["nodes"]) == len(joints), (len(tree["nodes"]), len(joints))
        frames, jmap = evaluate(joints, tree, parts)
        export_json(OUT / f"falcon_punch_{tag}.json", joints, tree, frames, act, jmap, world_rest)
        export_glb(OUT / f"falcon_punch_{tag}.glb", joints, frames, f"Captain_{act['symbol']}")
        nf = len(frames)
        picks = sorted(set([0, 20, 40, min(nf - 1, 52), min(nf - 1, 56), nf - 1]))
        cls = {i: bool(tree["type"] & 1) for i, ts in jmap.items() if ts}
        render_previews(joints, frames, tag, picks, cls)
        render_previews(joints, frames, tag + "_strip", list(range(0, nf, 10)), cls, views=("side",))
        ev = run_script(plca, act["script"], parts, joints)
        summary["actions"][tag] = {
            "index": idx, "symbol": act["symbol"], "anim_offset": act["anim_offset"],
            "anim_size": act["anim_size"], "flags": f"{act['flags']:#010x}",
            "tree_type": tree["type"], "tree_flags": tree["flags"], "frames": tree["frames"],
            "samples": nf,
            "track_types": {joints[i]["name"]: [TRACK_TYPE_NAMES.get(tree["tracks"][t]["obj_type"]) for t in ts]
                            for i, ts in jmap.items() if ts},
            "events": [{k: v for k, v in e.items() if k != "offset"} for e in ev],
        }
    (OUT / "falcon_punch_extract_summary.json").write_text(json.dumps(summary, indent=1, default=str))
    # bone map
    bm = ["index\tname\tparent\tcommon_part\tdecomp_enum_name\trest_world_pos\tnote"]
    for j in joints:
        wp = world_rest[j["index"]][:3, 3]
        bm.append(f"{j['index']}\t{j['name']}\t{j['parent']}\t{j['common_part']}\t{j['decomp_enum_name']}\t"
                  f"{wp[0]:.3f},{wp[1]:.3f},{wp[2]:.3f}\t{j['name_note'] or ''}")
    (OUT / "bone_map.tsv").write_text("\n".join(bm) + "\n")
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk not in ("events", "track_types")}
                      for k, v in summary["actions"].items()}, indent=1))


if __name__ == "__main__":
    main()
