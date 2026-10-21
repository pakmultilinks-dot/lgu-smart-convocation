"""Phase 35D — rebuild LGU brand assets from the authoritative seal.

Source of truth: assets/lgu-logo.png (444x444 RGBA transparent, full-color
LGU seal). This script NEVER alters the seal artwork; it composites the
unchanged seal onto the Phase 35C institutional surfaces:

  paper #F6F1E4  -> icon, favicon, splash background
  transparent    -> Android adaptive-icon foreground (bg color lives in
                    app.json adaptiveIcon.backgroundColor)

Paper is chosen over brand green for every surface because the real seal is
full-color (navy shield, green wreath, gold accents) and needs a light ground
to stay faithful — no knockout or recolor of the official artwork.

Outputs (overwritten in place; idempotent):
  assets/icon.png            1024x1024  paper bg + seal 58%
  assets/adaptive-icon.png   1024x1024  transparent + seal 55% (safe zone)
  assets/favicon.png           48x48    paper bg + seal 78%
  assets/splash.png         1242x2436   paper bg + seal + product ID text

Run from mobile/:  ..\\.venv\\Scripts\\python.exe scripts\\make-brand-assets.py
"""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
SEAL = ASSETS / "lgu-logo.png"

PAPER = (246, 241, 228, 255)  # #F6F1E4 — Phase 35C paper
INK = (27, 26, 22, 255)  # #1B1A16 — Phase 35C ink
MUTED = (110, 103, 80, 255)  # #6E6750 — Phase 35C muted

FRONT = ROOT / (
    "node_modules/@expo-google-fonts/bricolage-grotesque/"
    "500Medium/BricolageGrotesque_500Medium.ttf"
)
MONO = ROOT / "node_modules/@expo-google-fonts/dm-mono/500Medium/DMMono_500Medium.ttf"

EVENT = "CONVOCATION 2026"
UNIVERSITY = "Lahore Garrison University"


def seal(size: int) -> Image.Image:
    """The real seal, resampled only — artwork untouched."""
    return Image.open(SEAL).convert("RGBA").resize((size, size), Image.LANCZOS)


def paste_center(canvas: Image.Image, mark: Image.Image, cy: float) -> None:
    x = (canvas.width - mark.width) // 2
    y = int(canvas.height * cy) - mark.height // 2
    canvas.alpha_composite(mark, (x, y))


def build_icon() -> None:
    im = Image.new("RGBA", (1024, 1024), PAPER)
    paste_center(im, seal(594), 0.5)  # 58% — readable, inside iOS mask
    im.convert("RGB").save(ASSETS / "icon.png")


def build_adaptive() -> None:
    im = Image.new("RGBA", (1024, 1024), (0, 0, 0, 0))
    paste_center(im, seal(564), 0.5)  # 55% — inside Android 66% safe zone
    im.save(ASSETS / "adaptive-icon.png")


def build_favicon() -> None:
    im = Image.new("RGBA", (48, 48), PAPER)
    paste_center(im, seal(37), 0.5)  # 78% — reads at small size
    im.convert("RGB").save(ASSETS / "favicon.png")


def build_splash() -> None:
    w, h = 1242, 2436
    im = Image.new("RGBA", (w, h), PAPER)
    paste_center(im, seal(500), 0.41)  # 40% width, slightly above middle
    d = ImageDraw.Draw(im)
    f_name = ImageFont.truetype(str(FRONT), 54)
    f_event = ImageFont.truetype(str(MONO), 30)
    y = int(h * 0.41) + 250 + 56  # below seal + restraint gap
    for line, font, fill, gap in (
        (UNIVERSITY, f_name, INK, 34),
        (EVENT, f_event, MUTED, 0),
    ):
        tw = d.textlength(line, font=font)
        d.text(((w - tw) / 2, y), line, font=font, fill=fill)
        y += font.size + gap
    im.convert("RGB").save(ASSETS / "splash.png")


def verify() -> None:
    for name in ("icon.png", "adaptive-icon.png", "favicon.png", "splash.png"):
        p = ASSETS / name
        a = Image.open(p).convert("RGBA")
        c0 = a.getpixel((0, 0))
        print(f"{name}: {a.size} {a.mode} corner={c0} bytes={p.stat().st_size}")


if __name__ == "__main__":
    build_icon()
    build_adaptive()
    build_favicon()
    build_splash()
    verify()
