"""
fetch_data.py — Fetch stock recon source data from Redshift and save as CSVs.

Fetches four datasets (kit_prepared, calc_direct_refill, ops, sales) for a
given IST date range and writes them to the repo root so recon.py can detect
them by column fingerprint.

Usage:
    python src/fetch_data.py --start 2026-03-01 --end 2026-04-01
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import psycopg2
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent.parent

IST_OFFSET = timedelta(hours=5, minutes=30)
UTC = timezone.utc

QUERIES = {
    "kit_prepared": (
        "kd.created_at",
        """
WITH data AS (
    SELECT ad.sku_group_id, ad.item_quantity, kd.vending_machine_id, vm.warehouse_id
    FROM dc_prod_db_archive_dashboard_user_kit_with_details kd
    JOIN dc_prod_db_archive_dashboard_user_kit_refill_with_details ad
        ON kd.id = ad.dashboard_user_kit_id AND kd.slot_identifier = ad.slot_identifier
    JOIN dc_prod_db_vending_machines vm ON vm.id = kd.vending_machine_id
    JOIN dc_prod_db_vm_cohort_machines vcm ON vm.id = vcm.machine_id
    JOIN dc_prod_db_vending_machine_cohort vmc ON vmc.id = vcm.cohort_id
    WHERE kd.created_at BETWEEN %s AND %s
        AND vmc.id IN (380,383,384,385,407,408,449,509,386,434,516,387,413,450,767,790,768,779,1079)
        AND operation_type = 'fresh'
)
SELECT * FROM data ORDER BY warehouse_id
""",
    ),
    "calc_direct_refill": (
        "rd.start_time",
        """
WITH data AS (
    SELECT rd.pkey, dashboard_user_id, rd.vending_machine_id, rd.start_time, rd.end_time,
           rd.operation_type, rd.sku_group_id, rd.item_quantity AS rd_item_qty,
           kd.pkey AS kpkey, kd.item_quantity AS kit_prepare_qty, kd.created_at AS kit_prepared_at,
           vcm.cohort_id, vmc.name AS cohort, vm.warehouse_id
    FROM dc_prod_db_archive_dashboard_user_kit_refill_with_details rd
    JOIN dc_prod_db_vending_machines vm ON vm.id = rd.vending_machine_id
    JOIN dc_prod_db_vm_cohort_machines vcm ON vm.id = vcm.machine_id
    JOIN dc_prod_db_vending_machine_cohort vmc ON vmc.id = vcm.cohort_id
    LEFT JOIN dc_prod_db_archive_dashboard_user_kit_with_details kd
        ON rd.dashboard_user_kit_id = kd.id
        AND rd.manufacturer_variant_id = kd.manufacturer_variant_id
        AND rd.vending_machine_id = kd.vending_machine_id
        AND rd.slot_identifier = kd.slot_identifier
    WHERE rd.start_time BETWEEN %s AND %s
        AND operation_type = 'fresh'
        AND vmc.id IN (380,383,384,385,407,408,449,509,386,434,516,387,413,450,767,790,768,779,1079)
)
SELECT warehouse_id, vending_machine_id, sku_group_id, SUM(rd_item_qty) AS calc_direct_refill
FROM data
WHERE kpkey IS NULL
GROUP BY warehouse_id, vending_machine_id, sku_group_id
""",
    ),
    "ops": (
        "rd.end_time",
        """
WITH data AS (
    SELECT vm.warehouse_id, sku_group_id, item_quantity, operation_type, end_time, vending_machine_id
    FROM dc_prod_db_archive_dashboard_user_kit_refill_with_details rd
    JOIN dc_prod_db_vending_machines vm ON vm.id = rd.vending_machine_id
    JOIN dc_prod_db_vm_cohort_machines vcm ON vm.id = vcm.machine_id
    JOIN dc_prod_db_vending_machine_cohort vmc ON vmc.id = vcm.cohort_id
    WHERE rd.end_time BETWEEN %s AND %s
        AND vmc.id IN (380,383,384,385,407,408,449,509,386,434,516,387,413,450,767,790,768,779,1079)
)
SELECT warehouse_id, vending_machine_id, sku_group_id,
       SUM(CASE WHEN operation_type = 'extra' THEN item_quantity ELSE 0 END) AS extra,
       SUM(CASE WHEN operation_type = 'remove' THEN item_quantity ELSE 0 END) AS remove,
       SUM(CASE WHEN operation_type = 'expire' THEN item_quantity ELSE 0 END) AS expiry
FROM data
GROUP BY warehouse_id, vending_machine_id, sku_group_id
ORDER BY sku_group_id
""",
    ),
    "sales": (
        "oli.created_at_tz",
        """
WITH sales AS (
    SELECT vm.warehouse_id, oli.vending_machine_id, manufacturer_variant_id, success
    FROM dc_prod_db_order_line_items oli
    JOIN dc_prod_db_vending_machines vm ON vm.id = oli.vending_machine_id
    JOIN dc_prod_db_vm_cohort_machines vcm ON vm.id = vcm.machine_id
    JOIN dc_prod_db_vending_machine_cohort vmc ON vmc.id = vcm.cohort_id
    WHERE vmc.id IN (380,383,384,385,407,408,449,509,386,434,516,387,413,450,767,790,768)
        AND oli.created_at_tz BETWEEN %s AND %s
)
SELECT warehouse_id, vending_machine_id, manufacturer_variant_id, SUM(success) AS sales
FROM sales
GROUP BY warehouse_id, vending_machine_id, manufacturer_variant_id
ORDER BY warehouse_id
""",
    ),
}

OUTPUT_FILES = {
    "kit_prepared":      "kit_prepared.csv",
    "calc_direct_refill":"calc_direct_refill.csv",
    "ops":               "ops.csv",
    "sales":             "sales.csv",
}


# ---------------------------------------------------------------------------
# DB connection
# ---------------------------------------------------------------------------

def get_connection():
    host = os.getenv("REDSHIFT_HOST")
    port = os.getenv("REDSHIFT_PORT", "5439")
    dbname = os.getenv("REDSHIFT_DB", "dev")
    user = os.getenv("REDSHIFT_USER")
    password = os.getenv("REDSHIFT_PASSWORD")

    missing = [v for v, val in {"REDSHIFT_HOST": host, "REDSHIFT_USER": user, "REDSHIFT_PASSWORD": password}.items() if not val]
    if missing:
        sys.exit(f"ERROR: Missing required env vars: {', '.join(missing)}")

    return psycopg2.connect(
        dbname=dbname,
        user=user,
        password=password,
        host=host,
        port=port,
    )


# ---------------------------------------------------------------------------
# IST → UTC conversion
# ---------------------------------------------------------------------------

def ist_to_utc(dt: datetime) -> datetime:
    """Convert a naive IST datetime to a UTC-aware datetime."""
    return (dt - IST_OFFSET).replace(tzinfo=UTC)


# ---------------------------------------------------------------------------
# Null warehouse_id check
# ---------------------------------------------------------------------------

def check_null_warehouse_id(df: pd.DataFrame, name: str) -> None:
    null_mask = df["warehouse_id"].isna()
    null_count = null_mask.sum()
    if null_count > 0:
        affected_vms = df.loc[null_mask, "vending_machine_id"].unique().tolist()
        print(f"\nERROR: [{name}] {null_count} row(s) have null warehouse_id.")
        print(f"  Affected vending_machine_id values: {affected_vms}")
        sys.exit("Fix warehouse_id in the vending machines table before re-running.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch stock recon data from Redshift.")
    parser.add_argument("--start", required=True, help="IST start date inclusive (YYYY-MM-DD)")
    parser.add_argument("--end",   required=True, help="IST end date exclusive (YYYY-MM-DD)")
    args = parser.parse_args()

    try:
        ist_start = datetime.strptime(args.start, "%Y-%m-%d")
        ist_end   = datetime.strptime(args.end,   "%Y-%m-%d")
    except ValueError as exc:
        sys.exit(f"ERROR: Invalid date format — {exc}")

    utc_start = ist_to_utc(ist_start)
    utc_end   = ist_to_utc(ist_end)

    print(f"IST range : {args.start} → {args.end}")
    print(f"UTC range : {utc_start} → {utc_end}")

    load_dotenv(ROOT / ".env")

    conn = None
    try:
        print("\nConnecting to Redshift...")
        try:
            conn = get_connection()
        except psycopg2.OperationalError as exc:
            sys.exit(f"ERROR: Could not connect to Redshift — {exc}")

        for name, (ts_col, sql) in QUERIES.items():
            print(f"\n[{name}]  timestamp col: {ts_col}")
            print(f"  UTC range: {utc_start}  →  {utc_end}")

            with conn.cursor() as cur:
                cur.execute(sql, (utc_start, utc_end))
                cols = [desc[0] for desc in cur.description]
                df = pd.DataFrame(cur.fetchall(), columns=cols)

            print(f"  Rows fetched: {len(df):,}")

            check_null_warehouse_id(df, name)

            out_path = ROOT / OUTPUT_FILES[name]
            df.to_csv(out_path, index=False)
            print(f"  Saved → {OUTPUT_FILES[name]}")

        print("\nAll datasets fetched and saved.")

    finally:
        if conn is not None:
            conn.close()
            print("DB connection closed.")


if __name__ == "__main__":
    main()
