#!/bin/bash
# key.sh KEY [hold_ms] : press a key in the focused game window
wtype -P "$1" -s ${2:-120} -p "$1"
