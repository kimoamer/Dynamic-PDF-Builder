"""Original synthetic images for the M7.6 examples, drawn here so nothing third-party
is involved. Everything is deterministic."""
from __future__ import annotations

import os

from PIL import Image, ImageDraw

SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 64" width="240" height="64">
<circle cx="32" cy="32" r="28" fill="{a}"/><path d="M14 40 Q32 14 50 40 Z" fill="#ffffff"/>
<rect x="74" y="16" width="150" height="12" fill="{a}"/><rect x="74" y="38" width="96" height="8" fill="{b}"/>
</svg>"""


def _gradient(size, top, bottom):
    w, h = size
    column = Image.new("RGB", (1, h))
    for y in range(h):
        t = y / max(1, h - 1)
        column.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    return column.resize(size)


def landscape(path, size=(1800, 1100), sky=((24, 58, 96), (240, 176, 120)), hills=(28, 52, 60)):
    image = _gradient(size, *sky)
    d = ImageDraw.Draw(image)
    w, h = size
    d.ellipse((w * .62, h * .24, w * .78, h * .24 + w * .16), fill=(250, 214, 140))
    for k, (shade, base) in enumerate(((.6, .66), (.8, .74), (1.0, .84))):
        colour = tuple(round(c + (255 - c) * (1 - shade) * .5) for c in hills)
        points = [(0, h)]
        for x in range(0, w + 60, 60):
            wave = ((x * (k + 3)) % 420) / 420
            points.append((x, h * base - abs(wave - .5) * h * .16))
        d.polygon(points + [(w, h)], fill=colour)
    image.save(path, quality=88)


def plant(path, size=(1000, 1300)):
    """A portrait 'plant room' study: pipes and panels in flat colour."""
    image = _gradient(size, (232, 236, 238), (198, 208, 214))
    d = ImageDraw.Draw(image)
    w, h = size
    for k in range(5):
        x = w * (.12 + .17 * k)
        d.rectangle((x, h * .12, x + w * .1, h * .8), fill=(70 + 18 * k, 104, 124))
        d.ellipse((x - 8, h * .08, x + w * .1 + 8, h * .16), fill=(44, 72, 88))
    d.rectangle((0, h * .8, w, h), fill=(58, 66, 72))
    d.rectangle((w * .08, h * .46, w * .92, h * .5), fill=(214, 120, 62))
    image.save(path, quality=88)


def paper(path, size=(1240, 1754), tint=(244, 241, 234), line=(232, 227, 216)):
    image = Image.new("RGB", size, tint)
    d = ImageDraw.Draw(image)
    w, h = size
    for k in range(0, h + w, 90):
        d.line((0, k, k, 0), fill=line, width=2)
    d.rectangle((0, 0, w, h * .02), fill=line)
    image.save(path)


def logo(path, a=(20, 96, 122), b=(204, 88, 44), size=(960, 256)):
    image = Image.new("RGBA", size, (0, 0, 0, 0))
    d = ImageDraw.Draw(image)
    h = size[1]
    d.ellipse((8, 8, h - 8, h - 8), fill=a + (255,))
    d.polygon(((h * .2, h * .68), (h * .5, h * .2), (h * .8, h * .68)), fill=(255, 255, 255, 255))
    d.rectangle((h * 1.15, h * .24, size[0] - 30, h * .46), fill=a + (255,))
    d.rectangle((h * 1.15, h * .58, size[0] * .7, h * .72), fill=b + (255,))
    image.save(path)


def make(folder: str) -> dict:
    os.makedirs(folder, exist_ok=True)
    p = {k: os.path.join(folder, v) for k, v in {
        "harbour": "harbour.jpg", "dawn": "dawn.jpg", "plant": "plant.jpg", "paper": "paper.png",
        "logo": "logo.png", "logo_b": "logo_b.png", "svg": "logo.svg", "tiny": "tiny.png",
        "corrupt": "corrupt.png", "huge": "huge.png", "webp": "harbour.webp"}.items()}
    landscape(p["harbour"])
    landscape(p["dawn"], sky=((92, 60, 84), (246, 196, 132)), hills=(52, 44, 58))
    plant(p["plant"])
    paper(p["paper"])
    logo(p["logo"])
    logo(p["logo_b"], a=(120, 60, 110), b=(40, 120, 90))
    with open(p["svg"], "w", encoding="utf-8") as f:
        f.write(SVG.format(a="#14607a", b="#cc582c"))
    Image.open(p["harbour"]).resize((90, 55)).save(p["tiny"])
    with open(p["corrupt"], "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\nnot really an image")
    Image.new("L", (9000, 7000), 200).save(p["huge"], optimize=False)
    Image.open(p["harbour"]).save(p["webp"], quality=80)
    return p
