#!/bin/bash
# launch.sh : start the FPTest game with the test save home; log -> game.out
cd /Games/TF-OOT/FPTest
HOOKSHOT_NO_UPDATE_CHECK=1 XDG_DATA_HOME=/Games/TF-OOT/fptest-data exec ./bin/triforce > ${GAME_OUT:-/tmp/fptest_game.out} 2>&1
