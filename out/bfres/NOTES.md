# BFRES notes: OoT (Switch) adult Link skeleton and animations

## Tooling

All tools are in `tools/` and run from `/Games/TF-OOT/falconpunch`. They are pure Python and need no extra dependencies.

| file | purpose |
|---|---|
| `tools/bfres.py` | Library that reads and writes the format: header, `_RLT`, `_STR`, ResDic, FMDL/FSKL/bones, FSKA/BoneAnim/AnimCurve (including the v10.4 curve encoding), curve evaluation and sampling, curve builders, and `add_skeletal_anim()` |
| `tools/bfres_dump.py` | `skeleton`, `list`, `sample` and `info` dumps |
| `tools/bfres_add_anim.py` | CLI and functions `bfres_add_anim(in, out, name, json, fill=None, write_zs=False)` and `copy_anim(...)` |
| `tools/bfres_validate.py` | Decoder self-check: each curve's first key equals the base value, and `baked_size` matches the formula |
| `tools/test_bfres_write.py` | End-to-end test: round-trip, copy+modify, and custom-from-JSON |
| `tools/bfrestool/` | KillzXGaming BfresLibrary (vendored, netstandard2.0) and a small console app (`info` / `resave`). It is used only as an independent structural check. |

```sh
uv run python tools/bfres_dump.py skeleton unpacked/Player_Adult.Player_Adult.bfres out/bfres/link_adult_skeleton.json
uv run python tools/bfres_dump.py list out/bfres/player_adult_anims.txt unpacked/Player_Adult*.anim.bfres
uv run python tools/bfres_dump.py sample unpacked/Player_Adult_02_H_Animation.anim.bfres Hammer_Attack_Vertical_Advance out.json unpacked/Player_Adult.Player_Adult.bfres
uv run python tools/bfres_add_anim.py json IN.anim.bfres OUT.anim.bfres FalconPunch anim.json --fill unpacked/Player_Adult_02_H_Animation.anim.bfres:Hammer_Attack_Vertical_Advance --zs
uv run python tools/bfres_add_anim.py copy IN.anim.bfres OUT.anim.bfres NewName SRC.anim.bfres:SrcAnim --zs
uv run python tools/test_bfres_write.py
```

BfresLibrary needs an SDK. A .NET 9 SDK was installed (not system-wide) to `/tmp/opencode/dotnet`:

```sh
DOTNET_ROOT=/tmp/opencode/dotnet /tmp/opencode/dotnet/dotnet build -c Release tools/bfrestool/App
dotnet tools/bfrestool/App/bin/Release/net9.0/bfrestool.dll info file.bfres
```

BfresLibrary (2026-10 master) **parses the structure** of these files but **does not understand the v10.4 curve encoding**: its curve scale and offset are wrong. Its `resave` is not byte-identical either (the file grows from 516 KB to 775 KB). Do not use it for writing.

## Format version

- Header bytes 8..11 are `00 04 0A 00`, which is **FRES v10.4.0**. TotK was 10.0. BfresLibrary prints this as "10.0.4.0".
- The layout matches the 10.0 layout (nn::g3d2) except for the **AnimCurve** (see below).
- The header is 0xF0 bytes:
  - 0x20 name ptr
  - 0x28/0x30 model array/dict
  - 0x38..0x57 reserved
  - 0x58/0x60 FSKA array/dict
  - 0x68/0x70 material anims
  - …
  - 0xB8/0xC0 external-file array/dict
  - 0xD0 string pool ptr
  - 0xD8 string pool size
  - 0xDC u16 counts: model, ?, ?, skel, mat, bonevis, shape, scene, external
  - 0xEE external flags
- Header 0x16 holds the first-block offset as a **u16, truncated** to the low 16 bits of the `_STR` offset. 0x18 is the `_RLT` offset and 0x1C the file size. 0x10 is the filename offset, which points at the characters and is not relocated.
- All **string pointers point at the u16 length prefix**. The `_STR` block layout is: magic, next=0, size u32 (to `_RLT`), pad, count u32 (excluding the leading empty string), then the empty string at `+0x14`. The header pointer at 0xD0 points at that empty string. Strings are not sorted.
- `_RLT` has 6 sections. In anim files only section 0 (offset 0 to the end of `_STR`) has entries. Every pointer in the file is listed, so the writer shifts pointers generically.
  - `tools/bfres.py:encode_reloc_entries` reproduces Nintendo's entry grouping **exactly**: 251/251 and 106,880/106,880 entries.
  - The model file uses several sections and is not supported for writing. We don't need to write it.
- The ResDic Patricia-trie builder (`build_dict_nodes`) reproduces the game's dicts exactly, including the 568-entry one.
- Anim files have **no memory pool, no GPU buffer and no alignment above 8**. Anim data sits between the FSKA dict and `_STR`. `_RLT` is aligned to 8, not 0x100.
- The `_01`/`_02`/… files have one external file, `LoadAnimEventSet.flag`, which is an empty marker. Its pointers are shifted correctly by the writer.
- Model file: FMDL is 0x78 bytes and the skeleton pointer is at FMDL+0x18. Bone structs are 0x58 bytes: name, user-data array/dict, 8 reserved bytes, index, parent, smooth, rigid, billboard, numUD, flags, scale(3), rot(4), trans(3).

## Skeleton (`link_adult_skeleton.json`)

- 327 bones. Skeleton flags are 0x1200: **Euler XYZ in radians**, Maya scale mode.
- Rotation is stored as a vec4 (x,y,z,w=1).
- Local matrix is `T * R * S`, with `R = Rz*Ry*Rx` (column vectors, X applied first). This was verified by FK: the spine goes up, the nose is at +Z, and the head is at about 1.42 m.
- Units are meters, Y up, character facing +Z. Link's left is +X.
- Most bones have bit 23 (segment scale compensate) set.
- The mirror table pointer is 0 for this skeleton.
- Key bones:
  - Root(0) → Skl_Root(3, y=0.906) → Spine_1(4) → Spine_2(6)
  - Spine_2 → Clavicle_L(7) → Arm_1_L(8) → Arm_2_L(9) → Wrist_L(13) → fingers Finger_[A-E]_[1-3]_L, Weapon_L(18)
  - Spine_2 → Clavicle_R(54) → Arm_1_R(55) → Arm_2_R(56) → Wrist_R(61) → Weapon_R(66)
  - Spine_2 → Neck(102) → Head(103) → Head_2(104) → Face_Root(107)
  - Skl_Root → Waist(233) → Leg_1_L(234) → Leg_2_L(235) → Ankle_L(236) → Toe_L; the same chain for _R
  - Weapon_Root
  - `Ph_*` bones are physics, helper or twist bones.
- The arms are in an A-pose at rest: Arm_1_L is at (0.174, 1.226) and Wrist_L at (0.515, 0.885).

## Animations (`player_adult_anims.txt`)

- Each skeletal anim is listed with: frames, flags, bone count, curve count, quaternion bones, and the animated bones.
- Files:
  - `Player_Adult.anim.bfres`: 1 anim (`Player_Adult_1st`) plus 1 material anim
  - `_01`: 568 anims
  - `_02`: 475
  - `_02_H`: 525
  - `_03`: 541
  - `_04`: 169
  - `_Cba`: 652
  - `_Demo`: 172
- **The hammer attacks are in `Player_Adult_02_H_Animation`**:
  - `Hammer_Attack_Vertical_Advance` (20 frames) and `_AdvanceZero`
  - `Hammer_Attack_Left1_Advance` (60 frames) and `Right1_Advance` (54 frames)
  - `Hammer_Attack_Vertical_After*`, `Hammer_Attack_Jump*`, …
- The sword attacks (`Sword_Attack_*`, 91 anims) are in `_03`. The `LSword_Attack_*` (Biggoron) anims are in `_02`.
- Frame rate is presumably 30 fps (not verified).
- **Binding is by bone name.** Every FSKA has a bind-index table that is all 0xFFFF, and the bind-skeleton pointer is 0. The runtime therefore binds anims to the model skeleton by name.
  - Anims can contain any subset of bones. Game anims usually list 295 bones (all non-face-detail bones); `Voice_*` anims list 66.
- Which files are loaded: `Pack/Actor/Player_Adult.pack.zs` → `Component/AnimationParam/Player.engine__component__AnimationParam.bgyml` lists `AnimationResources`:
  - Player_Adult_Demo_Animation, _01, _02, _03, _04, _Cba, Player_Dark_Animation, _02_H
  - Anims are looked up by name across these files. `Player_Adult.anim.bfres` (the "1st" anim) is **not** in that list.

### FSKA (0x50 bytes)

| offset | field |
|---|---|
| 0x00 | magic |
| 0x04 | flags |
| 0x08 | name |
| 0x10 | path ("") |
| 0x18 | skeleton (0) |
| 0x20 | bind table |
| 0x28 | bone anim array |
| 0x30/0x38 | user data (none) |
| 0x40 | frame_count |
| 0x44 | num_curves |
| 0x48 | baked_size |
| 0x4C | numBoneAnim |
| 0x4E | numUserData |

FSKA flags:

- `0x2200` / `0x2204`: per-bone rotation mode, Maya scale, plus loop bit 2.
- `0x1200`: whole anim is Euler (used only by `Player_Adult_1st`).
- `baked_size = Σ align8(4*(end-start+1) + 28)` over the curves. This matches every anim checked: all 695 anims in `Player_Adult`, `_02_H` and `_04`.

### BoneAnim (0x38 bytes)

- Layout: name, curves pointer, base-data pointer, two u64 (0), flags u32, beginRotate=3, beginTranslate=6, numCurves, beginBaseTranslate=7, beginCurve (running index), pad.
- Flags:
  - bits 3/4/5: base S/R/T present. Game anims always store all three: S(3f), R(4f), T(3f).
  - bits 6..15: curve present for sx sy sz rx ry rz rw tx ty tz.
  - **bit 20 (0x100000): the bone uses a quaternion rotation.** The base rotate is xyzw, and there is at most one quaternion curve, flagged as `rw`, target 0x20. Otherwise the bone is Euler (base = x,y,z,1.0; curves rx/ry/rz). The game uses quaternions only for a few bones, such as Clavicle_L/R.
  - bit 23: segment scale compensate.
  - bits 24..27: base scale uniform / volume one / rotate zero / translate zero.
- **Base values are the frame-0 pose.** Curves overwrite components. Values are **absolute local transforms**, not relative to the rest pose. For example, Skl_Root t=(−0.065, 0.744, −0.071) versus rest (0, 0.906, 0).
- **Root motion**: the `Root` bone translation carries the locomotion. `Hammer_Attack_Vertical_Advance` moves Root tz from 0 to 1.2 m; the `*AdvanceZero` variants keep it at 0. `Weapon_Root` is a static (0, −0.906, 0).

### AnimCurve (0x30 bytes): v10.4 encoding

The layout is `frames ptr, keys ptr, flags u16, numKeys u16, target u32, start f32, end f32, frameScale f32, scale f32, offset f32, pad`.

Old 10.0 layout: `start, end, scale, offset, delta`.

Every curve in the game sets **flag bit 14 (0x4000)**, meaning hermite value+slope keys:

- **bits 0-1, frame type**:
  - 2 = u8
  - 1 = 16-bit fixed point (frame = s16/32)
  - 0 = f32
- **bits 2-3, key type**:
  - 0 = f32
  - 1 = u16, quantized
  - 2 = u8, quantized
- **bit 10 (0x400)**: frames = raw × frameScale (header 0x20). Seen with 2.0, 4.0, 8.0, and 1/32 for unsigned 16-bit frames. Otherwise header 0x20 is 0.
- **bit 11 (0x800)**: quantized. The key data starts with `slopeScale f32, slopeOffset f32`, followed by `numKeys × (valueQ, slopeQ)` unsigned ints:
  - `value = offset + scale*valueQ`
  - `slope = slopeOffset + slopeScale*slopeQ`
- **f32 keys (bit 11 clear)**: `numKeys × (value f32, slope f32)`. The header scale and offset are 0 and unused.
- **bit 7 (0x80)**: quaternion curve. Keys are `numKeys × (x,y,z,w) f32`, slerped between keys, with no slopes.
- **Interpolation** is cubic Hermite between consecutive keys. Slopes are **per frame**, so the tangent is `slope × (f1−f0)`.
  - Duplicate frame numbers are common: two keys at the same frame have the same value but different slopes, which is a tangent break.
  - Use the last key whose frame ≤ f.
  - Outside the key range, values are clamped.
- Validation: on 295k curves, `curve(start)` equals the base value to within quantization (≤0.0034 rad) or 2π.
- Flag combinations seen in the game: 0x4805, 0x4806, 0x4809, 0x480a, 0x4c05, 0x4c06, 0x4c09, 0x4c0a, 0x4002, 0x4081, 0x4082, 0x4481.

The writer emits **0x4002** (u8 frames, f32 hermite) and **0x4082** (u8 frames, f32 quaternion). If any frame is over 255 it uses 0x4001/0x4081 (16-bit fixed-point frames). Both combinations occur in game files.

The custom-anim path computes slopes by finite differences (Catmull-Rom). It reproduces the source exactly at integer frames; between frames it can differ by up to about 0.1 rad on very fast arm swings. Pass explicit slopes (`make_hermite_curve(..., slopes=...)`) or add more keys if needed.

## Writing (`add_skeletal_anim`)

The writer works as follows:

1. Insert the new anim's bind table, bone anims, base data, curves and keys just before `_STR`.
2. Insert the 0x50-byte FSKA header at the end of the FSKA array.
3. Grow the FSKA dict by one node and rebuild it with the Nintendo trie builder.
4. Append new strings to `_STR`.
5. Bump the anim count (header 0xE2).
6. Rebuild the `_RLT` and the header sizes.

Every insertion is a multiple of 8, and every pointer listed in `_RLT` that targets data at or after the insertion point is shifted.

- Existing anims keep their indices; the new anim is last.
- Results:
  - **Unchanged round trip is byte-identical**: tested on `Player_Adult.anim`, `_01` (51 MB) and `_04`.
  - `out/bfres/test_added_anim.bfres` (+`.zs`): `Player_Adult.anim.bfres` plus `FalconPunch_Test`, a copy of `Hammer_Attack_Vertical_Advance` with Root tz doubled.
  - `out/bfres/test_custom_anim.bfres` (+`.zs`): `FalconPunch_Custom`, built from per-frame TRS JSON (`test_custom_anim_input.json`), with the other bones filled from the template.
- Both files reparse with our parser and with BfresLibrary. Adding to `_04` (26 MB) takes about 1 s and also reparses and validates.
- `.zs` files use `zs.zsdic` (dict id 1), the same as the originals.

## Pitfalls / to-do for getting it in game

- **Which file to add to**: the anim must go into a file listed in `AnimationParam` (`_01`…`_04`, `_Cba`, `_02_H`, `_Demo`), not into `Player_Adult.anim.bfres`.
  - `_02_H` holds the hammer anims. `_04` is the smallest regular one (5.5 MB .zs).
  - Unknown: whether `_02_H` is loaded only while the hammer is equipped. If the punch should work all the time, `_01`/`_04` are safer.
- **RESTBL**: `System/Resource/ResourceSizeTable.Product.111.Nin_Ounce_NVN2.rsizetable.zs` exists. A bigger anim file probably needs its RESTBL entry raised (TotK behaviour), otherwise the game may crash or refuse to load it. This has not been handled yet.
- The ASB (`Player_Adult.root.asb`) references anims by name (`Hammer_Attack_Vertical_Advance` appears in it). Hooking up the new name is the AS/ASB side's job.
- Bones missing from an anim are not driven by that anim. Use `--fill` to supply the full 295-bone set so leftover pose layers do not leak in.
- Euler angles in game data are not wrapped (values such as 9.97 rad occur). The writer uses whatever values you give it, so unwrap the Euler sequences to avoid 2π jumps between keys. Quaternions are hemisphere-fixed automatically.
- Do not use BfresLibrary to save these files: it gets the curve encoding wrong and changes the layout.
