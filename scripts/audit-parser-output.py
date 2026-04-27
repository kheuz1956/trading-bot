"""Audit the parsed-budget.json to detect doubling/mis-classification.

Compares:
  A. Sum of CA across all 12 monthly records per brand
  B. Sum of CA in S1-budget records per brand
  C. Sum of CA in S2-budget records per brand
  D. Sum of CA in any other period codes per brand

If A == B + C  → parser is internally consistent (monthly sum = annual budget).
If A != B + C  → mis-classification or duplicate extraction.

Also flags:
  - duplicate (brand, model, period_code, indicator) tuples
  - records with suspicious period codes
"""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path

INPUT = Path("scripts/.local/parsed-budget.json")
if not INPUT.exists():
    print(f"NOT FOUND: {INPUT}", file=sys.stderr)
    sys.exit(1)

records = json.loads(INPUT.read_text(encoding="utf-8"))
print(f"Loaded {len(records):,} records from {INPUT}")
print()

# ===================================================================
# Per-brand aggregations
# ===================================================================
by_brand_monthly = defaultdict(float)
by_brand_s1 = defaultdict(float)
by_brand_s2 = defaultdict(float)
by_brand_other = defaultdict(lambda: defaultdict(float))

monthly_re = re.compile(r"^2026-\d{2}$")

for r in records:
    if r["indicator"] != "CA":
        continue
    val = r.get("value")
    if not isinstance(val, (int, float)):
        continue
    brand = r["brand"]
    p = r["period_code"]
    if monthly_re.match(p):
        by_brand_monthly[brand] += val
    elif p == "2026-S1-budget":
        by_brand_s1[brand] += val
    elif p == "2026-S2-budget":
        by_brand_s2[brand] += val
    elif p == "2026-S1-actual":
        by_brand_other[brand]["S1-actual"] += val
    else:
        by_brand_other[brand][p] += val

# ===================================================================
# Print comparison
# ===================================================================
brands = sorted(by_brand_monthly.keys() | by_brand_s1.keys() | by_brand_s2.keys())

print(f"{'Brand':<10} {'Monthly':>15} {'S1+S2':>15} {'Diff':>15} {'Ratio':>8}")
print("-" * 70)

total_monthly = 0
total_s1s2 = 0

for b in brands:
    m = by_brand_monthly[b]
    s1 = by_brand_s1[b]
    s2 = by_brand_s2[b]
    s1s2 = s1 + s2
    diff = m - s1s2
    ratio = m / s1s2 if s1s2 else float("nan")
    print(f"{b:<10} {m:>15,.0f} {s1s2:>15,.0f} {diff:>15,.0f} {ratio:>8.3f}")
    total_monthly += m
    total_s1s2 += s1s2

total_diff = total_monthly - total_s1s2
total_ratio = total_monthly / total_s1s2 if total_s1s2 else float("nan")
print("-" * 70)
print(f"{'TOTAL':<10} {total_monthly:>15,.0f} {total_s1s2:>15,.0f} {total_diff:>15,.0f} {total_ratio:>8.3f}")

print()
print("Other period codes detected (per brand):")
for b in brands:
    other = by_brand_other.get(b, {})
    if other:
        print(f"  {b}: {dict(other)}")

# ===================================================================
# Duplicate detection
# ===================================================================
print()
print("=" * 70)
print("Duplicate detection: (brand, model, period, indicator)")
print("=" * 70)

key_count = defaultdict(int)
for r in records:
    key = (r["brand"], r["model"], r["period_code"], r["indicator"])
    key_count[key] += 1

dups = {k: c for k, c in key_count.items() if c > 1}
if dups:
    print(f"FOUND {len(dups)} duplicate keys (showing first 20):")
    for k, c in list(dups.items())[:20]:
        print(f"  {k} ×{c}")
else:
    print("No duplicates found.")

# ===================================================================
# Period code distribution
# ===================================================================
print()
print("=" * 70)
print("Period code distribution (CA records only)")
print("=" * 70)

period_count = defaultdict(int)
period_sum = defaultdict(float)
for r in records:
    if r["indicator"] != "CA":
        continue
    val = r.get("value")
    period_count[r["period_code"]] += 1
    if isinstance(val, (int, float)):
        period_sum[r["period_code"]] += val

for p in sorted(period_count):
    print(f"  {p:<25} count={period_count[p]:<5} sum={period_sum[p]:>20,.0f}")
