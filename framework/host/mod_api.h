/* (Triforce) What a mod's own C may use (mods/<name>/code/*.c, built into the game: nx2/code_hooks.py has the
   layout and the hooks). A hook is called by the translated game, on the game's thread that runs the hooked
   function, with the game's registers:

       #include "mod_api.h"
       int my_before(Ctx *c);                         before <function>: other than 0 skips the function
       void my_after(Ctx *c);                         after, after-call, before-icall
       uint64_t my_value(Ctx *c, uint64_t value);     load32

   c->x[0..30] are the game's X registers (c->x[0..7] a function's arguments, c->x[0] its result), 64 bits each: a W
   register is the low half. A hook may change them; what the game's calling convention lets a function change
   (x0..x18) it may change freely in a before or an after hook.

   The game's memory is its heap and its program image (code and data), at the game's own addresses. A mod reads the
   game's objects through pointers the game holds, which may be stale or no pointers at all: the mod_ld and mod_st
   functions check each address and read 0 (write nothing) outside those two ranges, instead of faulting.

   Hooks of several mods on one function run in the mods' order. A hook runs often (some functions thousands of times
   a frame): no file, no log line a call, no lock held across it. */
#ifndef MOD_API_H
#define MOD_API_H
#include <stdint.h>
#include "hos.h"   /* (Ctx, the game's memory: GP) */

#ifdef __cplusplus
extern "C" {
#endif

/* 1 when [address, address + size) is the game's heap or its image */
int mod_readable(uint64_t address, uint64_t size);
uint8_t mod_ld8(uint64_t address);
uint32_t mod_ld32(uint64_t address);
uint64_t mod_ld64(uint64_t address);
float mod_ldf(uint64_t address);
void mod_st8(uint64_t address, uint8_t value);
void mod_st32(uint64_t address, uint32_t value);
void mod_st64(uint64_t address, uint64_t value);
void mod_stf(uint64_t address, float value);
/* The game's text at `address` (up to cap - 1 bytes and a 0) into out; out, "" where it is not readable */
const char *mod_cstr(uint64_t address, char *out, int cap);
/* 1 when the game's text at `address` is `text` */
int mod_streq(uint64_t address, const char *text);

/* Calls a function of the game from a hook: `function` is the translated function (declare it in the mod's C as
   the lift names it, void f_80953270(Ctx *c);), a0..a3 its first arguments. The registers are as they were when it
   returns, whatever the function did to them; its result (x0) is returned. The function runs on the hook's thread,
   on the game's stack below the hooked function's frame: only where the game itself could make the call there */
uint64_t mod_call(Ctx *c, void (*function)(Ctx *), uint64_t a0, uint64_t a1, uint64_t a2, uint64_t a3);

/* A line in triforce_log.txt, "mod: " before it. Not from a hook that runs every frame */
void mod_log(const char *fmt, ...);

/* A sound of the game's files or a mod's, by its path in the RomFS ("Sound/Mod/MyMod/Hit.wav": a mod puts it in
   its romfs folder, and the last mod that has the path wins, as with every RomFS file). A .wav file (PCM, 8 to 32
   bits or float, one or two channels, any rate) or a .bwav file of the game (PCM16 or DSP-ADPCM, at most 30 s).
   gain: 1 is the file as it is; the Master volume is over it. It plays once, over the game's own sound, from the next
   block the sound thread mixes (5 ms); up to 16 play at a time (one more ends the oldest).
   The file is read at its first use, on the caller's thread: mod_sound_load reads it ahead (in a hook that runs
   early, a load), so the first play does not wait for the disk. Both return 0 where the file is not there or not one
   of those formats (said once in the log). */
int mod_sound_load(const char *romfs_path);
int mod_sound_play(const char *romfs_path, float gain);

#ifdef __cplusplus
}
#endif
#endif
