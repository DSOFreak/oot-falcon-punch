# Code hooks for Triforce mods

A proposal for Triforce, with a working implementation against v0.7.0: a mod can carry **its own C**, built into the
game, and name the places of the game's code that call it. It is the third kind of code mod, next to the two Triforce
has (`exefs/*.ips`, `exefs/*.pchtxt`), and the first that can *add* behaviour: a patch file can change instructions,
but a code cave is refused, so there is nowhere to put new code. This is the way Triforce's own additions are made
(the sprint button: `nx2/oot_patches.py` and `host/oot_sprint.c`), opened to mods.

The Falcon Punch item in this repository (`mod/FalconPunch`) is built on it: 6 hooks and one C file.

## What a mod looks like

```
mods/MyMod/
  code/hooks.txt        where the game's code calls the mod
  code/*.c, *.h         the mod's C
  romfs/...             its game files, as before (sounds too: romfs/Sound/Mod/MyMod/Hit.wav)
```

`hooks.txt`, one hook a line. A function is its address in the game (the lift names it `f_<address>`):

```
game E0F3CCFAF50065AE                 # the build the addresses are for: the first 16 digits of its id, or more

before 0x80953270 my_command          # int my_command(Ctx *c): first thing in the function; not 0 skips it
after 0x82bc8960 my_power             # void my_power(Ctx *c): when it has returned, its result in c->x[0]
after-call 0x8019b6e0 my_item in 0x802ebd20 0x80609d00     # after each call of the first in the named callers
before-icall 0x83035be0 my_set        # before each indirect (virtual) call or jump of the function
load32 0x7d8 my_value in 0x82e57c30   # uint64_t my_value(Ctx *c, uint64_t v, uint64_t address): each 32-bit load from reg + 0x7d8
```

The C sees the game as the runtime does, through `host/mod_api.h`:

```c
#include "mod_api.h"

void my_power(Ctx *c) {                       /* after 0x82bc8960: a weapon's attack power */
    if ((uint32_t)c->x[0] == 3) c->x[0] = 9999;
}

int my_command(Ctx *c) {                      /* before 0x80953270: x2 -> the animation command's name */
    if (mod_streq(mod_ld64(c->x[2]), "CutJumpSt")) mod_sound_play("Sound/Mod/MyMod/Hit.wav", 1.0f);
    return 0;
}
```

| `mod_api.h` | |
|---|---|
| `c->x[0..30]` | the game's registers at the hook: arguments in `x[0..7]`, the result in `x[0]` |
| `mod_ld8/32/64/f`, `mod_st8/32/64/f` | the game's memory at its own addresses, checked: outside the game's heap and image a read is 0 and a write nothing, where a stale pointer would fault |
| `mod_cstr`, `mod_streq` | the game's text |
| `mod_call` | a function of the game, called from a hook with up to four arguments; the registers are restored after it |
| `mod_log`, `mod_time_ms` | a line in `triforce_log.txt`; a clock |
| `mod_sound_load`, `mod_sound_play` | a `.wav` (or one of the game's `.bwav`) by its RomFS path, mixed over the game's sound where the options' sounds are: after the limiter, under the Master volume. 16 at a time |

## How it is built in

Like a patch file, a hook is built in at the next **build** of the game, not loaded at its start:

1. `nx2/make_game.py` copies the active mods' `code` folders into the work folder (`code_hooks.stage`), refuses a
   mod made for another build of the game with a line that says so, and writes the parsed hooks to
   `mod_code/hooks.json`. That file is in the lift key: a mod added, taken out, switched off or edited translates the
   game again, and nothing else does.
2. The lift applies the hooks to the C it wrote, after the port's own patches (`chunks.py edit_c` →
   `code_hooks.apply`). `before` and `after` rename the function and put one of its own name around it, so every
   caller, direct or through the function table, and every way out of it (tail calls too) is covered. The other
   three kinds edit the function's text where the lift wrote the call or the load. A hook that finds no place stops
   the build and names the mod, the hook and the function.
3. `nx2/build.py` compiles the mods' `.c` files with the runtime's flags and headers, each mod with its own folder
   on the include path, and links them in.
4. The game's log names the mods whose code it is built with, at each start.

Switching a mod off (`-` or `_` before its folder's name) and building again takes its code out.

## What it changes in Triforce

Three new files, and ten small edits of six existing ones (`install.py` has each, with its anchor text):

| File | |
|---|---|
| `nx2/code_hooks.py` (new) | the format, staging, the edits of the lifted C |
| `host/mod_api.h`, `host/mod_api.c` (new) | what a mod's C may call; the sounds' mixer |
| `nx2/make_game.py` | stage before the lift key; the staged hooks in the key |
| `nx2/chunks.py` | `edit_c`: apply after `oot_patches` |
| `nx2/build.py` | compile the mods' C |
| `nx2/code_mods.py`, `host/mods.c` | a folder with only `code` is a mod; the log line |
| `host/nn_audio.c` | the mods' sounds into the block, after the options' sounds |

```sh
python framework/install.py <tree>            # a clone, or an unpacked AppImage's usr/share/hookshot
python framework/install.py <tree> --check    # only say what it would do
```

`diff -ru` of a tree before and after is the patch.

## What a maintainer should weigh

- **Trust.** A patch file and a RomFS mod can only change the game. A mod's C runs as the game's process does: it
  can do what any program can. The build says so for each such mod, and the log does at each start; Setup's Mods
  page should say it too and ask before a build with such a mod (not done here: the page is not in the AppImage's
  tree). An alternative is to compile mods' C against `mod_api.h` alone, without the runtime's headers, which
  narrows what it can name but not what C can do.
- **Addresses.** Hooks name functions by address, so a mod is for one build of the game (`game` line, checked). The
  text forms the edits look for are the lift's own (`code_hooks.py`: `DEFINITION`, `CALL`, `ICALL`, `LOAD32`); a
  change of the lifter's output has to move them, as it does `oot_patches.py`'s.
- **Not done:** hooks in the middle of a function at an address (the port's own patches do this by exact text),
  64-bit and float loads, stores, a per-mod options row. Tests in the
  style of `tests/test_code_mods.py`: `framework/test_code_hooks.py` covers the parser and the edits and runs
  without a game.
