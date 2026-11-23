#!/bin/bash
# wheel.sh DIR N [confirm] : hold RB (wheel), press DIR (Left/Right) N times, screenshot, then release RB (selects).
# One wtype run for the whole hold: in sway a wtype's keys are released when it exits.
cd "$(dirname "$0")"; . ./env.sh
seq=(-P r -s 1500)
for i in $(seq 1 $2); do seq+=(-P $1 -s 250 -p $1 -s 450); done
wtype "${seq[@]}" -s 2500 -p r &
sleep $(python3 -c "print(1.5 + $2 * 0.7 + 1.0)")
./shot.sh w.png 0.3
wait
