/* Falcon Punch for adult Link: an item of its own that hits like nothing else in the game.

   The item is the stored AssignableItem value 51 (the game's unused amiibo slot: the mod's RomFS files give it its
   name, icon and pouch row). The game's logic has no code for a 51, and none is written here: it is handed the
   Megaton Hammer (7) instead, so the item is drawn, swung, hits and is put away by the hammer's own code. Only the
   animation system is told the truth: its UsingItem is 51, where the mod's animation tree (AS/Player_Adult.root.asb)
   has the punch's branches beside the hammer's. UsingItem is not a value the game hands over: the animation system
   reads Link's own field, the item in his hand (Link +0x7d8; seen in memory, 2026-11-23: the blackboard's UsingItem
   is a copy nothing selects on). So that field holds 51 while the punch is in hand, and each of the game's loads of
   it is given the hammer.
   The punch's damage and its fire are data: the mod's entries in the player's attack table (tools/build_mod.py).

   Game 1.1.1's addresses (main at 0x80020000), found with tools/a64.py and the lifted C:
     f_8019b6e0  the equipped item, read from GameData (PlayerStatus.AssignableItem)
     f_83035be0  the item component's setter: it ends in a virtual call (blackboard, UsingItem's index, the item)
     f_837d9790  that call's target for the player: the blackboard's set-int (x0 blackboard, w1 index, w2 value)
     f_80953270  asks the animation system for a command (x0 its controller, w1 the slot, x2 -> the name's text)
   The hammer's attacks: the swing on the ground is the command CutS1; out of a jump or a run it is a jump slam,
   three commands: CutJumpSt (wind-up), CutJumpEd (the leap), CutJumpLand (the hit); then CutHammerAfter. */
#include <string.h>
#include "mod_api.h"

enum { FP_ITEM = 51, HAMMER = 7 };
#define LINK_CLASS 0x84b6dfc0ULL   /* what Link's first word reads (host/oot_sprint.c) */
#define LINK_HAND 0x7d8           /* Link's field: the item in his hand, -1 with none */
enum { PHASE_NONE, PHASE_GROUND, PHASE_WINDUP, PHASE_LEAP, PHASE_HIT };
#define GROUND_PUNCH_MS 1250   /* "PUNCH!" after "Falcon..." on the ground: the fist goes out at frame 42 of 30 a second */
#define SOUND_FALCON "Sound/Mod/FalconPunch/Falcon.wav"
#define SOUND_PUNCH "Sound/Mod/FalconPunch/Punch.wav"
#define SOUND_GAIN 1.0f

/* (plain words written and read on the game's threads, each whole: a stale read costs a frame at most) */
static volatile int equipped;            /* the equipped item is the punch */
static volatile int using_item = -1;     /* the animation system's UsingItem: 51 while the punch is in hand */
static volatile int phase;
static volatile uint64_t punch_due;      /* when the ground punch's "PUNCH!" is to be heard (mod_time_ms), 0: not */
static volatile uint64_t hand_address;   /* Link's +0x7d8, seen where the game loads it */
static volatile uint64_t blackboard;     /* the player's, and UsingItem's index in it: seen at the setter */
static volatile uint32_t blackboard_index;
volatile uint64_t fp_debug[8];           /* (for tools/testenv/memscan.py: sym fp_debug) */

void f_837d9790(Ctx *c);                 /* the game's: the blackboard's set-int */
static void shout_tick(void);

static uint64_t to_as(uint64_t item) {
    return (uint32_t)item == HAMMER && equipped ? FP_ITEM : item;
}

/* after f_8019b6e0 in the game logic's callers: 51 is the hammer to them */
void fp_item_get(Ctx *c) {
    if ((uint32_t)c->x[0] == FP_ITEM) c->x[0] = HAMMER;
}

/* the game's loads of the item in Link's hand: the hammer, where the field holds the punch */
uint64_t fp_hand_load(Ctx *c, uint64_t value, uint64_t address) {
    (void)c;
    if (address != hand_address && mod_ld64(address - LINK_HAND) == LINK_CLASS) hand_address = address;
    return (uint32_t)value == FP_ITEM ? HAMMER : value;
}

/* the field as the animation system is to read it: the punch while the punch is the equipped item and the hammer
   is what the game put in his hand */
static void hand_keep(void) {
    const uint64_t a = hand_address;
    if (!a || mod_ld64(a - LINK_HAND) != LINK_CLASS) return;
    const uint32_t now = mod_ld32(a);
    if (equipped && now == HAMMER) mod_st32(a, FP_ITEM);
    else if (!equipped && now == FP_ITEM) mod_st32(a, HAMMER);
}

/* the same in the player's item update (f_830350a0), which runs every frame and asks for the equipped item alone
   (other callers ask for other slots too): whether the punch is equipped is taken here. The game may have told the
   animation system "hammer" before this was known (it does so once, when the item is taken in hand): it is told
   again */
void fp_item_get_frame(Ctx *c) {
    const int punch = (uint32_t)c->x[0] == FP_ITEM;
    if (punch) c->x[0] = HAMMER;
    shout_tick();
    if (punch == equipped) {
        hand_keep();
        return;
    }
    equipped = punch;
    hand_keep();
    if (punch) mod_sound_load(SOUND_FALCON), mod_sound_load(SOUND_PUNCH);   /* (read ahead of the first punch) */
    if (blackboard && using_item == (punch ? HAMMER : FP_ITEM))
        mod_call(c, f_837d9790, blackboard, blackboard_index, punch ? FP_ITEM : HAMMER, 0);
}

/* loads of the current item (player +0x7d8) that are written to UsingItem */
uint64_t fp_as_item(Ctx *c, uint64_t value, uint64_t address) {
    (void)c, (void)address;
    return to_as(value);
}

/* f_83035be0's virtual call: x0 the blackboard, w1 UsingItem's index, w2 the item */
void fp_as_set(Ctx *c) {
    blackboard = c->x[0];
    blackboard_index = (uint32_t)c->x[1];
    c->x[2] = to_as(c->x[2]);
}

/* every write of the player's UsingItem, whoever makes it: what the animation system now has */
int fp_blackboard_set(Ctx *c) {
    if (c->x[0] != blackboard || (uint32_t)c->x[1] != blackboard_index || !blackboard) return 0;
    c->x[2] = to_as(c->x[2]);
    using_item = (int)(uint32_t)c->x[2];
    fp_debug[0] = (uint64_t)equipped, fp_debug[1] = (uint64_t)(uint32_t)using_item;
    if (using_item != FP_ITEM) phase = PHASE_NONE;
    return 0;
}

static void set_phase(int now) {
    if (now == phase) return;
    phase = now;
    fp_debug[2] = (uint64_t)now;
    punch_due = 0;
    if (now == PHASE_WINDUP) mod_sound_play(SOUND_FALCON, SOUND_GAIN);
    else if (now == PHASE_GROUND) mod_sound_play(SOUND_FALCON, SOUND_GAIN), punch_due = mod_time_ms() + GROUND_PUNCH_MS;
    else if (now == PHASE_LEAP) mod_sound_play(SOUND_PUNCH, SOUND_GAIN);
}

/* every frame (from the player's item update): the ground punch's second word, when its time has come */
static void shout_tick(void) {
    const uint64_t due = punch_due;
    if (!due || mod_time_ms() < due) return;
    punch_due = 0;
    if (phase == PHASE_GROUND) mod_sound_play(SOUND_PUNCH, SOUND_GAIN);
}

/* before f_80953270: the command the player's state asks the animation system for. The hit on the ground is one
   command (CutS1: "Falcon..." at its start, "PUNCH!" as the fist goes out), the jump slam three (CutJumpSt:
   "Falcon...", CutJumpEd: "PUNCH!") */
int fp_as_command(Ctx *c) {
    hand_keep();   /* (before the animation system picks the command's branch) */
    if (using_item != FP_ITEM) return 0;
    if ((uint32_t)c->x[1] != 0) return 0;   /* (the body's slot) */
    const uint64_t name = mod_ld64(c->x[2]);
    if (mod_streq(name, "CutS1")) set_phase(PHASE_GROUND);
    else if (mod_streq(name, "CutJumpSt")) set_phase(PHASE_WINDUP);
    else if (mod_streq(name, "CutJumpEd")) set_phase(phase == PHASE_NONE ? PHASE_NONE : PHASE_LEAP);
    else if (mod_streq(name, "CutJumpLand")) set_phase(phase == PHASE_NONE ? PHASE_NONE : PHASE_HIT);
    else set_phase(PHASE_NONE);
    fp_debug[5]++;
    return 0;
}
