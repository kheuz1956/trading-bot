"""Find the source cells that produce duplicate 2026-03 UNITES records."""

from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

records = json.loads(Path("scripts/.local/parsed-budget.json").read_text(encoding="utf-8"))

groups = defaultdict(list)
for r in records:
    if r["period_code"] == "2026-03" and r["indicator"] == "UNITES":
        key = (r["brand"], r["model"])
        groups[key].append((r["source_sheet"], r["source_cell"], r["value"]))

print("Duplicates for 2026-03 UNITES (showing source cells):")
print("=" * 80)
for (brand, model), entries in sorted(groups.items()):
    if len(entries) > 1:
        print(f"\n{brand} | {model}")
        for sheet, cell, val in entries:
            print(f"  -> {sheet}!{cell} = {val}")
