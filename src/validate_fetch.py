"""
validate_fetch.py — Pre-recon data quality validator.

Validates the 4 CSVs produced by fetch_data.py before recon.py runs.
Catches schema gaps, null keys, and suspicious metrics early with clear,
actionable error messages.

Usage:
    python src/validate_fetch.py
"""

import sys
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent

# Each file definition:
#   filename      : name in repo root
#   null_key      : column that must never be null (hard stop)
#   sku_col       : SKU-type column that must never be null (hard stop)
#   metric_cols   : numeric columns to check for negatives (warning only)

FILE_SPECS: list[dict] = [
    {
        "filename":    "kit_prepared.csv",
        "null_key":    "warehouse_id",
        "sku_col":     "sku_group_id",
        "metric_cols": ["item_quantity"],
    },
    {
        "filename":    "calc_direct_refill.csv",
        "null_key":    "warehouse_id",
        "sku_col":     "sku_group_id",
        "metric_cols": ["calc_direct_refill"],
    },
    {
        "filename":    "ops.csv",
        "null_key":    "warehouse_id",
        "sku_col":     "sku_group_id",
        "metric_cols": ["extra", "remove", "expiry"],
    },
    {
        "filename":    "sales.csv",
        "null_key":    "warehouse_id",
        "sku_col":     "manufacturer_variant_id",
        "metric_cols": ["sales"],
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt(n) -> str:
    """Format a number with comma thousands separator."""
    if isinstance(n, float) and n == int(n):
        return f"{int(n):,}"
    if isinstance(n, float):
        return f"{n:,.2f}"
    return f"{n:,}"


# ---------------------------------------------------------------------------
# Per-file validation
# ---------------------------------------------------------------------------

def validate_file(spec: dict) -> tuple[int, int]:
    """
    Run all checks for one file spec.

    Returns (hard_stops, warnings) increments from this file.
    Prints its own section header and results.
    """
    filename    = spec["filename"]
    null_key    = spec["null_key"]
    sku_col     = spec["sku_col"]
    metric_cols = spec["metric_cols"]

    path = ROOT / filename
    hard_stops = 0
    warnings   = 0

    print(f"\n=== {filename} ===")

    # ------------------------------------------------------------------
    # 1. File exists
    # ------------------------------------------------------------------
    if not path.exists():
        print(f"  ERROR: file not found → {path}")
        hard_stops += 1
        return hard_stops, warnings  # nothing else to check

    # ------------------------------------------------------------------
    # 2. Load
    # ------------------------------------------------------------------
    df = pd.read_csv(path, dtype=str)

    # ------------------------------------------------------------------
    # 3. Not empty
    # ------------------------------------------------------------------
    row_count = len(df)
    print(f"  rows        : {_fmt(row_count)}")
    if row_count == 0:
        print(f"  ERROR: file is empty — 0 rows.")
        hard_stops += 1
        return hard_stops, warnings

    # ------------------------------------------------------------------
    # 4. No null warehouse_id
    # ------------------------------------------------------------------
    if null_key not in df.columns:
        print(f"  ERROR: column '{null_key}' missing from file.")
        hard_stops += 1
    else:
        null_wh = df[null_key].isna() | (df[null_key].str.strip() == "")
        null_wh_count = null_wh.sum()
        if null_wh_count > 0:
            affected_vms = (
                df.loc[null_wh, "vending_machine_id"].dropna().unique().tolist()
                if "vending_machine_id" in df.columns
                else []
            )
            print(
                f"  {null_key}: ERROR — {_fmt(null_wh_count)} null row(s)."
                f" Affected vending_machine_ids: {affected_vms}"
            )
            hard_stops += 1
        else:
            print(f"  {null_key}: OK (no nulls)")

    # ------------------------------------------------------------------
    # 5. No null SKU column
    # ------------------------------------------------------------------
    if sku_col not in df.columns:
        print(f"  ERROR: column '{sku_col}' missing from file.")
        hard_stops += 1
    else:
        null_sku = df[sku_col].isna() | (df[sku_col].str.strip() == "")
        null_sku_count = null_sku.sum()
        if null_sku_count > 0:
            print(f"  {sku_col}: ERROR — {_fmt(null_sku_count)} null row(s).")
            hard_stops += 1
        else:
            print(f"  {sku_col}: OK (no nulls)")

    # ------------------------------------------------------------------
    # 6. Metric columns: sum + negative check
    # ------------------------------------------------------------------
    for col in metric_cols:
        if col not in df.columns:
            print(f"  {col}: ERROR — column missing.")
            hard_stops += 1
            continue

        series = pd.to_numeric(df[col], errors="coerce")
        col_sum     = series.sum()
        neg_count   = (series < 0).sum()
        coerce_nulls = series.isna().sum()

        neg_note = (
            f"WARNING — {_fmt(neg_count)} negative value(s)"
            if neg_count > 0
            else "0"
        )
        coerce_note = f" | {_fmt(coerce_nulls)} non-numeric" if coerce_nulls > 0 else ""

        print(
            f"  {col} sum : {_fmt(col_sum)}"
            f"  | negatives: {neg_note}{coerce_note}"
        )

        if neg_count > 0:
            warnings += 1

    return hard_stops, warnings


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    total_hard_stops = 0
    total_warnings   = 0

    for spec in FILE_SPECS:
        h, w = validate_file(spec)
        total_hard_stops += h
        total_warnings   += w

    # ------------------------------------------------------------------
    # Final verdict
    # ------------------------------------------------------------------
    print()
    if total_hard_stops == 0 and total_warnings == 0:
        print("All validations passed.")
    else:
        parts = []
        if total_hard_stops:
            parts.append(f"{total_hard_stops} hard stop(s)")
        if total_warnings:
            parts.append(f"{total_warnings} warning(s)")
        print(f"Validation complete: {', '.join(parts)}.")

    if total_hard_stops > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
