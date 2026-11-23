# Handover: Falcon Punch item for Link (Triforce OoT)

Snapshot of 2026-11-23. Repository: https://github.com/DSOFreak/oot-falcon-punch (public, branch `main`).
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

## Current state (2026-11-23, Triforce v0.7.0)

Two things live in this repository now:

- **`framework/`**: code hooks for Triforce mods, a proposal for upstream with a working implementation against
  v0.7.0 (`framework/README.md`). A mod carries `code/hooks.txt` and its own C; the build applies the hooks to the
  lifted C and compiles the C in. `framework/install.py <tree>` puts it into a Triforce source tree;
  `framework/test_code_hooks.py` tests it without a game.
- **`mod/FalconPunch/code/`**: the Falcon Punch on that framework (`hooks.txt`, `falcon_punch.c`). The mod's RomFS
  is built from the player's game files and Melee disc by `tools/build_mod.py` (never committed).

| Part | How | Where |
|---|---|---|
| Item identity | takes over `Pouch_Amiibo` (stored AssignableItem **51**; pouch row, pack, name, icon) | `tools/build_mod.py` |
| Game logic | the item getter `f_8019b6e0` gives its game-logic callers the hammer (7); the menus keep 51 | `hooks.txt`: `after-call` |
| Animation value | Link's field "item in hand" (Link +0x7d8) is kept at 51 while the punch is equipped, and every game load of it (88 functions) is given 7; the blackboard's UsingItem gets 51 too | `falcon_punch.c`: `hand_keep`, `fp_hand_load`, `fp_blackboard_set` |
| Animations | AS: `[51]` beside all 109 `UsingItem [7]` branches (hold, walk, put away: the hammer's nodes); the attack commands get the punch's own nodes with copied, edited Event nodes | `tools/build_asb.py`, `tools/baev.py` |
| Punch anims | the ground punch (66 frames, hit at 42: a long wind-up) and the jump slam's phases, from the Melee animation | `tools/make_phases.py`, `tools/make_recovery.py` |
| Damage, fire | data: the punch's AtCollision events use the burning Deku Stick's attack types (103, 104), whose entries in adult Link's attack table become the hammer's with `Fire` and a multiplier of 3000 | `tools/build_mod.py player_attacks`, `tools/build_asb.py ATTACK` |
| Shout | "Falcon..." and "PUNCH!" from the player's Melee disc (`audio/us/captain.ssm`, sounds 345 and 354), played by the mod's code at the attack's phases | `tools/melee_ssm.py`, `falcon_punch.c` |

Build and test:

```sh
tools/fp_builder.sh                                   # builder copy with the framework: /Games/TF-OOT/fpbuilder07
uv run python tools/gc_extract.py <GALE01.ciso> melee audio/us/captain.ssm
uv run python tools/melee_ssm.py melee/audio/us/captain.ssm out/melee/voice
uv run python tools/retarget_falcon_link.py && uv run python tools/make_phases.py
uv run python tools/make_recovery.py --punch out/retarget/falcon_punch_phase_land.json
uv run python tools/build_mod.py --romfs <game>/romfs   # out/mod/FalconPunch -> <game>/mods/FalconPunch
/Games/TF-OOT/fpbuilder07/AppRun --cli --update <game> --no-prepare-shaders
```

Test environment: `docs/test_environment.md` (headless sway, virtual gamepad `tools/testenv/pad.py`, memory tool
`tools/testenv/memscan.py` with `scan`, `filter`, `watch`, `write`, `sym`).

Hard-won rules:
- **RESTBL**: the entry sizes the resource's heap. Growth alone is not enough for `_04` and the AS: 4 MB slack
  (`build_mod.SLACK`). Too little shows as a black screen after loading, or a null call.
- **ASB**: appending is safe (bodies, strings, a relocated node table, new nodes, copies of Event nodes). The game
  does **not** follow a changed root index in the command table: a new root has to take the old root's node index
  (`asb_edit.swap_nodes`). A selector inside a OneDimensionalBlender or a Sequential stalls the state.
- **BAEV**: offsets become pointers in place at load, so a structure that holds a pointer must be reachable once
  only; an edited copy of an event node is copied whole (`baev.edited_node`). A parameter is (u64 type, u64 value).
  AtCollision's second parameter is the attack type (index of the game's enum; the player's
  `GameBalance/AttackParam` table has damage multiplier, elements, attributes by its hash).
- **The hammer's attacks**: the swing on the ground is the command `CutS1` (AttackComboType picks left, right,
  vertical); out of a jump or a run it is the jump slam, `CutJumpSt` / `CutJumpEd` / `CutJumpLand`; then
  `CutHammerAfter`. Link's current command name is the text at `[Link +0x238]`.
- **The item value**: the equipped item's getter is called for more than the equipped slot; only the player's item
  update (`f_830350a0`) says what is equipped. The animation system saw the hammer until Link's own field held 51.
- Never `pkill -f` with a pattern that is in the calling shell's own command line.

Seen in game (2026-11-23, test copy, headless): with the punch equipped, ZR draws and ZR hits; Link turns, winds
up for about a second and thrusts (the ground punch), the hit's dust burst follows, he recovers; the game stays up.

Open:
1. The hammer's model is still in Link's fist during the punch (scaling the `Weapon_L/R` bones in the punch's
   animations does not hide it): the weapon actor's model needs hiding in code or data.
2. Flames on the fist itself. The hit already has the `Fire` element in data (the game's own fire reaction on what
   is hit; not yet seen on an enemy). Fist flames are an effect call keyed by the animation's name in
   `ELink2/elink2.Product.110.belnk` (XLNK): it needs an entry for the punch's animations that names a fire emitter
   (e.g. `Ply_Magic_DinFire_*`), so an XLNK editor.
3. Not verified: the damage on an enemy (the test save has none nearby), the shout by ear (the log shows both
   sounds load; the code plays them at `CutS1` and 1.25 s later), the jump slam's phases with the real animations.
4. The icon in the wheel and the HUD is still the amiibo logo (drawn specially for this item).
5. A way to obtain the item in a real save, more languages, a drawn icon.
6. `fp_debug` in `falcon_punch.c` is test scaffolding (read by `memscan.py sym`): take it out before a release.

## Conventions

- Commit messages are short and descriptive. Push after each milestone (`git add -A && git commit -m … && git push`).
- Match the existing tool style: small, focused Python scripts in `tools/`, with output under `out/`.
