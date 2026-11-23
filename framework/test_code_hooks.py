"""Tests of nx2/code_hooks.py that need no game: the format, staging, the edits of lifted C.

    python framework/test_code_hooks.py [<tree>/nx2]     # the tree's nx2 for its code_mods.py; else a stand-in
"""
import json
import os
import sys
import tempfile
import types
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "nx2"))
if len(sys.argv) > 1 and os.path.isdir(sys.argv[1]):
    sys.path.insert(1, sys.argv.pop(1))
try:
    import code_mods  # noqa: F401
except ImportError:   # (a stand-in with what code_hooks uses: one level of mod folders)
    m = types.ModuleType("code_mods")
    m.find_mods = lambda root: sorted((n, os.path.join(root, n)) for n in (os.listdir(root) if os.path.isdir(root) else [])
                                      if n[:1] not in ".-_" and os.path.isdir(os.path.join(root, n)))
    sys.modules["code_mods"] = m
import code_hooks as H  # noqa: E402

BUILD = "e0f3ccfaf50065ae4ea01eb5aeb13b1a45da3348000000000000000000000000"
LIFTED = '''#include "a64.h"
void f_80001000(Ctx *A64_NOESC);
void f_80001000(Ctx *__restrict A64_NOESC c) {
    c->x[2]=recomp_load32(c,c->x[0] + 2008);
c->x[30] = 0x80001010ULL; f_80002000(c);
{ uint64_t _t = c->x[8]; c->x[30] = 0x80001020ULL; A64_ICALL(c, _t); }
    A64_IJUMP(c, c->x[3]); return;
}
void f_80002000(Ctx *__restrict A64_NOESC c) {
    c->x[0] = 0x1ULL;
    return;
}
'''


class Parse(unittest.TestCase):
    def test_kinds(self):
        build, hooks = H.parse("game E0F3CCFAF50065AE\nbefore 0x80002000 a   # note\nafter 0x80002000 b\n"
                               "after-call 0x80002000 c in 0x80001000 0x80003000\nbefore-icall 0x80001000 d\n"
                               "load32 0x7d8 e in 0x80001000\n")
        self.assertEqual(build, "E0F3CCFAF50065AE")
        self.assertEqual([h["kind"] for h in hooks], list(H.KINDS))
        self.assertEqual(hooks[2]["callee"], "f_80002000")
        self.assertEqual(hooks[2]["functions"], ["f_80001000", "f_80003000"])
        self.assertEqual(hooks[4]["offset"], 0x7d8)

    def test_refused(self):
        for text in ("before 0x80002000 a\n",                       # no game line
                     "game 1234\n",                                 # too short an id
                     "game E0F3CCFAF50065AE\nbefore f_80002000 a\n",   # not an address
                     "game E0F3CCFAF50065AE\nbefore 0x80002000 f_1\n",  # a game function's name as the hook
                     "game E0F3CCFAF50065AE\nbefore 0x80002000 a b\n",
                     "game E0F3CCFAF50065AE\nload32 x e in 0x80001000\n",
                     "game E0F3CCFAF50065AE\nafter-call 0x80002000 c 0x80001000\n",
                     "game E0F3CCFAF50065AE\nsometimes 0x80002000 a\n"):
            with self.assertRaises(H.Refused, msg=text):
                H.parse(text)


class Build(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.mods, self.work, self.gen = (os.path.join(self.tmp.name, d) for d in ("mods", "work", "gen"))
        os.makedirs(self.gen)
        os.makedirs(self.work)
        with open(os.path.join(self.gen, "code_000.c"), "w") as f:
            f.write(LIFTED)

    def tearDown(self):
        self.tmp.cleanup()

    def mod(self, name, hooks, c="void x(void) {}\n"):
        d = os.path.join(self.mods, name, "code")
        os.makedirs(d)
        with open(os.path.join(d, "hooks.txt"), "w") as f:
            f.write(hooks)
        if c is not None:
            with open(os.path.join(d, "m.c"), "w") as f:
                f.write(c)

    def lifted(self):
        with open(os.path.join(self.gen, "code_000.c")) as f:
            return f.read()

    def test_no_mods(self):
        self.assertEqual(H.stage(self.mods, self.work, [BUILD], say=lambda s: None), [])
        self.assertEqual(H.key_files(self.work), [])
        self.assertEqual(H.apply(self.gen, self.work), 0)
        self.assertEqual(self.lifted(), LIFTED)

    def test_all_kinds(self):
        self.mod("A", "game E0F3CCFAF50065AE\nbefore 0x80002000 a\nafter 0x80002000 b\n"
                      "after-call 0x80002000 c in 0x80001000\nbefore-icall 0x80001000 d\nload32 2008 e in 0x80001000\n")
        said = []
        entries = H.stage(self.mods, self.work, [BUILD], say=said.append)
        self.assertEqual([(e["mod"], e["state"], e["hooks"]) for e in entries], [("A", "built in", 5)])
        self.assertEqual(len(H.key_files(self.work)), 1)
        self.assertEqual([s[0] for s in H.sources(self.work)], ["00_A_m", "table"])
        H.apply(self.gen, self.work, say=said.append)
        out = self.lifted()
        self.assertIn("c->x[2]=e(c, recomp_load32(c,c->x[0] + 2008), c->x[0] + 2008);", out)
        self.assertIn("c->x[30] = 0x80001010ULL; f_80002000(c); c(c);", out)
        self.assertIn("{ d(c); { uint64_t _t = c->x[8]; c->x[30] = 0x80001020ULL; A64_ICALL(c, _t); } }", out)
        self.assertIn("{ d(c); A64_IJUMP(c, c->x[3]); return; }", out)
        self.assertIn("void mod_hooked_f_80002000(Ctx *__restrict A64_NOESC c) {\n    c->x[0] = 0x1ULL;", out)
        self.assertIn("void f_80002000(Ctx *__restrict A64_NOESC c) {\n    if (a(c)) return;\n"
                      "    mod_hooked_f_80002000(c);\n    b(c);\n}\n", out)
        self.assertIn("extern int a(Ctx *c);", out)
        self.assertIn("extern uint64_t e(Ctx *c, uint64_t value, uint64_t address);", out)
        self.assertEqual(out.count("void f_80001000(Ctx *__restrict A64_NOESC c) {"), 1)

    def test_other_build_and_off(self):
        self.mod("A", "game 0123456789ABCDEF\nbefore 0x80002000 a\n")
        self.mod("-B", "game E0F3CCFAF50065AE\nbefore 0x80002000 a\n")
        said = []
        entries = H.stage(self.mods, self.work, [BUILD], say=said.append)
        self.assertEqual([(e["mod"], e["state"]) for e in entries], [("A", "refused")])
        self.assertIn("another build", said[0])
        self.assertEqual(H.apply(self.gen, self.work), 0)
        self.assertEqual(self.lifted(), LIFTED)

    def test_no_place_stops(self):
        self.mod("A", "game E0F3CCFAF50065AE\nafter-call 0x80009999 c in 0x80001000\n")
        H.stage(self.mods, self.work, [BUILD], say=lambda s: None)
        with self.assertRaises(H.Refused):
            H.apply(self.gen, self.work)
        self.assertEqual(self.lifted(), LIFTED)

    def test_no_function_stops(self):
        self.mod("A", "game E0F3CCFAF50065AE\nbefore 0x80007777 a\n")
        H.stage(self.mods, self.work, [BUILD], say=lambda s: None)
        with self.assertRaises(H.Refused):
            H.apply(self.gen, self.work)

    def test_two_mods_order(self):
        self.mod("A", "game E0F3CCFAF50065AE\nbefore 0x80002000 a\n")
        self.mod("B", "game E0F3CCFAF50065AE\nbefore 0x80002000 b\n")
        H.stage(self.mods, self.work, [BUILD], say=lambda s: None)
        H.apply(self.gen, self.work, say=lambda s: None)
        self.assertIn("    if (a(c)) return;\n    if (b(c)) return;\n    mod_hooked_f_80002000(c);\n", self.lifted())

    def test_restage_drops_a_removed_mod(self):
        self.mod("A", "game E0F3CCFAF50065AE\nbefore 0x80002000 a\n")
        H.stage(self.mods, self.work, [BUILD], say=lambda s: None)
        os.rename(os.path.join(self.mods, "A"), os.path.join(self.mods, "_A"))
        H.stage(self.mods, self.work, [BUILD], say=lambda s: None)
        self.assertEqual(H.key_files(self.work), [])
        self.assertEqual(H.sources(self.work), [])

    def test_hooks_without_c(self):
        self.mod("A", "game E0F3CCFAF50065AE\nbefore 0x80002000 a\n", c=None)
        entries = H.stage(self.mods, self.work, [BUILD], say=lambda s: None)
        self.assertEqual(entries[0]["state"], "refused")


if __name__ == "__main__":
    unittest.main()
