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

# Months we expect in headers (lowercase, accent-stripped). Patterns must
# use word boundaries — naive substrings like "mar" would match "marque",
# "marge", "marketing", etc. and assign random columns to March.
MONTH_PATTERNS = [
    (r"\bjanvier\b|\bjanv?\b", 1),
    (r"\bf[eé]vrier\b|\bf[eé]v\b", 2),
    (r"\bmars\b", 3),
    (r"\bavril\b|\bavr\b", 4),
    (r"\bmai\b", 5),
    (r"\bjuin\b", 6),
    (r"\bjuillet\b|\bjuil\b", 7),
    (r"\bao[uû]t\b", 8),
    (r"\bseptembre\b|\bsept\b", 9),
    (r"\boctobre\b|\boct\b", 10),
    (r"\bnovembre\b|\bnov\b", 11),
    (r"\bd[eé]cembre\b|\bd[eé]c\b", 12),
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

    Order of checks matters: most specific first to avoid greedy substring
    matches (e.g., "BUDGET 2026 (Budget S1+S2)" must NOT match the S1-budget
    rule).

    Returns:
        period_code: "2026-01" .. "2026-12", "2026-S1-budget",
        "2026-S1-actual", "2026-S2-budget", "2026-S2-actual",
        "2026-total", "2026-adjusted", or None.
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
    if not norm:
        return None

    # ---- Most specific first ----

    # Annual total — must come before S2 / S1 budget checks because the
    # text "BUDGET 2026 (Budget S1+S2)" contains the substrings "budget s1",
    # "budget s2" and "budget 2".
    if re.search(r"\bbudget\s*2026\b", norm) or "s1+s2" in norm:
        return "2026-total"

    # Adjusted/forecast (Budget 2025 ajusté aux réalisations)
    if "ajuste" in norm:
        return "2026-adjusted"

    # Semester real/actual — keyword "real" present
    if re.search(r"\breal", norm):
        if "s1" in norm or "1ere semestre" in norm or "1er semestre" in norm:
            return "2026-S1-actual"
        if "s2" in norm or "2eme semestre" in norm or "2nd semestre" in norm:
            return "2026-S2-actual"

    # Semester budget — must use word boundaries to avoid matching inside
    # "Budget 2026" (already handled above) and "S1+S2" (already handled).
    if re.search(r"\bbudget\s*1(?:e|ere?)?\s*semestre\b", norm) or re.search(
        r"\bbudget\s*s1\b", norm
    ):
        return "2026-S1-budget"
    if re.search(r"\bbudget\s*2(?:e|eme|nd)?\s*semestre\b", norm) or re.search(
        r"\bbudget\s*s2\b", norm
    ):
        return "2026-S2-budget"

    # Match a single month from text (last resort)
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

    # Identify period for each data column. Skip columns to the LEFT of the
    # indicator (those are model-name / category columns, never periods),
    # and if two columns still map to the same period, keep only the
    # LEFT-MOST one — extra columns to the right are typically user-added
    # derived columns (margin %, growth rate) whose date header collides
    # with a real month.
    period_by_col: dict[int, str | None] = {}
    seen_periods: dict[str, int] = {}  # period -> first column that claimed it
    header_rows = range(1, 5)
    for c in range(indicator_col + 1, max_col + 1):
        period = detect_period_for_column(ws, c, header_rows)
        if period is None:
            period_by_col[c] = None
            continue
        if period in seen_periods:
            meta["anomalies"].append(
                f"Column {get_column_letter(c)} also claims period {period} "
                f"(already taken by {get_column_letter(seen_periods[period])}) — ignored"
            )
            period_by_col[c] = None
        else:
            period_by_col[c] = period
            seen_periods[period] = c

    meta["period_columns"] = {get_column_letter(c): p for c, p in period_by_col.items() if p}

    # Track model names we've already seen to handle real Excel duplicates
    # (e.g. GW sheet has 'H6 TOP' on rows 15 AND 35) — disambiguate with suffix
    # so the (brand, model) key remains unique downstream.
    model_seen: dict[str, int] = {}

    # Patterns that indicate the row is a SUMMARY / TOTAL line, not a real model.
    # These rows appear in some sheets (e.g. GW row 76 = "TOTAL PREVISION") and
    # would inflate aggregations if kept.
    SUMMARY_RE = re.compile(
        r"\b(total|somme|recap|recapitulatif|general|grand[\s_-]?total|sous[\s_-]?total)\b",
        re.IGNORECASE,
    )

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

        # Skip summary / total rows that are not real vehicle models
        if SUMMARY_RE.search(model_name):
            meta["anomalies"].append(
                f"Skipped summary row at {r}: {model_name!r} (matched TOTAL/SOMME/RECAP)"
            )
            r += 4
            continue

        # Disambiguate real duplicates: H6 TOP appearing twice → 'H6 TOP', 'H6 TOP (#2)', ...
        if model_name in model_seen:
            model_seen[model_name] += 1
            disambiguated = f"{model_name} (#{model_seen[model_name]})"
            meta["anomalies"].append(
                f"Duplicate model {model_name!r} at row {r} → renamed {disambiguated!r}"
            )
            model_name = disambiguated
        else:
            model_seen[model_name] = 1

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

    # ---- Duplicate detection ----
    key_count: dict[tuple[str, str, str, str], int] = {}
    for rec in all_records:
        key = (rec["brand"], rec["model"], rec["period_code"], rec["indicator"])
        key_count[key] = key_count.get(key, 0) + 1
    dups = {k: c for k, c in key_count.items() if c > 1}
    if dups:
        print(
            f"\n⚠️  WARNING: {len(dups)} duplicate keys found "
            f"(same brand/model/period/indicator extracted from multiple cells).",
            file=sys.stderr,
        )
        # Show top 5
        for k, c in list(dups.items())[:5]:
            print(f"     {k} ×{c}", file=sys.stderr)
        if len(dups) > 5:
            print(f"     ... +{len(dups) - 5} more", file=sys.stderr)
        print(
            "     This usually means the period detection misclassified a column; "
            "check the period_columns metadata.",
            file=sys.stderr,
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
