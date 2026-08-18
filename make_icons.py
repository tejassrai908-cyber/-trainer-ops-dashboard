#!/usr/bin/env python3
"""Generate PWA app icons (192 and 512) for the Trainer - Day Activity app."""
import math, os
from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.abspath(__file__))
ACC = (91, 157, 255)    # --acc  #5b9dff
ACC2 = (124, 92, 255)   # --acc2 #7c5cff
DARK = (4, 18, 43)      # #04122b

FONT_PATHS = [
    r"C:\Windows\Fonts\arialbd.ttf",
    r"C:\Windows\Fonts\arial.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]


def load_font(size):
    for p in FONT_PATHS:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def make_icon(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    # diagonal gradient background
    px = img.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * (size - 1)) if size > 1 else 0
            r = int(ACC[0] + (ACC2[0] - ACC[0]) * t)
            g = int(ACC[1] + (ACC2[1] - ACC[1]) * t)
            b = int(ACC[2] + (ACC2[2] - ACC[2]) * t)
            px[x, y] = (r, g, b, 255)
    # rounded corners mask
    mask = Image.new("L", (size, size), 0)
    mdraw = ImageDraw.Draw(mask)
    radius = int(size * 0.22)
    mdraw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    img.putalpha(mask)
    # draw "T"
    d = ImageDraw.Draw(img)
    font = load_font(int(size * 0.62))
    text = "T"
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    tx = (size - tw) / 2 - bbox[0]
    ty = (size - th) / 2 - bbox[1]
    d.text((tx, ty), text, font=font, fill=DARK)
    return img


if __name__ == "__main__":
    for s in (192, 512):
        out = os.path.join(BASE, "icon-%d.png" % s)
        make_icon(s).save(out)
        print("wrote", out)
