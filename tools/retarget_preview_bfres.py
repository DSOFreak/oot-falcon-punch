"""Stick-figure preview of the Falcon Punch anims sampled back from the written bfres (30 fps anim frames),
including the driven helper bones (skirt/belt/sleeves = green, twist/volume helpers = orange).
  uv run python tools/retarget_preview_bfres.py   -> out/retarget/preview_bfres_{FalconPunch,FalconPunch_Air}.png"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bfres  # noqa: E402
from retarget_falcon_link import Link, LINK_DRAW, OUT, SIDE_COL, rmat  # noqa: E402


def main(picks=(0, 10, 20, 26, 28, 40, 50)):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    L = Link()
    bf = bfres.load(OUT / "Player_Adult_04_Animation.anim.bfres")
    for name in ("FalconPunch", "FalconPunch_Air"):
        a = bf.find_anim(name)
        fig = plt.figure(figsize=(2.6 * len(picks), 7))
        for col, k in enumerate(picks):
            s = a.sample(k)
            pose = {n: {"t": np.array((s.get(n) or L.rest[n])["t"]), "R": rmat((s.get(n) or L.rest[n])["r"])}
                    for n in L.names}
            R, P = L.fk(pose)
            for row, (vn, ia, ib) in enumerate((("side", 2, 1), ("front", 0, 1))):
                ax = fig.add_subplot(2, len(picks), row * len(picks) + col + 1)
                for n in L.names:
                    i = L.idx[n]; pi = L.parent[i]
                    if pi < 0 or L.names[pi] == "Root":
                        continue
                    if n in LINK_DRAW:
                        c, lw = SIDE_COL(n), 1.4
                    elif n.startswith(("Ph_Skirt", "Ph_Belt", "Ph_WaistBelt", "Ph_Sleeve", "Ph_Leg_Support")) and n in s:
                        c, lw = "tab:green", .7
                    elif n.startswith(("Ph_Knee", "Ph_Elbow", "Ph_Wrist_Assist", "Ph_Arm_1_Assist", "Ph_Ankle")) and n in s:
                        c, lw = "tab:orange", .9
                    else:
                        continue
                    ax.plot([P[pi, ia], P[i, ia]], [P[pi, ib], P[i, ib]], "-", color=c, lw=lw)
                for S in "LR":
                    q = s[f"Ph_Pred_Ankle_{S}"]["t"]; r = s["Root"]["t"]
                    ax.plot(q[ia] + r[ia], q[ib] + r[ib], "x", color=SIDE_COL("_" + S), ms=6)
                cx = P[L.idx["Skl_Root"], ia] if ia != 0 else 0
                ax.axhline(0, color="g", lw=.6)
                ax.set_xlim(cx - .9, cx + .9); ax.set_ylim(-.1, 1.8); ax.set_aspect("equal"); ax.grid(alpha=.3)
                ax.tick_params(labelsize=5)
                ax.set_title(f"{name} anim f{k} {vn}", fontsize=7)
        fig.suptitle(f"{name} sampled from the written bfres (30 fps). x = Ph_Pred_Ankle", fontsize=9)
        fig.tight_layout()
        fig.savefig(OUT / f"preview_bfres_{name}.png", dpi=75)
        plt.close(fig)


if __name__ == "__main__":
    main()
