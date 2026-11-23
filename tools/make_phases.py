"""The punch as the phases of the hammer's attack (the jump slam: the AS commands CutJumpSt, CutJumpEd, CutJumpLand),
each a time-warped part of the retargeted Falcon Punch (tools/retarget_falcon_link.py: 60 fps Melee frames, the
hit at 52-56 of 100):

    uv run python tools/make_phases.py        # out/retarget/falcon_punch_phase_<name>.json

    FalconPunch_Ground, _GroundZero   the whole punch standing (the hammer's ground swing, the AS command CutS1),
                       with and without the step forward (the game blends the two)
    FalconPunch_Pre    the jump slam's wind-up, on the ground (the hammer's Hammer_Attack_Jump_Pre; the state goes on at its
                       CanChangeAS event, tools/build_asb.py PRE_GO)
    FalconPunch_St     the thrust (Hammer_Attack_Jump_St, 12 frames, start of the leap)
    FalconPunch_Jump   the fist held out, looped while Link is in the air (Hammer_Attack_Jump)
    FalconPunch_Land   the impact and the way back (Hammer_Attack_Vertical_Jump_Land, 65 frames, ends at 51)
The game's code moves Link in the jump slam, so its phases have no root motion (Root stays at 0).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import retarget_falcon_link as R  # noqa: E402

PRE_FRAMES = 45   # the wind-up's length in game frames (1.5 s; Melee's own is 0.87 s)
HIDE = ("Weapon_L", "Weapon_R")   # the bones a held item's model is bound to
TINY = 0.001
GROUND_HIT = 42   # the ground punch's frame of impact (the hammer's own swing hits at 14 of 40: tools/build_asb.py)
PHASES = {   # name -> ((game frame, Melee frame) knots, loop, root motion)
    # the hit on the ground (the AS command CutS1: the hammer's Hammer_Attack_*_Advance[Zero]), one animation
    "Ground": ([(0, 0), (GROUND_HIT, 52), (GROUND_HIT + 4, 56), (66, 100)], False, True),
    "GroundZero": ([(0, 0), (GROUND_HIT, 52), (GROUND_HIT + 4, 56), (66, 100)], False, False),
    # the jump slam's phases (CutJumpSt, CutJumpEd, CutJumpLand)
    "Pre": ([(0, 0), (PRE_FRAMES - 9, 40), (PRE_FRAMES, 44)], False, False),
    "St": ([(0, 44), (6, 53), (12, 54)], False, False),
    "Jump": ([(0, 54), (20, 54)], True, False),
    "Land": ([(0, 54), (6, 56), (50, 100), (65, 100)], False, False),
}

def main():
    specs = {rm: R.retarget(R.MELEE / "falcon_punch_ground.json", root_motion=rm, leg_ik=True) for rm in (False, True)}
    for name, (knots, loop, rm) in PHASES.items():
        out = R.warp(specs[rm], knots)
        out["loop"] = loop
        for b in HIDE:   # (the hammer's model, which the game's logic still puts in his hand, shrunk to nothing)
            out["bones"][b] = {"s": [[TINY] * 3] * (out["frame_count"] + 1)}
        p = R.OUT / f"falcon_punch_phase_{name.lower()}.json"
        p.write_text(json.dumps(out))
        print(p.name, out["frame_count"], "frames", "loop" if loop else "", "root motion" if rm else "")

if __name__ == "__main__":
    main()
