#!/usr/bin/env python3
"""Generate app icon, adaptive icon, splash and favicon PNGs.

Letters only: a gold "LGU" monogram on deep navy, with the university name on
the splash. No imagery, no logos of any third party.
"""

import os

from PIL import Image, ImageDraw, ImageFont

NAVY = (11, 36, 71)
GOLD = (201, 162, 39)
WHITE = (255, 255, 255)
GOLD_SOFT = (233, 212, 138)

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(BASE, "assets")
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def font(size: int, bold: bool = True) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)


def centered_text(draw: ImageDraw.ImageDraw, cx: int, y: int, text: str,
                  fnt: ImageFont.FreeTypeFont, fill: tuple) -> int:
    bbox = draw.textbbox((0, 0), text, font=fnt)
    w = bbox[2] - bbox[0]
    draw.text((cx - w / 2, y), text, font=fnt, fill=fill)
    return bbox[3] - bbox[1]


def letter_spaced(draw: ImageDraw.ImageDraw, cx: int, y: int, text: str,
                  fnt: ImageFont.FreeTypeFont, fill: tuple, tracking: int) -> None:
    widths = [draw.textlength(ch, font=fnt) for ch in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x = cx - total / 2
    for ch, w in zip(text, widths):
        draw.text((x, y), ch, font=fnt, fill=fill)
        x += w + tracking


def make_icon(path: str, size: int, ring: bool) -> None:
    img = Image.new("RGB", (size, size), NAVY)
    draw = ImageDraw.Draw(img)
    if ring:
        m = int(size * 0.06)
        draw.rounded_rectangle([m, m, size - m, size - m],
                               radius=int(size * 0.12), outline=GOLD, width=max(6, size // 128))
    f = font(int(size * 0.30))
    centered_text(draw, size // 2, int(size * 0.30), "LGU", f, GOLD)
    f2 = font(int(size * 0.055), bold=False)
    letter_spaced(draw, size // 2, int(size * 0.66), "SMART CONVOCATION",
                  f2, GOLD_SOFT, int(size * 0.012))
    img.save(path)


def make_splash(path: str, w: int, h: int) -> None:
    img = Image.new("RGB", (w, h), NAVY)
    draw = ImageDraw.Draw(img)
    cx = w // 2
    f = font(int(w * 0.16))
    centered_text(draw, cx, int(h * 0.36), "LGU", f, GOLD)
    bar_w = int(w * 0.28)
    draw.rectangle([cx - bar_w // 2, int(h * 0.52), cx + bar_w // 2,
                    int(h * 0.52) + max(4, w // 300)], fill=GOLD)
    f2 = font(int(w * 0.038))
    letter_spaced(draw, cx, int(h * 0.55), "LAHORE GARRISON UNIVERSITY",
                  f2, WHITE, int(w * 0.006))
    f3 = font(int(w * 0.028), bold=False)
    letter_spaced(draw, cx, int(h * 0.60), "SMART CONVOCATION SYSTEM",
                  f3, GOLD_SOFT, int(w * 0.005))
    img.save(path)


def main() -> None:
    os.makedirs(ASSETS, exist_ok=True)
    make_icon(os.path.join(ASSETS, "icon.png"), 1024, ring=True)
    make_icon(os.path.join(ASSETS, "adaptive-icon.png"), 1024, ring=False)
    make_splash(os.path.join(ASSETS, "splash.png"), 1242, 2436)
    make_icon(os.path.join(ASSETS, "favicon.png"), 48, ring=False)
    print("assets written to", ASSETS)


if __name__ == "__main__":
    main()
