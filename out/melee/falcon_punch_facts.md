# Falcon Punch: gameplay facts (Melee NTSC-U 1.02, decoded from the disc data + decomp)

These facts come from the subaction scripts in `PlCa.dat` (`ftDataCaptain` +0xC action table, entries 301/302, script pointer at +0xC). The scripts were decoded with the generic commands in `lb/lbcommand.c` (`Command_00..09`) and the fighter command table in `ft/ftaction.c` (`ftAction_803C06E8`, lengths `ftAction_803C0870`).

Frame timing was simulated with the timer logic of `ftAction_80073240`:
* timer −= 1 per run;
* sync timer: `timer += n`;
* async timer: `timer = n − frame`;
* commands run while timer ≤ 0.

"Frame" below means the **1-based game frame of the action**, which equals the animation frame (see README, Timing). Commands scheduled for anim frame 0 also happen on game frame 1. Full decoded data is in `falcon_punch_extract_summary.json` → `actions.{ground,air}.events`.

## Totals

| | Ground `SpecialN` (action 301) | Air `SpecialAirN` (action 302) |
|---|---|---|
| figatree | `PlyCaptain5K_Share_ACTION_SpecialN_figatree` (PlCaAJ.dat @0x7FD60, 14016 B) | `PlyCaptain5K_Share_ACTION_SpecialAirN_figatree` (@0x83420, 14711 B) |
| anim length | 100 frames (end frame 100.0) | 100 frames |
| ends | Anim end → `ft_8008A2BC` (Wait), so **100 frames** total | Anim end → `ftCo_Fall_Enter`, a normal Fall, not special fall |
| interrupt | The script sets allow-interrupt at f65, but `ftCa_SpecialN_IASA` is empty. Nothing reads it, so in effect there is no early interrupt. | `ftCa_SpecialAirN_IASA` only applies the f50 lunge velocity |
| action flags | `0x82000002`: TransN root motion converted to ground velocity | `0x00000002` |
| ground/air switch | Leaving the ground → SpecialAirN, keeping the frame (`ftCa_SpecialN_Coll`) | Landing → SpecialN, keeping the frame |

## Hitboxes (`ftAction_8007121C`, opcode 0x0B)

* **Active: frames 52–56** (5 frames). Created at f52 and cleared by "clear all hitboxes" (opcode 0x10) at f57.
* Ground and air use the same timing.
* All hitboxes:
  * angle **361** (Sakurai angle)
  * KBG **102**
  * WDSK 0
  * element **fire** (1)
  * shield damage +0
  * clank and rebound bits set
  * hit grounded and aerial targets
  * hit group 0
* Bone indices are **raw Captain joint indices** (`use_common_bone_ids` = 0). Offsets are in the bone's local frame, in Melee units, assigned as decomp `b_offset.(x,y,z)`.

| id | bone | dmg | radius (ground / air) | offset (x,y,z) | BKB ground / air | hit-SFX severity/kind |
|---|---|---|---|---|---|---|
| 0 | 45 RShoulderJ (upper arm) | **27** | 3.906 / 5.273 | (2.344, 0, 0) | 30 / 40 | 2 / 2 |
| 1 | 45 RShoulderJ | **25** | 3.516 / 4.688 | (−2.344, 0, 0) | 30 / 40 | 2 / 2 |
| 2 | 47 RHandN (wrist) | **23** | 4.883 / 4.883 | (3.906, 0, 0) | 30 / 40 | 1 / 2 |

These damage values are the base values in the script. `ftColl_8007ABD0` then applies fighter scale, `ftCo_800DEEB8` and stale-move scaling.

Hitbox world centres relative to the fighter origin, computed from the exported pose with TransN root motion removed (model space: +Z forward, +Y up):

* ground f53–56: id0 ≈ (2.6, 9.9, 12.1), id1 ≈ (3.3, 9.9, 7.4), id2 ≈ (2.7, 9.9, 20.3)
* ground f52, while the arm is still swinging: id0 (−2.6, 10.2, 4.0), id1 (−1.2, 10.8, 8.5), id2 (−2.9, 9.7, 10.5)
* air f53–56: id0 (2.2, 10.3, 12.1), id1 (2.5, 10.6, 7.4), id2 (3.2, 8.0, 19.5)

## Timeline (ground; air is identical except where noted)

| frame | command | meaning |
|---|---|---|
| 1 (anim 0) | 0x2E color anim (`ftCo_800BFFD0`, id 71) | Colour overlay on the fighter during the charge |
| 1 (anim 0) | 0x11 sound, behaviour 2 (`ft_800881D8` = voice channel) **sfx 60025** | **"Falcon…" voice** |
| 1 (anim 0) | 0x2B rumble (`ftCommon_8007EBAC`, 11) | |
| 1 (anim 1) | 0x15 → `throw_flags_b1` | Read by `ftCa_SpecialN_Phys`/`doPhys` in the same tick: **`efSync_Spawn(1167, gobj, parts[TopN], parts[57])`** spawns the **falcon effect** |
| 10 | 0x0A spawn GFX **1094** on joint 0 (TopN), offset fields (0, 7.81, −1.95) | `efAsync` case 0x446: common particle generator 0x1B (EfCoData), lifetime 22 |
| 50 (air only) | 0x13 cmd_var0 = 1, cmd_var1 = 1 | `ftCa_SpecialAirN_IASA`: forward lunge velocity `1.95·(cos a, sin a)`, where `a` = stick-Y angle up to ±30° (`specialn_*` attrs 0.125/0.625/30/1.95/0.92). Phys case 1 multiplies velocity by 0.92 each frame. |
| 52 | 0x34 `ft_8008A1B8(1)` | Sets `fp->x221C` flags |
| 52 | 3 × hitbox (above) | |
| 52 | 0x11 sound, behaviour 2 (voice) **sfx 60052** | **"PUNCH!" voice** |
| 52 | 0x11 sound, behaviour 0 **sfx 60079** | Punch / fire whoosh SE (captain bank) |
| 52 | 0x11 sound, behaviour 0 **sfx 116** | Common SE (main.ssm bank) |
| 52 | 0x0A spawn GFX **1023** on TopN | `efAsync` case 0x3FF: common effect 5 (EfCoData) at the fighter position |
| 52 | 0x2B rumble (14) | |
| 57 | 0x10 clear all hitboxes | |
| 65 | 0x15 → `throw_flags_b1` again | `x2219_b0` is already set, so `ftCommon_8007DB24` clears the flag and calls **`efLib_DestroyAll`**, which removes the falcon effect |
| 65 | 0x17 allow interrupt (ground) / 0x13 cmd_var1 = 2 (air → normal air drift `ft_80084DB0`) | |
| 77 (ground) | 0x34 `ft_8008A1B8(3)`, then end of script | |

Ganondorf's Warlock Punch shares this code (`ftcaptainspecialn.c`). For Captain, the wind effect inline returns immediately.

## Falcon effect assets (for later use)

* `efSync_Spawn(1167)` → `ef/efalt.c` case 0x48F:
  * `efLib_Create_Attach_Scale_FacingDir(0xFA0, gobj, TopN)`
  * `next = …(0xFA1, gobj, joint 57)`
* Effect id / 1000 = bank 4 → `efAsync_DatEntries[4]` = **`EfCaData.dat`**, symbol **`effCaptainDataTable`** (`ef/efasync.c`). Index = id % 1000.
* The table is `{cmd_bank*, tex_bank*, EF_EffectDesc descs[]}`. Each `EF_EffectDesc` (0x14 bytes) is `{f32 lifetime; StaticModelDesc{HSD_Joint*, AnimJoint*, MatAnimJoint*, ShapeAnimJoint*}}`, so these effects are **animated JObj models**, not particles:
  * desc 0 (gfx 4000, attached to TopN, rotated by facing dir): lifetime 100. Data offsets: joint 0x21888, animjoint 0x22084, matanim 0x22B3C. This is most likely the falcon bird body.
  * desc 1 (gfx 4001, attached to joint 57 RHaveN = right fist): lifetime 90.1. Joint 0x23A88, animjoint 0x249E4. This is most likely the fist flame.
  * desc 2 and desc 3 belong to other Captain moves.
* GFX 1094 and 1023 are common effects from `EfCoData.dat` (`effCommonDataTable`).

## Sounds / voice (for later use)

* SFX id → sound bank is given by the range table `lbAudioAx_80023130` (`s32_arr_803BB8D4`). 0xEA60–0xEAB4 (60000–60084) is bank 6 = **`captain.ssm`**, and 0–0x20F is bank 0 = `main.ssm`.
* Captain-bank ids, relative to 60000:
  * "Falcon…" = **60025** (rel 25)
  * "PUNCH!" = **60052** (rel 52)
  * fire/swing SE = **60079** (rel 79)
* Common SE: **116** (main.ssm).
* Behaviour 2 goes to `ft_800881D8`, which plays on the per-player voice channel and stops the previous voice. Behaviour 0 goes to `ft_PlaySFX`.
* On the NTSC-U disc, English voices load from **`/audio/us/captain.ssm`** with the script table **`/audio/us/smash2.sem`** (`lbAudioAx` `setup_audio_lang`, `str_audio_us = "/audio/us/"`). The JP set is in `/audio/captain.ssm` + `/audio/smash2.sem`.
* Turning an SFX id into a DSP-ADPCM sample index inside the .ssm goes through the `.sem` sound script. It is not simply the relative id.
* `offsets_arr_803BC6A4` maps 60079 to 330051, the Kirby-hat (`kirbytm.ssm`) copy.
