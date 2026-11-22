"""Add a skeletal animation to an anim .bfres (FRES v10.4, OoT Switch player anim files).

From per-frame TRS JSON:
  uv run python tools/bfres_add_anim.py json IN.bfres OUT.bfres ANIM_NAME anim.json [--fill FILE.bfres:ANIM] [--zs]
From an existing anim (any anim bfres), renamed:
  uv run python tools/bfres_add_anim.py copy IN.bfres OUT.bfres NEW_NAME SRC.bfres:SRC_ANIM [--zs]

JSON format (frames 0..frame_count inclusive => frame_count+1 samples per channel):
{
  "frame_count": 40, "loop": false,
  "bones": {
    "Arm_1_R": {"r": [[x,y,z], ...],            # euler XYZ radians (R=Rz*Ry*Rx)  -- or [x,y,z,w] quaternions
                "t": [[x,y,z], ...],            # local translation (absolute, same units as skeleton: meters)
                "s": [[x,y,z], ...]},           # optional; channels may be omitted (rest/base used)
    "Root": {"t": [[0,0,z0], ...], "frames": [0, 1, ...]}   # optional explicit key frames per bone
  }
}
Values are absolute local transforms (like the game's anims), not deltas from the rest pose.
--fill FILE:ANIM copies (frame 0 / static pose of) every bone of a template anim that the JSON doesn't
mention, so the new anim has the full 295-bone set like the game's anims.
--zs also writes OUT.zs compressed with the game's zstd dictionary.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import bfres  # noqa: E402


def _load(spec):
    path, name = spec.rsplit(":", 1)
    return bfres.load(path).find_anim(name)


def static_bone_from(ba: bfres.BoneAnim, frame=0.0, anim=None):
    """Constant bone anim equal to ba's pose at `frame`."""
    tmp = bfres.SkeletalAnim("", "", anim.flags if anim else 0x2200, 0, 0, [ba], [])
    p = tmp.sample(frame)[ba.name]
    quat = p["rot"] == "quat"
    r = p["r"] if quat else list(p["r"]) + [1.0]
    out = bfres.build_bone_anim(ba.name, [0], [p["s"]], [p["r"]], [p["t"]], quat=quat,
                                seg_scale_compensate=bool(ba.flags & bfres.SEG_SCALE_COMPENSATE))
    out.base_rotate = tuple(r)
    return out


def anim_from_json(name, spec, fill=None, template_flags=0x2200):
    bones = spec["bones"]
    if fill is not None:
        # Omitted channels of a listed bone would otherwise become zero (build_bone_anim's default base),
        # e.g. a bone given only "r" collapsed onto its parent. Use the fill template's frame-0 value instead.
        fill_pose = fill.sample(0.0)
        bones = {}
        for bname, ch in spec["bones"].items():
            ch = dict(ch)
            p = fill_pose.get(bname)
            n = len(ch.get("frames") or range(int(spec["frame_count"]) + 1))
            if p is not None:
                for c in ("s", "t"):
                    if c not in ch:
                        ch[c] = [p[c]] * n
                if "r" not in ch:
                    ch["r"] = [p["r"]] * n
            bones[bname] = ch
    anim = bfres.anim_from_frames(name, int(spec["frame_count"]), bones, loop=bool(spec.get("loop")))
    anim.flags = (template_flags & ~bfres.ANIM_LOOP) | (bfres.ANIM_LOOP if spec.get("loop") else 0)
    if fill is not None:
        have = {ba.name for ba in anim.bone_anims}
        extra = [static_bone_from(ba, 0.0, fill) for ba in fill.bone_anims if ba.name not in have]
        # keep the template's bone order (game anims list bones in skeleton order)
        order = {ba.name: i for i, ba in enumerate(fill.bone_anims)}
        anim.bone_anims = sorted(anim.bone_anims + extra, key=lambda b: order.get(b.name, 1 << 30))
        anim.bind_indices = [0xFFFF] * len(anim.bone_anims)
    return anim


def bfres_add_anim(in_bfres, out_bfres, anim_name, json_with_per_frame_trs, fill=None, write_zs=False):
    """Library entry point. json_with_per_frame_trs: path or dict. fill: 'file.bfres:Anim' or None."""
    spec = json_with_per_frame_trs
    if not isinstance(spec, dict):
        spec = json.loads(Path(spec).read_text())
    fill_anim = _load(fill) if fill else None
    bf = bfres.load(in_bfres)
    anim = anim_from_json(anim_name, spec, fill_anim, template_flags=fill_anim.flags if fill_anim else 0x2200)
    return write(bf, anim, out_bfres, write_zs)


def copy_anim(in_bfres, out_bfres, new_name, src_spec, write_zs=False):
    src = _load(src_spec)
    src.name = new_name
    return write(bfres.load(in_bfres), src, out_bfres, write_zs)


def write(bf, anim, out_bfres, write_zs):
    data = bfres.add_skeletal_anim(bf, anim)
    out = Path(out_bfres)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    # verify
    chk = bfres.load(out)
    assert chk.skel_anim_names()[-1] == anim.name
    nodes = chk.read_dict(chk.skel_anim_dict)
    assert bfres.dict_lookup(nodes, anim.name) == len(nodes) - 2
    chk.find_anim(anim.name)
    print(f"wrote {out} ({len(data)} bytes), {anim.name}: {anim.frame_count} frames, {len(anim.bone_anims)} bones")
    if write_zs:
        import zs
        zp = out.with_name(out.name + ".zs")
        zp.write_bytes(zs.compress(data, zp.name))
        print(f"wrote {zp}")
    return data


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    opts = sys.argv[1:]
    fill = opts[opts.index("--fill") + 1] if "--fill" in opts else None
    if fill:
        args.remove(fill)
    zsflag = "--zs" in opts
    if not args:
        print(__doc__); sys.exit(1)
    if args[0] == "json":
        bfres_add_anim(args[1], args[2], args[3], args[4], fill=fill, write_zs=zsflag)
    elif args[0] == "copy":
        copy_anim(args[1], args[2], args[3], args[4], write_zs=zsflag)
    else:
        print(__doc__)
