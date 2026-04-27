"""Parse the VN brand sheets from the budget Excel and emit normalized JSON.

Output format (one record per (brand, model, period, indicator)):
    {
      "brand": "VW",
      "brand_full": "VOLKSWAGEN",
      "model": "TIGUAN TREND",
      "period_code": "2026-01" | "2026-S1" | "2026-S2" | "2026" | "2026-S1-actual",
      "indicator": "UNITES" | "CA" | "REVIENT" | "MARGES",
      "scenario": "BUDGET" | "ACTUAL",
      "value": <int|float|null>,
      "source_sheet": "VW",
      "source_cell": "D4"
    }

Usage:
    uvx --with openpyxl python scripts/parse-budget-vn.py \
        --input "<path>.xlsx" \
        --output parsed-budget.json \
        [--report]      # print summary stats instead of records
        [--anonymize]   # round values to 2 sig figs (for sharing structure)

NO confidential data leaves the machine unless the user explicitly chooses
to share the output JSON. The default produces JSON with raw values; pass
--report for safe-to-share statistics.
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
# Configuration: brand sheets layout
# ----------------------------------------------------------------------------

# Brands and their canonical codes
BRAND_SHEETS: dict[str, dict[str, Any]] = {
    "VW": {"full": "VOLKSWAGEN", "header_row_candidates": [2, 3]},
    "GW": {"full": "GREAT WALL", "header_row_candidates": [2, 3]},
    "CHERY": {"full": "CHERY", "header_row_candidates": [2, 3]},
    "LOVOL": {"full": "LOVOL", "header_row_candidates": [2, 3]},
    "SINOTRUK": {"full": "SINOTRUK", "header_row_candidates": [2, 3]},
    "SEALAND": {"full": "SEALANDS", "header_row_candidates": [2, 3]},
    "MOTOS": {"full": "MOTOS", "header_row_candidates": [2, 3]},
}

# Indicators expected in column B (or similar) — block of 4 rows per model
INDICATORS = ("UNITES", "CA", "REVIENT", "MARGES")
INDICATOR_ALIASES = {
    "UNITES": {"UNITES", "UNITÉS", "UNITE"},
    "CA": {"CA", "CHIFFRE D'AFFAIRES"},
    "REVIENT": {"REVIENT", "PRIX REVIENT", "COUT", "COÛT"},
    "MARGES": {"MARGES", "MARGE"},
}

# Months we expect in headers (lowercase, accent-stripped)
MONTH_PATTERNS = [
    (r"jan", 1),
    (r"f[eé]v", 2),
    (r"mar", 3),
    (r"avr", 4),
    (r"mai", 5),
    (r"juin", 6),
    (r"juil", 7),
    (r"ao[uû]", 8),
    (r"sept", 9),
    (r"oct", 10),
    (r"nov", 11),
    (r"d[eé]c", 12),
]


def normalize(s: str) -> str:
    """Lowercase + strip accents/spaces for fuzzy matching."""
    if not isinstance(s, str):
        return ""
    s = s.lower().strip()
    repl = str.maketrans("àâäéèêëîïôöùûüÿç", "aaaeeeeiioouuuyc")
    return s.translate(repl)


def detect_period_for_column(
    ws: Worksheet, col: int, header_rows: range
) -> str | None:
    """Try to figure out what period a column represents based on its header.

    Returns:
        period_code like "2026-01", "2026-S1", "2026-S2", "2026", or None
    """
    texts: list[str] = []
    for r in header_rows:
        v = ws.cell(row=r, column=col).value
        if v is None:
            continue
        if hasattr(v, "year") and hasattr(v, "month"):
            # datetime — extract month
            return f"{v.year:04d}-{v.month:02d}"
        if isinstance(v, str):
            texts.append(v)

    full_text = " ".join(texts)
    norm = normalize(full_text)

    # Semester totals
    if "budget 1" in norm or "budget s1" in norm or "1ere semestre" in norm:
        return "2026-S1-budget"
    if "real" in norm and ("1ere semestre" in norm or "s1" in norm):
        return "2026-S1-actual"
    if "budget 2" in norm or "budget s2" in norm or "2eme semestre" in norm or "2ème semestre" in norm:
        return "2026-S2-budget"
    if "budget 2026" in norm:
        return "2026-total"
    if "ajuste" in norm or "ajusté" in norm:
        return "2026-adjusted"

    # Match a single month from text
    for pattern, month in MONTH_PATTERNS:
        if re.search(pattern, norm):
            return f"2026-{month:02d}"

    return None


def find_indicator_column(ws: Worksheet, max_col: int = 5) -> int | None:
    """Find the column that contains UNITES/CA/REVIENT/MARGES labels.

    Usually column B but sometimes C.
    Returns 1-indexed column number or None.
    """
    for c in range(1, max_col + 1):
        hits = 0
        for r in range(2, min(ws.max_row + 1, 30)):
            v = ws.cell(row=r, column=c).value
            if isinstance(v, str):
                vu = v.strip().upper()
                for ind, aliases in INDICATOR_ALIASES.items():
                    if vu in aliases or any(a in vu for a in aliases):
                        hits += 1
                        break
        if hits >= 4:
            return c
    return None


def find_model_column(ws: Worksheet, indicator_col: int) -> int:
    """Model name is usually one column to the left of the indicator col."""
    return max(1, indicator_col - 1)


def parse_brand_sheet(
    ws: Worksheet, brand_code: str, brand_full: str, anonymize: bool = False
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Parse a brand sheet and return (records, metadata).

    metadata includes counts and anomalies.
    """
    records: list[dict[str, Any]] = []
    meta: dict[str, Any] = {
        "sheet": ws.title,
        "brand_code": brand_code,
        "brand_full": brand_full,
        "max_row": ws.max_row,
        "max_col": ws.max_column,
        "models_found": 0,
        "cells_extracted": 0,
        "anomalies": [],
    }

    indicator_col = find_indicator_column(ws)
    if indicator_col is None:
        meta["anomalies"].append("indicator column not detected")
        return records, meta
    meta["indicator_col"] = get_column_letter(indicator_col)

    model_col = find_model_column(ws, indicator_col)
    meta["model_col"] = get_column_letter(model_col)

    # Cap columns to scan (some sheets have 16k cols due to formatting)
    max_col = min(ws.max_column, 30)

    # Identify period for each data column (D..end)
    period_by_col: dict[int, str | None] = {}
    header_rows = range(1, 5)
    for c in range(1, max_col + 1):
        period = detect_period_for_column(ws, c, header_rows)
        period_by_col[c] = period

    meta["period_columns"] = {get_column_letter(c): p for c, p in period_by_col.items() if p}

    # Walk rows looking for "block of 4 rows" pattern
    r = 3  # start after header rows
    while r <= ws.max_row:
        # Read the indicator at this row
        ind_val = ws.cell(row=r, column=indicator_col).value
        ind_label = None
        if isinstance(ind_val, str):
            iv = ind_val.strip().upper()
            for canonical, aliases in INDICATOR_ALIASES.items():
                if iv in aliases or any(a in iv for a in aliases):
                    ind_label = canonical
                    break

        if ind_label != "UNITES":
            r += 1
            continue

        # Found a UNITES row — look for the model name (this row, model_col, or row above)
        model_name = None
        for try_r in (r, r - 1, r + 1):
            if try_r < 1 or try_r > ws.max_row:
                continue
            mv = ws.cell(row=try_r, column=model_col).value
            if isinstance(mv, str) and mv.strip() and len(mv.strip()) > 1:
                # Avoid taking indicator labels as model name
                if mv.strip().upper() not in {"UNITES", "CA", "REVIENT", "MARGES"}:
                    model_name = mv.strip()
                    break
        if not model_name:
            meta["anomalies"].append(f"UNITES at row {r} without model name")
            r += 4
            continue

        meta["models_found"] += 1

        # Extract this 4-row block
        for offset, expected_ind in enumerate(INDICATORS):
            data_r = r + offset
            actual_ind_val = ws.cell(row=data_r, column=indicator_col).value
            if isinstance(actual_ind_val, str):
                actual_iv = actual_ind_val.strip().upper()
                actual_ind = None
                for canonical, aliases in INDICATOR_ALIASES.items():
                    if actual_iv in aliases or any(a in actual_iv for a in aliases):
                        actual_ind = canonical
                        break
                if actual_ind != expected_ind:
                    # Not the expected pattern; could mean variable number of rows
                    continue

            for c in range(indicator_col + 1, max_col + 1):
                period = period_by_col.get(c)
                if not period:
                    continue
                val = ws.cell(row=data_r, column=c).value
                if val is None:
                    continue
                if not isinstance(val, (int, float)):
                    continue

                if anonymize:
                    # Round to 2 significant figures for safe sharing
                    if val == 0:
                        v_anon = 0
                    else:
                        from math import floor, log10

                        magnitude = floor(log10(abs(val)))
                        factor = 10 ** (magnitude - 1)
                        v_anon = round(val / factor) * factor
                    val = v_anon

                # Determine scenario from period suffix
                scenario = "BUDGET"
                if period.endswith("-actual"):
                    scenario = "ACTUAL"

                records.append(
                    {
                        "brand": brand_code,
                        "brand_full": brand_full,
                        "model": model_name,
                        "period_code": period,
                        "indicator": expected_ind,
                        "scenario": scenario,
                        "value": val,
                        "source_sheet": ws.title,
                        "source_cell": f"{get_column_letter(c)}{data_r}",
                    }
                )
                meta["cells_extracted"] += 1

        r += 4  # advance to next block

    return records, meta


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", required=True, help="Path to budget Excel")
    p.add_argument("--output", default="parsed-budget.json", help="JSON output path")
    p.add_argument("--report", action="store_true", help="Print summary stats only (safe to share)")
    p.add_argument("--anonymize", action="store_true", help="Round values to 2 sig figs in output")
    args = p.parse_args()

    src = Path(args.input)
    if not src.exists():
        print(f"Input not found: {src}", file=sys.stderr)
        return 1

    print(f"Loading {src.name} ({src.stat().st_size / 1024 / 1024:.2f} MB)...")
    wb = openpyxl.load_workbook(src, read_only=False, data_only=True)

    all_records: list[dict[str, Any]] = []
    all_meta: list[dict[str, Any]] = []

    for code, cfg in BRAND_SHEETS.items():
        if code not in wb.sheetnames:
            print(f"  WARN: sheet {code!r} not found", file=sys.stderr)
            continue
        ws = wb[code]
        records, meta = parse_brand_sheet(ws, code, cfg["full"], anonymize=args.anonymize)
        all_records.extend(records)
        all_meta.append(meta)
        print(
            f"  {code:<12s}  models={meta['models_found']:<3d}"
            f"  cells={meta['cells_extracted']:<5d}"
            f"  anomalies={len(meta['anomalies'])}"
        )

    # Always emit metadata (safe — no values)
    meta_path = Path(args.output).with_suffix(".meta.json")
    meta_path.write_text(json.dumps(all_meta, indent=2, default=str), encoding="utf-8")
    print(f"\nMetadata written: {meta_path}")

    if args.report:
        # Summary only — safe to share
        by_brand = defaultdict(lambda: defaultdict(int))
        for r in all_records:
            by_brand[r["brand"]][r["indicator"]] += 1

        print("\n=== REPORT (safe-to-share) ===")
        print(f"Total records extracted: {len(all_records)}")
        print(f"Unique models: {len({(r['brand'], r['model']) for r in all_records})}")
        print(f"Unique periods: {sorted({r['period_code'] for r in all_records})}")
        print()
        print(f"{'Brand':<12s} {'UNITES':>8s} {'CA':>8s} {'REVIENT':>8s} {'MARGES':>8s}")
        for b in sorted(by_brand):
            print(
                f"{b:<12s} "
                f"{by_brand[b]['UNITES']:>8d} "
                f"{by_brand[b]['CA']:>8d} "
                f"{by_brand[b]['REVIENT']:>8d} "
                f"{by_brand[b]['MARGES']:>8d}"
            )
    else:
        out_path = Path(args.output)
        out_path.write_text(json.dumps(all_records, indent=2, default=str), encoding="utf-8")
        print(f"\nOutput: {out_path} ({len(all_records)} records)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
