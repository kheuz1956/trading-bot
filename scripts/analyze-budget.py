"""Analyze the structure of the user's existing budget Excel file.

Output: structure summary (sheet names, dimensions, headers) — NO actual values
to avoid leaking sensitive financial data into logs/repo.

Run with: uvx --with openpyxl --with pandas python scripts/analyze-budget.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import openpyxl
from openpyxl.utils import get_column_letter

FILE = Path(
    r"C:\Users\CHEIKH MBACKE DIENG\Documents\AUDIT&CONTROLE DE GESTION"
    r"\BUDGET 2026\REVISION BUDGET 2026 VENTILLE RIST NOU CMD.xlsx"
)

if not FILE.exists():
    print(f"NOT FOUND: {FILE}", file=sys.stderr)
    sys.exit(1)

print(f"Loading {FILE.name} ({FILE.stat().st_size / 1024 / 1024:.2f} MB)...")
wb = openpyxl.load_workbook(FILE, read_only=True, data_only=True)

print(f"\n=== WORKBOOK SUMMARY ===")
print(f"Sheets count: {len(wb.sheetnames)}")
print(f"Active sheet: {wb.active.title}")

print(f"\n=== ALL SHEETS ===")
for i, name in enumerate(wb.sheetnames, 1):
    ws = wb[name]
    print(f"{i:3d}. {name:<55s}  rows={ws.max_row}  cols={ws.max_column}")

# Detail first 5 sheets
print(f"\n=== STRUCTURE OF EACH SHEET (first 8 rows × first 12 cols, no values) ===")
for name in wb.sheetnames[:30]:
    ws = wb[name]
    print(f"\n--- Sheet: {name} ---")
    print(f"  max_row={ws.max_row}, max_col={ws.max_column}")
    # Print only header row (row 1) and types of first data row to avoid leaking values
    if ws.max_row >= 1:
        headers = []
        for c in range(1, min(ws.max_column + 1, 25)):
            val = ws.cell(row=1, column=c).value
            if val is not None:
                headers.append(f"{get_column_letter(c)}={str(val)[:50]}")
        if headers:
            print(f"  Row 1 (headers): {headers}")

    # Show types of first data rows (without exposing values)
    if ws.max_row >= 2:
        types_row2 = []
        for c in range(1, min(ws.max_column + 1, 15)):
            val = ws.cell(row=2, column=c).value
            t = type(val).__name__ if val is not None else "None"
            types_row2.append(f"{get_column_letter(c)}:{t}")
        print(f"  Row 2 types:    {types_row2}")

    # If there are merged cells (often headers), report
    # Note: read_only mode doesn't expose merged_cells; reload non-readonly later if needed
print(f"\n=== DONE ===")
