"""Build a local self-contained dashboard from the user's budget Excel.

Reads the user's Excel via the existing parser, then injects the JSON data
INLINE into a copy of dashboard/index.html. The resulting file is fully
self-contained and openable from file:// (no server needed).

Output goes to scripts/.local/dashboard.html which is gitignored — the
populated dashboard contains real financial values and must NEVER be
committed.

Usage:
    uvx --with openpyxl python scripts/build-local-dashboard.py
        [--input <path-to-xlsx>]
        [--output scripts/.local/dashboard.html]

Defaults read the user's budget at the path used during parser dev.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

DEFAULT_INPUT = Path(
    r"C:\Users\CHEIKH MBACKE DIENG\Documents\AUDIT&CONTROLE DE GESTION"
    r"\BUDGET 2026\REVISION BUDGET 2026 VENTILLE RIST NOU CMD.xlsx"
)
REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = REPO_ROOT / "dashboard" / "index.html"
DEFAULT_OUTPUT = REPO_ROOT / "scripts" / ".local" / "dashboard.html"
PARSER_OUTPUT = REPO_ROOT / "scripts" / ".local" / "parsed-budget.json"
META_OUTPUT = REPO_ROOT / "scripts" / ".local" / "parsed-budget.meta.json"


def run_parser(src: Path) -> tuple[list[dict], list[dict]]:
    """Run the parser script, return (records, brand_meta)."""
    parser_script = REPO_ROOT / "scripts" / "parse-budget-vn.py"
    print(f"Running parser on {src.name}...")

    PARSER_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            sys.executable,
            str(parser_script),
            "--input",
            str(src),
            "--output",
            str(PARSER_OUTPUT),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        print(f"Parser failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    print(result.stdout)

    records = json.loads(PARSER_OUTPUT.read_text(encoding="utf-8"))
    brand_meta = json.loads(META_OUTPUT.read_text(encoding="utf-8"))
    return records, brand_meta


def build_dashboard(records: list[dict], brand_meta: list[dict], src: Path, out: Path) -> None:
    if not TEMPLATE.exists():
        print(f"Template not found: {TEMPLATE}", file=sys.stderr)
        sys.exit(1)

    template_html = TEMPLATE.read_text(encoding="utf-8")

    meta = {
        "source_file": src.name,
        "build_date": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "record_count": len(records),
        "brand_meta": brand_meta,
    }

    # Use compact JSON to keep file size reasonable
    data_json = json.dumps(records, separators=(",", ":"), ensure_ascii=False)
    meta_json = json.dumps(meta, separators=(",", ":"), ensure_ascii=False, default=str)

    # Replace placeholders. Use simple string replace — the template has these
    # exact tokens nowhere else (verified manually in dashboard/index.html).
    populated = template_html.replace("__DATA__", data_json).replace("__META__", meta_json)

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(populated, encoding="utf-8")

    size_kb = out.stat().st_size / 1024
    print(f"\nDashboard written: {out}")
    print(f"  Size: {size_kb:,.1f} KB")
    print(f"  Records embedded: {len(records):,}")
    print(f"  Open in browser: file:///{out.as_posix()}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", default=str(DEFAULT_INPUT), help="Path to budget Excel")
    p.add_argument("--output", default=str(DEFAULT_OUTPUT), help="Output dashboard HTML")
    args = p.parse_args()

    src = Path(args.input)
    if not src.exists():
        print(f"Input not found: {src}", file=sys.stderr)
        return 1

    records, brand_meta = run_parser(src)
    build_dashboard(records, brand_meta, src, Path(args.output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
