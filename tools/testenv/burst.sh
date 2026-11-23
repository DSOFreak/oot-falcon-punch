#!/bin/bash
# burst.sh DIR N [interval_s] : N unscaled frames of the test display into DIR (raw ppm: about 40 ms each; grim's
# scaling is the slow part, so sheet.py scales afterwards)
. "$(dirname "$0")/env.sh"
mkdir -p "$1"; rm -f "$1"/f_*.ppm
for i in $(seq -w 0 $(($2 - 1))); do grim -t ppm "$1/f_$i.ppm"; [ -n "$3" ] && sleep $3; done
