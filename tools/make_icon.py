"""Draw the integration's generic bathroom-scale icon (no Withings branding).

Usage: uv run --with pillow tools/make_icon.py
Writes custom_components/withings_local/brand/{icon,icon@2x,dark_icon,dark_icon@2x}.png:
square, transparent background, 256 px and 512 px, as Home Assistant brand images expect.
The white scale reads on both light and dark backgrounds, so the dark variants are the same image.
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "custom_components" / "withings_local" / "brand"
SS = 4  # supersampling factor for smooth edges

BODY = (250, 250, 250)
EDGE = (176, 190, 197)
SCREEN = (38, 50, 56)
RUNE = (3, 169, 244)
# Bluetooth symbol as one stroke, on the same 224 grid as the rest.
RUNE_POINTS = [(98, 43), (126, 65), (112, 77), (112, 31), (126, 43), (98, 65)]


def draw(size: int) -> Image.Image:
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = s / 224  # design on a 224 grid

    def box(x0, y0, x1, y1):
        return [round(x0 * u), round(y0 * u), round(x1 * u), round(y1 * u)]

    # Scale platform with a light edge.
    d.rounded_rectangle(box(0, 0, 224, 224), radius=round(53 * u), fill=BODY, outline=EDGE, width=round(6 * u))
    # Display.
    d.rounded_rectangle(box(68, 24, 156, 84), radius=round(18 * u), fill=SCREEN)
    # Bluetooth symbol on the display, with round caps.
    pts = [(x * u, y * u) for x, y in RUNE_POINTS]
    w = round(6 * u)
    d.line(pts, fill=RUNE, width=w, joint="curve")
    for x, y in (pts[0], pts[-1]):
        d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill=RUNE)
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for prefix in ("", "dark_"):
        for size, suffix in ((256, ""), (512, "@2x")):
            path = OUT / f"{prefix}icon{suffix}.png"
            draw(size).save(path, optimize=True)
            print(f"wrote {path.relative_to(OUT.parent.parent.parent)}")


if __name__ == "__main__":
    main()
