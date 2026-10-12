"""Compose the top banner of a sheet as ONE picture.

Gradient (from the reference workbook), Kanerika logo on the left, the sheet title in white
and the Databricks -> Fabric logo on the right are drawn into a single image, every element
centred vertically in the band. Placed at A1 with an absolute size, it looks the same in
Excel, LibreOffice and Google Sheets: no element can overlap another or drift with column
widths (separate pictures anchored to columns did, because Excel caps column offsets).

Rendered at 2x and shown at 1x, so text stays sharp on high-DPI screens.
"""

from __future__ import annotations

import io
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from dbx_premig.resources import asset_path

__all__ = ["BAND_HEIGHT_PX", "compose_banner"]

#: Height of rows 1-4 (24 + 24 + 20 + 10 pt) in pixels at 96 dpi.
BAND_HEIGHT_PX = 104
_SCALE = 2
_LOGO_H = 45  # px (Kanerika logo, as in the reference workbook)
_PLATFORM_H = 44
_LEFT = 16
_RIGHT = 28
_GAP = 36
_TITLE_PX = (19, 17, 15, 13, 12)  # font sizes tried, largest first


@lru_cache(maxsize=4)
def _source(name: str) -> Image.Image:
    with Image.open(asset_path(name)) as img:
        return img.convert("RGBA")


@lru_cache(maxsize=8)
def _font(px: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(asset_path("banner_font.ttf")), px * _SCALE)


def _scaled(img: Image.Image, height: int) -> Image.Image:
    width = round(img.width * height / img.height)
    return img.resize((width, height), Image.Resampling.LANCZOS)


@lru_cache(maxsize=128)
def compose_banner(title: str, width_px: int) -> bytes:
    """JPEG bytes of the banner for ``title``, ``width_px`` x 104 px (rendered at 2x)."""
    s = _SCALE
    w, h = width_px * s, BAND_HEIGHT_PX * s
    canvas = _source("banner.png").resize((w, h), Image.Resampling.BICUBIC)

    logo = _scaled(_source("kanerika_logo.png"), _LOGO_H * s)
    canvas.alpha_composite(logo, (_LEFT * s, (h - logo.height) // 2))

    platform = _scaled(_source("platform_logo.png"), _PLATFORM_H * s)
    px = w - _RIGHT * s - platform.width
    canvas.alpha_composite(platform, (px, (h - platform.height) // 2))

    draw = ImageDraw.Draw(canvas)
    left = _LEFT * s + logo.width + _GAP * s
    room = px - _GAP * s - left
    text = title
    for size in _TITLE_PX:
        font = _font(size)
        if draw.textlength(text, font=font) <= room:
            break
    else:  # still too long at the smallest size: ellipsize
        while text and draw.textlength(text + "…", font=font) > room:
            text = text[:-1]
        text = text.rstrip() + "…"
    top, bottom = draw.textbbox((0, 0), "Hg", font=font)[1::2]
    y = (h - (bottom - top)) // 2 - top
    draw.text((left, y), text, font=font, fill=(255, 255, 255, 255))

    out = io.BytesIO()
    # JPEG: the banner is opaque and a gradient, which PNG compresses badly (3x the size).
    canvas.convert("RGB").save(out, format="JPEG", quality=92, subsampling=0, optimize=True)
    return out.getvalue()
