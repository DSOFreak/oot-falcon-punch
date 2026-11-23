#!/bin/bash
# key.sh KEY [hold_ms] : press a key in the test display (the game has its focus; the real keyboard is not involved)
. "$(dirname "$0")/env.sh"
wtype -P "$1" -s ${2:-250} -p "$1"
