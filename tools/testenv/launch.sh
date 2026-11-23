#!/bin/bash
# launch.sh : start the FPTest game in the test environment (headless sway, own caches, test saves); log -> $GAME_OUT
. "$(dirname "$0")/env.sh"
"$(dirname "$0")/display.sh" start >/dev/null || exit 1
cd $FP_GAME
game_env ./bin/triforce > $GAME_OUT 2>&1
