"""Put the code hooks into a Triforce source tree (a clone, or the tree an AppImage unpacks to: usr/share/hookshot).

    python framework/install.py <tree> [--check]

New files: nx2/code_hooks.py, host/mod_api.h, host/mod_api.c. Edits of the tree's own files, each at one anchor (the
exact text below); a tree whose text differs is left as it was and the anchor is named. Run again on an installed
tree: the new files are copied again, the edits found in place are left alone. --check: says what it would do.
docs/ has what the edits are for; `diff -ru` of a tree before and after is the patch for the tree's own repository.
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
NEW = ("nx2/code_hooks.py", "host/mod_api.h", "host/mod_api.c")

# (file, the tree's text, what it becomes)
EDITS = [
    # a folder that holds only code is a mod too
    ("nx2/code_mods.py",
     'PARTS = ("romfs", "exefs", "cheats")',
     'PARTS = ("romfs", "exefs", "cheats", "code")'),
    ("host/mods.c",
     '    if ((has_romfs || has_exefs || has_cheats) && depth > 0) {',
     '    snprintf(probe, sizeof probe, "%s\\\\code", dir);   /* (a mod of built-in code alone: nx2/code_hooks.py) */\n'
     '    const int has_code = GetFileAttributesA(probe) != INVALID_FILE_ATTRIBUTES;\n'
     '    if ((has_romfs || has_exefs || has_cheats || has_code) && depth > 0) {'),
    # the game's log names the mods whose code it is built with
    ("host/mods.c",
     'void hos_mods_init(const char *image_path) {\n',
     'void hos_mods_init(const char *image_path) {\n'
     '    void hos_mod_code_report(void);   /* (mod_api.c) */\n'
     '    hos_mod_code_report();\n'),
    # the build: the mods' code folders staged before the lift's key is taken, and their hooks in the key
    ("nx2/make_game.py",
     'import code_mods as _code_mods',
     'import code_hooks as _code_hooks   # (Triforce: the mods\' own C and its hooks in the translated code)\n'
     'import code_mods as _code_mods'),
    ("nx2/make_game.py",
     '    files.append((work, os.path.join(work, "hot_funcs.txt")))\n',
     '    files.append((work, os.path.join(work, "hot_funcs.txt")))\n'
     '    files += [(work, f) for f in _code_hooks.key_files(work)]   # ((Triforce) the mods\' hooks: nx2/code_hooks.py)\n'),
    ("nx2/make_game.py",
     '    code_patches = _code_mods.build_step(exefs, out, say=lambda line: print(line, flush=True))\n',
     '    code_patches = _code_mods.build_step(exefs, out, say=lambda line: print(line, flush=True))\n'
     '    # (Triforce) code hooks: the mods\' own C (mods/<name>/code), copied to the work folder, where the lift finds the\n'
     '    # hooks (chunks.py edit_c) and the compile the files (build.py). Their hooks are in the lift\'s key (lift_key)\n'
     '    _code_hooks.stage(_code_mods.mods_folder(out), work,\n'
     '                      [m.build_id for m in _code_mods.load_modules(exefs).values()],\n'
     '                      say=lambda line: print(line, flush=True))\n'),
    # the lift: the hooks, after the port's own patches of the written C
    ("nx2/chunks.py",
     '        oot_patches.apply(gen, protect_hearts=supported, required=supported and whole)\n',
     '        oot_patches.apply(gen, protect_hearts=supported, required=supported and whole)\n'
     '        import code_hooks   # ((Triforce) the mods\' hooks, staged by make_game.py in the work folder)\n'
     '        code_hooks.apply(gen, os.environ.get("OOT_WORK") or os.path.dirname(os.path.dirname(os.path.abspath(gen))))\n'),
    # the compile: the mods' C, as the runtime's own files
    ("nx2/build.py",
     '    # libopus 1.5.2 (third_party/opus, from TOTKPort)',
     '    # (Triforce) the mods\' own C (mods/<name>/code/*.c, staged in the work folder: nx2/code_hooks.py), compiled as the\n'
     '    # runtime\'s files are, each mod with its own headers beside the runtime\'s\n'
     '    if host_srcs:\n'
     '        import code_hooks\n'
     '        for mod_obj, mod_src, mod_dir in code_hooks.sources(kit.WORK):\n'
     '            jobs.append((cc, mod_src, os.path.join(obj_dir, "modcode_" + mod_obj + ".o"), host_fl + ["-I" + mod_dir],\n'
     '                         host_deps + code_hooks.headers(mod_dir)))\n'
     '    # libopus 1.5.2 (third_party/opus, from TOTKPort)'),
    # the sound thread: the mods' sounds over the game's, with the options' sounds
    ("host/nn_audio.c",
     '    hos_menu_sound_frame(out[0], out[1], FRAME);\n',
     '    hos_menu_sound_frame(out[0], out[1], FRAME);\n'
     '    {   /* (Triforce) the mods\' sounds (mod_api.c mod_sound_play), the same way */\n'
     '        void hos_mod_sound_frame(float *left, float *right, uint32_t frames);\n'
     '        hos_mod_sound_frame(out[0], out[1], FRAME);\n'
     '    }\n'),
]


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    check = "--check" in sys.argv
    if len(args) != 1:
        raise SystemExit(__doc__)
    tree = args[0]
    if not os.path.isfile(os.path.join(tree, "nx2", "make_game.py")):
        raise SystemExit("%s is not a Triforce source tree (no nx2/make_game.py)" % tree)
    texts, todo = {}, []
    for rel, old, new in EDITS:
        if rel not in texts:
            with open(os.path.join(tree, rel), encoding="utf-8", newline="") as f:
                texts[rel] = f.read()
        text = texts[rel]
        eol = "\r\n" if "\r\n" in text else "\n"
        old, new = old.replace("\n", eol), new.replace("\n", eol)
        if new in text:
            continue
        if text.count(old) != 1:
            raise SystemExit("%s: the text to edit is there %d times, not once (another version of the tree?):\n%s"
                             % (rel, text.count(old), old))
        texts[rel] = text.replace(old, new)
        todo.append(rel)
    for rel in sorted(set(todo)):
        print("edit %s (%d places)" % (rel, todo.count(rel)))
        if not check:
            with open(os.path.join(tree, rel), "w", encoding="utf-8", newline="") as f:
                f.write(texts[rel])
    for rel in NEW:
        print("copy %s" % rel)
        if not check:
            shutil.copyfile(os.path.join(HERE, rel), os.path.join(tree, rel))
    print("checked, nothing written" if check else "installed in %s" % tree)


if __name__ == "__main__":
    main()
