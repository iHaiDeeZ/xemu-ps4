# Placeholder pictures for the package, until there is real art:
#   sce_sys/icon0.png   512x512 app icon
#   sce_sys/pic1.png    1920x1080 PS4 home screen background
# Windows python (Pillow):  py scripts/make-art.py
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
GREEN = (16, 124, 16)
LIGHT = (120, 220, 90)


def font(size, bold=True):
    for name in ("segoeuib.ttf" if bold else "segoeui.ttf", "arialbd.ttf", "arial.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            pass
    return ImageFont.load_default()


def backdrop(w, h):
    img = Image.new("RGB", (w, h), (8, 12, 8))
    glow = Image.new("RGB", (w, h), (0, 0, 0))
    d = ImageDraw.Draw(glow)
    r = int(min(w, h) * 0.42)
    cx, cy = w // 2, h // 2
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=GREEN, width=max(6, r // 10))
    glow = glow.filter(ImageFilter.GaussianBlur(r // 6))
    img = Image.blend(img, glow, 0.9)
    d = ImageDraw.Draw(img)
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=LIGHT, width=max(3, r // 40))
    return img


def centered(d, xy, text, f, fill):
    x0, y0, x1, y1 = d.textbbox((0, 0), text, font=f)
    d.text((xy[0] - (x1 - x0) / 2 - x0, xy[1] - (y1 - y0) / 2 - y0), text, font=f, fill=fill)


icon = backdrop(512, 512)
d = ImageDraw.Draw(icon)
centered(d, (256, 236), "xemu", font(150), (235, 255, 230))
centered(d, (256, 352), "for PS4", font(46, bold=False), LIGHT)
icon.save(ROOT / "sce_sys" / "icon0.png")

pic = backdrop(1920, 1080)
d = ImageDraw.Draw(pic)
centered(d, (960, 500), "xemu", font(260), (235, 255, 230))
centered(d, (960, 680), "ORIGINAL XBOX EMULATOR FOR PS4", font(54, bold=False), LIGHT)
pic.save(ROOT / "sce_sys" / "pic1.png")
print("sce_sys/icon0.png, sce_sys/pic1.png")
