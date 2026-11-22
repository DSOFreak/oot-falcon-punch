"""Export adult Link's skeleton with the Falcon Punch anims as a skeleton-only glb (Blender imports it as an armature).

  uv run python tools/retarget_export_glb.py [anim.bfres]   (default out/retarget/Player_Adult_04_Animation.anim.bfres)
The anims are sampled back from the written bfres (end-to-end check of what the game would see), 30 fps, meters.
"""
import json
import struct
import sys
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation as Rot

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import bfres  # noqa: E402

ROOT = HERE.parent
SKEL = ROOT / "out/bfres/link_adult_skeleton.json"
ANIMS = ["FalconPunch", "FalconPunch_AdvanceZero", "FalconPunch_Air"]
FPS = 30.0


def quat(r):
    return Rot.from_quat(r).as_quat() if len(r) == 4 else Rot.from_euler("xyz", r[:3]).as_quat()


def main():
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "out/retarget/Player_Adult_04_Animation.anim.bfres"
    bones = json.loads(SKEL.read_text())["bones"]
    n = len(bones)
    bf = bfres.load(src)
    buf = bytearray(); accessors = []; views = []

    def add(arr, typ, minmax=False):
        a = np.asarray(arr, dtype=np.float32)
        while len(buf) % 4:
            buf.append(0)
        views.append({"buffer": 0, "byteOffset": len(buf), "byteLength": a.nbytes})
        buf.extend(a.tobytes())
        acc = {"bufferView": len(views) - 1, "componentType": 5126, "count": int(a.shape[0]), "type": typ}
        if minmax:
            acc["min"] = [float(a.min())]; acc["max"] = [float(a.max())]
        accessors.append(acc)
        return len(accessors) - 1

    nodes = [{"name": b["name"], "translation": b["translation"], "rotation": list(quat(b["rotation"][:3])),
              "scale": b["scale"]} for b in bones]
    for b in bones:
        if b["parent"] >= 0:
            nodes[b["parent"]].setdefault("children", []).append(b["index"])
    animations = []
    for name in ANIMS:
        a = bf.find_anim(name)
        nf = a.frame_count + 1
        samples = [a.sample(k) for k in range(nf)]
        tin = add(np.arange(nf) / FPS, "SCALAR", minmax=True)
        samplers, channels = [], []
        for i, b in enumerate(bones):
            if b["name"] not in samples[0]:
                continue
            T = [samples[k][b["name"]]["t"] for k in range(nf)]
            Q = [quat(samples[k][b["name"]]["r"]) for k in range(nf)]
            for k in range(1, nf):
                if np.dot(Q[k], Q[k - 1]) < 0:
                    Q[k] = -Q[k]
            S = [samples[k][b["name"]]["s"] for k in range(nf)]
            for path, data, typ in (("translation", T, "VEC3"), ("rotation", Q, "VEC4"), ("scale", S, "VEC3")):
                samplers.append({"input": tin, "output": add(data, typ), "interpolation": "LINEAR"})
                channels.append({"sampler": len(samplers) - 1, "target": {"node": i, "path": path}})
        animations.append({"name": name, "samplers": samplers, "channels": channels})
    ibm = []
    for b in bones:
        m = np.eye(4)
        m[:3, :3] = np.array(b["world_rotation_matrix"]); m[:3, 3] = b["world_position"]
        ibm.append(np.linalg.inv(m).T.reshape(-1))
    gltf = {"asset": {"version": "2.0", "generator": "falconpunch retarget_export_glb.py"},
            "scene": 0, "scenes": [{"nodes": [0]}], "nodes": nodes,
            "skins": [{"joints": list(range(n)), "skeleton": 0, "inverseBindMatrices": add(np.array(ibm), "MAT4"),
                       "name": "Player_Adult"}],
            "animations": animations, "accessors": accessors, "bufferViews": views,
            "buffers": [{"byteLength": len(buf)}]}
    js = json.dumps(gltf).encode()
    js += b" " * (-len(js) % 4)
    buf.extend(b"\0" * (-len(buf) % 4))
    out = ROOT / "out/retarget/falcon_punch_link.glb"
    data = struct.pack("<III", 0x46546C67, 2, 28 + len(js) + len(buf))
    data += struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(buf), 0x004E4942) + bytes(buf)
    out.write_bytes(data)
    print("wrote", out, len(data))


if __name__ == "__main__":
    main()
