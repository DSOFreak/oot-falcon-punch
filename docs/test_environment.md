# In-game test environment

Nothing here touches `/Games/TF-OOT/Hookshot` or the player's real saves.

- **Game copy:** `/Games/TF-OOT/FPTest`, a btrfs reflink copy of `Hookshot` (`cp -a --reflink=always`, about 11 s,
  almost no extra space). Test mods go in `FPTest/mods/<name>/romfs/...`.
- **Save copy:** `/Games/TF-OOT/fptest-data/triforce/user` since v0.7 (before: `.../hookshot`), a copy of the real saves. The game takes
  `$XDG_DATA_HOME/hookshot`. It mounts `save-tx/<id>/work`, so patch both `save/` and `save-tx/.../work`.
- **Launch:** `tools/testenv/launch.sh`. It sets `HOOKSHOT_NO_UPDATE_CHECK=1`; otherwise a zenity "update to v0.6.0?"
  dialog blocks the start, with *Update now* preselected, so never confirm it. The log goes to **stdout**
  (`$GAME_OUT`), not to `triforce_log.txt`. That file in FPTest is a stale copy of the original.
- **Own environment (since 2026-11-23):** tests never use the user's screen, keyboard or caches.
  `tools/testenv/display.sh start` runs a **headless sway** (own socket `wayland-fptest`, `WLR_LIBINPUT_NO_DEVICES=1`,
  1920x1080, game fullscreen and focused). `env.sh` gives the game its own XDG cache/config and GPU driver shader
  caches under `/Games/TF-OOT/fptest-env` (the user's game shares `~/.cache/nvidia` otherwise). `wtype` and `grim`
  act on that display only. The first run compiles all shaders once (about 42.5k).
- **Drive:** `toplay.sh` (title → Continue → newest slot), `key.sh KEY [ms]` (wtype), `shot.sh OUT [scale]` (grim on
  the window).
- **Keys (VK codes in triforce_options.ini):**
  - A = `e`, B = Shift, X = Space, Plus = Tab/Enter, RT/ZR = `f`/`x`, RB/R = `r`
  - move: `wasd`; camera / right stick: arrows
- **Item wheel:**
  - Hold RB (`wtype -P r`), then step with the arrow keys. Arrow presses sometimes drop, so screenshot to check.
  - Press-and-release `r` again to equip.
  - The Megaton Hammer sits left of the Hookshot.
- **Kill the game:** use `pkill -9 -x triforce`. Never `pkill -f bin/triforce`, which matches the calling shell.
  SIGTERM during start can hang.

## Save editing (`tools/progress_sav.py`)

- **Inventory:** the item wheel is driven by `PouchData.Item_<X>.StockNum` (Int > 0). `IsGet.Item_<X>` alone does
  not add an item.
- **Test saves:** they have `IsGet.Item_Hammer=1`, `PouchData.Item_Hammer.StockNum=1` and `FireTemple_GetHammer=1`.
- **C-button enums:** `0x6bee602d`, `0xa0029837` and `0xbc32ce24` (stored as `mmh3` values) hold
  Bomb/Boomerang/Hookshot. They are not the RT slot.

## Mod file rules found so far

- **`.bfres.zs` files:** compress them with `zs.zsdic`, the same as the game's (dict id 1).
- **`System/Resource/ResourceSizeTable...rsizetable.zs`:** compress it **without** a dictionary. With a dictionary
  the game hangs at boot right after loading it. See `tools/restbl.py`.
  - Grow an entry when a file grows: `new = old_entry + (new_size - original_size)`.

## Result of the first animation test (2026-11-22)

- **Setup:** `Hammer_Attack_Vertical_Advance(Zero)` in `_02_H` was renamed in place, and the retargeted Falcon Punch
  was added under those names to `_04`.
- **Result:** the game played our animation for the hammer swing. Link shows the Falcon Punch wind-up (left arm out,
  right fist cocked) and the lunge, with correct facing and no broken bones. After about 20 frames the AS moves on
  to `Hammer_Attack_Vertical_After`.
- **Conclusions:** the bfres writer, by-name binding across anim files, the RESTBL edit and the 30 fps timing work.
