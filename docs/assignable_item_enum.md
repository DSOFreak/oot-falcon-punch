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
