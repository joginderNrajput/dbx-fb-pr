"""TODO(prompt 09 - assess flow): read a reviewed discovery workbook back into a report.

The discovery workbook is a file format: its data sheets' headers and row order are a
contract (``writer.DATA_SHEETS``). The reader will rebuild ``DiscoveryReport`` from the rows
and recompute every total, so editing a row changes the assessment and editing a total does
not. Until then, ``--input snapshot.json`` is the supported way to re-run a discovery.
"""

from __future__ import annotations

__all__: list[str] = []
