"""sheet.py DIR OUT.png [cols] [every] : contact sheet of a burst (burst.sh), centre crop, every n-th frame"""
import glob
import sys

from PIL import Image

fs = sorted(glob.glob(sys.argv[1] + "/f_*.ppm"))[::int(sys.argv[4]) if len(sys.argv) > 4 else 1]
cols = int(sys.argv[3]) if len(sys.argv) > 3 else 6
ims = []
for f in fs:
    im = Image.open(f)
    w, h = im.size
    ims.append(im.crop((w // 4, h // 8, 3 * w // 4, 7 * h // 8)).resize((w // 6, h // 6 * 3 // 4 * 4 // 3)))
cw, ch = ims[0].size
s = Image.new("RGB", (cw * cols, ch * ((len(ims) + cols - 1) // cols)))
for i, im in enumerate(ims):
    s.paste(im, ((i % cols) * cw, (i // cols) * ch))
s.save(sys.argv[2])
print(len(ims), "frames")
