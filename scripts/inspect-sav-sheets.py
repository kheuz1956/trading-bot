"""Deep inspection of SAV sheets (SAV VP, SAV VL, ATL & MAG).

Goal: understand the layout so we can extend the parser. Unlike brand
sheets (4-row blocks per model), these likely use 1-row-per-poste with
months as columns.
"""

from __future__ import annotations

from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter

FILE = Path(
    r"C:\Users\CHEIKH MBACKE DIENG\Documents\AUDIT&CONTROLE DE GESTION"
    r"\BUDGET 2026\REVISION BUDGET 2026 VENTILLE RIST NOU CMD.xlsx"
)
SHEETS = ["SAV VP", "SAV VL", "ATL& MAG"]


def cell_summary(val):
    if val is None:
        return ""
    if hasattr(val, "year") and hasattr(val, "month"):
        return f"DATE({val.year}-{val.month:02d}-{val.day:02d})"
    if isinstance(val, str):
        return f"STR({val[:35]!r})"
    if isinstance(val, (int, float)):
        if abs(val) < 1:
            return f"NUM({val:.4f})"
        if abs(val) > 1000:
            return f"NUM({val:,.0f})"
        return f"NUM({val})"
    return f"OTHER({type(val).__name__})"


wb = openpyxl.load_workbook(FILE, read_only=False, data_only=True)

for name in SHEETS:
    if name not in wb.sheetnames:
        print(f"\n[NOT FOUND] {name}")
        continue
    ws = wb[name]
    print(f"\n{'=' * 90}")
    print(f"Sheet: {name!r}    rows={ws.max_row}  cols={ws.max_column}")
    print(f"{'=' * 90}")

    # Header rows (1-5) for first 22 columns
    max_col = min(ws.max_column, 22)
    for r in range(1, min(6, ws.max_row + 1)):
        line = f"  R{r}: "
        for c in range(1, max_col + 1):
            v = ws.cell(row=r, column=c).value
            if v is not None:
                line += f"{get_column_letter(c)}={cell_summary(v)[:40]} | "
        print(line[:280])

    # Sample of data rows (8-15) col A and a couple of value cols
    print("  --- Sample data rows ---")
    for r in range(6, min(16, ws.max_row + 1)):
        line = f"  R{r}: "
        for c in range(1, max_col + 1):
            v = ws.cell(row=r, column=c).value
            if v is not None:
                line += f"{get_column_letter(c)}={cell_summary(v)[:30]} | "
        print(line[:280])
