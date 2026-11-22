"""Build the playable mod (v1): the Megaton Hammer's vertical attack plays the Falcon Punch.

Output: out/mod/FalconPunch/romfs/... (git-ignored: it is built from the player's own game files).
Copy that FalconPunch folder into <game folder>/mods/ to use it.

    uv run python tools/retarget_falcon_link.py   # once: writes out/retarget/falcon_punch_link_*.json
    uv run python tools/build_mod.py [--romfs /Games/TF-OOT/Hookshot/romfs] [--out out/mod/FalconPunch]

What it writes:
- Model/Player_Adult_02_H_Animation.anim.bfres.zs: the original, with the names of
  Hammer_Attack_Vertical_Advance(Zero) changed in place (last letter -> 'Q') so the game no longer finds them there.
- Model/Player_Adult_04_Animation.anim.bfres.zs: the original plus the retargeted punch under those two names
  (ground with root motion as _Advance, in place as _AdvanceZero). Anims are bound by name across all the player's
  anim files, so the AS now plays ours.
- System/Resource/ResourceSizeTable...rsizetable.zs: the _04 entry grown by the size difference (no dictionary).
"""
import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import restbl  # noqa: E402
import zs  # noqa: E402

P02 = "Model/Player_Adult_02_H_Animation.anim.bfres"
P04 = "Model/Player_Adult_04_Animation.anim.bfres"
ANIMS = {  # game anim name -> retarget output
    "Hammer_Attack_Vertical_Advance": "falcon_punch_link_ground.json",
    "Hammer_Attack_Vertical_AdvanceZero": "falcon_punch_link_ground_advancezero.json",
}


def hide_names(data, names):
    d = bytearray(data)
    for n in names:
        s = n.encode() + b"\0"
        i = d.find(s)
        assert i > 0 and d.find(s, i + 1) < 0, n
        d[i + len(s) - 2:i + len(s) - 1] = b"Q"
    return bytes(d)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--romfs", default="/Games/TF-OOT/Hookshot/romfs")
    ap.add_argument("--out", default=str(ROOT / "out/mod/FalconPunch"))
    a = ap.parse_args()
    romfs, out = Path(a.romfs), Path(a.out) / "romfs"
    work = ROOT / "out/mod/work"
    work.mkdir(parents=True, exist_ok=True)
    (out / "Model").mkdir(parents=True, exist_ok=True)

    p02 = zs.load(str(romfs / (P02 + ".zs")))
    p04 = zs.load(str(romfs / (P04 + ".zs")))
    (work / "p04_orig.bfres").write_bytes(p04)

    cur = work / "p04_orig.bfres"
    for i, (name, js) in enumerate(ANIMS.items()):
        nxt = work / f"p04_{i}.bfres"
        subprocess.run([sys.executable, str(ROOT / "tools/bfres_add_anim.py"), "json", str(cur), str(nxt), name,
                        str(ROOT / "out/retarget" / js), "--fill", f"{work / 'p04_orig.bfres'}:Wait"], check=True)
        cur = nxt
    new04 = cur.read_bytes()

    (out / (P02 + ".zs")).write_bytes(zs.compress(hide_names(p02, ANIMS), "x.bfres.zs"))
    (out / (P04 + ".zs")).write_bytes(zs.compress(new04, "x.bfres.zs"))

    t = restbl.load(romfs)
    old = t.get(P04)
    t.set(P04, old + len(new04) - len(p04))
    (out / restbl.REL).parent.mkdir(parents=True, exist_ok=True)
    restbl.save(t, out / restbl.REL)
    print(f"{P04}: {len(p04)} -> {len(new04)} bytes; RESTBL {old} -> {t.get(P04)}")
    print("mod written to", out.parent)


if __name__ == "__main__":
    main()
