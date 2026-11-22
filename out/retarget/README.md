# Retarget: Falcon Punch (Melee) → adult Link

Made by `uv run python tools/retarget_falcon_link.py` (about 10 s). Inputs: `out/melee/falcon_punch_{ground,air}.json`,
`out/bfres/link_adult_skeleton.json`, and `unpacked/Player_Adult_04_Animation.anim.bfres` (the `Wait` pose for neutral
bones, and the `Wait_Service_Stretch` f167 pose for the clenched right fist).

## Method

World-space rotation retarget with rest-pose alignment (see the script docstring). There are 20 mapped bone pairs
(spine, neck, head, arms, legs). Unmapped Link bones keep the `Wait` pose. The right hand uses a fist pose.
`Skl_Root` follows Falcon's hips, scaled by the leg-length ratio (0.0652 m per Melee unit). Ground root motion
(TransN Z) goes to Link's `Root`. Ground anims also get a 2-bone leg IK pass so the feet stay planted.

## Outputs (git-ignored, apart from this file)

| File | What |
|---|---|
| `falcon_punch_link_ground.json` | `FalconPunch`: ground, with root motion on `Root` |
| `falcon_punch_link_ground_advancezero.json` | `FalconPunch_AdvanceZero`: ground, without root motion (the game's `*_AdvanceZero` convention) |
| `falcon_punch_link_air.json` | `FalconPunch_Air`: air version, no root motion and no leg IK |
| `Player_Adult_04_Animation.anim.bfres(.zs)` | Copy of `_04` (169 anims) with the 3 anims above added (172). Unlisted bones are filled from `_04:Wait`, so each anim has all 295 bones. `.zs` uses the game's zstd dictionary. |
| `preview_ground.png`, `preview_air.png` | Falcon (scaled) versus Link stick figures at Melee frames 0/20/40/52/56/80/100, side and front views |
| `preview_fist.png` | Right hand at Melee f54 |
| `rotation_delta_report.json` | Worst per-frame local rotation change per bone (from the 60 fps data) |

Rebuild the bfres:

```sh
F=unpacked/Player_Adult_04_Animation.anim.bfres; R=out/retarget; T=$(mktemp -d)
uv run python tools/bfres_add_anim.py json $F $T/a.bfres FalconPunch $R/falcon_punch_link_ground.json --fill $F:Wait
uv run python tools/bfres_add_anim.py json $T/a.bfres $T/b.bfres FalconPunch_AdvanceZero $R/falcon_punch_link_ground_advancezero.json --fill $F:Wait
uv run python tools/bfres_add_anim.py json $T/b.bfres $R/Player_Adult_04_Animation.anim.bfres FalconPunch_Air $R/falcon_punch_link_air.json --fill $F:Wait --zs
```

## Frame rate: 30 fps, so 50 frames

- The game's anims are in 30 fps game frames. Evidence: `triforce_log.txt` says
  `real-time step on: ratio 2.082, game's frame rate 29`. The native game runs at 30 fps, and Triforce scales time to
  real time at higher frame rates. The TotK engine is the same.
- Melee runs at 60 fps. The JSONs are resampled 2:1 (`to_fps`, which keeps the even Melee frames), so 100 Melee
  frames become **50 anim frames**. Real-time length stays 1.67 s.
- Timing map: anim frame = Melee frame / 2.
  - Hitbox active Melee f52–56 → **anim frames 26–28**. Clear at f57 → anim 28.5.
  - "Falcon…" voice: anim frame 0.
  - "PUNCH!" voice, SE and GFX at Melee f52 → anim 26.
  - Falcon effect destroyed at Melee f65 → anim 32.5.
  - Air lunge at Melee f50 → anim 25.
- Previews and the delta report still use Melee (60 fps) frame numbers.

## Checks done

- **Pose:** at Melee f56, Link's right fist is fully extended along +Z at shoulder height, and every sampled pose
  matches Falcon's silhouette (`preview_ground.png`).
- **No retarget flips:** the large per-frame deltas match Falcon's source deltas on the same bones and frames
  (Arm_2_R 147.2° at f52, Wrist_L 135.8° at f51, air Ankle_L 174.8° at f50). Melee's punch snaps within one or two
  frames. At 30 fps the largest Euler component step is 2.95 rad (< π), so there is no wraparound.
- **bfres:** `tools/bfres_validate.py` reports bake sizes OK for all 172 anims. Its 516 small base-value
  mismatches also appear in the original file. Sampling the new anims reproduces the JSON values exactly.

## Known limitations / open points

- **Euler interpolation:** the curves are Euler (Hermite, per component). When the game samples between frames
  (above 30 fps), the snap frames (Melee f50–52) interpolate component-wise rather than by slerp. If the punch
  looks wobbly in game, write those bones as quaternion curves instead (`bfres.make_quat_curve`).
- **Not tested in game yet.** Next step: a temporary test mod pointing an AS state at `FalconPunch` (see
  `HANDOVER.md`). Check whether the resource size table needs an entry for the larger bfres (+180 KB).
- The left hand and the face keep the `Wait` pose. The fingers of the left hand are not animated.
