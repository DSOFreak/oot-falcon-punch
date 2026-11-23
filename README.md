# oot-falcon-punch

A new item for adult Link in the Triforce native build of *The Legend of Zelda: Ocarina of Time* (the Switch 2
remake on the Tears of the Kingdom engine): Captain Falcon's **Falcon Punch**. Link winds up for a second with a
burning fist, shouts "Falcon... PUNCH!" and thrusts. The animation and the voice come from your own copy of *Super
Smash Bros. Melee*, retargeted onto Link.

It comes in two parts:

- **`framework/`**: code hooks for Triforce mods. A mod can carry its own C, built into the game, and name the
  places of the game's code that call it. It is written as a proposal for Triforce itself, with a working
  implementation against v0.7.0, an installer and tests: see [`framework/README.md`](framework/README.md).
- **`mod/FalconPunch/`** and **`tools/`**: the item, built on that framework. Its game files are made from your
  games by `tools/build_mod.py`.

**No game data is in this repository.** The scripts read your files and write to the git-ignored `melee/`,
`unpacked/` and `out/` folders.

## What the item is

| | |
|---|---|
| Item | takes over the game's amiibo item (in every save's item wheel): name, text, pouch row |
| Attack | the hammer's code, the punch's animations: the standing hit has a 1.4 s wind-up (impact at frame 42 of 66) |
| Shout | "Falcon..." at the start, "PUNCH!" 1.25 s later (Melee's `captain.ssm`, sounds 345 and 354) |
| Flames | the game's own burning flame on the fist through the wind-up, on the arm from the thrust |
| Damage | its own attack type: the hammer's hit, fire, and a multiplier of 3000 |
| In hand | nothing: the hammer that hits is not drawn |

Known gaps: the icon in the wheel is still the amiibo logo; the name is English only; the damage on an enemy and
the punch out of a run or jump are built but not yet seen in game (`HANDOVER.md`, "Open").

## Build

Needs Triforce v0.7.0 (the AppImage), your dump of the game, a Melee disc image (NTSC-U 1.02), Python with `uv`.

```sh
uv venv && uv pip install zstandard oead numpy scipy mmh3 capstone matplotlib pillow
tools/fp_builder.sh                                   # a copy of the Triforce builder with the framework installed
uv run python tools/gc_extract.py <GALE01.ciso> melee PlCa.dat PlCaAJ.dat PlCaNr.dat audio/us/captain.ssm
uv run python tools/melee_ssm.py melee/audio/us/captain.ssm out/melee/voice
uv run python tools/retarget_falcon_link.py && uv run python tools/make_phases.py
uv run python tools/make_recovery.py --punch out/retarget/falcon_punch_phase_land.json
uv run python tools/build_mod.py --romfs <game folder>/romfs
cp -r out/mod/FalconPunch <game folder>/mods/
<builder copy>/AppRun --cli --update <game folder>          # builds the mod's code into the game
```

In game: open the item wheel, pick **Falcon Punch**, press the item button to draw and again to punch.

## Tools

| File | Purpose |
|---|---|
| `tools/build_mod.py` | the mod's RomFS from the game's files (calls the builders below) |
| `tools/build_asb.py`, `asb.py`, `asb_edit.py`, `baev.py` | the player's animation tree and its event file |
| `tools/build_elink.py`, `xlnk.py` | the effect link file (XLNK): the punch's flames |
| `tools/bfres*.py` | bfres v10.4 reading and writing (animations) |
| `tools/melee_anim.py`, `hsd_archive.py`, `melee_ssm.py`, `gc_extract.py` | Melee: animation, voice, disc image |
| `tools/retarget_falcon_link.py`, `make_phases.py`, `make_recovery.py` | Falcon's punch onto Link's skeleton |
| `tools/zs.py`, `byml7.py`, `restbl.py`, `msbt.py` | the game's containers: zstd dictionaries, BYML v7, size table, text |
| `tools/a64.py` | static helpers over the game's image (cross-references, disassembly) |
| `tools/testenv/` | a headless test setup: virtual gamepad, screenshots, memory scans (`docs/test_environment.md`) |

`HANDOVER.md` has what was learned about the game's formats and code on the way.
