"""Dump skeletons / skeletal animations from BFRES v10 files.

  uv run python tools/bfres_dump.py skeleton unpacked/Player_Adult.Player_Adult.bfres out/bfres/link_adult_skeleton.json
  uv run python tools/bfres_dump.py list out/bfres/player_adult_anims.txt unpacked/Player_Adult*.anim.bfres
  uv run python tools/bfres_dump.py sample unpacked/Player_Adult_01_Animation.anim.bfres Hammer_Attack_Vertical out.json
  uv run python tools/bfres_dump.py info unpacked/xxx.bfres
"""
import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import bfres  # noqa: E402


def euler_xyz_to_matrix(rx, ry, rz):
    """nn::g3d Euler XYZ: R = Rz * Ry * Rx (column vectors; X applied first)."""
    cx, sx = math.cos(rx), math.sin(rx)
    cy, sy = math.cos(ry), math.sin(ry)
    cz, sz = math.cos(rz), math.sin(rz)
    return [
        [cy * cz, sx * sy * cz - cx * sz, cx * sy * cz + sx * sz],
        [cy * sz, sx * sy * sz + cx * cz, cx * sy * sz - sx * cz],
        [-sy, sx * cy, cx * cy],
    ]


def quat_to_matrix(x, y, z, w):
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]


def matmul3(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def local_matrix(s, r, t, euler=True):
    R = euler_xyz_to_matrix(*r[:3]) if euler else quat_to_matrix(*r)
    RS = [[R[i][j] * s[j] for j in range(3)] for i in range(3)]
    return RS, list(t)


def fk(bones, locals_):
    """bones: list of (name,parent); locals_: list of (M3, t). Returns world (M3, t) list."""
    world = []
    for i, (name, parent) in enumerate(bones):
        M, t = locals_[i]
        if parent < 0:
            world.append((M, t))
        else:
            PM, pt = world[parent]
            wm = matmul3(PM, M)
            wt = [pt[k] + sum(PM[k][j] * t[j] for j in range(3)) for k in range(3)]
            world.append((wm, wt))
    return world


def rnd(v, n=6):
    return [round(float(x), n) for x in v]


def load_skeleton(path):
    bf = bfres.load(path)
    m = bf.q(0x28)
    return bf, bf.read_skeleton(bf.model_skeleton_offset(m))


def cmd_skeleton(src, dst):
    bf, sk = load_skeleton(src)
    bones = sk["bones"]
    world = fk([(b.name, b.parent) for b in bones],
               [local_matrix(b.scale, b.rotation, b.translation, b.euler) for b in bones])
    out = {
        "source": str(src),
        "bfres_version": bf.version_str,
        "skeleton_flags": hex(sk["flags"]),
        "rotation_mode": "euler_xyz_radians" if sk["flags"] & (1 << 12) else "quaternion",
        "rotation_convention": "R = Rz*Ry*Rx (column vectors, X applied first); local = T*R*S; "
                               "rotation stored as vec4 (x,y,z,w) where w is unused (1.0) in euler mode",
        "units": "meters, Y up",
        "bone_count": len(bones),
        "num_smooth_matrices": sk["num_smooth"],
        "num_rigid_matrices": sk["num_rigid"],
        "bones": [],
    }
    for b, (wm, wt) in zip(bones, world):
        out["bones"].append({
            "index": b.index, "name": b.name, "parent": b.parent,
            "parent_name": bones[b.parent].name if b.parent >= 0 else None,
            "flags": hex(b.flags),
            "rotation_euler": b.euler,
            "segment_scale_compensate": bool(b.flags & (1 << 23)),
            "smooth_matrix_index": b.smooth_index, "rigid_matrix_index": b.rigid_index,
            "translation": rnd(b.translation), "rotation": rnd(b.rotation), "scale": rnd(b.scale),
            "world_position": rnd(wt), "world_rotation_matrix": [rnd(r) for r in wm],
            "mirror_bone": (bones[sk["mirror_table"][b.index]].name if sk["mirror_table"] else None),
        })
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    Path(dst).write_text(json.dumps(out, indent=1))
    print(f"wrote {dst}: {len(bones)} bones")


def anim_summary(a):
    fl = a.flags
    parts = []
    if fl & bfres.ANIM_BAKED: parts.append("baked")
    if fl & bfres.ANIM_LOOP: parts.append("loop")
    parts.append("euler" if fl & bfres.ANIM_ROT_EULER else "per-bone-rot" if fl & bfres.ANIM_ROT_PER_BONE else "quat")
    parts.append("scale=" + ["none", "std", "maya", "softimage"][(fl >> 8) & 3])
    return ",".join(parts)


def cmd_list(dst, srcs):
    lines = []
    for src in srcs:
        bf = bfres.load(src)
        anims = bf.skeletal_anims(names_only=True)
        lines.append(f"### {Path(src).name}  (FRES v{bf.version_str}, {len(anims)} skeletal anims, "
                     f"{bf.counts['mat_anim']} material anims, size {len(bf.data)})")
        for a in anims:
            animated = [ba.name for ba in a.bone_anims if ba.flags & 0xFFC0]
            quat_bones = [ba.name for ba in a.bone_anims if ba.flags & bfres.BONE_QUAT]
            lines.append(f"{a.name}\tframes={a.frame_count}\tflags={a.flags:#x}({anim_summary(a)})\tbones={len(a.bone_anims)}"
                         f"\tcurves={a.num_curves}\tquat_bones={','.join(quat_bones) or '-'}"
                     f"\tanimated={len(animated)}: {' '.join(animated)}")
        lines.append("")
        print(src, len(anims))
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    Path(dst).write_text("\n".join(lines))


def find_anim(bf, name):
    keys = bf.dict_keys(bf.skel_anim_dict)
    i = keys.index(name)
    return bf.read_fska(bf.skel_anim_array + i * bfres.FSKA_SIZE)


def cmd_sample(src, name, dst, skeleton=None):
    bf = bfres.load(src)
    a = bf.find_anim(name)
    out = {"source": str(src), "name": a.name, "path": a.path, "frame_count": a.frame_count,
           "flags": hex(a.flags), "flags_decoded": anim_summary(a), "baked_size": a.baked_size,
           "rotation": "per bone: 'rot'=='euler' -> r = euler XYZ radians (R=Rz*Ry*Rx); 'quat' -> r = quaternion xyzw",
           "note": "per bone local TRS, absolute (replaces the rest pose, not relative to it); s=scale t=translation r=rotation. "
                   "frames 0..frame_count inclusive",
           "bones": {}}
    for ba in a.bone_anims:
        out["bones"][ba.name] = {
            "flags": hex(ba.flags), "rotation_mode": "quat" if a.bone_is_quat(ba) else "euler",
            "base_scale": rnd(ba.base_scale) if ba.base_scale else None,
            "base_rotate": rnd(ba.base_rotate) if ba.base_rotate else None,
            "base_translate": rnd(ba.base_translate) if ba.base_translate else None,
            "curves": [{"comp": c.comp, "type": c.type_name, "flags": hex(c.flags), "keys": len(c.frames),
                        "key_frames": c.frames, "start": c.start, "end": c.end} for c in ba.curves],
        }
    frames = []
    for f in range(a.frame_count + 1):
        smp = a.sample(f)
        frames.append({bn: {k: (rnd(v) if k != "rot" else v) for k, v in trs.items()} for bn, trs in smp.items()})
    out["frames"] = frames
    if skeleton:
        _, sk = load_skeleton(skeleton)
        bones = sk["bones"]
        rest = {b.name: b for b in bones}
        cmp_ = {}
        for ba in a.bone_anims:
            b = rest.get(ba.name)
            if b is None:
                cmp_[ba.name] = "NOT IN MODEL SKELETON"
                continue
            f0 = frames[0][ba.name]
            cmp_[ba.name] = {"rest_t": rnd(b.translation), "anim_t0": f0["t"], "rest_r": rnd(b.rotation[:3]),
                             "anim_r0": f0["r"]}
        out["rest_vs_frame0"] = cmp_
        # world positions of a few key bones per frame
        idx = {b.name: i for i, b in enumerate(bones)}
        keyb = [n for n in ("Root", "Skl_Root", "Spine_1", "Spine_2", "Neck", "Head", "Arm_1_L", "Arm_2_L", "Hand_L",
                            "Arm_1_R", "Arm_2_R", "Hand_R", "Weapon_R", "Weapon_L") if n in idx]
        wp = []
        for fr in frames:
            loc = []
            for b in bones:
                if b.name in fr:
                    s, r, t = fr[b.name]["s"], fr[b.name]["r"], fr[b.name]["t"]
                    loc.append(local_matrix(s, r, t, fr[b.name]["rot"] == "euler"))
                else:
                    loc.append(local_matrix(b.scale, b.rotation, b.translation, b.euler))
            w = fk([(b.name, b.parent) for b in bones], loc)
            wp.append({n: rnd(w[idx[n]][1], 4) for n in keyb})
        out["world_positions_key_bones"] = wp
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    Path(dst).write_text(json.dumps(out, indent=1))
    print(f"wrote {dst}: {a.name} {a.frame_count} frames, {len(a.bone_anims)} bone anims")


def cmd_info(src):
    bf = bfres.load(src)
    print(f"{src}: FRES v{bf.version_str} size={len(bf.data)} counts={bf.counts} ext_flags={bf.external_flags:#x}")
    print(f"  string pool @{bf.string_pool:#x} size={bf.string_pool_size:#x}, RLT @{bf.rlt_ofs:#x} "
          f"sections={len(bf.sections)} entries={len(bf.reloc_entries)} slots={len(bf.slots)}")
    if bf.q(0xC0):
        print("  external files:", bf.dict_keys(bf.q(0xC0)))
    if bf.counts["skel_anim"]:
        keys = bf.dict_keys(bf.skel_anim_dict)
        print(f"  {len(keys)} skeletal anims: {', '.join(keys[:10])}{' ...' if len(keys) > 10 else ''}")


if __name__ == "__main__":
    c = sys.argv[1]
    if c == "skeleton":
        cmd_skeleton(sys.argv[2], sys.argv[3])
    elif c == "list":
        cmd_list(sys.argv[2], sys.argv[3:])
    elif c == "sample":
        cmd_sample(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5] if len(sys.argv) > 5 else None)
    elif c == "info":
        for s in sys.argv[2:]:
            cmd_info(s)
    else:
        print(__doc__)
