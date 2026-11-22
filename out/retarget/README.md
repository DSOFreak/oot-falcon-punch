# Retarget: Falcon Punch (Melee) → adult Link

```sh
uv run python tools/retarget_falcon_link.py     # JSON + previews (~10 s; ~90 s the first time, to build helper_pool.npz)
uv run python tools/retarget_build_bfres.py     # copy of _04 + 3 anims, .zs, round-trip checks -> bfres_check.json
uv run python tools/retarget_export_glb.py      # falcon_punch_link.glb (sampled back from the written bfres)
uv run python tools/retarget_preview_bfres.py   # preview_bfres_*.png (sampled back from the written bfres)
```

Inputs:
- `out/melee/falcon_punch_{ground,air}.json`
- `out/bfres/link_adult_skeleton.json`
- `unpacked/Player_Adult_04_Animation.anim.bfres` (this is identical to a fresh decompress of the romfs `.zs`), which supplies:
  - `Wait` f0: the neutral pose and the `--fill` template
  - `Wait_Service_Stretch` f167: the clenched right fist
- `_02_H`/`_03`/`_04` anims: the helper-bone pose pool

## Method

1. **Rotation retarget in world space, with rest-pose alignment.**
   - For each mapped pair, a limb frame is built in both rest poses:
     - primary axis: from the joint to its child
     - secondary axis: thumb direction for arms, +Z for spine and legs, +Y for clavicles and feet
   - `A = B_F·B_Lᵀ` maps Link's A-pose limb frame onto Falcon's T-pose frame. Each frame: `W_L(t) = W_F(t)·W_F(rest)ᵀ·A·W_L(rest)`.
   - Local rotations are solved top-down. Arm twist is aligned through the hand frame: Link's hand frame matches Falcon's to within about 3° on every frame.
2. **Hips and root motion.**
   - `Skl_Root` translation follows the midpoint of Falcon's hip joints, scaled by the leg-length ratio (hip-to-ankle height): **0.06525 m per Melee unit**.
   - Ground root motion (TransN Z, 12.7 units ≈ 0.83 m) goes on `Root` tz, the same convention as the game's `*_Advance` anims. `_AdvanceZero` keeps `Root` at 0.
3. **Leg IK (ground only).** A two-bone IK puts Link's ankles at Falcon's scaled ankle positions. It keeps the retargeted knee plane, so the feet stay planted.
4. **Hands.**
   - Right hand: the fist pose (fingers, thumb, `Wrist_Finger_*`, `Ph_Finger_*`).
   - Left hand: the open `Wait` hand.
5. **Helper bones (`Ph_*`) that the game's own anims key.**
   - Twist helpers use rules fitted on game anims (residual ≤ 0.5°):
     - `Ph_Wrist_Assist_A/B` = 0.72 × wrist twist
     - `Ph_Arm_1_Assist` = −0.64 × upper-arm twist
     - `Ph_Arm_1_Assist_B` = −0.295 × upper-arm twist − 2.1°
   - Knee, elbow and ankle helpers, sleeves, collar, belt and skirt use a pose-space lookup:
     - the 8 nearest of 17.5k game frames by driver-bone rotation, inverse-distance weighted
     - 1-2-1 temporal smoothing
   - `Ph_Pred_Ankle_*` follows the game convention: the ankle xz of the current or next planted foot, y = 0.103, in Root space.
   - Only the 295 bones that `Wait` lists are written. Hair, cap and similar bones are runtime physics.
6. **Unmapped bones** come from `Wait` f0 through the fill: face, weapon attach and `Weapon_Root`.
7. **Euler continuity.** For each frame the code picks between the two equivalent XYZ solutions and adds ±2π shifts so values stay continuous. Clavicles are written as quaternions, like the game does.

### Bone map

| Link | Falcon | | Link | Falcon |
|---|---|---|---|---|
| Skl_Root, Waist | HipN (4) | | Leg_1_L/R | LLegJ 7 / RLegJ 13 |
| Spine_1 | WaistN2 (18) | | Leg_2_L/R | LKneeJ 8 / RKneeJ 14 |
| Spine_2 | BustN (19) | | Ankle_L/R | LFootJ 10 / RFootJ 16 |
| Neck | NeckN (38) | | Clavicle_L/R | LShoulderN 21 / RShoulderN 42 |
| Head | HeadN (39) | | Arm_1_L/R | LShoulderJ 23 / RShoulderJ 45 |
| Root (tz) | TransN (1) TRAZ × 0.06525 | | Arm_2_L/R | LArmJ 24 / RArmJ 46 |
| | | | Wrist_L/R | LHandN 25 / RHandN 47 |

## Frame rate: 30 fps, 50 frames

- The game runs at 30 fps. `Hookshot/triforce_log.txt` says "game's frame rate 29", and the real-time step ratio is about 2.
- TotK-engine anims count frames in game frames. A counter-argument: the root speeds of `Move_Run`, `Move_Walk` and `Move_Dash` (2.7 m / 30 frames, and so on) look slow at 30 fps. Locomotion playback is speed-synced, though, so that is weak evidence.
- Melee is 60 fps. The anims are resampled 2:1 (`to_fps`, which keeps the even Melee frames), and the real-time length stays 1.67 s.
- **Anim frame = Melee frame / 2.**
  - Hitbox Melee f52–56 → **anim 26–28**.
  - "PUNCH!", the SE and the GFX → anim 26.
  - "Falcon…" voice → anim 0.
  - Effect cleared at anim 32.5.
  - Air lunge → anim 25.
- `preview_ground.png`, `preview_air.png`, `preview_fist.png` and `rotation_delta_report.json` use Melee (60 fps) frame numbers. `preview_bfres_*.png` and the glb use anim frames.

## Outputs

| File | What |
|---|---|
| `falcon_punch_link_ground.json` | `FalconPunch`: ground, root motion on `Root` (input format of `tools/bfres_add_anim.py`) |
| `falcon_punch_link_ground_advancezero.json` | `FalconPunch_AdvanceZero`: the same, `Root` fixed |
| `falcon_punch_link_air.json` | `FalconPunch_Air`: no root motion, no leg IK |
| `Player_Adult_04_Animation.anim.bfres(.zs)` | Copy of `_04`: 169 anims plus the 3 new ones (172). Each new anim has 295 bones and flags 0x2200, not looping. The `.zs` uses the game's dictionary. |
| `bfres_check.json` | Round-trip results: old anims unchanged; new anims match the JSON (rotation error ≤ 2e-5°); full-skeleton FK error ≤ 1e-6 m |
| `falcon_punch_link.glb` | Link's 327-bone skeleton with the 3 anims at 30 fps, sampled from the written bfres. Blender imports it as an armature. |
| `preview_{ground,air}.png` | Falcon (scaled) next to Link, Melee frames 0/20/40/52/56/80/100, side and front views |
| `preview_bfres_{FalconPunch,FalconPunch_Air}.png` | Poses sampled back from the bfres, including helper bones and the Pred_Ankle markers |
| `preview_fist.png`, `rotation_delta_report.json`, `helper_pool.npz` (cache) | |

## Checks

- **Poses:** every sampled pose matches Falcon's silhouette. At Melee f56 (anim 28), the right fist is fully extended along +Z at shoulder height. The wind-up (fist drawn back, left arm forward) and the lunge both read correctly.
- **Flips and discontinuities:**
  - The biggest per-frame rotations equal Falcon's own source deltas: Arm_2_R 147° at f52, Wrist_L 136° at f51, air Ankle_L 175° at f50. Melee snaps the punch in 1–2 frames; these are not retarget flips.
  - After the 30 fps resample, the largest Euler component step is under π.
- **bfres:** `tools/bfres_validate.py` gives bake OK for 172/172. Its 516 base-value mismatches are all in original anims and exist in the source file too.

## Known issues / open points

- Not tested in game yet. RESTBL and the larger `_04` (+560 KB raw) are unchecked.
- **Interpolation between keys:** curves are Euler Hermite with finite-difference slopes. If the game samples between keys (blending, rate ≠ 1), the 1–2 frame snaps interpolate per component. If that looks wobbly, switch those bones to quaternion curves.
- **Wrist twist:** the wrist twists up to about ±100° from rest during the wind-up (left hand open, palm forward). Game anims stay within about −76…+35°. The wrist assists take 72% of it, but some candy-wrapping at the wrist is possible.
- **Pose-space helpers:** skirt and belt are a nearest-neighbour approximation of the game's baked cloth. They have not been checked on the mesh, only as sticks.
- The face keeps the `Wait` expression; there is no shouting mouth for "PUNCH!".
- The air version has no foot contact (by design). Falcon's raw snaps are kept.
