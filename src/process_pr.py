"""
process_pr.py — Purchase Receive cleaning and aggregation
Usage: python src/process_pr.py

Expects in root:
  - One or more CSVs matching *PurchaseReceive*.csv (the two half-year exports)
  - warehouse_lookup.csv (warehouse ID lookup)

Output:
  - pr_processed_<YYYY-MM-DD>.csv (aggregated warehouse_id + sku_id + qty_received)
"""

import glob
import os
import sys
import pandas as pd
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

KEEP_COLS = {
    "Purchase Receive ID": "receive_id",
    "Receive Number": "receive_number",
    "Receive Date": "receive_date",
    "Vendor Name": "vendor_name",
    "PO Number": "po_number",
    "Item Name": "item_name",
    "SKU": "sku_raw",
    "Quantity Received": "qty_received",
    "Warehouse Name": "warehouse_name",
    "CF.MUMBAI": "cf_warehouse",
}

LOOKUP_FILE = "warehouse_lookup.csv"


def load_pr_files():
    pattern = os.path.join(ROOT, "*PurchaseReceive*.csv")
    files = sorted(glob.glob(pattern))
    if not files:
        sys.exit("ERROR: No *PurchaseReceive*.csv files found in root.")
    print(f"Found {len(files)} PR file(s):")
    for f in files:
        print(f"  {os.path.basename(f)}")
    frames = [pd.read_csv(f, dtype=str) for f in files]
    return pd.concat(frames, ignore_index=True)


def clean_pr(df):
    # Keep and rename relevant columns
    missing = [c for c in KEEP_COLS if c not in df.columns]
    if missing:
        sys.exit(f"ERROR: Missing expected columns: {missing}")

    df = df[list(KEEP_COLS.keys())].rename(columns=KEEP_COLS)

    # Drop rows with no qty
    df["qty_received"] = pd.to_numeric(df["qty_received"], errors="coerce")
    df = df.dropna(subset=["qty_received"])

    # SKU check and clean: extract first digit sequence
    sku_str = df["sku_raw"].str.strip()
    df["check_sku"] = sku_str.str.match(r"^\d+$").map({True: "OK", False: "INVALID"})
    df["sku_id"] = sku_str.str.extract(r"(\d+)")[0]

    invalid_count = (df["check_sku"] == "INVALID").sum()
    if invalid_count:
        print(f"  {invalid_count} INVALID SKUs found — numeric portion extracted.")

    df = df.dropna(subset=["sku_id"])
    df["sku_id"] = df["sku_id"].astype(int)

    return df


def add_warehouse_id(df):
    lookup_path = os.path.join(ROOT, LOOKUP_FILE)
    if not os.path.exists(lookup_path):
        sys.exit(f"ERROR: Lookup file not found: {LOOKUP_FILE}")

    lookup = pd.read_csv(lookup_path, dtype=str)
    lookup.columns = ["cf_warehouse", "warehouse_id"]
    lookup["cf_warehouse"] = lookup["cf_warehouse"].str.strip()
    lookup["warehouse_id"] = pd.to_numeric(lookup["warehouse_id"], errors="coerce").astype("Int64")

    df["cf_warehouse"] = df["cf_warehouse"].str.strip()
    df = df.merge(lookup, on="cf_warehouse", how="left")

    unmatched = df["warehouse_id"].isna().sum()
    if unmatched:
        unmatched_vals = df.loc[df["warehouse_id"].isna(), "cf_warehouse"].unique()
        print(f"  WARNING: {unmatched} rows have no warehouse_id match. Unmatched cf_warehouse values:")
        for v in unmatched_vals:
            print(f"    '{v}'")

    return df


def aggregate(df):
    agg = (
        df.groupby(["warehouse_id", "sku_id"], dropna=False)["qty_received"]
        .sum()
        .reset_index()
    )
    agg.columns = ["warehouse_id", "sku_id", "pr_qty"]
    return agg


def main():
    print("=== PR Processing ===")

    df = load_pr_files()
    print(f"Total rows loaded: {len(df):,}")

    df = clean_pr(df)
    print(f"Rows after cleaning: {len(df):,}")

    df = add_warehouse_id(df)

    result = aggregate(df)
    print(f"Aggregated rows (warehouse x sku): {len(result):,}")

    out_file = os.path.join(ROOT, f"pr_processed_{date.today()}.csv")
    result.to_csv(out_file, index=False)
    print(f"Output: {os.path.basename(out_file)}")


if __name__ == "__main__":
    main()
