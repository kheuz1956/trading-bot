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
SAV_OUTPUT = REPO_ROOT / "scripts" / ".local" / "parsed-sav.json"
SAV_META_OUTPUT = REPO_ROOT / "scripts" / ".local" / "parsed-sav.meta.json"


def run_parser(src: Path) -> tuple[list[dict], list[dict]]:
    """Run the VN parser script, return (records, brand_meta)."""
    parser_script = REPO_ROOT / "scripts" / "parse-budget-vn.py"
    print(f"Running VN parser on {src.name}...")

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
        print(f"VN parser failed:\n{result.stderr}", file=sys.stderr)
        sys.exit(1)
    print(result.stdout)

    records = json.loads(PARSER_OUTPUT.read_text(encoding="utf-8"))
    brand_meta = json.loads(META_OUTPUT.read_text(encoding="utf-8"))
    return records, brand_meta


def run_sav_parser(src: Path) -> tuple[list[dict], list[dict]]:
    """Run the SAV parser script, return (records, sav_meta). Soft-fails."""
    parser_script = REPO_ROOT / "scripts" / "parse-sav.py"
    if not parser_script.exists():
        print("SAV parser script not found — skipping SAV section.")
        return [], []
    print(f"Running SAV parser on {src.name}...")

    SAV_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            sys.executable,
            str(parser_script),
            "--input",
            str(src),
            "--output",
            str(SAV_OUTPUT),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if result.returncode != 0:
        print(f"SAV parser failed (non-fatal):\n{result.stderr}", file=sys.stderr)
        return [], []
    print(result.stdout)

    records = json.loads(SAV_OUTPUT.read_text(encoding="utf-8")) if SAV_OUTPUT.exists() else []
    sav_meta = (
        json.loads(SAV_META_OUTPUT.read_text(encoding="utf-8")) if SAV_META_OUTPUT.exists() else []
    )
    return records, sav_meta


def build_dashboard(
    records: list[dict],
    brand_meta: list[dict],
    sav_records: list[dict],
    sav_meta: list[dict],
    src: Path,
    out: Path,
) -> None:
    if not TEMPLATE.exists():
        print(f"Template not found: {TEMPLATE}", file=sys.stderr)
        sys.exit(1)

    template_html = TEMPLATE.read_text(encoding="utf-8")

    meta = {
        "source_file": src.name,
        "build_date": dt.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "record_count": len(records),
        "sav_record_count": len(sav_records),
        "brand_meta": brand_meta,
        "sav_meta": sav_meta,
    }

    # Use compact JSON to keep file size reasonable
    data_json = json.dumps(records, separators=(",", ":"), ensure_ascii=False)
    sav_json = json.dumps(sav_records, separators=(",", ":"), ensure_ascii=False)
    meta_json = json.dumps(meta, separators=(",", ":"), ensure_ascii=False, default=str)

    # Replace placeholders.
    populated = (
        template_html.replace("__DATA__", data_json)
        .replace("__SAV_DATA__", sav_json)
        .replace("__META__", meta_json)
    )

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(populated, encoding="utf-8")

    size_kb = out.stat().st_size / 1024
    print(f"\nDashboard written: {out}")
    print(f"  Size: {size_kb:,.1f} KB")
    print(f"  VN records embedded:  {len(records):,}")
    print(f"  SAV records embedded: {len(sav_records):,}")
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
    sav_records, sav_meta = run_sav_parser(src)
    build_dashboard(records, brand_meta, sav_records, sav_meta, src, Path(args.output))
    return 0


if __name__ == "__main__":
    sys.exit(main())
