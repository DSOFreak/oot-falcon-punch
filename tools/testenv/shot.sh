#!/bin/bash
# shot.sh OUT.png [scale] : screenshot of the game window
G=$(hyprctl clients -j | python3 -c "
import json,sys
for c in json.load(sys.stdin):
  if c['class']=='io.github.NotRexed.Hookshot': print(f\"{c['at'][0]},{c['at'][1]} {c['size'][0]}x{c['size'][1]}\")")
grim -g "$G" -s ${2:-0.4} "$1"
