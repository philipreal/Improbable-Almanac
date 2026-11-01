"""Render PNG app icons (for iPhone home screens) from the same design as icons/icon.svg."""
from PIL import Image, ImageDraw

from tracker import ROOT


def render(size: int) -> Image.Image:
    s = size / 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=14 * s, fill="#b23a2a")
    d.ellipse([8 * s, 8 * s, 56 * s, 56 * s], outline="#f4ecdc", width=max(1, round(2 * s)))
    d.arc([22 * s, 11 * s, 44 * s, 31 * s], start=190, end=430, fill="#f4ecdc", width=round(5 * s))
    d.line([(33 * s, 31 * s), (33 * s, 37 * s)], fill="#f4ecdc", width=round(5 * s))
    d.ellipse([29.6 * s, 41.6 * s, 36.4 * s, 48.4 * s], fill="#f4ecdc")
    d.polygon([(48 * s, 12 * s), (49.6 * s, 15.6 * s), (53 * s, 17 * s), (49.6 * s, 18.4 * s), (48 * s, 22 * s),
               (46.4 * s, 18.4 * s), (43 * s, 17 * s), (46.4 * s, 15.6 * s)], fill="#f3cf6a")
    return img


if __name__ == "__main__":
    for size in (180, 192, 512):
        render(size).save(ROOT / "site" / "icons" / f"icon-{size}.png")
