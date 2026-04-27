"""Parse CPT EXPL (Compte d'Exploitation) sheet from the budget Excel.

The CPT EXPL sheet contains the P&L aggregated by poste (account-like
rows) with monthly + S1 + S2 + Total columns for 2026. Unlike brand
sheets (4-row UNITES/CA/REVIENT/MARGES blocks), here each row is a
single poste with one value per period.

Output format (one record per (poste, period)):
    {
      "section": "VENTES" | "ACHATS" | "FRAIS_GENERAUX" | "MARGES"
                | "RESULTAT" | "OTHER",  # heuristic
      "poste_code": "RVENTES CHERY" | "PVENTES VW" | None,
      "poste_label": "VENTES CHERY",
      "period_code": "2026-01" .. "2026-12" | "2026-S1-budget"
                  | "2026-S1-actual" | "2026-S2-budget" | "2026-total",
      "scenario": "BUDGET" | "ACTUAL",
      "value": <number>,
      "source_sheet": "CPT EXPL",
      "source_cell": "D4"
    }
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

import openpyxl
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

# CPT EXPL has the same column layout as VW brand sheets.
# Headers in row 3:
#   A=R<code>  B=P<code>  C=POSTE LABEL
#   D-I=2026 Jan-Jun  J=Budget S1  K=Réal S1
#   M-R=2026 Jul-Dec  S=Budget S2  T=BUDGET 2026 (S1+S2)
# Note: column L is empty / decorative.
PERIOD_LAYOUT: dict[int, str] = {
    4: "2026-01",
    5: "2026-02",
    6: "2026-03",
    7: "2026-04",
    8: "2026-05",
    9: "2026-06",
    10: "2026-S1-budget",
    11: "2026-S1-actual",
    13: "2026-07",
    14: "2026-08",
    15: "2026-09",
    16: "2026-10",
    17: "2026-11",
    18: "2026-12",
    19: "2026-S2-budget",
    20: "2026-total",
}

# Section heuristics based on poste label.
# IMPORTANT: order matters — first match wins. Place specific before generic.
SECTION_RULES = [
    (re.compile(r"\bventes?\b|\bvente\b|\bca\b", re.IGNORECASE), "VENTES"),
    (re.compile(r"\bachats?\b|approvisionn|\bappro\b", re.IGNORECASE), "ACHATS"),
    (re.compile(r"\bmarges?\b|\bmb\b|\bmn\b", re.IGNORECASE), "MARGES"),
    (
        re.compile(
            r"\bsalaire|\bcharges?\s+(personnel|salair)|\bpersonnel\b|effectif",
            re.IGNORECASE,
        ),
        "PERSONNEL",
    ),
    (re.compile(r"\bimp[oô]ts?\b|\btaxes?\b", re.IGNORECASE), "IMPOTS"),
    (re.compile(r"\br[eé]sultats?\b|\bb[eé]n[eé]fice|\bperte\b", re.IGNORECASE), "RESULTAT"),
    (
        re.compile(
            r"\bfrais\b|\btransport|\bloyer|\bmarketing\b|\bcharges?\s+(externes|fin)",
            re.IGNORECASE,
        ),
        "FRAIS_GENERAUX",
    ),
]


def classify_poste(label: str) -> str:
    if not label:
        return "OTHER"
    for pattern, section in SECTION_RULES:
        if pattern.search(label):
            return section
    return "OTHER"


def parse_cpt_expl(ws: Worksheet) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    records: list[dict[str, Any]] = []
    meta: dict[str, Any] = {
        "sheet": ws.title,
        "max_row": ws.max_row,
        "max_col": ws.max_column,
        "postes_found": 0,
        "cells_extracted": 0,
        "anomalies": [],
    }

    # Data rows start at row 4 (rows 1-3 are titles + headers)
    for r in range(4, ws.max_row + 1):
        # Get poste from columns A, B, C (preference: C label, fall back A, B)
        code_a = ws.cell(row=r, column=1).value  # e.g. "RVENTES CHERY"
        code_b = ws.cell(row=r, column=2).value  # e.g. "PVENTES CHERY"
        label_c = ws.cell(row=r, column=3).value  # e.g. "VENTES CHERY"

        # Skip empty rows
        all_values = [ws.cell(row=r, column=col).value for col in PERIOD_LAYOUT]
        has_numeric = any(isinstance(v, (int, float)) and v != 0 for v in all_values)

        poste_label = None
        if isinstance(label_c, str) and label_c.strip():
            poste_label = label_c.strip()
        elif isinstance(code_a, str) and code_a.strip():
            poste_label = code_a.strip()
        elif isinstance(code_b, str) and code_b.strip():
            poste_label = code_b.strip()

        if not poste_label:
            continue

        if not has_numeric and not poste_label:
            continue

        meta["postes_found"] += 1

        poste_code = (
            (code_a if isinstance(code_a, str) else None)
            or (code_b if isinstance(code_b, str) else None)
        )
        section = classify_poste(poste_label)

        for col, period in PERIOD_LAYOUT.items():
            val = ws.cell(row=r, column=col).value
            if val is None or not isinstance(val, (int, float)):
                continue

            scenario = "ACTUAL" if "actual" in period.lower() else "BUDGET"

            records.append(
                {
                    "section": section,
                    "poste_code": poste_code.strip() if isinstance(poste_code, str) else None,
                    "poste_label": poste_label,
                    "period_code": period,
                    "scenario": scenario,
                    "value": val,
                    "source_sheet": ws.title,
                    "source_cell": f"{get_column_letter(col)}{r}",
                }
            )
            meta["cells_extracted"] += 1

    return records, meta


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True)
    p.add_argument("--output", default="parsed-cpt-expl.json")
    p.add_argument("--report", action="store_true")
    args = p.parse_args()

    src = Path(args.input)
    if not src.exists():
        print(f"Input not found: {src}", file=sys.stderr)
        return 1

    print(f"Loading {src.name}...")
    wb = openpyxl.load_workbook(src, read_only=False, data_only=True)

    if "CPT EXPL" not in wb.sheetnames:
        print("Sheet 'CPT EXPL' not found", file=sys.stderr)
        return 1

    records, meta = parse_cpt_expl(wb["CPT EXPL"])
    print(
        f"  CPT EXPL  postes={meta['postes_found']}  "
        f"cells={meta['cells_extracted']}  anomalies={len(meta['anomalies'])}"
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    meta_path = out_path.with_suffix(".meta.json")
    meta_path.write_text(json.dumps([meta], indent=2, default=str), encoding="utf-8")
    print(f"\nMetadata: {meta_path}")

    if args.report:
        from collections import defaultdict

        by_section_period = defaultdict(lambda: defaultdict(float))
        for r in records:
            if isinstance(r["value"], (int, float)):
                by_section_period[r["section"]][r["period_code"]] += r["value"]

        print(f"\n=== REPORT (safe-to-share) ===")
        print(f"Total records: {len(records)}")
        print(f"Unique postes: {len({r['poste_label'] for r in records})}")
        for section in sorted(by_section_period):
            print(f"\n--- Section: {section} ---")
            for p in sorted(by_section_period[section]):
                v = by_section_period[section][p]
                print(f"  {p:<25}  sum={v:>20,.0f}")
    else:
        out_path.write_text(json.dumps(records, indent=2, default=str), encoding="utf-8")
        print(f"\nOutput: {out_path} ({len(records)} records)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
