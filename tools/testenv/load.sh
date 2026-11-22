#!/bin/bash
# wait for title (log line) then Continue + newest slot
cd "$(dirname "$0")"
timeout 400 bash -c 'until grep -a -q "startup logo finished" game.out; do sleep 3; done'
sleep 20; hyprctl dispatch focuswindow class:io.github.NotRexed.Hookshot >/dev/null; sleep 1
./key.sh e; sleep 4; ./key.sh e; sleep 3; ./key.sh e; sleep 2; ./key.sh e; sleep 35; ./shot.sh w.png 0.25
