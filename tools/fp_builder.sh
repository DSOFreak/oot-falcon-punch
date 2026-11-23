#!/bin/sh
# Make/refresh a Triforce builder with code hooks (framework/): a copy of an unpacked Triforce AppImage, with the
# framework installed into its source tree. The game is then built with it:
#   tools/fp_builder.sh [/Games/TF-OOT/fpbuilder07]
#   <builder>/AppRun --cli --update <game folder>      # builds the mods' code folders in (mods/FalconPunch/code)
set -e
SRC=${FP_BUILDER_SRC:-/Games/TF-OOT/tf07/squashfs-root}   # (Triforce-v0.7.0-x86_64.AppImage --appimage-extract)
B=${1:-/Games/TF-OOT/fpbuilder07}
[ -d "$B" ] || cp -a --reflink=auto "$SRC" "$B"
python3 "$(dirname "$0")/../framework/install.py" "$B/usr/share/hookshot"
