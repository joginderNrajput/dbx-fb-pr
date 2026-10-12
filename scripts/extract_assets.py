"""Regenerate the workbook brand assets in ``dbx_premig/excel/assets``.

* ``kanerika_logo.png`` and ``banner.png`` are copied byte-identically out of the reference
  workbook (``Tempelate_sheet.xlsx``), so the branding matches Kanerika's other accelerators.
* ``platform_logo.png`` ("Databricks -> Microsoft Fabric") is rendered from the SVGs in
  ``scripts/brand_src`` (see SOURCES.md there).
* ``titles/<Sheet>.png`` are the white sheet titles drawn over the banner (cell text would
  sit under the banner picture). Re-run this script after adding a sheet or changing a title.
* ``app.ico`` is the executable icon for PyInstaller.

Build-time only (needs the ``dev`` extra: cairosvg, pillow). Never imported by the package.

    python scripts/extract_assets.py [--template Tempelate_sheet.xlsx]
"""

from __future__ import annotations

import argparse
import io
import zipfile
from pathlib import Path

import cairosvg
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "scripts" / "brand_src"
OUT = ROOT / "dbx_premig" / "excel" / "assets"
PACKAGING = ROOT / "packaging"

# Members of the reference workbook (checked by SHA-256 in tests/test_assets.py).
TEMPLATE_MEMBERS = {"xl/media/image1.png": "banner.png", "xl/media/image2.png": "kanerika_logo.png"}

_FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/inter/Inter-SemiBold.otf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
)


def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in _FONT_CANDIDATES:
        if Path(candidate).is_file():
            return ImageFont.truetype(candidate, size)
    return ImageFont.load_default()


def _svg(name: str, height: int) -> Image.Image:
    png = cairosvg.svg2png(url=str(SRC / name), output_height=height)
    return Image.open(io.BytesIO(png)).convert("RGBA")


def copy_template_assets(template: Path) -> None:
    with zipfile.ZipFile(template) as zf:
        for member, target in TEMPLATE_MEMBERS.items():
            (OUT / target).write_bytes(zf.read(member))


def render_platform_logo() -> None:
    """White 'Databricks -> Microsoft Fabric' strip on transparency (shown on the dark banner)."""
    height, icon = 190, 132
    font = _font(64)
    dbx = _svg("databricks.svg", icon)
    fab = _svg("microsoft_fabric.svg", icon)
    parts: list[Image.Image | str] = [dbx, "Databricks", "→", fab, "Fabric"]
    gap = 26
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    widths = [
        p.width if isinstance(p, Image.Image) else int(probe.textlength(p, font=font))
        for p in parts
    ]
    width = sum(widths) + gap * (len(parts) - 1) + 8
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    x = 4
    for part, w in zip(parts, widths, strict=True):
        if isinstance(part, Image.Image):
            img.alpha_composite(part, (x, (height - part.height) // 2))
        else:
            box = draw.textbbox((0, 0), part, font=font)
            y = (height - (box[3] - box[1])) // 2 - box[1]
            draw.text((x, y), part, font=font, fill=(255, 255, 255, 255))
        x += w + gap
    img.save(OUT / "platform_logo.png", optimize=True)


def sheet_titles() -> dict[str, str]:
    """Sheet name -> banner title, read from the package (the single source of the titles)."""
    import sys

    sys.path.insert(0, str(ROOT))
    from dbx_premig.excel import dashboard
    from dbx_premig.excel.sheets import information, totals
    from dbx_premig.excel.writer import DATA_SHEETS

    titles = {
        "Discovery": dashboard.TITLE,
        "Information": information.TITLE,
        "Totals": totals.TITLE,
    }
    titles.update({spec.name: spec.title for spec in DATA_SHEETS})
    return titles


def render_titles() -> None:
    """White title text on transparency, rendered at 2x (shown at half size, never stretched)."""
    out = OUT / "titles"
    out.mkdir(exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    font = _font(42)
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    for sheet, title in sorted(sheet_titles().items()):
        box = probe.textbbox((0, 0), title, font=font)
        width, height = box[2] - box[0] + 8, 64
        img = Image.new("RGBA", (int(width + width % 2), height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.text(
            (4 - box[0], (height - (box[3] - box[1])) // 2 - box[1]),
            title,
            font=font,
            fill=(255, 255, 255, 255),
        )
        img.save(out / f"{sheet}.png", optimize=True)


def render_icon() -> None:
    PACKAGING.mkdir(exist_ok=True)
    base = Image.new("RGBA", (256, 256), (27, 49, 57, 255))
    mark = _svg("databricks.svg", 176)
    base.alpha_composite(mark, ((256 - mark.width) // 2, (256 - mark.height) // 2))
    base.save(PACKAGING / "app.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (256, 256)])
    base.save(PACKAGING / "app.png")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--template", type=Path, default=ROOT / "Tempelate_sheet.xlsx")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    copy_template_assets(args.template)
    render_platform_logo()
    render_titles()
    render_icon()
    print(f"assets written to {OUT.relative_to(ROOT)} and {PACKAGING.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
