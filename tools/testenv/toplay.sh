#!/bin/bash
# toplay.sh : wait for title, Continue, load newest slot, wait in game
cd "$(dirname "$0")"; . ./env.sh
until grep -a -q "startup logo finished" $GAME_OUT 2>/dev/null; do sleep 2; done
for i in $(seq 1 60); do ./shot.sh t.png 0.1; m=$(uv run --with pillow python -c "from PIL import Image,ImageStat;print(int(sum(ImageStat.Stat(Image.open('t.png').convert('L')).mean)))" 2>/dev/null); [ "${m:-0}" -gt 25 ] && break; sleep 3; done
sleep 2; ./key.sh e; sleep 4; ./key.sh e; sleep 3; ./key.sh e; sleep 2; ./key.sh e; sleep 30
./shot.sh g.png
