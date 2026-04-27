"""Parse SAV VP and SAV VL sheets from the budget Excel.

Output format (one record per (sheet, poste, period)):
    {
      "activity": "SAV-VP" | "SAV-VL",
      "poste": "CA sur pieces detachees Ateliers (...)",
      "section": "REVENUE" | "COST" | "MARGIN" | "OTHER",  # heuristic
      "period_code": "2026-01" .. "2026-12" | "2026-S1-budget"
                   | "2026-S2-budget" | "2026-total" | "hist-2024-real-S1"
                   | "hist-2025-real" | ...,
      "scenario": "BUDGET" | "ACTUAL",
      "value": <number>,
      "source_sheet": "SAV VP",
      "source_cell": "F4"
    }

Usage:
    uvx --with openpyxl python scripts/parse-sav.py
        --input <xlsx>
        --output scripts/.local/parsed-sav.json
        [--report]

Layouts (column-letter indexed):

  SAV VP (rows 3..end, headers in row 2):
    A=Poste  B=Real_S1_2024  C=Moy_2024  D=Real_2025  E=Moy_2025
    F-K=Jan-Jun 2026  L=S1  M-R=Jul-Dec 2026  S=S2  T=Total 2026

  SAV VL (rows 3..end, headers in row 2):
    A=Poste  B=Montant_annuel  C=Commentaires
    D=Real_S1_2024  E=Moy_2024  F=Real_2025  G=Moy_2025
    H-M=Jan-Jun 2026  N=S1  O-T=Jul-Dec 2026
    (no S2/Total cols — only 22 cols in this sheet)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

# ----------------------------------------------------------------------------
# Period layouts (hardcoded — these sheets have stable column positions)
# ----------------------------------------------------------------------------

PERIOD_LAYOUTS: dict[str, dict[int, str]] = {
    "SAV VP": {
        2: "hist-2024-real-S1",
        3: "hist-2024-monthly-avg",
        4: "hist-2025-real",
        5: "hist-2025-monthly-avg",
        6: "2026-01",
        7: "2026-02",
        8: "2026-03",
        9: "2026-04",
        10: "2026-05",
        11: "2026-06",
        12: "2026-S1-budget",
        13: "2026-07",
        14: "2026-08",
        15: "2026-09",
        16: "2026-10",
        17: "2026-11",
        18: "2026-12",
        19: "2026-S2-budget",
        20: "2026-total",
    },
    "SAV VL": {
        2: "annual-amount",  # col B = Montant annuel
        # col C = Commentaires (skip)
        4: "hist-2024-real-S1",
        5: "hist-2024-monthly-avg",
        6: "hist-2025-real",
        7: "hist-2025-monthly-avg",
        8: "2026-01",
        9: "2026-02",
        10: "2026-03",
        11: "2026-04",
        12: "2026-05",
        13: "2026-06",
        14: "2026-S1-budget",
        15: "2026-07",
        16: "2026-08",
        17: "2026-09",
        18: "2026-10",
        19: "2026-11",
        20: "2026-12",
    },
}

# ----------------------------------------------------------------------------
# Section detection (heuristic based on emoji + keywords)
# ----------------------------------------------------------------------------

SECTION_MARKERS = {
    "🔵": "SECTION_REVENUE_HEADER",
    "🔹": "SUBTOTAL_REVENUE",
    "🔸": "SECTION_COST_HEADER",
    "✅": "SECTION_MARGIN_HEADER",
    "📌": "NOTE",
}

REVENUE_KW = re.compile(r"\b(ca|chiffre.+affaires?|vente|recette|produit)\b", re.IGNORECASE)
COST_KW = re.compile(
    r"\b(co[uû]t|charge|d[eé]pense|achats?|frais|salaire|main\s*d.?[oœ]uvre)\b",
    re.IGNORECASE,
)
MARGIN_KW = re.compile(r"\b(marge|b[eé]n[eé]fice|r[eé]sultat)\b", re.IGNORECASE)
TOTAL_KW = re.compile(r"\btotal\b", re.IGNORECASE)


def classify_section(poste: str) -> str:
    """Heuristic section classifier from poste label."""
    if not poste:
        return "OTHER"
    s = poste.strip()
    # Look at emoji prefix first
    for marker, section in SECTION_MARKERS.items():
        if s.startswith(marker):
            return section
    # Keyword fallback
    if MARGIN_KW.search(s):
        return "MARGIN"
    if COST_KW.search(s):
        return "COST"
    if REVENUE_KW.search(s):
        return "REVENUE"
    if TOTAL_KW.search(s):
        return "SUBTOTAL"
    return "OTHER"


# ----------------------------------------------------------------------------
# Parser
# ----------------------------------------------------------------------------


def is_skippable_row(poste: Any, values: list[Any]) -> bool:
    """A row is skippable if poste is None/empty AND no numeric values."""
    if poste and isinstance(poste, str) and poste.strip():
        return False
    has_numeric = any(isinstance(v, (int, float)) for v in values)
    return not has_numeric


def parse_sav_sheet(
    ws: Worksheet, activity_code: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    layout = PERIOD_LAYOUTS[ws.title]
    records: list[dict[str, Any]] = []
    meta: dict[str, Any] = {
        "sheet": ws.title,
        "activity": activity_code,
        "max_row": ws.max_row,
        "max_col": ws.max_column,
        "postes_found": 0,
        "cells_extracted": 0,
        "anomalies": [],
    }

    # Data rows start at row 3 (row 2 is header, row 1 often empty)
    for r in range(3, ws.max_row + 1):
        poste = ws.cell(row=r, column=1).value
        all_values = [ws.cell(row=r, column=c).value for c in layout]

        if is_skippable_row(poste, all_values):
            continue

        if not isinstance(poste, str) or not poste.strip():
            meta["anomalies"].append(f"Row {r}: numeric values without poste label — skipped")
            continue

        poste_clean = poste.strip()

        # Skip pure section headers (no numbers, just emoji + label) — they
        # are still emitted as records-of-zero so the dashboard can show
        # the section structure
        section = classify_section(poste_clean)
        meta["postes_found"] += 1

        for col, period in layout.items():
            val = ws.cell(row=r, column=col).value
            if val is None:
                continue
            if not isinstance(val, (int, float)):
                continue

            scenario = "BUDGET"
            if "real" in period.lower() or "actual" in period.lower():
                scenario = "ACTUAL"

            records.append(
                {
                    "activity": activity_code,
                    "poste": poste_clean,
                    "section": section,
                    "period_code": period,
                    "scenario": scenario,
                    "value": val,
                    "source_sheet": ws.title,
                    "source_cell": f"{get_column_letter(col)}{r}",
                }
            )
            meta["cells_extracted"] += 1

    return records, meta


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True)
    p.add_argument("--output", default="parsed-sav.json")
    p.add_argument("--report", action="store_true")
    args = p.parse_args()

    src = Path(args.input)
    if not src.exists():
        print(f"Input not found: {src}", file=sys.stderr)
        return 1

    print(f"Loading {src.name}...")
    wb = openpyxl.load_workbook(src, read_only=False, data_only=True)

    sheets = [("SAV VP", "SAV-VP"), ("SAV VL", "SAV-VL")]
    all_records: list[dict[str, Any]] = []
    all_meta: list[dict[str, Any]] = []

    for sheet_name, activity_code in sheets:
        if sheet_name not in wb.sheetnames:
            print(f"  WARN: sheet {sheet_name!r} not found", file=sys.stderr)
            continue
        ws = wb[sheet_name]
        records, meta = parse_sav_sheet(ws, activity_code)
        all_records.extend(records)
        all_meta.append(meta)
        print(
            f"  {sheet_name:<10s}  postes={meta['postes_found']:<3d}"
            f"  cells={meta['cells_extracted']:<5d}"
            f"  anomalies={len(meta['anomalies'])}"
        )

    # Duplicate detection
    key_count: dict[tuple[str, str, str], int] = {}
    for rec in all_records:
        key = (rec["activity"], rec["poste"], rec["period_code"])
        key_count[key] = key_count.get(key, 0) + 1
    dups = {k: c for k, c in key_count.items() if c > 1}
    if dups:
        print(
            f"\nWARNING: {len(dups)} duplicate keys (activity, poste, period).",
            file=sys.stderr,
        )
        for k, c in list(dups.items())[:5]:
            print(f"  {k} x{c}", file=sys.stderr)

    # Write outputs
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path = out_path.with_suffix(".meta.json")
    meta_path.write_text(json.dumps(all_meta, indent=2, default=str), encoding="utf-8")
    print(f"\nMetadata: {meta_path}")

    if args.report:
        # Aggregate by activity × period × section
        by_period = defaultdict(lambda: defaultdict(float))
        for r in all_records:
            if not isinstance(r["value"], (int, float)):
                continue
            by_period[(r["activity"], r["section"])][r["period_code"]] += r["value"]

        print("\n=== REPORT (safe-to-share) ===")
        print(f"Total records: {len(all_records)}")
        print(f"Unique postes: {len({(r['activity'], r['poste']) for r in all_records})}")
        print()

        for (activity, section), periods in sorted(by_period.items()):
            print(f"\n--- {activity} / section={section} ---")
            for p in sorted(periods):
                print(f"  {p:<25s}  sum={periods[p]:>20,.0f}")
    else:
        out_path.write_text(json.dumps(all_records, indent=2, default=str), encoding="utf-8")
        print(f"\nOutput: {out_path} ({len(all_records)} records)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
