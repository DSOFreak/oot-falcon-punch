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

## Next steps (suggested order)

1. ~~Finish the retarget~~ (done; hit window = anim frames 26–28 at 30 fps).
2. **First in-game test of the animation (data only, temporary):** a test mod in
   `Hookshot/mods/zz-fp-test/romfs/Model/Player_Adult_04_Animation.anim.bfres.zs`. Point one existing AS state
   (for example `Hammer_Attack_Vertical_Advance`) at `FalconPunch`, which needs an ASB editor or parser (not written
   yet), or temporarily overwrite the hammer animation's data. Possible blocker:
   `System/Resource/ResourceSizeTable*.rsizetable.zs` may need a larger entry for the enlarged bfres (as in TotK).
   Ask the user before creating a mods folder in `Hookshot`, and remind them to remove it afterwards.
3. **ASB (AS) format:** write a parser/writer for `AS/*.root.asb` (TotK ASB, see dt-12345's asb tools) so new
   `FalconPunch` states can be added.
4. **Enum, option B:**
   - Find every consumer of the stored item value. Use `out/enum_bound_sites.json` and the lifted C, and/or run
     `bin/triforce` under gdb: lifted calls are native C calls, so a breakpoint on `f_82d833b0` gives guest call
     chains through backtraces.
   - Write `nx2`-style patch scripts that add `FalconPunch` (index 55 / stored 54 / its mmh3 hash) to the conversion
     sites, and send the behaviour to Hammer (7) except where identity matters (icon, name, pouch actor, AS choice).
   - Keep these patches as a separate script in the repo (for example `patches/fp_patches.py`) that edits our copy
     of the builder's `nx2/`, so it can be applied again to a new Triforce version.
5. **Data for the new item:**
   - `Item_FalconPunch`, `Pouch_FalconPunch` and `Weapon_FalconPunch` packs, cloned from the Hammer: an invisible
     weapon with the attack shape on `Weapon_R`/`Wrist_R`, and the hitbox active on the frames from
     `falcon_punch_facts.md`.
   - PouchActorInfo rows, GameData (`IsGet.*`, `PouchData.*`, and `FalconPunch` added to the `RawValues` of the
     C-button enums), the icon, the message text, and a way to obtain it (a cheat, chest or shop).
   - Optional: the fire/falcon effect (`EfCaData.dat`) and the voice clips (`captain.ssm`, ids 60025/60052).

Regenerate `out/enum_bound_sites.json` with a capstone/numpy scan over `image.bin` (see `tools/a64.py`). Match
`(w & 0xFFFFFC1F) == 0x7100001F | imm << 10` for `imm` in 0x34–0x37, followed by `b.cond`, and flag a `br` within
14 instructions.

## Conventions

- Commit messages are short and descriptive. Push after each milestone (`git add -A && git commit -m … && git push`).
- Match the existing tool style: small, focused Python scripts in `tools/`, with output under `out/`.
