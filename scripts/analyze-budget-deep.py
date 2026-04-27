"""Deep analysis of priority sheets in the budget Excel.

For each priority sheet, find the real header row (often in rows 1-6 due to
merged cells), then list non-empty header cells with their column letters.
Detect month patterns to understand period axis.

NO actual values are printed — only structure metadata.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.utils import get_column_letter

FILE = Path(
    r"C:\Users\CHEIKH MBACKE DIENG\Documents\AUDIT&CONTROLE DE GESTION"
    r"\BUDGET 2026\REVISION BUDGET 2026 VENTILLE RIST NOU CMD.xlsx"
)

PRIORITY = [
    "BUDGET 2010",  # Main budget framework
    "CPT EXPL",  # Compte d'exploitation
    "RSTAT",  # Résultat
    "BFR",  # Besoin fonds de roulement
    "PILOTAG",  # Pilotage
    "VENTES 2023",  # Ventes (already known structure)
    "CA VN 2023",  # CA véhicules neufs
    "CA VN",  # CA véhicules neufs (current)
    "VW",  # Volkswagen
    "GW",  # Great Wall
    "CHERY",
    "LOVOL",
    "SINOTRUK",
    "SEALAND",
    "MOTOS",
    "SAV VP",  # SAV véhicules particuliers
    "SAV VL",  # SAV véhicules légers
    "ATL& MAG",  # Atelier & magasin
    "ACHAT VP",
    "ACHAT VL",
    "COMMANDE",
    "COUT CMD",
    "TVA",
    "ENCAISSEMENTS",
    "DECAISSEMENTS",
    "Compte de resultat",
    "CHARGES FONCTIONNEMENT 25",
    "RECAP BUDGET ACH 25",
    "Objectifs commerciaux 2024",
    "FRAIS.APP.ACHATS",
    "MRKTING",
    "CMD",
    "FIN CMD",
    "DC",
    "F F",
    "PVN",
    "TAIRIF",
    "TAR",
    "SEUIL RENTAB",
    "CT AN",
    "CA GL",
    "Budget SAV & MAG 2024",
    "2025",
]


def cell_summary(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, (int, float)):
        return f"<{type(val).__name__}>"
    if hasattr(val, "year"):
        # datetime — show only year (no day/month-specific)
        return f"<date:{val.year}>"
    s = str(val)
    return s[:80].replace("\n", " ")


def analyze_sheet(wb: openpyxl.Workbook, name: str) -> None:
    ws = wb[name]
    print(f"\n{'=' * 70}")
    print(f"Sheet: {name!r}    rows={ws.max_row}  cols={ws.max_column}")
    print(f"{'=' * 70}")

    # Print rows 1 to 8 (or until we have content)
    rows_to_show = min(8, ws.max_row)
    cols_to_show = min(20, ws.max_column)

    for r in range(1, rows_to_show + 1):
        row_data = []
        for c in range(1, cols_to_show + 1):
            cell = ws.cell(row=r, column=c)
            val = cell.value
            if val is not None:
                summary = cell_summary(val)
                if summary:
                    row_data.append(f"{get_column_letter(c)}{r}={summary}")
        if row_data:
            print(f"  R{r}: {row_data}")

    # Detect "month header" patterns by scanning rows 1-10 for common French month names
    months_fr = [
        "jan",
        "fév",
        "fev",
        "mar",
        "avr",
        "mai",
        "juin",
        "juil",
        "aoû",
        "aou",
        "sep",
        "oct",
        "nov",
        "déc",
        "dec",
    ]
    month_hits: list[tuple[int, int, str]] = []  # (row, col, value)
    for r in range(1, min(11, ws.max_row + 1)):
        for c in range(1, min(ws.max_column + 1, 30)):
            val = ws.cell(row=r, column=c).value
            if isinstance(val, str):
                low = val.lower()
                for m in months_fr:
                    if m in low:
                        month_hits.append((r, c, val[:20]))
                        break
    if month_hits:
        print(f"  → Month-like headers found: {len(month_hits)} cells")
        for r, c, v in month_hits[:6]:
            print(f"     {get_column_letter(c)}{r}={v!r}")
        if len(month_hits) > 6:
            print(f"     ... +{len(month_hits) - 6} more")


print(f"Loading {FILE.name}...")
wb = openpyxl.load_workbook(FILE, read_only=False, data_only=True)

for name in PRIORITY:
    if name in wb.sheetnames:
        try:
            analyze_sheet(wb, name)
        except Exception as e:
            print(f"\n!!! Error analyzing {name}: {e}", file=sys.stderr)
    else:
        print(f"\n--- Sheet not found: {name} ---", file=sys.stderr)

print(f"\n=== DONE ===")
