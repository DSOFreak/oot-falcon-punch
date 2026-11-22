#!/bin/bash
# wheel.sh DIR N : open wheel, press DIR (Left/Right) until N steps registered (checked by screenshot change), stay open
cd "$(dirname "$0")"
hyprctl dispatch focuswindow class:io.github.NotRexed.Hookshot >/dev/null
wtype -P r; sleep 1.2
for i in $(seq 1 $2); do ./key.sh $1 250; sleep 0.7; done
./shot.sh w.png 0.25
