# Handover: Falcon Punch item for Link (Triforce OoT)

Snapshot of 2026-11-22. Repository: https://github.com/DSOFreak/oot-falcon-punch (public, branch `main`).
Working directory: `/Games/TF-OOT/falconpunch`.

## What the user wants

- A **real new item** for adult Link that does Captain Falcon's **Falcon Punch**, using the animation extracted
  from the user's own Super Smash Bros. Melee disc.
- The user chose **option B**: a genuinely new `AssignableItem` enum value (`FalconPunch`). That rules out reusing
  a dead slot (option A) and replacing the Megaton Hammer (option C). They know it is high-risk and needs a lot of
  reverse engineering.
- **Commit and push progress automatically** to the repo after each meaningful step.
- **Never commit game data or game-derived output.** `.gitignore` already covers `melee/`, `unpacked/`, `liftwork/`,
  `triforce-appimage/`, `out/**` (except `*.md` and `*.tsv`), `*.bfres`, `*.zs`, `*.dat` and `*.glb`.
- Python: always use `uv` (`uv run python …`, `uv pip install …`). The venv is at `.venv`.
- Root: use `pkexec`, never `sudo`, and only when it's really needed.

## Environment and key paths

| Path | What |
|---|---|
| `/Games/TF-OOT/Hookshot/` | The built game folder (Triforce v0.5.1). **Read-only, don't modify.** `romfs/` is the game data, `.triforce_exefs/main` the original ARM64 code (decompressed NSO), `image.bin` the Eden-layout image at `0x80000000`, `bin/triforce` the translated x86-64 game (functions named `f_<guest addr>`), `triforce_log.txt` the run log. |
| `/Games/TF-OOT/Triforce-v0.5.1-linux-test-x86_64.AppImage` | The builder. `launch.sh` runs the game. |
| `falconpunch/triforce-appimage/` | The extracted AppImage. It includes the **builder source**: `usr/share/hookshot/{nx2,host,gpu,…}` and its Python at `usr/python/bin/python3`. `nx2/oot_patches.py` shows how Triforce patches the lifted C. `host/oot_sprint.c` is an example of a hand-written hook (Link class `0x84b6dfc0`, actor manager, and so on). The readme is `usr/share/hookshot/readme.md`, with a Mods section. |
| `falconpunch/liftwork/gen/` | Lifted C of the whole game (82 files, about 1.5 GB). Made with `OOT_EXEFS=/Games/TF-OOT/Hookshot/.triforce_exefs OOT_WORK=/Games/TF-OOT/falconpunch/liftwork ../../python/bin/python3 -I nx2/lift.py --write`, run from `triforce-appimage/usr/share/hookshot`; takes about 140 s. Use it to grep functions, for example `grep -n "^void f_82d833b0" liftwork/gen/*.c`. |
| `~/.cache/triforce-build/objcache` | The builder's object cache: a rebuild only recompiles the chunks that changed. The full build took 30 min, with compiling 26 min of that. |
| `/home/lm/projects/games/melee/disc/GALE01.ciso` | Melee disc image (NTSC-U 1.02). |
| `/home/lm/projects/decomp/refs/melee` | doldecomp/melee source. |
| `/home/lm/projects/games/melee/melee-pc` | Melee PC port. |
| `/tmp/opencode/main_strings.txt` | `strings -n 4` of `main`. Temporary; `tools/gdnames.py` reads it. Regenerate if it's gone. |
| `/tmp/opencode/dotnet` | .NET 9 SDK for `tools/bfrestool` (optional cross-check only). Temporary. |

## Facts established

- **The Triforce project:** about 99.99% of the game code is *machine-translated* ARM64 → C (about 295k `f_<addr>`
  functions, 465 MB). It is not decompiled. About 24 hand-written `hos_oot_*` hooks exist, around 22 KB.
- **Game formats:** TotK engine. bfres **v10.4**, BYML **v7** (oead reads it if you patch the version to 4:
  `tools/byml7.py`), SARC `.pack`, and zstd with dictionaries (`tools/zs.py`). Enum values in bgyml/GameData are
  **murmur3_32(name), seed 0** (`mmh3`).
- **Mods:** `Hookshot/mods/<name>/romfs/...` loads at start. `exefs/*.pchtxt|.ips` are applied at rebuild, but
  **code caves are refused**. So new code means C patches to the lifted code, in the style of `oot_patches.py`, in
  our own copy of the builder. Rebuild command: `triforce-appimage/AppRun --cli --update /Games/TF-OOT/Hookshot`.
  Not tried yet; consider building into a *copy* of the game folder first.
- **Item data model:** each item has three actors, `Item_X` (pickup), `Pouch_X` (inventory) and `Weapon_X` (held).
  `RSDB/PouchActorInfo.Product.111.rstbl.byml` maps each to `AssignableItem` and `ActionGuideType`. GameData keys
  are `IsGet.<actor>` and `PouchData.<actor>.StockNum`. C-buttons are the `PlayerStatus.AssignableItem` struct
  (enums, with `RawValues` lists). The template is the Megaton Hammer: `Pack/Actor/Item_Hammer.pack.zs`,
  `Weapon_Hammer.pack.zs` (`WeaponParam.HoldAnimationType=Hammer`, attack shape `Item_Hammer_AtkPlayer`).
- **The enum (option B target):** see `docs/assignable_item_enum.md`. It covers the hash table `0x83f163c0` plus the
  sorted index table at +0xdc (binary search with bound `0x36`, in `f_82d82fe0` and `f_82d833b0`), the names at
  `0x83f0ac60` with offsets at +0x250 (nine inlined *toText* sites with `cmp #0x36`), the name pointer table
  `0x84bfc7b0` (*isValid* at `0x80bcdec0`, bound `0x37`), and the value spaces (stored value = index-1, so
  Empty = -1; `FalconPunch` = index 55, stored 54).
- **Candidate bound/switch sites:** `out/enum_bound_sites.json` (git-ignored, regenerate with the snippet in
  "Next steps"). It lists `cmp wN,#0x34..0x37` followed by a conditional branch: 61/59/118/68 sites, and only 4 with
  `#0x37` lead to a `br` jump table. Most are probably unrelated; each needs checking.
- **Player animation:** `Player_Adult.root.asb` (AS) names states such as `Hammer_Attack_Vertical_Advance`. The
  player's animation files are listed in `Player_Adult.pack` → `AnimationParam`: `_Demo`, `_01`–`_04`, `_Cba`,
  `_02_H` and `Player_Dark_Animation`. Hammer attacks are in `_02_H`. The AI folder has only 14 AINB files, so the
  player's logic is in code.

## Work done (tools; all in the repo)

| Step | State | Files |
|---|---|---|
| Melee extraction | **Done and verified** (cross-checked decoder; previews show the punch at frames 52–56) | `tools/melee_anim.py`, `hsd_archive.py`, `verify_fobj.py`, `gc_extract.py`; docs in `out/melee/README.md`, `falcon_punch_facts.md`, `bone_map.tsv` |
| bfres v10.4 read/write | **Done** (byte-identical round-trip; added animations re-parse; **not yet loaded in game**) | `tools/bfres.py`, `bfres_add_anim.py`, `bfres_dump.py`, `bfres_validate.py`, `test_bfres_write.py`; docs in `out/bfres/NOTES.md` |
| Retarget Falcon → Link | **Done** (30 fps, 50 frames; `FalconPunch`, `_AdvanceZero`, `_Air` inserted into a copy of `_04`; **not yet loaded in game**) | `tools/retarget_falcon_link.py`; docs in `out/retarget/README.md` |
| Enum reverse engineering | Tables and conversion sites mapped; consumers not yet | `tools/a64.py`, `docs/assignable_item_enum.md` |

## Current state (2026-11-22, Triforce v0.7.0)

The user chose the **rebuild route** (a real new item, built with our own builder copy). Architecture:

| Part | How | Where |
|---|---|---|
| Item identity | takes over `Pouch_Amiibo` (stored AssignableItem **51**; has pouch row, pack, GameData) | `tools/build_mod.py` item mode |
| Name / caption | `ActorMsg/PouchContent.msbt` in `Mals/USen`, `EUen` | `tools/msbt.py` |
| Icon | `UI/Tex/Icon/Pouch_Amiibo.bntx` = Golden Gauntlets icon, renamed (stand-in) | `build_mod.item_icon` |
| Game logic | C patch: `fp_item()` maps 51 -> 7 at every load of `player+0x7d8` (current item) in 88 functions | `patches/fp_patches.py`, `tools/find_item_sites.py` |
| Animations | AS: `[51]` next to all 109 `UsingItem [7]` branches; the 3 vertical-attack leaves and the 9 follow-through leaves wrapped in `UsingItem` selectors (51 -> punch / recovery) | `tools/build_asb.py`, `tools/asb_edit.py` |
| Punch anims | `FalconPunch*` in `_04`, time-warped to the hammer's AS event timing (hit f17, 40 frames); `FalconPunch_After` recovery (46 f) | `tools/retarget_falcon_link.py` (`warp`), `tools/make_recovery.py` |

Builder: `tools/fp_builder.sh` makes `/Games/TF-OOT/fpbuilder07` (extracted v0.7.0 AppImage + our hook in
`nx2/chunks.py`). Rebuild the test copy: `/Games/TF-OOT/fpbuilder07/AppRun --cli --update /Games/TF-OOT/FPTest
--no-prepare-shaders` (shares `~/.cache/triforce-build`; a few changed files take about 4-15 min).

Hard-won rules (ASB 0x41b):
- Appending is safe: bodies, strings, a relocated node table, new nodes.
- A node that owns **Event nodes** (event slot) cannot be copied: sharing its Event nodes or copying them (new GUIDs,
  header 0x1c raised) crashes at load. Only copy event-free leaves; insert selectors above/below instead.
- Event nodes are placeholders (index 0xffff); their real events are in `AnimationEvent/AsNode/*.root.baev`, keyed by
  FNV-1a of the node GUID text (`tools/baev.py`). The hammer attack's events (AtCollision 14-24, AtSound 10,
  EmitEffect 20, cancels 40) live on Event node #16179 under blender #16176.
- The follow-through state ends by AnmSeqCancel@44 on its blender (#17398), so its leaves are wrapped, not the blender.

Open:
1. **In-game test of the C patch** (FPTest built with it): equip "Falcon Punch" (amiibo slot, far right of the wheel),
   press the item button; expect hammer behaviour with the punch animation. If the AS sees 7 instead of 51, find the
   `UsingItem` blackboard write and exempt it.
2. Weapon model: the hammer may show in Link's hand for 51; make it invisible (weapon actor/model for the item).
3. A way to obtain it for real saves (save editor `tools/progress_sav.py`, or a chest/shop), more languages, a drawn
   icon, sounds/effect (falcon voice, fire).
4. Saves: v0.7 keeps them in `$XDG_DATA_HOME/triforce/user/...` (test copy: `/Games/TF-OOT/fptest-data/triforce`).

## Conventions

- Commit messages are short and descriptive. Push after each milestone (`git add -A && git commit -m … && git push`).
- Match the existing tool style: small, focused Python scripts in `tools/`, with output under `out/`.
