#!/bin/bash
# mem.sh CMD... : one command to the running memscan (tools/testenv/memscan.py), its answer from the log
cd "$(dirname "$0")"; . ./env.sh
C=$FP_ENV/ctrl; n=$(wc -l < $C/log 2>/dev/null || echo 0)
echo "$*" > $C/cmd
for i in $(seq 1 200); do sleep 0.3; [ -e $C/cmd ] || { sleep 0.3; break; }; done
tail -n +$((n + 1)) $C/log
