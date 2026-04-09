"""
export.py — Export recon outputs to Excel for sharing with finance/accounts teams.

Reads from the most recent archive/ run and root output files.
Produces two .xlsx files in root:

  final-stock-recon-YYYY-MM-DD.xlsx
    Tabs: FINAL, PR, kit prepared, calc. refill, ops, WH OS, VM OS, Sales, variant info

  stock-recon-mapper-variant-YYYY-MM-DD.xlsx
    Tabs: stock-recon-on-mapper-variant, variant-mapper

Usage:
    python src/export.py
"""

import sys
import glob
from datetime import date
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent

COLUMN_ALIASES = {
    "sku_group_id":            "sku_id",
    "manufacturer_variant_id": "sku_id",
    "item_quantity":           "kit_prepared_qty",
    "expiry":                  "expire",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def latest_archive() -> Path:
    dirs = sorted(ROOT.glob("archive/*/"))
    if not dirs:
        sys.exit("ERROR: No archive directories found. Run recon first.")
    return dirs[-1]


def latest_file(pattern: str) -> Path:
    matches = sorted(ROOT.glob(pattern))
    if not matches:
        sys.exit(f"ERROR: No file matching '{pattern}' found in root.")
    return matches[-1]


def normalise(df: pd.DataFrame) -> pd.DataFrame:
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    df.rename(columns=COLUMN_ALIASES, inplace=True)
    return df


def aggregate(df: pd.DataFrame, metric_cols: list) -> pd.DataFrame:
    df = normalise(df)
    for col in metric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    agg = {col: "sum" for col in metric_cols if col in df.columns}
    return df.groupby(["warehouse_id", "sku_id"], as_index=False).agg(agg)


# ---------------------------------------------------------------------------
# Load source tabs
# ---------------------------------------------------------------------------

def load_final(root: Path) -> pd.DataFrame:
    return pd.read_csv(latest_file("final-stock-recon-output_*.csv"))


def load_pr(archive: Path) -> pd.DataFrame:
    matches = sorted(archive.glob("pr_processed_*.csv"))
    if not matches:
        sys.exit(f"ERROR: pr_processed_*.csv not found in {archive}")
    return pd.read_csv(matches[0])


def load_kit_prepared(archive: Path) -> pd.DataFrame:
    return aggregate(pd.read_csv(archive / "kit_prepared.csv"), ["kit_prepared_qty"])


def load_calc_refill(archive: Path) -> pd.DataFrame:
    return aggregate(pd.read_csv(archive / "calc_direct_refill.csv"), ["calc_direct_refill"])


def load_ops(archive: Path) -> pd.DataFrame:
    return aggregate(pd.read_csv(archive / "ops.csv"), ["extra", "remove", "expire"])


def load_wh_os(archive: Path) -> pd.DataFrame:
    df = pd.read_csv(archive / "wh-vm-os.csv")
    df = normalise(df)
    return df[["warehouse_id", "sku_id", "wh_cs_actual"]].rename(columns={"wh_cs_actual": "wh_os"})


def load_vm_os(archive: Path) -> pd.DataFrame:
    df = pd.read_csv(archive / "wh-vm-os.csv")
    df = normalise(df)
    return df[["warehouse_id", "sku_id", "vm_cs_actual"]].rename(columns={"vm_cs_actual": "vm_os"})


def load_sales(archive: Path) -> pd.DataFrame:
    return aggregate(pd.read_csv(archive / "sales.csv"), ["sales"])


def load_variant_info(root: Path) -> pd.DataFrame:
    return pd.read_csv(root / "variant-info.csv")


def load_mapper_output(root: Path) -> pd.DataFrame:
    return pd.read_csv(latest_file("final-stock-recon-mapped-output_*.csv"))


def load_variant_mapper(root: Path) -> pd.DataFrame:
    return pd.read_csv(latest_file("variant-mapping-reference_*.csv"))


# ---------------------------------------------------------------------------
# Write Excel
# ---------------------------------------------------------------------------

def write_excel(path: Path, sheets: dict) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for tab_name, df in sheets.items():
            df.to_excel(writer, sheet_name=tab_name, index=False)
    print(f"  Written → {path.name}  ({len(sheets)} tabs)")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    archive = latest_archive()
    print(f"Using archive: {archive.name}")

    today = date.today().strftime("%Y-%m-%d")

    # ------------------------------------------------------------------
    # Sheet 1 — Final Stock Recon
    # ------------------------------------------------------------------
    print("\nBuilding final-stock-recon xlsx...")
    sheet1 = {
        "FINAL":        load_final(ROOT),
        "PR":           load_pr(archive),
        "kit prepared": load_kit_prepared(archive),
        "calc. refill": load_calc_refill(archive),
        "ops":          load_ops(archive),
        "WH OS":        load_wh_os(archive),
        "VM OS":        load_vm_os(archive),
        "Sales":        load_sales(archive),
        "variant info": load_variant_info(ROOT),
    }
    write_excel(ROOT / f"final-stock-recon-{today}.xlsx", sheet1)

    # ------------------------------------------------------------------
    # Sheet 2 — Mapper Variant
    # ------------------------------------------------------------------
    print("\nBuilding stock-recon-mapper-variant xlsx...")
    sheet2 = {
        "stock-recon-on-mapper-variant": load_mapper_output(ROOT),
        "variant-mapper":                load_variant_mapper(ROOT),
    }
    write_excel(ROOT / f"stock-recon-mapper-variant-{today}.xlsx", sheet2)

    print("\nExport complete.")


if __name__ == "__main__":
    main()
