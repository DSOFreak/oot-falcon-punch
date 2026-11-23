#!/bin/bash
# key.sh KEY [hold_ms] : press a key in the test display (the game has its focus; the real keyboard is not involved)
. "$(dirname "$0")/env.sh"
wtype -s 300 -P "$1" -s ${2:-250} -p "$1" -s 300   # (waits around the key: a new virtual keyboard drops its first event, and its release must arrive before it goes)
