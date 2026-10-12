"""Shared worksheet layout: branding band (rows 1-5), header row 6, data from row 7."""

from __future__ import annotations

import io
from collections.abc import Sequence

from openpyxl.drawing.image import Image as XLImage
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, OneCellAnchor
from openpyxl.drawing.xdr import XDRPositiveSize2D
from openpyxl.utils import get_column_letter
from openpyxl.utils.units import pixels_to_EMU
from openpyxl.worksheet.properties import PageSetupProperties
from openpyxl.worksheet.worksheet import Worksheet

from dbx_premig.excel import theme
from dbx_premig.excel.banner import BAND_HEIGHT_PX, compose_banner

__all__ = [
    "DATA_START_ROW",
    "HEADER_ROW",
    "back_link",
    "branding_band",
    "column_px",
    "data_range",
    "nav_link",
]

HEADER_ROW = 6
DATA_START_ROW = 7
#: Formula ranges reach at least this row so a reviewer can append rows by hand.
MIN_RANGE_END = 100_000

_BAND_ROW_HEIGHTS = {1: 24.0, 2: 24.0, 3: 20.0, 4: 10.0, 5: 18.0}
_MIN_BAND_PX = 1500
_MAX_BAND_PX = 4000


def column_px(ws: Worksheet, index: int) -> int:
    """Approximate rendered width of a 1-based column, in pixels."""
    dim = ws.column_dimensions.get(get_column_letter(index))
    width = dim.width if dim is not None and dim.width else 8.43
    return int(width * 7 + 5)


def data_range(sheet: str, column: str, rows: int) -> str:
    """Absolute range over a data column, e.g. 'Jobs'!$A$7:$A$100000."""
    end = max(MIN_RANGE_END, DATA_START_ROW + rows + 1000)
    return f"'{sheet}'!${column}${DATA_START_ROW}:${column}${end}"


def nav_link(sheet: str, text: str | None = None) -> str:
    label = (text or sheet).replace('"', "'")
    return f'=HYPERLINK("#\'{sheet}\'!A1","{label}")'


def back_link(ws: Worksheet, description: str, home: str = "Discovery") -> None:
    ws["A5"] = nav_link(home, f"«  Back to {home}")
    ws["A5"].font = theme.LINK_FONT
    ws["B5"] = description
    ws["B5"].font = theme.NOTE_FONT


def branding_band(ws: Worksheet, title: str, last_col: int, title_key: str | None = None) -> None:
    """Rows 1-4: one composed banner picture (logo, title, platform logo), row 5 is free."""
    del title_key  # kept for call compatibility
    for row, height in _BAND_ROW_HEIGHTS.items():
        ws.row_dimensions[row].height = height
    ws.sheet_view.showGridLines = False
    # Print / PDF: landscape, one page wide.
    ws.page_setup.orientation = "landscape"
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr = PageSetupProperties(fitToPage=True)

    # As wide as the used columns, and at least _MIN_BAND_PX.
    span = sum(column_px(ws, c) for c in range(1, last_col + 1))
    width = max(_MIN_BAND_PX, min(span, _MAX_BAND_PX))
    img = XLImage(io.BytesIO(compose_banner(title, width)))
    img.width, img.height = width, BAND_HEIGHT_PX
    img.anchor = OneCellAnchor(
        _from=AnchorMarker(col=0, colOff=0, row=0, rowOff=0),
        ext=XDRPositiveSize2D(pixels_to_EMU(width), pixels_to_EMU(BAND_HEIGHT_PX)),
    )
    ws.add_image(img)


def set_widths(ws: Worksheet, widths: Sequence[float]) -> None:
    for i, width in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = width
