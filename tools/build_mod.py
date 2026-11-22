"""Build the mod's RomFS from the player's own game files.

Output: out/mod/FalconPunch/romfs/... (git-ignored: it is built from game data). Copy the FalconPunch folder into
<game folder>/mods/ to use it.

    uv run python tools/retarget_falcon_link.py      # once: out/retarget/falcon_punch_link_*.json
    uv run python tools/build_mod.py [--v1 | --replace-hammer] [--romfs ...] [--out out/mod/FalconPunch]

Modes:
  (default)         the Falcon Punch item: anims FalconPunch* in _04, the AS with [51] branches (tools/build_asb.py),
                    the Pouch_Amiibo row turned into the item. Needs the code patches (patches/fp_patches.py).
  --replace-hammer  test: the same files, but the hammer's own vertical attack (UsingItem 7) plays the punch through
                    the AS. No code change needed: checks the AS editor in game.
  --v1              the first version: the hammer's vertical attack animations renamed in _02_H and the punch added
                    under their names to _04 (no AS change).
"""
import argparse
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import restbl  # noqa: E402
import zs  # noqa: E402

P02 = "Model/Player_Adult_02_H_Animation.anim.bfres"
P04 = "Model/Player_Adult_04_Animation.anim.bfres"
ASB = "AS/Player_Adult.root.asb"
ASNODE = "AnimationEvent/AsNode/Player_Adult.root.baev"
V1_ANIMS = {
    "Hammer_Attack_Vertical_Advance": "falcon_punch_link_ground.json",
    "Hammer_Attack_Vertical_AdvanceZero": "falcon_punch_link_ground_advancezero.json",
}
ANIMS = {   # (time-warped to the hammer attack's AS event timing: tools/retarget_falcon_link.py HAMMER_KNOTS)
    "FalconPunch": "falcon_punch_link_ground_hammertimed.json",
    "FalconPunch_AdvanceZero": "falcon_punch_link_ground_advancezero_hammertimed.json",
    "FalconPunch_Air": "falcon_punch_link_air_hammertimed.json",
    "FalconPunch_After": "falcon_punch_link_after.json",   # (tools/make_recovery.py)
}


RSDB_POUCH = "RSDB/PouchActorInfo.Product.111.rstbl.byml"
CARRIER = "Pouch_Amiibo"   # the item row/actor the Falcon Punch takes over (stored AssignableItem value 51)
ITEM_ROW = {"PouchSpecialDeal": "None", "ActionGuideType": "Hammer", "PouchGetType": "Large"}
ITEM_ROW_DROP = ("IsUsableSelectItemInWater",)
TEXT = {   # Mals/<lang>.Product.110.sarc -> ActorMsg/PouchContent.msbt
    f"{CARRIER}_Name": "Falcon Punch",
    f"{CARRIER}_Caption": "Gather the power of the falcon in\nyour fist and unleash it in one\ndevastating, fiery punch!",
}
TEXT_LANGS = ("USen", "EUen")


def item_data(romfs, out, t):
    """The carrier row in PouchActorInfo (plain zstd, no dictionary) and the item's name/caption"""
    import byml7
    import oead
    import zstandard
    import msbt
    rows = byml7.load(zs.load(str(romfs / (RSDB_POUCH + ".zs"))))
    for r in rows:
        if str(r["__RowId"]) == CARRIER:
            for k, v in ITEM_ROW.items():
                r[k] = v
            for k in ITEM_ROW_DROP:
                if k in r:
                    del r[k]
    raw = byml7.dump(rows)
    (out / "RSDB").mkdir(parents=True, exist_ok=True)
    (out / (RSDB_POUCH + ".zs")).write_bytes(zstandard.ZstdCompressor(level=19).compress(raw))
    grow(t, RSDB_POUCH, len(zs.load(str(romfs / (RSDB_POUCH + ".zs")))), len(raw))
    for lang in TEXT_LANGS:
        rel = f"Mals/{lang}.Product.110.sarc"
        old = zs.load(str(romfs / (rel + ".zs")))
        sarc = oead.Sarc(old)
        w = oead.SarcWriter.from_sarc(sarc)
        m = msbt.Msbt(bytes(sarc.get_file("ActorMsg/PouchContent.msbt").data))
        for label, text in TEXT.items():
            m.set_text(label, text)
        w.files["ActorMsg/PouchContent.msbt"] = m.to_bytes()
        new = bytes(w.write()[1])
        (out / "Mals").mkdir(parents=True, exist_ok=True)
        (out / (rel + ".zs")).write_bytes(zs.compress(new, "x.sarc.zs"))
        grow(t, rel, len(old), len(new))


ICON_SRC = "Armor_Adult_Gauntlet_Gold"   # stand-in icon (a fist) until a drawn one exists


def item_icon(romfs, out, t, name=CARRIER):
    """UI/Tex/Icon/<carrier>.bntx: a copy of ICON_SRC with its texture renamed (the name is stored once, at the
    string table: u16 length + text; the new name is shorter, the rest is zero-padded). New file: new RESTBL entry,
    the source entry's overhead over its file size kept"""
    src_rel, rel = f"UI/Tex/Icon/{ICON_SRC}.bntx", f"UI/Tex/Icon/{name}.bntx"
    d = bytearray(zs.load(str(romfs / (src_rel + ".zs"))))
    old = ICON_SRC.encode()
    i = d.find(old)
    assert i > 0 and d.find(old, i + 1) < 0 and struct.unpack_from("<H", d, i - 2)[0] == len(old), "icon name layout"
    assert len(name) <= len(old)
    struct.pack_into("<H", d, i - 2, len(name))
    d[i:i + len(old)] = name.encode().ljust(len(old), b"\0")
    (out / rel).parent.mkdir(parents=True, exist_ok=True)
    (out / (rel + ".zs")).write_bytes(zs.compress(bytes(d), "x.bntx.zs"))
    if t.get(rel) is None:
        t.set(rel, t.get(src_rel))
        print(f"RESTBL {rel}: new entry {t.get(rel)}")


def hide_names(data, names):
    d = bytearray(data)
    for n in names:
        s = n.encode() + b"\0"
        i = d.find(s)
        assert i > 0 and d.find(s, i + 1) < 0, n
        d[i + len(s) - 2:i + len(s) - 1] = b"Q"
    return bytes(d)


def add_anims(p04, anims, work):
    (work / "p04_orig.bfres").write_bytes(p04)
    cur = work / "p04_orig.bfres"
    for i, (name, js) in enumerate(anims.items()):
        nxt = work / f"p04_{i}.bfres"
        subprocess.run([sys.executable, str(ROOT / "tools/bfres_add_anim.py"), "json", str(cur), str(nxt), name,
                        str(ROOT / "out/retarget" / js), "--fill", f"{work / 'p04_orig.bfres'}:Wait"], check=True)
        cur = nxt
    return cur.read_bytes()


def grow(t, rel, old_size, new_size):
    e = t.get(rel)
    t.set(rel, e + max(0, new_size - old_size))
    print(f"RESTBL {rel}: {e} -> {t.get(rel)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--romfs", default="/Games/TF-OOT/Hookshot/romfs")
    ap.add_argument("--out", default=str(ROOT / "out/mod/FalconPunch"))
    ap.add_argument("--v1", action="store_true")
    ap.add_argument("--replace-hammer", action="store_true")
    a = ap.parse_args()
    romfs, out = Path(a.romfs), Path(a.out) / "romfs"
    work = ROOT / "out/mod/work"
    work.mkdir(parents=True, exist_ok=True)
    (out / "Model").mkdir(parents=True, exist_ok=True)
    t = restbl.load(romfs)

    p04 = zs.load(str(romfs / (P04 + ".zs")))
    if a.v1:
        p02 = zs.load(str(romfs / (P02 + ".zs")))
        new04 = add_anims(p04, V1_ANIMS, work)
        (out / (P02 + ".zs")).write_bytes(zs.compress(hide_names(p02, V1_ANIMS), "x.bfres.zs"))
    else:
        (out / (P02 + ".zs")).unlink(missing_ok=True)
        new04 = add_anims(p04, ANIMS, work)
        baev_src = work / "Player_Adult.root.baev.orig"
        baev_src.write_bytes(zs.load(str(romfs / (ASNODE + ".zs"))))
        cmd = [sys.executable, str(ROOT / "tools/build_asb.py"), "--src", str(work / "Player_Adult.root.asb.orig"),
               "--out", str(work / "Player_Adult.root.asb"), "--baev-src", str(baev_src),
               "--baev-out", str(work / "Player_Adult.root.baev")]
        (work / "Player_Adult.root.asb.orig").write_bytes(zs.load(str(romfs / (ASB + ".zs"))))
        if a.replace_hammer:
            cmd.append("--replace-hammer")
        subprocess.run(cmd, check=True)
        asb_old = zs.load(str(romfs / (ASB + ".zs")))
        asb_new = (work / "Player_Adult.root.asb").read_bytes()
        (out / "AS").mkdir(exist_ok=True)
        (out / (ASB + ".zs")).write_bytes(zs.compress(asb_new, "x.asb.zs"))
        grow(t, ASB, len(asb_old), len(asb_new))
        baev_new = (work / "Player_Adult.root.baev").read_bytes()
        if baev_new != baev_src.read_bytes():
            (out / ASNODE).parent.mkdir(parents=True, exist_ok=True)
            (out / (ASNODE + ".zs")).write_bytes(zs.compress(baev_new, "x.baev.zs"))
            grow(t, ASNODE, baev_src.stat().st_size, len(baev_new))
        if not a.replace_hammer:
            item_data(romfs, out, t)
            item_icon(romfs, out, t)
    (out / (P04 + ".zs")).write_bytes(zs.compress(new04, "x.bfres.zs"))
    grow(t, P04, len(p04), len(new04))
    (out / restbl.REL).parent.mkdir(parents=True, exist_ok=True)
    restbl.save(t, out / restbl.REL)
    print("mod written to", out.parent)


if __name__ == "__main__":
    main()
