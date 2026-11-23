#!/bin/bash
# restart.sh : (re)start the test game under memscan in the test environment and load the newest save (about 2 min)
cd "$(dirname "$0")"; . ./env.sh
pkill -9 -x triforce; sleep 1
for p in $(pgrep -x 'python|python3|python3\.[0-9]+'); do grep -qa "memscan" /proc/$p/cmdline 2>/dev/null && kill $p; done   # (by process name: a pattern on full command lines also matches the calling shell)
./display.sh start >/dev/null
C=$FP_ENV/ctrl; mkdir -p $C; rm -f $C/cmd $C/log $GAME_OUT
( setsid uv run python memscan.py $C > $FP_ENV/memscan.out 2>&1 & )
sleep 5; pgrep -x triforce | xargs -r renice -n 10 -p >/dev/null
until grep -a -q "startup logo finished" $GAME_OUT 2>/dev/null; do sleep 3; pgrep -x triforce >/dev/null || { echo "game exited"; tail -5 $GAME_OUT; exit 1; }; done
sleep 20; ./key.sh e; sleep 4; ./key.sh e; sleep 3; ./key.sh e; sleep 3; ./key.sh e; sleep 40
./shot.sh g.png 0.3
