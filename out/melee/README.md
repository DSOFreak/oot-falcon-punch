# Melee Captain Falcon: Falcon Punch extraction

Source: Super Smash Bros. Melee NTSC-U 1.02 (GALE01). Files: `PlCa.dat` (fighter data), `PlCaAJ.dat` (animations), `PlCaNr.dat` (neutral-costume model), and `PlCo.dat` (common fighter data, for the per-fighter joint ↔ common-part table).

To regenerate everything: `uv run python tools/melee_anim.py`. To check the keyframe decoder: `uv run python tools/verify_fobj.py`.

## Files

| file | contents |
|---|---|
| `falcon_punch_ground.json` | Ground Falcon Punch (action 301 `PlyCaptain5K_Share_ACTION_SpecialN_figatree`). It has 101 samples, for anim frames 0‥100. |
| `falcon_punch_air.json` | Air Falcon Punch (action 302 `PlyCaptain5K_Share_ACTION_SpecialAirN_figatree`). It has 101 samples. |
| `falcon_punch_{ground,air}.glb` | Skeleton-only glTF: 63 joint nodes plus a dummy skin, so Blender imports it as an armature. One animation is sampled at 60 fps with linear interpolation. Units are Melee units, and no conversion is applied. |
| `bone_map.tsv` | Joint index, name, parent, common-part id, decomp enum name and rest world position. |
| `preview_{ground,air}.png` | Stick figures at frames 0/20/40/52/56/100, in side and front views. |
| `preview_{ground,air}_strip.png` | Side view every 10 frames. |
| `falcon_punch_extract_summary.json` | Raw dump: action-table entries, per-joint track types, and the fully decoded subaction event list. |
| `falcon_punch_facts.md` | Gameplay facts: frames, hitboxes, effects and sounds. |

## JSON layout

```
{ fps: 60, frame_count: 101,
  joints: [{index, name, parent, common_part, decomp_enum_name, name_note,
            jobj_flags, animated_tracks, rest:{t,r,s}, rest_world_pos}],
  frames: [[{t:[x,y,z], r:[rx,ry,rz], s:[sx,sy,sz]} per joint] per frame] }
```

* `frames[k]` is the **local** TRS of every joint after the k-th `HSD_AObjInterpretAnim` step (anim frame k). Animated channels replace the rest values. Channels without a track keep the rest value, because `ftAnim_8006FA58` resets the joints to the model's `HSD_Joint` values before the tracks are bound.
* Game timing: `ftCa_SpecialN_Enter` / `ftCa_SpecialAirN_Enter` call `Fighter_ChangeMotionState`, which evaluates frame 0 and runs the script. They then call `ftAnim_8006EBA4`, which advances to frame 1 and runs the script again, all in the same tick. So 1-based game frame g of the move shows anim frame g. Frame 0 is never displayed; it is the blend-in pose. Frame 100 is the last displayed frame, after which the action ends.
* Joint order is the depth-first order of the `HSD_Joint` tree: node, then child (unless `JOBJ_INSTANCE`), then next sibling. This is exactly the order used by `ftParts_SetupParts` and by `ftAnim_8006F4C8` when it consumes the FigaTree `nodes[]` counts. Captain has no skipped parts (the `PlCo` +0x14 table is empty for kind 2), so track-node *i* belongs to joint *i*. There are 63 joints, which equals `parts_num`.

## Rotation / matrix convention (jobj.c / mtx.c)

`HSD_JObjMakeMatrix` → `HSD_MtxSRT(m, scale, rotate, translate, parent_scl)`:

```
local  M = T · Rz(rz) · Ry(ry) · Rx(rx) · S        (column vectors)
world  W = W_parent · M                            (PSMTXConcat(parent->mtx, mtx))
```

The rotation is Euler XYZ in radians. X is applied first, then Y, then Z, all about fixed parent axes. This is extrinsic XYZ, the same as Blender's `XYZ` Euler mode. `HSD_MkRotationMtx` gives the identical matrix. When the parent has a non-classical accumulated scale (`jobj->scl`), `HSD_MtxSRT` applies a compensation term, and it is implemented in `world_matrices()`. All Captain rest scales are 1, so it has no effect here. The only animated scale is `SCAX` on a head leaf joint.

The glTF quaternions are `qz·qy·qx` of the same Euler angles. The tool checks that world positions from the glTF TRS match the HSD FK to 1e-14.

Model space has +Y up, the character facing +Z, and the character's right side at −X. In game, `TopN` gets `rotY = facing_dir·π/2` (`fighter.c`, `ftPartSetRotY(fp, 0, M_PI_2*facing_dir)`), and the fighter is scaled by `model_scaling` = **0.97** for Captain (`ftCo_DatAttrs` +0x8C).

## Root motion

* **Ground** action flags are `0x82000002`, so `x594_b0` is set. Each frame `ftAnim_8006E054` reads TransN's translation, converts the delta into ground velocity (`x6A4_transNOffset`), and **zeroes TransN visually**. The JSON/GLB keep the raw TransN `TRAZ` channel: about 0 until frame ~50, then a lunge to +12.7 units around frames 53–60. Drop it, or turn it into root motion, depending on the target engine.
* **Air** action flags are `0x00000002`. There is no root-motion flag, and the air TransN track stays at 0. Air movement comes from `ftCa_SpecialAirN_IASA`/`_Phys` (velocity set at frame 50 from `specialn_vel_x` = 1.95 and `specialn_vel_mul` = 0.92).

## Decoding provenance (decomp file:function)

* Archive: `sysdolphin/baselib/archive.c:HSD_ArchiveParse`. It has a 0x20 header, data, reloc offsets, public and extern symbols, then strings. Pointers are data-relative.
* Action table: `ftData` +0xC is an array of `Fighter_WaitAnimData` (0x18 bytes: symbol, AJ offset, AJ size, script, flags), indexed by submotion id (`ftData_80085A14`/`ftData_80085CD8`). Submotion = `ftCo_SM_Count` (295) + 6/7 → 301/302 (`ftCaptain/forward.h`). The AJ slice is its own HSD archive whose public symbol is the action name (`HSD_ArchiveParse` + `HSD_ArchiveGetPublicAs(FigaTree, …)`).
* FigaTree / FigaTrack: `lb/lbanim.h`. A FigaTree is {type, flags, frames, s8 nodes[] terminated by −1, FigaTrack tracks[]}. A FigaTrack is 0xC bytes: u16 length, u16 startframe, u8 type, frac_value, frac_slope, pad, data pointer. Tracks are bound by `lbAnim_8001E6D8` (AObj flags = tree.flags, rewind 0, end = tree.frames, and `JOBJ_CLASSICAL_SCALE` = type & 1).
* Keys: a literal port of `sysdolphin/baselib/fobj.c` (`HSD_FObjInterpretAnim`, `FObjLoadData`, `FObjAnimCON/Linear/SPL0/SPL/SLP/Key`, `FObjLoadWait`, `FObjUpdateAnim`, `parseFloat`, `parsePackInfo`, `parseWait`) and `aobj.c` (`HSD_AObjReqAnim`, `HSD_AObjInterpretAnim`, with the first-play rate of 0).
  * Opcodes: CON 1, LIN 2, SPL0 3, SPL 4, SLP 5, KEY 6.
  * Value format: `frac & 0xE0` selects float/s16/u16/s8/u8, and the value is divided by `1 << (frac & 0x1F)`. Values are **little-endian** byte order (`parseFloat`).
  * Pack count: `((b>>4)&7)+1` plus 7-bit continuation bytes at shift 3.
  * Wait: 7-bit varint.
  * Hermite: `spline.c:splGetHelmite`.
  * Computation is in float32 like the game.
  * These Falcon Punch tracks use ops 1–5 and all five value formats.
  * `tools/verify_fobj.py` re-decodes every track with a separate segment-based decoder and matches the state machine to within 2.5e-7.
* Channel application: `jobj.c:JObjUpdateFunc`. Types 1–3 are ROTX/Y/Z, 5–7 TRAX/Y/Z, and 8–10 SCAX/Y/Z, with |scale| clamped to ≥ 1e-3.

## Bone naming

Melee files store **no joint names**. Names come from the per-fighter part table in `PlCo.dat` (`ftLoadCommonData` +0x10 → `FighterPartsTable[Ft_Kind_Captain]` {joint_to_part, part_to_joint, parts_num}). It maps each Captain joint to a *common part id*.

The common-part ids are named with m-ex's `FtCommonBoneNames` enum (MexTK `fighter.h`). The decomp's `enum Fighter_Part` (`melee/ft/forward.h`) is only right for ids 0–15. It lacks `WaistN2` and mislabels the HaveN item bones, so the decomp names from id 16 onward are shifted. For example, decomp `FtPart_RThumbNb` (49) is really RHaveN, the item-hold bone. The decomp name is kept in the `decomp_enum_name` column so code can be cross-referenced.

The m-ex names fit the Captain geometry exactly:
* JA joints carry the static −90° offsets (flags 0x8).
* JA/J pairs share a position.
* HandN is the wrist with five finger chains.
* ThrowN sits at ground level.
* RHaveN has the item-attach orientation and is the joint the Falcon effect is attached to.

Ten Captain-only joints have no common id. They are given descriptive `Ca_*` names, which are guesses from position and hierarchy only.

| idx | name | parent | | idx | name | parent |
|---|---|---|---|---|---|---|
| 0 | TopN | – | | 32 | L4thNa | 25 |
| 1 | TransN | 0 | | 33 | L4thNb | 32 |
| 2 | XRotN | 1 | | 34 | Ca_LHandAuxN* | 25 |
| 3 | YRotN | 2 | | 35 | LThumbNa | 25 |
| 4 | HipN | 3 | | 36 | LThumbNb | 35 |
| 5 | Ca_HipSideN* (mesh) | 4 | | 37 | Ca_LShoulderPadN* | 21 |
| 6 | LLegJA | 4 | | 38 | NeckN | 19 |
| 7 | LLegJ | 6 | | 39 | HeadN | 38 |
| 8 | LKneeJ | 7 | | 40 | Ca_HeadFrontN_a* | 39 |
| 9 | LFootJA | 8 | | 41 | Ca_HeadFrontN_b* | 39 |
| 10 | LFootJ | 9 | | 42 | RShoulderN | 19 |
| 11 | Ca_LToeN* | 10 | | 43 | Ca_RShoulderMeshN* (mesh) | 42 |
| 12 | RLegJA | 4 | | 44 | RShoulderJA | 42 |
| 13 | RLegJ | 12 | | 45 | RShoulderJ (upper arm) | 44 |
| 14 | RKneeJ | 13 | | 46 | RArmJ (elbow/forearm) | 45 |
| 15 | RFootJA | 14 | | 47 | RHandN (wrist) | 46 |
| 16 | RFootJ | 15 | | 48–55 | R1stNa…R4thNb (fingers) | 47/… |
| 17 | Ca_RToeN* | 16 | | 56 | Ca_RHandAuxN* | 47 |
| 18 | WaistN2 | 4 | | 57 | RHaveN (item / effect anchor) | 47 |
| 19 | BustN (chest) | 18 | | 58 | RThumbNa | 47 |
| 20 | Ca_CollarN* | 19 | | 59 | RThumbNb | 58 |
| 21 | LShoulderN (clavicle) | 19 | | 60 | Ca_RShoulderPadN* | 42 |
| 22 | LShoulderJA | 21 | | 61 | ThrowN | 3 |
| 23 | LShoulderJ | 22 | | 62 | Extra (decomp part 0x35) | 0 |
| 24 | LArmJ | 23 | | | | |
| 25 | LHandN | 24 | | | | |
| 26–31 | L1stNa…L3rdNb | 25/… | | | | |

Captain has no WaistN (common id 5) and no LHaveN (id 31). See `bone_map.tsv` for the complete list with rest world positions.

For retargeting, the useful chains are:
* Spine: HipN → WaistN2 → BustN → NeckN → HeadN.
* Arms: L/RShoulderN (clavicle) → JA (fixed offset) → ShoulderJ (upper arm) → ArmJ (forearm) → HandN.
* Legs: L/RLegJA → LegJ (thigh) → KneeJ → FootJA → FootJ → toe.
* XRotN/YRotN are animated body-root helpers that sit above HipN.
