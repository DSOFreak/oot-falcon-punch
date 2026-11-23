"""Launch the test game as a child and scan its guest memory on command (Yama ptrace_scope=1 lets a parent read
/proc/<child>/mem).

    uv run python tools/testenv/memscan.py CTRL_DIR &
    echo "scan 5"   > CTRL_DIR/cmd    # all aligned int32 == 5 in the guest window
    echo "filter 7" > CTRL_DIR/cmd    # keep candidates that now hold 7
    echo "show"     > CTRL_DIR/cmd
    echo "read 8a1b2c30 64" > CTRL_DIR/cmd   (guest address, bytes; hex dump to the log)
Results go to CTRL_DIR/log. The game's stdout goes to $GAME_OUT. Guest address = host - 0x100000000000.
"""
import os
import subprocess
import sys
import time

import numpy as np

BASE = 0x100000000000
GAME = "/Games/TF-OOT/FPTest"


def guest_fd(pid):
    """The guest memory is one memfd (memfd:hookshot-guest, 512 GB, sparse): file offset = guest address"""
    for fd in os.listdir(f"/proc/{pid}/fd"):
        try:
            if "hookshot-guest" in os.readlink(f"/proc/{pid}/fd/{fd}"):
                return os.open(f"/proc/{pid}/fd/{fd}", os.O_RDONLY)
        except OSError:
            pass
    raise RuntimeError("no guest memfd")


def regions(fd):
    """Populated extents of the memfd, as host addresses (BASE + guest)"""
    out, off = [], 0
    while True:
        try:
            lo = os.lseek(fd, off, os.SEEK_DATA)
        except OSError:
            break
        hi = os.lseek(fd, lo, os.SEEK_HOLE)
        out.append((BASE + lo, BASE + hi))
        off = hi
    return out


def main():
    ctrl = sys.argv[1]
    os.makedirs(ctrl, exist_ok=True)
    cmdf, logf = os.path.join(ctrl, "cmd"), os.path.join(ctrl, "log")
    fp_env = os.environ.get("FP_ENV", "/Games/TF-OOT/fptest-env")   # (same environment as env.sh: run under display.sh)
    env = dict(os.environ, HOOKSHOT_NO_UPDATE_CHECK="1", XDG_DATA_HOME="/Games/TF-OOT/fptest-data",
               XDG_CACHE_HOME=f"{fp_env}/cache", XDG_CONFIG_HOME=f"{fp_env}/config",
               __GL_SHADER_DISK_CACHE_PATH=f"{fp_env}/cache/nvidia", MESA_SHADER_CACHE_DIR=f"{fp_env}/cache/mesa",
               WAYLAND_DISPLAY="wayland-fptest", SDL_VIDEODRIVER="wayland",
               SDL_GAMECONTROLLER_IGNORE_DEVICES="0x045e/0x028e",   # (a plugged-in pad overrides keyboard RB)
               HOS_WATCH=os.path.join(ctrl, "watch"))   # (write up to 4 guest addresses there: data breakpoints, see host/posix/prof.c)
    env.pop("DISPLAY", None)
    env.pop("HYPRLAND_INSTANCE_SIGNATURE", None)
    out = open(os.environ.get("GAME_OUT", f"{fp_env}/game.out"), "wb")
    p = subprocess.Popen(["./bin/triforce"], cwd=GAME, env=env, stdout=out, stderr=subprocess.STDOUT)
    memf = gfd = None
    state_dt = ["i4"]
    cand = np.zeros(0, np.int64)

    def log(*a):
        with open(logf, "a") as f:
            print(*a, file=f, flush=True)

    def read(a, n):
        return os.pread(gfd, n, a - BASE)

    log("pid", p.pid)
    while p.poll() is None:
        time.sleep(0.3)
        if not os.path.exists(cmdf):
            continue
        line = open(cmdf).read().split()
        os.unlink(cmdf)
        if not line:
            continue
        if memf is None:
            memf = gfd = guest_fd(p.pid)
        t0 = time.time()
        try:
            if line[0] == "scan":   # scan VALUE [i4|u1]  (one 1 MB read at a time: a read fails where pages are unmapped)
                v = int(line[1], 0)
                dt = line[2] if len(line) > 2 else "i4"
                state_dt[0] = dt
                size = np.dtype(dt).itemsize
                parts = []
                for lo, hi in regions(gfd):
                    for a in range(lo, hi, 1 << 20):
                        try:
                            b = read(a, min(1 << 20, hi - a))
                        except OSError:
                            continue
                        w = np.frombuffer(b[:len(b) - len(b) % size], dtype="<" + dt if size > 1 else dt)
                        idx = np.nonzero(w == (v if dt != "i4" else np.int32(np.uint32(v & 0xFFFFFFFF))))[0]
                        if len(idx):
                            parts.append(a + size * idx.astype(np.int64))
                cand = np.sort(np.concatenate(parts)) if parts else np.zeros(0, np.int64)
            elif line[0] == "filter":
                v = int(line[1], 0)
                pages, starts = np.unique(cand >> 16, return_index=True)
                ends = list(starts[1:]) + [len(cand)]
                keep = []
                for pg, s0, s1 in zip(pages, starts, ends):
                    try:
                        page = np.frombuffer(read(int(pg) << 16, 1 << 16), dtype=np.uint8)
                    except OSError:
                        continue
                    sel = cand[s0:s1]
                    off = sel & 0xFFFF
                    if state_dt[0] == "u1":
                        got = page[off]
                    else:
                        got = page.view("<u4")[off >> 2] if True else None
                    keep.append(sel[got == (v & 0xFFFFFFFF if state_dt[0] != "u1" else v)])
                cand = np.concatenate(keep) if keep else np.zeros(0, np.int64)
            elif line[0] == "sym":   # sym NAME [bytes]: a host variable of the game binary (nm), e.g. fp_punch_equipped
                n = int(line[2], 0) if len(line) > 2 else 4
                nm = subprocess.run(["nm", f"{GAME}/bin/triforce"], capture_output=True, text=True).stdout
                off = next(int(l.split()[0], 16) for l in nm.splitlines() if l.split()[-1] == line[1])
                base = next(int(l.split("-")[0], 16) for l in open(f"/proc/{p.pid}/maps") if "bin/triforce" in l)
                with open(f"/proc/{p.pid}/mem", "rb") as m:
                    m.seek(base + off)
                    b = m.read(n)
                log(f"{line[1]} @{base + off:x}: {b.hex(' ')} ({int.from_bytes(b[:4], 'little', signed=True)})")
            elif line[0] == "watch":   # watch ADDR SECONDS: a 32-bit value sampled as fast as it reads, its changes
                a, secs = int(line[1], 16), float(line[2])
                seq, t_end = [], time.time() + secs
                while time.time() < t_end:
                    v = int.from_bytes(read(BASE + a, 4), "little", signed=True)
                    if not seq or seq[-1][1] != v:
                        seq.append((round(time.time() - t0, 2), v))
                log(f"watch {a:x}:", " ".join(f"{t}s={v}" for t, v in seq[:80]))
            elif line[0] == "write":   # write ADDR VALUE: a 32-bit value into the game's memory (an experiment's poke)
                a, v = int(line[1], 16), int(line[2], 0)
                for fd in os.listdir(f"/proc/{p.pid}/fd"):   # (the guest's memory is a memfd: its offset is the address)
                    path = f"/proc/{p.pid}/fd/{fd}"
                    try:
                        if "hookshot-guest" in os.readlink(path):
                            w = os.open(path, os.O_RDWR)
                            os.pwrite(w, (v & 0xFFFFFFFF).to_bytes(4, "little"), a)
                            os.close(w)
                            break
                    except OSError:
                        continue
                log(f"write {a:x} = {v}")
            elif line[0] == "read":
                a, n = int(line[1], 16), int(line[2], 0)
                b = read(BASE + a, n)
                for k in range(0, n, 16):
                    log(f"{a + k:08x}: {b[k:k + 16].hex(' ')}")
            if line[0] in ("scan", "filter", "show"):
                log(f"{' '.join(line)}: {len(cand)} candidates ({time.time() - t0:.1f}s)",
                    " ".join(f"{int(x) - BASE:08x}" for x in cand[:64]))
        except Exception as e:
            log("error:", repr(e))
    log("game exited", p.returncode)


if __name__ == "__main__":
    main()
