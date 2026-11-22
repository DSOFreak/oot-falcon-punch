# gdb -q -batch -x tools/testenv/gdbscan.py   (run from /Games/TF-OOT/FPTest; see docs/test_environment.md)
#
# Runs the test game under gdb, which allows reading its memory with Yama ptrace_scope=1. Each SIGUSR2 sent to
# the game stops it. gdb then runs the Python in $GDBSCAN_CMD (one file, re-read at every stop; it gets `mem`,
# `regions`, `state`) and continues. Guest memory is at host 0x100000000000 + guest address.
import os

import gdb

CMD = os.environ.get("GDBSCAN_CMD", "/tmp/gdbscan_cmd.py")
LOG = os.environ.get("GDBSCAN_LOG", "/tmp/gdbscan.log")
BASE = 0x100000000000
state = {}


def log(*a):
    with open(LOG, "a") as f:
        print(*a, file=f)


def regions():
    """rw mappings inside the guest window, as (host_start, host_end)"""
    pid = gdb.selected_inferior().pid
    out = []
    for line in open(f"/proc/{pid}/maps"):
        parts = line.split()
        lo, hi = (int(x, 16) for x in parts[0].split("-"))
        if BASE <= lo < BASE + (1 << 32) and parts[1].startswith("rw"):
            out.append((lo, hi))
    return out


def mem(lo, n):
    pid = gdb.selected_inferior().pid
    with open(f"/proc/{pid}/mem", "rb") as f:
        f.seek(lo)
        return f.read(n)


for sig in ("SIGSEGV", "SIGBUS", "SIGTRAP", "SIGPIPE") + tuple(f"SIG{n}" for n in range(32, 65)):
    try:
        gdb.execute(f"handle {sig} nostop noprint pass", to_string=True)
    except gdb.error:
        pass
gdb.execute("handle SIGUSR2 stop noprint nopass", to_string=True)
gdb.execute("set pagination off")
gdb.execute("set confirm off")
gdb.execute("set startup-with-shell off")
gdb.execute("set environment HOOKSHOT_NO_UPDATE_CHECK=1")
gdb.execute("set environment XDG_DATA_HOME=/Games/TF-OOT/fptest-data")
gdb.execute("file ./bin/triforce")
log("starting")
gdb.execute("run > " + os.environ.get("GAME_OUT", "/tmp/fptest_game.out") + " 2>&1")
while True:
    try:
        inf = gdb.selected_inferior()
        if not inf.pid:
            log("exited")
            break
        try:
            code = open(CMD).read()
            exec(compile(code, CMD, "exec"), {"gdb": gdb, "mem": mem, "regions": regions, "state": state,
                                              "log": log, "BASE": BASE})
        except Exception as e:  # keep the game running whatever the command does
            import traceback
            log("cmd error:", traceback.format_exc())
        gdb.execute("continue")
    except gdb.error as e:
        log("gdb error:", e)
        break
