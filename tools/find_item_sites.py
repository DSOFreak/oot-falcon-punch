"""Find the functions that use the player's current-item field (player+0x7d8) as an item value.

    uv run python tools/find_item_sites.py   ->  patches/fp_item_functions.txt

player+0x7d8 holds the stored AssignableItem value (Hammer 7, Deku Stick 0, amiibo 51...): the item-use states compare
it (f_80a5f750: cmp #7, f_80a61414: cmp #0x33, bit masks of arrows...). Other classes keep a flag word at the same
offset (and/orr/tbz on it), so only loads whose value is used as an item (cmp/sub/ccmp/cbz/shift amount) or copied
count; patches/fp_patches.py maps 51 -> 7 at every +0x7d8 load of these functions.
"""
import bisect
import json
import sys
from pathlib import Path

import capstone
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import a64  # noqa: E402

md = capstone.Cs(capstone.CS_ARCH_ARM64, capstone.CS_MODE_ARM)
md.skipdata = True


def main():
    w = a64.words()
    imm = 0x7d8 // 4
    loads = np.nonzero((w & 0xFFFFFC00) == (0xB9400000 | (imm << 10)))[0]   # ldr wT, [xN, #0x7d8]
    fj = json.load(open(ROOT / "liftwork/image/functions.json"))
    starts = sorted(int(k, 16) for k in fj)
    item, flags = set(), set()
    for i in loads:
        a = a64.BASE + int(i) * 4
        f = starts[bisect.bisect_right(starts, a) - 1]
        ins = list(md.disasm(a64.data()[a - a64.BASE:a - a64.BASE + 32], a))
        reg = ins[0].op_str.split(",")[0]
        for x in ins[1:]:
            if reg not in x.op_str:
                continue
            m = x.mnemonic
            if m in ("and", "orr", "eor", "tbz", "tbnz", "bfi", "bfxil", "ubfx", "tst"):
                flags.add(f)
            elif m in ("cmp", "sub", "subs", "ccmp", "cmn", "cbz", "cbnz") or (m in ("lsl", "lsr") and x.op_str.endswith(reg)):
                item.add(f)
            break
    keep = sorted(item - flags)
    out = ROOT / "patches/fp_item_functions.txt"
    out.write_text("# functions whose loads of player+0x7d8 get fp_item() (tools/find_item_sites.py)\n" +
                   "".join(f"f_{f:08x}\n" for f in keep))
    print(f"{len(keep)} functions ({len(item & flags)} left out: they also use +0x7d8 as flags) -> {out}")


if __name__ == "__main__":
    main()
