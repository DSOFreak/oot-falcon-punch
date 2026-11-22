#!/bin/sh
# Make/refresh our builder copy with the Falcon Punch C patches hooked in (upstream files stay untouched).
#   tools/fp_builder.sh [/Games/TF-OOT/fpbuilder]
set -e
SRC=${FP_BUILDER_SRC:-/Games/TF-OOT/tf07/squashfs-root}   # (the extracted Triforce AppImage: --appimage-extract)
B=${1:-/Games/TF-OOT/fpbuilder07}
[ -d "$B" ] || cp -a --reflink=auto "$SRC" "$B"
N="$B/usr/share/hookshot/nx2"
cp "$(dirname "$0")/../patches/fp_patches.py" "$N/fp_patches.py"
grep -q "fp_patches" "$N/chunks.py" || sed -i 's|^\(\s*\)oot_patches.apply(gen, protect_hearts=supported, required=supported and whole)$|&\n\1import fp_patches; fp_patches.apply(gen)   # (Falcon Punch mod)|' "$N/chunks.py"
grep -n "fp_patches" "$N/chunks.py"
