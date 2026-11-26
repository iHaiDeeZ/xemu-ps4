#!/usr/bin/env python3
"""The README's banner (docs/images/banner.png, 1600x480): green rings of light over a circuit-board
dark, and the title, in Crema's layout. Original art: no console or game art, no logos.

    py scripts/make-banner.py          (Windows python with Pillow; WSL python3 works too)
"""
import math
import os
import random

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
W, H = 1600, 480
BG_TOP, BG_LOW = (6, 14, 8), (2, 6, 3)
GREEN = (36, 176, 52)
LIGHT = (150, 240, 110)
TEXT_TOP, TEXT_LOW = (214, 255, 190), (60, 196, 70)
MUTED = (150, 186, 150)


def font(size, bold=True):
    names = ("segoeuib.ttf", "arialbd.ttf") if bold else ("segoeui.ttf", "arial.ttf")
    for name in names:
        for folder in ("C:/Windows/Fonts", "/mnt/c/Windows/Fonts"):
            path = os.path.join(folder, name)
            if os.path.exists(path):
                return ImageFont.truetype(path, size)
    dejavu = "/usr/share/fonts/truetype/dejavu/DejaVuSans%s.ttf" % ("-Bold" if bold else "")
    return ImageFont.truetype(dejavu, size) if os.path.exists(dejavu) else ImageFont.load_default()


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def backdrop():
    """The dark, with faint circuit traces: right-angled runs ending in pads."""
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        d.line([(0, y), (W, y)], fill=lerp(BG_TOP, BG_LOW, y / (H - 1)))
    rng = random.Random(1)
    traces = Image.new("RGB", (W, H))
    td = ImageDraw.Draw(traces)
    for _ in range(70):
        x, y = rng.randrange(0, W, 20), rng.randrange(0, H, 20)
        colour = lerp((10, 34, 14), (20, 70, 26), rng.random())
        for _ in range(rng.randint(2, 4)):
            if rng.random() < 0.5:
                nx, ny = x + rng.choice((-1, 1)) * rng.randrange(40, 200, 20), y
            else:
                nx, ny = x, y + rng.choice((-1, 1)) * rng.randrange(20, 120, 20)
            td.line([(x, y), (nx, ny)], fill=colour, width=2)
            x, y = nx, ny
        td.ellipse([x - 4, y - 4, x + 4, y + 4], outline=colour, width=2)
    return ImageChops.add(img, traces)


def rings(img):
    """Three rings of green light around a bright core, left of centre: the emulated CPU's clock."""
    cx, cy = int(W * 0.24), H // 2
    glow = Image.new("RGB", (W, H))
    gd = ImageDraw.Draw(glow)
    for r, width, colour in ((182, 16, GREEN), (128, 10, lerp(GREEN, LIGHT, 0.4)), (78, 7, LIGHT)):
        gd.ellipse([cx - r, cy - r, cx + r, cy + r], outline=colour, width=width)
    halo = glow.filter(ImageFilter.GaussianBlur(18))
    img = ImageChops.add(img, halo)
    img = ImageChops.add(img, glow.filter(ImageFilter.GaussianBlur(2)))
    # Ticks around the outer ring, every 15 degrees, longer every 90.
    d = ImageDraw.Draw(img)
    for k in range(24):
        a = math.radians(k * 15)
        r0, r1 = 202, 214 if k % 6 else 230
        d.line([(cx + r0 * math.cos(a), cy + r0 * math.sin(a)), (cx + r1 * math.cos(a), cy + r1 * math.sin(a))],
               fill=lerp(GREEN, LIGHT, 0.3), width=3 if k % 6 == 0 else 2)
    # The core: a soft bright disc.
    core = Image.new("L", (W, H), 0)
    ImageDraw.Draw(core).ellipse([cx - 34, cy - 34, cx + 34, cy + 34], fill=255)
    core = core.filter(ImageFilter.GaussianBlur(12))
    return Image.composite(Image.new("RGB", (W, H), (210, 255, 190)), img, core)


def text_panel(img):
    """The right side darkens towards the title, so the text reads over the traces."""
    shade = Image.new("L", (W, H), 0)
    sd = ImageDraw.Draw(shade)
    start = int(W * 0.40)
    for x in range(start, W):
        sd.line([(x, 0), (x, H)], fill=int(190 * min(1.0, ((x - start) / (W * 0.2)) ** 1.2)))
    return Image.composite(Image.new("RGB", (W, H), (4, 10, 5)), img, shade)


def gradient_text(img, xy, text, f, top, low, glow=None):
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).text(xy, text, font=f, fill=255)
    box = mask.getbbox()
    if glow:
        halo = mask.filter(ImageFilter.GaussianBlur(14))
        halo = ImageChops.multiply(halo, Image.new("L", img.size, glow[1]))
        img = Image.composite(Image.new("RGB", img.size, glow[0]), img, halo)
    fill = Image.new("RGB", img.size)
    fd = ImageDraw.Draw(fill)
    for y in range(box[1], box[3] + 1):
        fd.line([(box[0], y), (box[2], y)], fill=lerp(top, low, (y - box[1]) / max(1, box[3] - box[1])))
    return Image.composite(fill, img, mask)


def main():
    img = text_panel(rings(backdrop()))
    x = int(W * 0.50)
    img = gradient_text(img, (x, 104), "xemu-ps4", font(132), TEXT_TOP, TEXT_LOW, glow=((40, 200, 60), 140))
    d = ImageDraw.Draw(img)
    d.text((x + 8, 280), "original Xbox emulator  \u00b7  on PS4", font=font(38, bold=False), fill=MUTED)
    # A thin rule under the subtitle, fading out to the right.
    for i in range(560):
        d.point((x + 8, 340), fill=GREEN)
        d.point((x + 8 + i, 340), fill=lerp((90, 220, 90), (4, 10, 5), (i / 560) ** 0.8))
    out = os.path.join(ROOT, "docs", "images", "banner.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    img.save(out, optimize=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
