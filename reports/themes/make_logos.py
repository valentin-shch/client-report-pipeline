"""Regenerate the placeholder agency logos referenced by the theme files.

Each is a simple white wordmark with a square mark, sized for a ~34px-tall
header and rendered at 3x for sharpness on high-density screens. Run this after
changing an agency name or accent colour:

    python reports/themes/make_logos.py
"""

from __future__ import annotations

import tomllib
from pathlib import Path

from matplotlib import font_manager
from PIL import Image, ImageDraw, ImageFont

THEMES_DIR = Path(__file__).resolve().parent
SCALE = 3
HEIGHT = 34 * SCALE
PAD = 6 * SCALE
MARK = 22 * SCALE
GAP = 10 * SCALE

_font_path = font_manager.findfont(font_manager.FontProperties(family="DejaVu Sans", weight="bold"))
FONT = ImageFont.truetype(_font_path, 22 * SCALE)


def make_logo(name: str, accent: str, out: Path) -> None:
    tmp = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    text_w = tmp.textlength(name, font=FONT)
    width = int(PAD + MARK + GAP + text_w + PAD)

    img = Image.new("RGBA", (width, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    mark_top = (HEIGHT - MARK) // 2
    draw.rounded_rectangle(
        [PAD, mark_top, PAD + MARK, mark_top + MARK], radius=5 * SCALE, fill="#ffffff"
    )
    draw.text(
        (PAD + MARK / 2, HEIGHT / 2), name[0], font=FONT, fill=accent, anchor="mm"
    )
    draw.text(
        (PAD + MARK + GAP, HEIGHT / 2), name, font=FONT, fill="#ffffff", anchor="lm"
    )
    img.save(out)
    print(f"wrote {out.name}  ({width}x{HEIGHT})")


def main() -> None:
    for toml_path in sorted(THEMES_DIR.glob("*.toml")):
        cfg = tomllib.loads(toml_path.read_text())
        if not cfg.get("logo"):
            continue
        make_logo(cfg["name"], cfg["accent"], THEMES_DIR / cfg["logo"])


if __name__ == "__main__":
    main()
