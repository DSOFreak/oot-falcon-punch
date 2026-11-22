"""Insert the retargeted Falcon Punch anims into a copy of Player_Adult_04_Animation.anim.bfres and verify.

  uv run python tools/retarget_build_bfres.py
Inputs : out/retarget/falcon_punch_link_{ground,ground_advancezero,air}.json  (tools/retarget_falcon_link.py)
         /Games/TF-OOT/Hookshot/romfs/Model/Player_Adult_04_Animation.anim.bfres.zs (read only)
Outputs: out/retarget/Player_Adult_04_Animation.anim.bfres(.zs), out/retarget/bfres_check.json
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation as Rot

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bfres  # noqa: E402
import zs  # noqa: E402
from bfres_add_anim import anim_from_json  # noqa: E402

ROOT = HERE.parent
OUT = ROOT / "out/retarget"
SRC_ZS = Path("/Games/TF-OOT/Hookshot/romfs/Model/Player_Adult_04_Animation.anim.bfres.zs")
FILL = "Wait"  # neutral pose template for every bone the JSON doesn't drive (from the same file)
ANIMS = [("FalconPunch", "falcon_punch_link_ground.json"),
         ("FalconPunch_AdvanceZero", "falcon_punch_link_ground_advancezero.json"),
         ("FalconPunch_Air", "falcon_punch_link_air.json")]


def rmat(r):
    return (Rot.from_quat(r) if len(r) == 4 else Rot.from_euler("xyz", r)).as_matrix()


def main():
    raw = zs.decompress(SRC_ZS.read_bytes(), SRC_ZS.name)
    bf = bfres.Bfres(raw)
    fill = bf.find_anim(FILL)
    ssc = {ba.name: bool(ba.flags & bfres.SEG_SCALE_COMPENSATE) for ba in fill.bone_anims}
    specs = {}
    data = raw
    for name, fn in ANIMS:
        spec = json.loads((OUT / fn).read_text())
        for b, ch in spec["bones"].items():
            ch["ssc"] = ssc.get(b, True)
        specs[name] = spec
        anim = anim_from_json(name, spec, fill, template_flags=fill.flags)
        data = bfres.add_skeletal_anim(bfres.Bfres(data), anim)
        print(f"added {name}: {anim.frame_count} frames, {len(anim.bone_anims)} bones")
    out = OUT / "Player_Adult_04_Animation.anim.bfres"
    out.write_bytes(data)
    zp = out.with_name(out.name + ".zs")
    zp.write_bytes(zs.compress(data, zp.name))
    print("wrote", out, len(data), "and", zp, zp.stat().st_size)

    # ---- verify: reparse, old anims untouched, new anims sample back to the JSON
    chk = bfres.load(out)
    orig = bfres.Bfres(raw)
    names = chk.skel_anim_names()
    assert names[:len(orig.skel_anim_names())] == orig.skel_anim_names()
    assert names[-3:] == [a for a, _ in ANIMS], names[-3:]
    report = {"anim_count_before": len(orig.skel_anim_names()), "anim_count_after": len(names)}
    for a_old in ("Wait", orig.skel_anim_names()[0], orig.skel_anim_names()[-1]):
        A, B = orig.find_anim(a_old), chk.find_anim(a_old)
        for f in (0, A.frame_count / 3, A.frame_count):
            pa, pb = A.sample(f), B.sample(f)
            assert all(pa[k] == pb[k] for k in pa), a_old
    for name, _ in ANIMS:
        spec = specs[name]
        A = chk.find_anim(name)
        fill_pose = fill.sample(0)
        worst_r = worst_t = 0.0
        where = None
        for k in range(spec["frame_count"] + 1):
            p = A.sample(k)
            for b, ch in spec["bones"].items():
                if "r" in ch:
                    d = Rot.from_matrix(rmat(p[b]["r"]).T @ rmat(ch["r"][k])).magnitude()
                    if d > worst_r:
                        worst_r, where = d, (b, k)
                if "t" in ch:
                    worst_t = max(worst_t, float(np.abs(np.array(p[b]["t"]) - ch["t"][k]).max()))
        # full-skeleton FK: bfres-sampled pose vs JSON (+ Wait for unlisted bones/channels), world positions
        from retarget_falcon_link import Link, pose_from_spec
        L = Link()
        fk_err = 0.0
        for k in range(spec["frame_count"] + 1):
            p = A.sample(k)
            got = {n: {"t": np.array((p.get(n) or L.rest[n])["t"]), "R": rmat((p.get(n) or L.rest[n])["r"])}
                   for n in L.names}
            want = pose_from_spec(L, spec, k, fill_pose)
            fk_err = max(fk_err, float(np.abs(L.fk(got)[1] - L.fk(want)[1]).max()))
        # bones not in JSON must equal the fill template's frame-0 pose
        p = A.sample(spec["frame_count"] / 2)
        fill_err = max(Rot.from_matrix(rmat(p[b]["r"]).T @ rmat(fill_pose[b]["r"])).magnitude()
                       for b in fill_pose if b not in spec["bones"])
        report[name] = {"frames": A.frame_count, "bones": len(A.bone_anims), "curves": A.num_curves,
                        "max_rot_err_deg_at_keys": math.degrees(worst_r), "worst_at": where,
                        "max_trans_err_m": worst_t, "fk_world_pos_max_err_m": fk_err, "fill_bones_max_err_deg": math.degrees(fill_err),
                        "loop": bool(A.flags & bfres.ANIM_LOOP), "flags": hex(A.flags)}
        print(name, report[name])
        assert fk_err < 1e-4 and math.degrees(worst_r) < 1e-2 and worst_t < 1e-4, name
    (OUT / "bfres_check.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
