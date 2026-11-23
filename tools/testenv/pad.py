"""A virtual gamepad (uinput) for the test game: the game's own controls, as the user plays them, without guessing the
keyboard bindings. It exists only while a sequence runs (made, used, removed), so it is not left behind.

    uv run --with evdev python tools/testenv/pad.py "ZR 150; wait 1500; X 150; wait 2000"

Steps: NAME [ms] presses a button (default 120 ms), NAME+NAME [ms] presses them together, "hold NAME" / "release
NAME", "wait ms", "stick X Y ms" (left stick, -1..1), "rstick X Y ms" (right stick: the camera),
"tilt X Y" (the left stick held there until the next tilt). Names are the Switch buttons (Triforce maps the pad by
position: A east, B south, X north, Y west): A B X Y L R ZL ZR PLUS MINUS UP DOWN LEFT RIGHT LS RS.
Note: any SDL program running at the time sees the pad (only the test game should be running).
"""
import sys
import time

from evdev import AbsInfo, UInput, ecodes as e

# (as the Linux xpad driver reports an Xbox pad, which SDL's mapping for these ids expects: the Xbox Y button, north,
#  is BTN_Y = BTN_WEST's code, the Xbox X button, west, is BTN_X = BTN_NORTH's code; Switch X is north, Y west)
BTN = {"A": e.BTN_EAST, "B": e.BTN_SOUTH, "X": e.BTN_Y, "Y": e.BTN_X, "L": e.BTN_TL, "R": e.BTN_TR,
       "PLUS": e.BTN_START, "MINUS": e.BTN_SELECT, "LS": e.BTN_THUMBL, "RS": e.BTN_THUMBR, "HOME": e.BTN_MODE}
TRIG = {"ZL": e.ABS_Z, "ZR": e.ABS_RZ}
HAT = {"UP": (e.ABS_HAT0Y, -1), "DOWN": (e.ABS_HAT0Y, 1), "LEFT": (e.ABS_HAT0X, -1), "RIGHT": (e.ABS_HAT0X, 1)}
STICK = AbsInfo(0, -32768, 32767, 16, 128, 0)
CAPS = {
    e.EV_KEY: list(BTN.values()),
    e.EV_ABS: [(e.ABS_X, STICK), (e.ABS_Y, STICK), (e.ABS_RX, STICK), (e.ABS_RY, STICK),
               (e.ABS_Z, AbsInfo(0, 0, 255, 0, 0, 0)), (e.ABS_RZ, AbsInfo(0, 0, 255, 0, 0, 0)),
               (e.ABS_HAT0X, AbsInfo(0, -1, 1, 0, 0, 0)), (e.ABS_HAT0Y, AbsInfo(0, -1, 1, 0, 0, 0))],
}


def set_(ui, name, down):
    if name in BTN:
        ui.write(e.EV_KEY, BTN[name], 1 if down else 0)
    elif name in TRIG:
        ui.write(e.EV_ABS, TRIG[name], 255 if down else 0)
    elif name in HAT:
        ax, v = HAT[name]
        ui.write(e.EV_ABS, ax, v if down else 0)
    else:
        raise SystemExit(f"unknown button {name}")
    ui.syn()


def run(ui, script):
    for step in [s.strip() for s in script.split(";") if s.strip()]:
        w = step.split()
        if w[0] == "wait":
            time.sleep(int(w[1]) / 1000)
        elif w[0] in ("hold", "release"):
            set_(ui, w[1], w[0] == "hold")
        elif w[0] == "tilt":   # (the left stick held there until another tilt: "tilt 0 1; ZR; tilt 0 0")
            ui.write(e.EV_ABS, e.ABS_X, int(float(w[1]) * 32767))
            ui.write(e.EV_ABS, e.ABS_Y, int(-float(w[2]) * 32767))
            ui.syn()
        elif w[0] in ("stick", "rstick"):   # (rstick: the camera)
            ax, ay = (e.ABS_X, e.ABS_Y) if w[0] == "stick" else (e.ABS_RX, e.ABS_RY)
            ui.write(e.EV_ABS, ax, int(float(w[1]) * 32767))
            ui.write(e.EV_ABS, ay, int(-float(w[2]) * 32767))
            ui.syn()
            time.sleep(int(w[3]) / 1000)
            ui.write(e.EV_ABS, ax, 0)
            ui.write(e.EV_ABS, ay, 0)
            ui.syn()
        else:
            names = w[0].split("+")
            for n in names:
                set_(ui, n, True)
            time.sleep((int(w[1]) if len(w) > 1 else 120) / 1000)
            for n in names:
                set_(ui, n, False)
        time.sleep(0.05)


def main():
    # (an Xbox One S pad's ids: SDL knows its layout; the user's own pad, 045e:028e, stays ignored by the test game)
    with UInput(CAPS, name="Microsoft X-Box One S pad", vendor=0x045E, product=0x02EA, version=0x0301,
                bustype=e.BUS_USB) as ui:
        time.sleep(float(sys.argv[2]) if len(sys.argv) > 2 else 2.0)   # (the game picks the pad up)
        run(ui, sys.argv[1])
        time.sleep(0.3)


if __name__ == "__main__":
    main()
