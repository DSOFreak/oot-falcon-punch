# The AssignableItem enum (game build in `Hookshot/.triforce_exefs/main`, Eden layout at 0x80000000)

Goal: add a 56th value, `FalconPunch`.

## Value spaces

| Space | Range | Where |
|---|---|---|
| hash index `i` | 0..54 (`Empty`=0 … `NormalLure`=54) | the hash table, name tables |
| stored value `v` | `v = i - 1`: `Empty`=-1, `DekuStick`=0 … `NormalLure`=53 | what objects hold; `f_82d83160` stores `index - 1` |
| GameData / bgyml | murmur3_32(name), seed 0 | C-button enums in GameData (`PlayerStatus.AssignableItem` struct), `AssignableItem:` fields in bgyml, `RSDB/PouchActorInfo` (as a string) |

`FalconPunch` would be hash index 55, stored value 54, hash `mmh3("FalconPunch")`.

## Tables (read-only data)

| Address | Contents | Code that reads it |
|---|---|---|
| `0x83f163c0` | 55 × u32 murmur3 hashes in index order | `f_82d82fe0` (bgyml node `0xd3` → value) and `f_82d833b0` (hash → index, or -1) |
| `0x83f1649c` (= table + 0xdc) | 55 × s32 indices, sorted by hash: a binary search with bound `0x36` | the same two functions |
| `0x83f0ac60` | the names, NUL-separated | |
| `0x83f0aeb0` (= names + 0x250) | 55 × s32 offsets from `0x83f0ac60`, by index | inlined *toText* at `0x80424d40 0x805b2b74 0x809d392c 0x80a8e5e4 0x80a9463c 0x80a971c4 0x82d83224 0x833c4cd8 0x833c4e40`, each `cmp wN,#0x36 ; b.hi <empty string 0x83cfdd43>` |
| `0x84bfc7b0` | 55 × `char*` to the names, then a pointer to `""` | `0x80bcdec0`: *isValid(name)*, a loop bounded by `0x37` |

The enum's reflection vtable (no RTTI in this build) is at about `0x84b60650..0x84b60710`: `f_82d82fe0` (from a bgyml
node), `f_82d83160` (from text), `f_82d83200` (to text), `f_82d832c0` (reset to -1), `f_82d832d0` (copy), and
`f_82d83300` (size 4).

## Data side (no code needed)

- `RSDB/PouchActorInfo.Product.111.rstbl.byml`: rows `Item_X`, `Pouch_X`, `Weapon_X` with `AssignableItem`,
  `ActionGuideType`, `PouchCategory`, `PouchTabCategory`, and so on.
- GameData (`GameData/GameDataList.Product.110.byml`): `IsGet.<actor>` (Bool) and `PouchData.<actor>` (Struct) /
  `PouchData.<actor>.StockNum` (Int). The C-button enums list their allowed values in `RawValues`, so the new name
  must be added there too.
- The actor packs, for example `Pack/Actor/Item_Hammer.pack.zs` and `Weapon_Hammer.pack.zs`, hold `AssignableItem`,
  `WeaponParam.HoldAnimationType` and `PouchContentParam`.

## Plan for the code

These are C changes to the lifted functions, applied by a build step like `nx2/oot_patches.py`. That route is
needed because `.pchtxt`/`.ips` code caves are refused by the Triforce build.

1. Conversions: add the hash/name/index of `FalconPunch` to the sites above (hash → index, index → name, isValid).
2. Behaviour: at every switch over the stored value where the item's use is decided, send 54 to the Hammer
   case (7). Keep identity where it matters: the C-button icon and name, the pouch actor, and the AS animation
   choice.
3. The AS: new states in `Player_Adult.root.asb` that play `FalconPunch*` when the equipped item is `FalconPunch`.

## Runtime findings (2026-11-22, tools/testenv/memscan.py + HOS_WATCH)

- Guest memory is the memfd `memfd:hookshot-guest` (512 GB, sparse, 39-bit addresses; host = 0x100000000000 +
  guest). `memscan.py` launches the game as its child, finds the memfd and scans only its populated extents.
- **The player's current item:** an s32 at heap guest `0x10523069e8`. It held the same address in two runs; it
  should still be found again each run. Hookshot gives 5, Hammer gives 7 (the stored AssignableItem value). Nearby
  words at `+0xe0` / `+0xf0` hold copies, and two other heap copies (UI/slots) are not read while playing.
- **Consumers:** `HOS_WATCH` saw about 120 reads per 4 s (one per frame) from these functions:
  `f_804a2b30 f_804b9c30 f_804bbe90 f_804c60d0 f_804c6be0 f_804c7120 f_804c7270 f_804c75b0 f_804d74b0 f_804d7690`
  `f_80818d00 f_80819140 f_80819be0 f_80819fc0 f_8081a7c0 f_8081a890 f_8081abe0 f_8081be30 f_80a614e0 f_80c225d0`
  `f_832c4c40 f_83034d60 f_830350a0(write on equip) f_830357a0 f_83035fd0 f_83036730`.
  Most of them inline the field read (`ldr wN, [xM, #0xe8]`). The only getter, `0x83035f9c`, has no direct callers.
- **The AS** (see tools/asb.py) picks hammer animations with `IntSelector on bb:UsingItem` == 7. There are 189 such
  selectors, and 109 have a `7` branch. Value 0 = DekuStick, so `bb:UsingItem` is the stored AssignableItem value.

So a distinct item value needs, at each consumer above (and in event-driven code that was not seen in 4 s), a "45
behaves as 7" mapping. That needs more instructions than an in-place `.ips` can add, unless a site is a switch
jump table.

## Test: does `ActionGuideType` drive item behaviour? (2026-11-22) — no

- `Item_ScrubBusinessSeed` (value 49) is a real Triforce item ("Business Scrub Seed", X = Summon), not an unused one.
- With its PouchActorInfo row set to `ActionGuideType: Hammer`, it still did its own action. Behaviour follows the
  AssignableItem value, which the code checks.
- The AS selects on `UsingItem` (the same value), so a "hammer variant" with value 7 cannot get its own
  animations. Two items with value 7 are the same to both the code and the AS. A distinct item needs a distinct
  value **and** code that treats it as 7. That is C changes in the translated game, more than in-place `.ips` room
  allows.

## Findings for the rebuild route (2026-11-22)

- **Identity follows the value.** With `Pouch_Amiibo` set to `AssignableItem: Hammer`, the wheel lists it as
  "amiibo" (the name comes from the actor), but the equipped HUD says "Megaton Hammer / Hit" and the icon is blank.
  Two items with one value are one item to the HUD and the AS.
- **The carrier:** `Pouch_Amiibo` (value 51) has a pouch row, a pack and GameData (`IsGet`, `PouchData`). With
  `PouchSpecialDeal: None` it shows in the wheel (name "amiibo", amiibo icon). Equipped it shows "X Activate"
  (value 51 behaviour).
- **Slot layout:** the item-slot object holds the per-button assignments at +220…+244. `f_83036730` maps item to
  button: +232 gives button 7 (the use slot), +224 gives 1, +240 gives 10, and so on.
- **Animation events** (hits, sounds) are in `AnimationEvent/Animation/<anim file>.anim.baev` (BFFH), keyed by
  FNV-1a-32 of the animation name. The hammer attack's events are in `_02_H`'s file, and our `_04` animations have
  none. That also holds for v1, which plays without the hammer's hit events. Adding `FalconPunch` events needs a
  BAEV editor.
