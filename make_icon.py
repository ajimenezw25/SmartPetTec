"""
make_icon.py
------------
Converts static/img/smartpethome-icon.png to smartpet-icon.ico
with the standard Windows icon sizes.

Run:  python make_icon.py
Requires: Pillow  (pip install Pillow)
"""

import sys
import os

try:
    from PIL import Image
except ImportError:
    print("[ERROR] Pillow is not installed. Run:  pip install Pillow")
    sys.exit(1)

_here   = os.path.dirname(os.path.abspath(__file__))
_src    = os.path.join(_here, "static", "img", "smartpethome-icon.png")
_dst    = os.path.join(_here, "smartpet-icon.ico")

_SIZES  = [16, 24, 32, 48, 64, 128, 256]

if not os.path.exists(_src):
    print(f"[ERROR] Source PNG not found: {_src}")
    sys.exit(1)

img = Image.open(_src).convert("RGBA")

frames = []
for size in _SIZES:
    frame = img.copy()
    frame.thumbnail((size, size), Image.LANCZOS)
    # Pad to exact square if thumbnail shrank one axis
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    offset = ((size - frame.width) // 2, (size - frame.height) // 2)
    canvas.paste(frame, offset, frame)
    frames.append(canvas)

frames[0].save(
    _dst,
    format="ICO",
    sizes=[(s, s) for s in _SIZES],
    append_images=frames[1:],
)

print(f"[OK] Icon written to: {_dst}")
print(f"     Sizes: {_SIZES}")
