#!/bin/bash
# hit.sh [OUT.png] : with the item equipped (not drawn): pad ZR (draw), ZR (hit); a burst over the hit -> contact sheet
cd "$(dirname "$0")"; . ./env.sh
B=$FP_ENV/burst
(uv run --with evdev python pad.py "ZR 100; wait 2200; ZR 100; wait 3000" 2.5 > $FP_ENV/pad.out 2>&1 &)
sleep 5.2; ./burst.sh $B 70 0.02
uv run --with pillow python - "$B" "${1:-sheet.png}" <<'PY'
import glob, sys
from PIL import Image
fs = sorted(glob.glob(sys.argv[1] + "/f_*.ppm"))[::2][:36]
ims = [Image.open(f).crop((560, 250, 1360, 950)).resize((320, 280)) for f in fs]
s = Image.new("RGB", (320 * 6, 280 * 6))
for i, im in enumerate(ims):
    s.paste(im, ((i % 6) * 320, (i // 6) * 280))
s.save(sys.argv[2])
PY
