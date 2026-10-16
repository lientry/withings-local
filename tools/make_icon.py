"""Draw the integration's generic bathroom-scale icon (no Withings branding).

Usage: uv run --with pillow tools/make_icon.py
Writes custom_components/withings_local/brand/{icon,icon@2x,dark_icon,dark_icon@2x}.png:
square, transparent background, 256 px and 512 px, as Home Assistant brand images expect.
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "custom_components" / "withings_local" / "brand"
SS = 4  # supersampling factor for smooth edges

THEMES = {
    "": {"body": (55, 71, 79), "pad": (84, 110, 122), "screen": (236, 239, 241), "digits": (3, 169, 244)},
    "dark_": {"body": (176, 190, 197), "pad": (144, 164, 174), "screen": (38, 50, 56), "digits": (79, 195, 247)},
}


def draw(size: int, theme: dict) -> Image.Image:
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = s / 512  # design on a 512 grid

    def box(x0, y0, x1, y1):
        return [round(x0 * u), round(y0 * u), round(x1 * u), round(y1 * u)]

    # Scale platform.
    d.rounded_rectangle(box(24, 24, 488, 488), radius=round(96 * u), fill=theme["body"])
    # Display.
    d.rounded_rectangle(box(156, 84, 356, 176), radius=round(28 * u), fill=theme["screen"])
    # Three bar "digits" on the display.
    for x in (186, 236, 286):
        d.rounded_rectangle(box(x, 112, x + 40, 148), radius=round(8 * u), fill=theme["digits"])
    # Foot electrodes.
    d.rounded_rectangle(box(96, 236, 236, 432), radius=round(56 * u), fill=theme["pad"])
    d.rounded_rectangle(box(276, 236, 416, 432), radius=round(56 * u), fill=theme["pad"])
    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for prefix, theme in THEMES.items():
        for size, suffix in ((256, ""), (512, "@2x")):
            path = OUT / f"{prefix}icon{suffix}.png"
            draw(size, theme).save(path, optimize=True)
            print(f"wrote {path.relative_to(OUT.parent.parent.parent)}")


if __name__ == "__main__":
    main()
