# oot-falcon-punch

Work in progress: a new item for adult Link in the Triforce native build of *The Legend of Zelda: Ocarina of Time*
(the Switch 2 remake on the Tears of the Kingdom engine) that performs Captain Falcon's Falcon Punch, with the
animation taken from *Super Smash Bros. Melee* and retargeted onto Link.

**No game data is in this repository.** Everything here works on your own copies of both games: the scripts read
your files and write their output to the git-ignored `melee/`, `unpacked/` and `out/` folders.

## Plan

1. **Melee extraction** (`tools/melee_anim.py`, `tools/hsd_archive.py`): read the HSD archives `PlCa.dat`,
   `PlCaAJ.dat` and `PlCaNr.dat` from the disc (`tools/gc_extract.py` reads CISO images) and decode the
   `SpecialN`/`SpecialAirN` figatrees to per-frame joint transforms. The gameplay facts (hitbox frames, effects,
   voice timing) are written to `out/melee/falcon_punch_facts.md`.
2. **bfres v10.4 tooling** (`tools/bfres.py` and its command-line tools): read Link's skeleton and animations, and
   add new skeletal animations. Unchanged re-saves are byte-identical.
3. **Retarget** the punch onto Link's 327-bone skeleton, then add it to `Player_Adult_04_Animation.anim.bfres`.
4. **A real item** (`Item_FalconPunch` / `Weapon_FalconPunch` / `Pouch_FalconPunch`): actor packs, PouchActorInfo,
   GameData flags, icon and name, plus the player's AS (`Player_Adult.root.asb`) states.
5. **A new AssignableItem enum value** (`FalconPunch` = 55). The game's item enum is a fixed 55-entry table in its
   code: a sorted murmur3 hash table at `0x83f163c0` that is binary-searched with the bound `0x36`, and a name table
   at `0x84bfc7b0`. These and every switch over the enum are patched as C changes to Triforce's translated code,
   applied at build time in the same way as Triforce's own `nx2/oot_patches.py`.

## Tools

| File | Purpose |
|---|---|
| `tools/zs.py` | zstd with the game's dictionaries (`Pack/ZsDic.pack.zs`) |
| `tools/byml7.py` | BYML v7 through oead |
| `tools/gc_extract.py` | Extract files from a GameCube CISO |
| `tools/melee_anim.py`, `tools/hsd_archive.py`, `tools/verify_fobj.py` | Melee animation extraction |
| `tools/bfres*.py` | bfres v10.4 reading and writing |
| `tools/a64.py` | Static helpers over the game's Eden-layout image (string and ADRP cross-references, disassembly) |
| `tools/gdnames.py` | Recover GameData names from their murmur3 hashes |

Python setup: `uv venv && uv pip install zstandard oead numpy mmh3 capstone matplotlib pygltflib`.
