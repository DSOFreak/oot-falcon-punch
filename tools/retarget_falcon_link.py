"""Retarget Captain Falcon's Falcon Punch (Melee, out/melee/*.json) onto adult Link (OoT Switch).

Method: world-space rotation retarget with rest-pose alignment.
  For each mapped bone pair (Link L <- Falcon F) we build an orthonormal "limb frame" in each skeleton's
  rest pose (primary = joint->child direction, secondary = thumb / forward / up hint). The alignment
  A = B_F * B_L^T maps Link's rest limb frame onto Falcon's. Per frame:
      W_L(t) = W_F(t) * W_F(rest)^T * A * W_L(rest)
  i.e. Link's bone gets Falcon's world-rotation delta from (aligned) rest. Local rotations are then
  recovered top-down through Link's hierarchy (unmapped intermediate bones keep a neutral pose).
  Hips: Skl_Root translation follows Falcon's hip-joint midpoint (scaled by leg-length ratio);
  root motion (ground TransN Z) goes to Link's `Root` bone. Legs then get an optional 2-bone IK
  pass that puts Link's ankles where Falcon's (scaled) ankles are, so feet stay planted.

Usage:  uv run python tools/retarget_falcon_link.py            (writes out/retarget/*)
"""
import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation as Rot

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import bfres  # noqa: E402

OUT = ROOT / "out/retarget"
SKEL = ROOT / "out/bfres/link_adult_skeleton.json"
MELEE = ROOT / "out/melee"
NEUTRAL = (ROOT / "unpacked/Player_Adult_04_Animation.anim.bfres", "Wait", 0.0)
FIST = (ROOT / "unpacked/Player_Adult_04_Animation.anim.bfres", "Wait_Service_Stretch", 167.0)

UP = np.array([0.0, 1.0, 0.0])
FWD = np.array([0.0, 0.0, 1.0])

# link bone, falcon joint, (link dir from,to), (falcon dir from,to), secondary hint
#   dir None -> primary = UP (hips/head: no limb direction, identity alignment)
#   hint: "fwd" | "up" | "thumb_L" | "thumb_R"
MAP = [
    ("Skl_Root", "HipN", None, None, "fwd"),
    ("Waist", "HipN", None, None, "fwd"),
    ("Spine_1", "WaistN2", ("Spine_1", "Spine_2"), ("WaistN2", "BustN"), "fwd"),
    ("Spine_2", "BustN", ("Spine_2", "Neck"), ("BustN", "NeckN"), "fwd"),
    ("Neck", "NeckN", ("Neck", "Head"), ("NeckN", "HeadN"), "fwd"),
    ("Head", "HeadN", None, None, "fwd"),
]
for S in "LR":
    MAP += [
        (f"Clavicle_{S}", f"{S}ShoulderN", (f"Clavicle_{S}", f"Arm_1_{S}"), (f"{S}ShoulderN", f"{S}ShoulderJ"), "up"),
        (f"Arm_1_{S}", f"{S}ShoulderJ", (f"Arm_1_{S}", f"Arm_2_{S}"), (f"{S}ShoulderJ", f"{S}ArmJ"), f"thumb_{S}"),
        (f"Arm_2_{S}", f"{S}ArmJ", (f"Arm_2_{S}", f"Wrist_{S}"), (f"{S}ArmJ", f"{S}HandN"), f"thumb_{S}"),
        (f"Wrist_{S}", f"{S}HandN", (f"Wrist_{S}", f"@fingers_{S}"), (f"{S}HandN", f"@fingers_{S}"), f"thumb_{S}"),
        (f"Leg_1_{S}", f"{S}LegJ", (f"Leg_1_{S}", f"Leg_2_{S}"), (f"{S}LegJ", f"{S}KneeJ"), "fwd"),
        (f"Leg_2_{S}", f"{S}KneeJ", (f"Leg_2_{S}", f"Ankle_{S}"), (f"{S}KneeJ", f"{S}FootJ"), "fwd"),
        (f"Ankle_{S}", f"{S}FootJ", (f"Ankle_{S}", f"Toe_{S}"), (f"{S}FootJ", f"Ca_{S}ToeN"), "up"),
    ]
LINK_FINGERS = {S: [f"Finger_{c}_1_{S}" for c in "BCDE"] for S in "LR"}
LINK_THUMB = {S: f"Finger_A_1_{S}" for S in "LR"}
FALCON_FINGERS = {S: [f"{S}{n}Na" for n in ("1st", "2nd", "3rd", "4th")] for S in "LR"}
FALCON_THUMB = {S: f"{S}ThumbNa" for S in "LR"}


def rmat(r):
    return (Rot.from_quat(r) if len(r) == 4 else Rot.from_euler("xyz", r)).as_matrix()


def basis(d, n):
    d = d / np.linalg.norm(d)
    n = n - d * (n @ d)
    n = n / np.linalg.norm(n)
    return np.column_stack([d, n, np.cross(d, n)])


# ------------------------------------------------------------------------------------------------ Falcon
class Falcon:
    def __init__(self, path):
        d = json.loads(Path(path).read_text())
        self.fps = d["fps"]
        self.joints = d["joints"]
        self.idx = {j["name"]: j["index"] for j in self.joints}
        self.frames = d["frames"]
        self.rest = [j["rest"] for j in self.joints]

    def fk(self, pose):
        n = len(self.joints)
        R = np.zeros((n, 3, 3)); P = np.zeros((n, 3)); S = np.ones((n, 3))
        for j in self.joints:
            i, p = j["index"], j["parent"]
            trs = pose[i]
            lr = rmat(trs["r"]) * np.array(trs["s"])  # R*S
            lt = np.array(trs["t"])
            if p is None:
                R[i], P[i] = lr, lt
            else:
                P[i] = P[p] + R[p] @ lt
                R[i] = R[p] @ lr
        # strip scale from rotation (only a head leaf animates scale)
        Rn = np.array([m / np.linalg.norm(m, axis=0) for m in R])
        return Rn, P

    def pos(self, P, name):
        if name.startswith("@fingers_"):
            return np.mean([P[self.idx[n]] for n in FALCON_FINGERS[name[-1]]], axis=0)
        return P[self.idx[name]]


# ------------------------------------------------------------------------------------------------ Link
class Link:
    def __init__(self):
        sk = json.loads(SKEL.read_text())["bones"]
        self.bones = sk
        self.names = [b["name"] for b in sk]
        self.idx = {n: i for i, n in enumerate(self.names)}
        self.parent = [b["parent"] for b in sk]
        self.rest = {b["name"]: {"t": list(b["translation"]), "r": list(b["rotation"][:3]), "s": list(b["scale"])}
                     for b in sk}
        self.children = {i: [] for i in range(len(sk))}
        for b in sk:
            if b["parent"] >= 0:
                self.children[b["parent"]].append(b["index"])

    def descendants(self, name):
        out, st = [], [self.idx[name]]
        while st:
            i = st.pop()
            for c in self.children[i]:
                out.append(self.names[c]); st.append(c)
        return out

    def fk(self, pose):
        """pose: name -> {'t','R'(3x3)} (missing -> rest). Returns world R (n,3,3), P (n,3)."""
        n = len(self.names)
        R = np.zeros((n, 3, 3)); P = np.zeros((n, 3))
        for i, nm in enumerate(self.names):
            p = pose.get(nm)
            lt = np.array(p["t"]); lr = p["R"]
            if self.parent[i] < 0:
                R[i], P[i] = lr, lt
            else:
                q = self.parent[i]
                P[i] = P[q] + R[q] @ lt
                R[i] = R[q] @ lr
        return R, P

    def pos(self, P, name):
        if name.startswith("@fingers_"):
            return np.mean([P[self.idx[n]] for n in LINK_FINGERS[name[-1]]], axis=0)
        return P[self.idx[name]]


def sample_pose(path, anim, frame):
    a = bfres.load(path).find_anim(anim)
    return a.sample(frame), {ba.name: a.bone_is_quat(ba) for ba in a.bone_anims}


# ------------------------------------------------------------------------------------------------ math
def two_bone_ik(a, b, c, target, pole_hint):
    """Rotate chain a(hip)-b(knee)-c(ankle) so c reaches target. Returns world-rotation deltas (Ra, Rb)
    to apply to upper and lower segment (left-multiplied)."""
    l1 = np.linalg.norm(b - a); l2 = np.linalg.norm(c - b)
    t = target - a
    dist = np.clip(np.linalg.norm(t), abs(l1 - l2) + 1e-5, l1 + l2 - 1e-5)
    tdir = t / np.linalg.norm(t)
    # bend plane from current knee position (keeps the retargeted knee direction)
    pole = (b - a) - tdir * ((b - a) @ tdir)
    if np.linalg.norm(pole) < 1e-6:
        pole = pole_hint - tdir * (pole_hint @ tdir)
    pole /= np.linalg.norm(pole)
    cos_a = (l1 * l1 + dist * dist - l2 * l2) / (2 * l1 * dist)
    ang = math.acos(np.clip(cos_a, -1, 1))
    b_new = a + l1 * (math.cos(ang) * tdir + math.sin(ang) * pole)
    c_new = a + tdir * dist
    Ra = rot_between(b - a, b_new - a)
    # lower segment: after Ra, the ankle sits at a + Ra(c-a); then rotate about b_new
    c_after = a + Ra @ (c - a)
    Rb = rot_between(c_after - b_new, c_new - b_new)
    return Ra, Rb


def rot_between(u, v):
    u = u / np.linalg.norm(u); v = v / np.linalg.norm(v)
    x = np.cross(u, v); s = np.linalg.norm(x); c = u @ v
    if s < 1e-9:
        if c > 0:
            return np.eye(3)
        p = np.cross(u, [1, 0, 0]) if abs(u[0]) < .9 else np.cross(u, [0, 1, 0])
        return Rot.from_rotvec(math.pi * p / np.linalg.norm(p)).as_matrix()
    return Rot.from_rotvec(x / s * math.atan2(s, c)).as_matrix()


def euler_continuous(mats, ref):
    """Euler XYZ (R=Rz*Ry*Rx) per frame, choosing between the two equivalent solutions and 2pi shifts
    so consecutive frames are as close as possible. ref: euler to stay near at frame 0."""
    out = []
    prev = np.array(ref, float)
    for m in mats:
        e = Rot.from_matrix(m).as_euler("xyz")
        alt = np.array([e[0] + math.pi, math.pi - e[1], e[2] + math.pi])
        best = None
        for c in (e, alt):
            c = c + 2 * math.pi * np.round((prev - c) / (2 * math.pi))
            dd = np.abs(c - prev).sum()
            if best is None or dd < best[0]:
                best = (dd, c)
        prev = best[1]
        out.append(prev.copy())
    return np.array(out)


def quat_continuous(mats, ref=None):
    out = []
    prev = np.array(ref) if ref is not None else None
    for m in mats:
        q = Rot.from_matrix(m).as_quat()
        if prev is not None and q @ prev < 0:
            q = -q
        prev = q
        out.append(q)
    return np.array(out)


# ------------------------------------------------------------------------------------------------ retarget
def retarget(falcon_json, root_motion=True, leg_ik=True):
    F = Falcon(falcon_json)
    L = Link()
    neutral, quat_bones = sample_pose(*NEUTRAL)
    fist, _ = sample_pose(*FIST)

    # neutral local pose for every Link bone (Wait frame 0, rest for bones Wait doesn't list)
    base = {}
    for nm in L.names:
        p = neutral.get(nm) or {"t": L.rest[nm]["t"], "r": L.rest[nm]["r"]}
        base[nm] = {"t": np.array(p["t"]), "R": rmat(p["r"]), "r0": p["r"]}
    # right fist: every bone under Wrist_R except the weapon attach / armour helper
    fist_bones = [n for n in L.descendants("Wrist_R") if n.startswith(("Finger", "Wrist_Finger", "Ph_Finger"))]
    for nm in fist_bones:
        if nm in fist:
            base[nm] = {"t": np.array(fist[nm]["t"]), "R": rmat(fist[nm]["r"]), "r0": fist[nm]["r"]}

    # rest-pose world frames (skeleton bind pose for Link, HSD_Joint rest for Falcon)
    Lrest = {nm: {"t": np.array(L.rest[nm]["t"]), "R": rmat(L.rest[nm]["r"])} for nm in L.names}
    LR0, LP0 = L.fk(Lrest)
    FR0, FP0 = F.fk(F.rest)

    def hint(kind, P, side_pos, skel):
        if kind == "fwd":
            return FWD
        if kind == "up":
            return UP
        S = kind[-1]
        if skel == "L":
            return L.pos(P, LINK_THUMB[S]) - L.pos(P, f"Wrist_{S}")
        return F.pos(P, FALCON_THUMB[S]) - F.pos(P, f"{S}HandN")

    align = {}
    for lb, fj, ld, fd, h in MAP:
        if ld is None:
            BL = basis(UP, FWD); BF = basis(UP, FWD)
        else:
            BL = basis(L.pos(LP0, ld[1]) - L.pos(LP0, ld[0]), hint(h, LP0, None, "L"))
            BF = basis(F.pos(FP0, fd[1]) - F.pos(FP0, fd[0]), hint(h, FP0, None, "F"))
        # Wref = A * W_L_rest ; combined with W_F_rest^T
        align[lb] = FR0[F.idx[fj]].T @ (BF @ BL.T) @ LR0[L.idx[lb]]

    # scale: hip-joint -> ankle height
    l_leg = LP0[L.idx["Leg_1_L"]][1] - LP0[L.idx["Ankle_L"]][1]
    f_leg = FP0[F.idx["LLegJ"]][1] - FP0[F.idx["LFootJ"]][1]
    scale = l_leg / f_leg
    f_hip0 = (FP0[F.idx["LLegJ"]] + FP0[F.idx["RLegJ"]]) / 2
    l_hip0 = (LP0[L.idx["Leg_1_L"]] + LP0[L.idx["Leg_1_R"]]) / 2
    hip_off_waist = (base["Leg_1_L"]["t"] + base["Leg_1_R"]["t"]) / 2  # in Waist space (Waist t = 0)
    f_ank0 = {S: FP0[F.idx[f"{S}FootJ"]] for S in "LR"}
    l_ank0 = {S: LP0[L.idx[f"Ankle_{S}"]] for S in "LR"}

    mapped = {m[0]: m[1] for m in MAP}
    order = [n for n in L.names if n in mapped]
    nfr = len(F.frames)
    local_R = {n: [] for n in order}
    skl_t, root_t = [], []
    for k in range(nfr):
        FR, FP = F.fk(F.frames[k])
        trans = FP[F.idx["TransN"]].copy()
        target_W = {lb: FR[F.idx[fj]] @ align[lb] for lb, fj in mapped.items()}
        # hips position
        f_hip = (FP[F.idx["LLegJ"]] + FP[F.idx["RLegJ"]]) / 2 - trans
        hip_target = l_hip0 + scale * (f_hip - f_hip0)
        p_skl = hip_target - target_W["Waist"] @ hip_off_waist
        rt = np.array([0.0, 0.0, scale * trans[2]]) if root_motion else np.zeros(3)
        # local rotations top-down
        pose = {n: dict(base[n]) for n in L.names}
        pose["Root"] = {"t": rt, "R": np.eye(3)}
        pose["Skl_Root"] = {"t": p_skl, "R": target_W["Skl_Root"]}  # Root has identity rotation
        W = {"Root": np.eye(3)}
        for nm in L.names:
            pi = L.parent[L.idx[nm]]
            pw = W[L.names[pi]] if pi >= 0 else np.eye(3)
            if nm in mapped:
                pose[nm]["R"] = pw.T @ target_W[nm]
            W[nm] = pw @ pose[nm]["R"]
        if leg_ik:
            for S in "LR":
                R_, P_ = L.fk(pose)
                a = P_[L.idx[f"Leg_1_{S}"]]; b = P_[L.idx[f"Leg_2_{S}"]]; c = P_[L.idx[f"Ankle_{S}"]]
                f_ank = FP[F.idx[f"{S}FootJ"]] - trans
                tgt = l_ank0[S] + scale * (f_ank - f_ank0[S])
                tgt = tgt + np.array([0, 0, 0]) + pose["Root"]["t"]
                Ra, Rb = two_bone_ik(a, b, c, tgt, FWD)
                # apply: new world of Leg_1 = Ra*W1, Leg_2 = Rb*Ra*W2, ankle keeps its world rotation
                W1 = R_[L.idx[f"Leg_1_{S}"]]; W2 = R_[L.idx[f"Leg_2_{S}"]]; W3 = R_[L.idx[f"Ankle_{S}"]]
                Wp = R_[L.parent[L.idx[f"Leg_1_{S}"]]]
                nW1 = Ra @ W1; nW2 = Rb @ Ra @ W2
                pose[f"Leg_1_{S}"]["R"] = Wp.T @ nW1
                pose[f"Leg_2_{S}"]["R"] = nW1.T @ nW2
                pose[f"Ankle_{S}"]["R"] = nW2.T @ W3
        for n in order:
            local_R[n].append(pose[n]["R"])
        skl_t.append(p_skl); root_t.append(rt)

    # ---- JSON
    bones = {}
    for n in order:
        if quat_bones.get(n):
            r = quat_continuous(local_R[n], neutral[n]["r"] if n in neutral else None).tolist()
        else:
            r = euler_continuous(local_R[n], base[n]["r0"][:3]).tolist()
        ent = {"r": r}
        if n == "Skl_Root":
            ent["t"] = [list(map(float, v)) for v in skl_t]
        bones[n] = ent
    bones["Root"] = {"t": [list(map(float, v)) for v in root_t], "r": [[0.0, 0.0, 0.0]] * nfr}
    for n in fist_bones:
        if n in fist:
            p = fist[n]
            bones[n] = {"t": [p["t"]] * nfr, "r": [p["r"]] * nfr, "s": [p["s"]] * nfr}
    spec = {"frame_count": nfr - 1, "loop": False, "fps": 60,
            "source": str(falcon_json), "scale_m_per_melee_unit": scale,
            "fill_template": f"{NEUTRAL[0].name}:{NEUTRAL[1]}", "bones": bones}
    return spec


# ------------------------------------------------------------------------------------------------ checks
def pose_from_spec(L, spec, k, fill):
    pose = {}
    for nm in L.names:
        b = spec["bones"].get(nm)
        if b:
            r = b["r"][k] if "r" in b else (fill[nm]["r"] if nm in fill else L.rest[nm]["r"])
            t = b["t"][k] if "t" in b else (fill[nm]["t"] if nm in fill else L.rest[nm]["t"])
        else:
            p = fill.get(nm) or L.rest[nm]
            r, t = p["r"], p["t"]
        pose[nm] = {"t": np.array(t), "R": rmat(r)}
    return pose


def max_delta_report(spec):
    rep = {}
    for n, b in spec["bones"].items():
        r = b.get("r")
        if not r or len(r) < 2:
            continue
        Ms = [rmat(x) for x in r]
        d = [math.degrees(Rot.from_matrix(Ms[i].T @ Ms[i + 1]).magnitude()) for i in range(len(Ms) - 1)]
        comp = np.abs(np.diff(np.array(r), axis=0)).max()
        rep[n] = (max(d), int(np.argmax(d)), float(comp))
    return rep


SIDE_COL = lambda n: "tab:red" if n.endswith("_R") else ("tab:blue" if n.endswith("_L") else "k")  # noqa: E731
LINK_DRAW = {"Skl_Root", "Waist", "Spine_1", "Spine_2", "Neck", "Head", "Head_2"} | {
    f"{b}_{S}" for S in "LR" for b in ("Clavicle", "Arm_1", "Arm_2", "Wrist", "Leg_1", "Leg_2", "Ankle", "Toe",
                                       "Finger_A_1", "Finger_A_2", "Finger_A_3", "Wrist_Finger_C", "Finger_C_1",
                                       "Finger_C_2", "Finger_C_3")}


def render_preview(spec, falcon_json, path, picks=(0, 20, 40, 52, 56, 80, 100), title=""):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    L = Link(); F = Falcon(falcon_json)
    fill, _ = sample_pose(*NEUTRAL)
    s = spec["scale_m_per_melee_unit"]
    views = (("side", 2, 1), ("front", 0, 1))
    fig = plt.figure(figsize=(2.6 * len(picks), 3.4 * 2 * 2))
    for col, k in enumerate(picks):
        R, P = L.fk(pose_from_spec(L, spec, k, fill))
        FR, FP = F.fk(F.frames[k])
        FP = FP * s
        for vi, (vn, a, b) in enumerate(views):
            for who in range(2):
                ax = fig.add_subplot(4, len(picks), (vi * 2 + who) * len(picks) + col + 1)
                if who == 0:
                    for j in F.joints:
                        if j["parent"] is None or j["name"] in ("ThrowN", "Extra", "TransN", "XRotN", "YRotN"):
                            continue
                        nm = j["name"]
                        c = "tab:red" if nm.startswith(("R", "Ca_R")) else (
                            "tab:blue" if nm.startswith(("L", "Ca_L")) else "k")
                        pa, pb = FP[j["parent"]], FP[j["index"]]
                        ax.plot([pa[a], pb[a]], [pa[b], pb[b]], "-", color=c, lw=1.4)
                    for nm, mk in (("RHandN", "r*"), ("LHandN", "b*"), ("HeadN", "ko")):
                        q = FP[F.idx[nm]]; ax.plot(q[a], q[b], mk, ms=7)
                    cx = FP[F.idx["HipN"], a]
                    lab = "Falcon (scaled)"
                else:
                    for nm in LINK_DRAW:
                        i = L.idx[nm]; pi = L.parent[i]
                        if L.names[pi] == "Root" and nm != "Skl_Root":
                            continue
                        pa, pb = P[pi], P[i]
                        ax.plot([pa[a], pb[a]], [pa[b], pb[b]], "-", color=SIDE_COL(nm), lw=1.4)
                    for nm, mk in (("Wrist_R", "r*"), ("Wrist_L", "b*"), ("Head", "ko")):
                        q = P[L.idx[nm]]; ax.plot(q[a], q[b], mk, ms=7)
                    cx = P[L.idx["Skl_Root"], a]
                    lab = "Link"
                if a == 0:
                    cx = 0
                ax.axhline(0, color="g", lw=.6)
                ax.set_xlim(cx - .9, cx + .9); ax.set_ylim(-.1, 1.8)
                ax.set_aspect("equal"); ax.grid(alpha=.3)
                ax.tick_params(labelsize=5)
                ax.set_title(f"{lab} f{k} {vn}" + (" (Z fwd ->)" if vn == "side" else " (X ->)"), fontsize=7)
    fig.suptitle(f"{title}  red = right, blue = left, * = wrist, o = head", fontsize=9)
    fig.tight_layout()
    fig.savefig(path, dpi=75)
    plt.close(fig)


def render_hand(spec, path, k=54):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    L = Link(); fill, _ = sample_pose(*NEUTRAL)
    R, P = L.fk(pose_from_spec(L, spec, k, fill))
    names = ["Wrist_R"] + L.descendants("Wrist_R")
    names = [n for n in names if n.startswith(("Wrist", "Finger"))]
    fig, axs = plt.subplots(1, 3, figsize=(10, 3.6))
    for ax, (a, b, t) in zip(axs, ((2, 1, "side"), (0, 1, "front"), (0, 2, "top"))):
        for n in names[1:]:
            i = L.idx[n]; pi = L.parent[i]
            ax.plot([P[pi, a], P[i, a]], [P[pi, b], P[i, b]], "o-", ms=2, color="tab:orange" if "_A_" in n else "k")
        w = P[L.idx["Wrist_R"]]
        ax.set_xlim(w[a] - .15, w[a] + .15); ax.set_ylim(w[b] - .15, w[b] + .15); ax.set_aspect("equal")
        ax.set_title(f"right hand f{k} {t} (orange = thumb)", fontsize=8)
    fig.tight_layout(); fig.savefig(path, dpi=80); plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    jobs = [("ground", "falcon_punch_link_ground", True),
            ("ground", "falcon_punch_link_ground_advancezero", False),
            ("air", "falcon_punch_link_air", False)]
    report = {}
    for src, name, rm in jobs:
        fj = MELEE / f"falcon_punch_{src}.json"
        spec = retarget(fj, root_motion=rm, leg_ik=(src == "ground"))
        (OUT / f"{name}.json").write_text(json.dumps(spec))
        rep = max_delta_report(spec)
        worst = sorted(rep.items(), key=lambda kv: -kv[1][0])[:8]
        report[name] = {n: {"max_deg_per_frame": round(v[0], 2), "at_frame": v[1], "max_component_jump_rad": round(v[2], 3)}
                        for n, v in worst}
        print(name, "scale", spec["scale_m_per_melee_unit"], "worst per-frame deltas:",
              [(n, round(v[0], 1), v[1], round(v[2], 2)) for n, v in worst])
        if rm or src == "air":
            render_preview(spec, fj, OUT / f"preview_{src}.png", title=name)
    render_hand(json.loads((OUT / "falcon_punch_link_ground.json").read_text()), OUT / "preview_fist.png")
    (OUT / "rotation_delta_report.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
