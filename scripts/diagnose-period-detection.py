"""Diagnose: do multiple columns map to the same month in brand sheets?

For each brand sheet, print what each header column resolves to (month
or semester or none), and flag if multiple columns claim the same month.
This validates / invalidates the 'CA doubled' hypothesis.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter

FILE = Path(
    r"C:\Users\CHEIKH MBACKE DIENG\Documents\AUDIT&CONTROLE DE GESTION"
    r"\BUDGET 2026\REVISION BUDGET 2026 VENTILLE RIST NOU CMD.xlsx"
)
BRANDS = ["VW", "GW", "CHERY", "LOVOL", "SINOTRUK", "SEALAND", "MOTOS"]


def cell_summary(val):
    if val is None:
        return ""
    if hasattr(val, "year") and hasattr(val, "month"):
        return f"DATETIME({val.year}-{val.month:02d}-{val.day:02d})"
    if isinstance(val, str):
        return f"STR({val[:40]!r})"
    if isinstance(val, (int, float)):
        return f"NUM({val})"
    return f"OTHER({type(val).__name__})"


print(f"Loading {FILE.name}...")
wb = openpyxl.load_workbook(FILE, read_only=False, data_only=True)

for brand in BRANDS:
    if brand not in wb.sheetnames:
        continue
    ws = wb[brand]
    print(f"\n{'=' * 70}")
    print(f"Sheet: {brand}")
    print(f"{'=' * 70}")

    # For each column 1..30, print what's in rows 1-4
    max_col = min(ws.max_column, 30)
    rows_to_check = 4

    print(f"{'Col':<5}", end="")
    for r in range(1, rows_to_check + 1):
        print(f"{'R' + str(r):<35}", end="")
    print()
    print("-" * (5 + 35 * rows_to_check))

    for c in range(1, max_col + 1):
        col_letter = get_column_letter(c)
        print(f"{col_letter:<5}", end="")
        for r in range(1, rows_to_check + 1):
            val = ws.cell(row=r, column=c).value
            summary = cell_summary(val)[:34]
            print(f"{summary:<35}", end="")
        print()

    # Analysis: which columns have a datetime, what month does each resolve to?
    print("\n--- Datetime month analysis (excluding non-data columns) ---")
    month_to_cols = defaultdict(list)
    for c in range(1, max_col + 1):
        for r in range(1, rows_to_check + 1):
            val = ws.cell(row=r, column=c).value
            if hasattr(val, "year") and hasattr(val, "month"):
                month_to_cols[val.month].append(get_column_letter(c))
                break  # first datetime wins

    for month in sorted(month_to_cols):
        cols = month_to_cols[month]
        flag = "⚠️ DOUBLE" if len(cols) > 1 else "ok"
        print(f"  Month {month:2d}: cols {cols}  [{flag}]")

print(f"\n=== DONE ===")
