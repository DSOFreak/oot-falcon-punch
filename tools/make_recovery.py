"""FalconPunch_After: a short recovery from the punch's last pose to the end pose of the hammer's follow-through.

    uv run python tools/make_recovery.py [--frames 14] [--out out/retarget/falcon_punch_link_after.json]

Start pose: the last frame of out/retarget/falcon_punch_link_ground_hammertimed.json, with Wait f0 (the same fill the
game anim got) for bones the punch does not key. End pose: the last frame of Hammer_Attack_Vertical_After (_02_H),
so the next state (hammer idle) follows on without a jump. Rotations are slerped with smoothstep and written as
quaternions; translations are lerped; Root stays where the end pose has it (no root motion back).
Output: the JSON format of tools/bfres_add_anim.py.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation as Rot, Slerp

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import bfres  # noqa: E402


def quat(r):
    return Rot.from_quat(r) if len(r) == 4 else Rot.from_euler("xyz", r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=14, help="blend length")
    ap.add_argument("--total", type=int, default=46, help="anim length: the hammer's follow-through state ends by its "
                    "AnmSeqCancel event at frame 44, so the anim has to reach it (the end pose is held)")
    ap.add_argument("--punch", default=str(ROOT / "out/retarget/falcon_punch_link_ground_hammertimed.json"))
    ap.add_argument("--p02", default=str(ROOT / "unpacked/Player_Adult_02_H_Animation.anim.bfres"))
    ap.add_argument("--p04", default=str(ROOT / "unpacked/Player_Adult_04_Animation.anim.bfres"))
    ap.add_argument("--end-anim", default="Hammer_Attack_Vertical_After")
    ap.add_argument("--out", default=str(ROOT / "out/retarget/falcon_punch_link_after.json"))
    a = ap.parse_args()

    punch = json.load(open(a.punch))
    last = punch["frame_count"]
    wait = bfres.load(a.p04).find_anim("Wait").sample(0)
    end_anim = bfres.load(a.p02).find_anim(a.end_anim)
    end = end_anim.sample(end_anim.frame_count - 1)

    start = {n: {"r": b["r"], "t": b["t"], "s": b["s"]} for n, b in wait.items()}
    for n, b in punch["bones"].items():
        start.setdefault(n, {}).update({k: (v[last] if isinstance(v, list) and len(v) == last + 1 else v)
                                        for k, v in b.items() if k in ("r", "t", "s")})

    n = a.frames
    w = [3 * (k / n) ** 2 - 2 * (k / n) ** 3 for k in range(n + 1)] + [1.0] * (a.total - n)
    bones = {}
    for name, e in end.items():
        s = start.get(name, e)
        rs = Rot.concatenate([quat(s["r"]), quat(e["r"])])
        sl = Slerp([0, 1], rs)
        r = [list(map(float, q)) for q in sl(w).as_quat()]
        ts, te = np.array(s["t"], float), np.array(e["t"], float)
        ss, se = np.array(s["s"], float), np.array(e["s"], float)
        t = [list(map(float, ts + (te - ts) * x)) for x in w]
        sc = [list(map(float, ss + (se - ss) * x)) for x in w]
        if name == "Root":
            t = [list(map(float, te))] * len(w)
        bones[name] = {"r": r, "t": t, "s": sc}
    out = dict(frame_count=len(w) - 1, loop=False, fps=30, source=f"blend {Path(a.punch).name}[{last}] -> {a.end_anim}[end]",
               bones=bones)
    Path(a.out).write_text(json.dumps(out))
    print(f"wrote {a.out}: {len(w) - 1} frames ({n} blending), {len(bones)} bones")


if __name__ == "__main__":
    main()
