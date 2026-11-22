"""End-to-end write tests. Run: uv run python tools/test_bfres_write.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import bfres  # noqa: E402
import bfres_add_anim as baa  # noqa: E402

SMALL = "unpacked/Player_Adult.anim.bfres"
HAMMER = "unpacked/Player_Adult_02_H_Animation.anim.bfres"
OUT = Path("out/bfres")


def max_pose_diff(a, b, frames):
    worst = 0.0
    for f in frames:
        pa, pb = a.sample(f), b.sample(f)
        for bn, ta in pa.items():
            tb = pb[bn]
            for k in ("s", "t"):
                worst = max(worst, max(abs(x - y) for x, y in zip(ta[k], tb[k])))
            if ta["rot"] == "quat":
                d = abs(sum(x * y for x, y in zip(ta["r"], tb["r"])))
                worst = max(worst, 1 - d)
            else:
                worst = max(worst, max(abs(x - y) for x, y in zip(ta["r"], tb["r"])))
    return worst


def main():
    # 0) round trip
    bf = bfres.load(SMALL)
    assert bfres.rewrite_unchanged(bf) == bytes(bf.data), "round trip not byte identical"
    print("round trip: byte identical")

    # 1) copy hammer attack, rename, modify Root tz (root motion doubled)
    src = bfres.load(HAMMER).find_anim("Hammer_Attack_Vertical_Advance")
    orig = bfres.load(HAMMER).find_anim("Hammer_Attack_Vertical_Advance")
    src.name = "FalconPunch_Test"
    root = next(ba for ba in src.bone_anims if ba.name == "Root")
    c = root.curve_for("tz")
    frames = list(range(src.frame_count + 1))
    root.curves[root.curves.index(c)] = bfres.make_hermite_curve("tz", frames, [2 * c.evaluate(f) for f in frames])
    data = baa.write(bfres.load(SMALL), src, OUT / "test_added_anim.bfres", write_zs=True)
    chk = bfres.Bfres(data)
    print("anims:", chk.skel_anim_names(), "mat anims:", chk.dict_keys(chk.q(0x70)))
    assert chk.find_anim("Player_Adult_1st").bone_anims[5].curves[0].raw_keys == \
        bf.find_anim("Player_Adult_1st").bone_anims[5].curves[0].raw_keys
    new = chk.find_anim("FalconPunch_Test")
    rt = [new.sample(f)["Root"]["t"][2] for f in (0, 10, 15, 20)]
    print("Root tz (doubled):", [round(x, 4) for x in rt])
    for ba in new.bone_anims:
        ba.curves = [cc for cc in ba.curves if not (ba.name == "Root")]
    o2 = bfres.load(HAMMER).find_anim("Hammer_Attack_Vertical_Advance")
    for ba in o2.bone_anims:
        ba.curves = [cc for cc in ba.curves if not (ba.name == "Root")]
    print("copied anim vs original (excluding Root) max diff:", max_pose_diff(new, o2, range(0, 21)))
    # unchanged existing anim/material data still identical when re-read
    assert chk.read_dict(chk.q(0x70)) == bf.read_dict(bf.q(0x70))

    # 2) custom anim from per-frame TRS JSON (built from the sampled hammer attack), filled from template
    spec = {"frame_count": orig.frame_count, "loop": False, "bones": {}}
    samples = [orig.sample(f) for f in frames]
    for ba in orig.bone_anims:
        if not ba.curves:
            continue
        spec["bones"][ba.name] = {k: [s[ba.name][k] for s in samples] for k in ("s", "r", "t")}
    (OUT / "test_custom_anim_input.json").write_text(json.dumps(spec))
    data2 = baa.bfres_add_anim(SMALL, OUT / "test_custom_anim.bfres", "FalconPunch_Custom",
                               OUT / "test_custom_anim_input.json", fill=HAMMER + ":Hammer_Attack_Vertical_Advance",
                               write_zs=True)
    cus = bfres.Bfres(data2).find_anim("FalconPunch_Custom")
    print("custom anim: bones", len(cus.bone_anims), "curves", cus.num_curves, "baked", cus.baked_size)
    print("custom vs original max diff (integer frames):", max_pose_diff(cus, orig, frames))
    print("custom vs original max diff (half frames):", max_pose_diff(cus, orig, [f + 0.5 for f in frames[:-1]]))


if __name__ == "__main__":
    main()
