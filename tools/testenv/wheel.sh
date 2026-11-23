#!/bin/bash
# wheel.sh DIR N : open the wheel (hold RB), press DIR (Left/Right) N times, stay open (release: wtype -p r; confirm: key.sh r)
cd "$(dirname "$0")"; . ./env.sh
wtype -P r; sleep 1.2
for i in $(seq 1 $2); do ./key.sh $1 250; sleep 0.7; done
./shot.sh w.png 0.25
