"""Generate the app icons in app/static/ from assets/logo.png.

    uv run --with pillow python assets/make-icons.py

logo.png is an opaque square: a rounded tile on a dark background. Each icon
needs a different framing:
- "any" icons and favicon: the tile alone, corners made transparent;
- maskable icon: the whole image (the platform crops it, the drawing sits
  well inside the 80 % safe zone);
- apple-touch-icon: the tile, opaque (iOS rounds the corners itself and
  shows transparency as black).
"""

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "assets" / "logo.png"
OUT = ROOT / "app" / "static"

# Tile position in logo.png (1254 x 1254), measured on the image
TILE_BOX = (166, 156, 1088, 1078)
TILE_RADIUS = 0.22  # corner radius, fraction of the tile side


def resized(image: Image.Image, size: int) -> Image.Image:
    return image.resize((size, size), Image.LANCZOS)


def rounded(image: Image.Image) -> Image.Image:
    """The image with transparent rounded corners, antialiased (drawn at 4x)."""
    side = image.width * 4
    mask = Image.new("L", (side, side), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        (0, 0, side - 1, side - 1), radius=int(side * TILE_RADIUS), fill=255
    )
    result = image.convert("RGBA")
    result.putalpha(mask.resize(image.size, Image.LANCZOS))
    return result


def main() -> None:
    logo = Image.open(SOURCE).convert("RGB")
    tile = logo.crop(TILE_BOX)
    tile_any = rounded(tile)

    resized(tile_any, 192).save(OUT / "icon-192.png", optimize=True)
    resized(tile_any, 512).save(OUT / "icon-512.png", optimize=True)
    resized(logo, 512).save(OUT / "icon-maskable-512.png", optimize=True)
    resized(tile, 180).save(OUT / "apple-touch-icon.png", optimize=True)
    resized(tile_any, 256).save(OUT / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])


if __name__ == "__main__":
    main()
