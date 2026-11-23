#!/bin/bash
# shot.sh OUT.png [scale] : screenshot of the test display (the game is fullscreen there)
. "$(dirname "$0")/env.sh"
grim -s ${2:-0.4} "$1"
