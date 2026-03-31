"""
recon.py — Monthly/quarterly stock reconciliation script.

Automates the stock reconciliation previously done manually in Google Sheets.
Detects input CSVs by column fingerprint, merges and aggregates them, computes
derived stock columns, validates totals, and writes a dated output CSV.

Usage:
    python recon.py [folder]   # folder defaults to the script's own directory
"""

import sys
import shutil
import logging
from datetime import date, datetime
from pathlib import Path

import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Maps each logical role to the set of normalised column names that uniquely
# identify it.  ALL listed columns must be present for a match.
FINGERPRINTS: dict[str, set[str]] = {
    "wh_vm_os":          {"wh_cs_actual", "vm_cs_actual", "warehouse_id", "sku_id"},
    "pr":                {"pr_qty", "warehouse_id", "sku_id"},           # after alias applied
    "calc_direct_refill":{"calc_direct_refill", "warehouse_id", "sku_id"},
    "kit_prepared":      {"kit_prepared_qty", "sku_id", "warehouse_id"}, # item_quantity → kit_prepared_qty; sku_group_id → sku_id
    "ops":               {"extra", "remove", "expire", "warehouse_id", "sku_id"},  # expiry → expire
    "sales":             {"sales", "warehouse_id", "sku_id"},
    # variant_info is optional / reference only — not in fingerprint loop
}

# Order matters: first matching alias wins.
# Applied after the basic strip/lower/replace normalisation.
COLUMN_ALIASES: dict[str, str] = {
    "cleaned_sku":              "sku_id",
    "sku_group_id":             "sku_id",
    "manufacturer_variant_id":  "sku_id",
    "mvid":                     "sku_id",
    "sum_of_quantity_received": "pr_qty",
    "item_quantity":            "kit_prepared_qty",
    "expiry":                   "expire",
}

# Mandatory roles that MUST be found (variant_info is optional)
MANDATORY_ROLES = list(FINGERPRINTS.keys())

# Output column order (must match specification exactly)
OUTPUT_COLUMNS = [
    "warehouse_id", "sku_id", "helper",
    "pr_qty", "wh_os", "vm_os",
    "kit_prepared_qty", "calc_direct_refill", "total_fresh",
    "extra", "remove", "expire",
    "sales", "wh_cs_calc", "vm_cs_calc",
]

# Files / patterns that must never be treated as inputs
EXCLUDE_PATTERNS = ("final-stock-recon", "recon_run.log", "variant-info")


# ---------------------------------------------------------------------------
# Column normalisation
# ---------------------------------------------------------------------------

def normalise_cols(df: pd.DataFrame) -> pd.DataFrame:
    """
    Normalise all column names in *df* in-place (returns same df):
      1. strip + lower + spaces→underscores  (single-pass normalisation)
      2. apply COLUMN_ALIASES
    """
    renamed = {}
    for col in df.columns:
        normalised = col.strip().lower().replace(" ", "_")
        aliased = COLUMN_ALIASES.get(normalised, normalised)
        renamed[col] = aliased
    df.rename(columns=renamed, inplace=True)
    return df


# ---------------------------------------------------------------------------
# File detection
# ---------------------------------------------------------------------------

def _should_exclude(path: Path) -> bool:
    """Return True if *path* should never be considered an input."""
    name_lower = path.name.lower()
    for pat in EXCLUDE_PATTERNS:
        if pat in name_lower:
            return True
    # Also exclude the output files explicitly
    if "final-stock-recon-output" in name_lower:
        return True
    return False


def detect_files(folder: Path) -> dict[str, Path]:
    """
    Scan *folder* for CSVs, apply column fingerprinting, and return a mapping
    of role → Path for every mandatory role.

    Hard stops (sys.exit(1)):
      - any mandatory role not found
      - more than one CSV matches the same role
    """
    candidates = [
        p for p in folder.glob("*.csv")
        if not _should_exclude(p)
    ]

    role_matches: dict[str, list[Path]] = {role: [] for role in MANDATORY_ROLES}

    for path in candidates:
        try:
            # Read only the header row to keep it fast
            header_df = pd.read_csv(path, nrows=0)
        except Exception as exc:
            logging.warning("Could not read %s: %s — skipping", path.name, exc)
            continue

        # Normalise the header in a throwaway df
        normalise_cols(header_df)
        cols = set(header_df.columns)

        for role, fingerprint in FINGERPRINTS.items():
            if fingerprint.issubset(cols):
                role_matches[role].append(path)

    # Guardrail #2 — duplicate matches
    duplicated = {
        role: paths
        for role, paths in role_matches.items()
        if len(paths) > 1
    }
    if duplicated:
        lines = []
        for role, paths in duplicated.items():
            names = ", ".join(p.name for p in paths)
            lines.append(f"  {role}: {names}")
        sys.exit(
            "ERROR: Multiple CSVs match the same role fingerprint:\n"
            + "\n".join(lines)
        )

    # Guardrail #1 — missing mandatory roles
    missing = [role for role in MANDATORY_ROLES if not role_matches[role]]
    if missing:
        sys.exit(
            "ERROR: No CSV found for mandatory role(s): "
            + ", ".join(missing)
        )

    detected = {role: role_matches[role][0] for role in MANDATORY_ROLES}

    # Log what was detected
    for role, path in detected.items():
        logging.info("Detected %-20s → %s", role, path.name)

    return detected


# ---------------------------------------------------------------------------
# Load & normalise
# ---------------------------------------------------------------------------

def load_and_normalise(path: Path, role: str) -> pd.DataFrame:
    """
    Load *path* as a CSV, normalise columns, and apply basic validation:
      - Guardrail #6: fingerprint columns must be present after normalisation
      - Guardrail #3: warehouse_id / sku_id must not be null (where applicable)

    Returns the fully normalised DataFrame.
    """
    df = pd.read_csv(path, dtype=str)  # load as str first to avoid int/float coercion issues
    normalise_cols(df)

    # Guardrail #6 — schema drift: fingerprint cols must be present
    fingerprint = FINGERPRINTS[role]
    missing_fp = fingerprint - set(df.columns)
    if missing_fp:
        sys.exit(
            f"ERROR: Schema drift in {path.name} (role={role}): "
            f"expected fingerprint columns {missing_fp} not found after normalisation. "
            f"Actual columns: {list(df.columns)}"
        )

    # Convert numeric columns to float (coerce errors → NaN for later detection)
    numeric_candidates = [
        "wh_cs_actual", "vm_cs_actual", "pr_qty",
        "calc_direct_refill", "kit_prepared_qty",
        "extra", "remove", "expire", "sales",
    ]
    for col in numeric_candidates:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # Guardrail #3 — null keys
    key_cols = [c for c in ("warehouse_id", "sku_id") if c in df.columns]
    for kc in key_cols:
        null_count = df[kc].isna().sum()
        if null_count > 0:
            sys.exit(
                f"ERROR: Null key '{kc}' found in {path.name} (role={role}): "
                f"{null_count} row(s) affected."
            )

    return df


# ---------------------------------------------------------------------------
# Summary statistics
# ---------------------------------------------------------------------------

def run_summary_stats(dfs: dict[str, pd.DataFrame]) -> None:
    """
    Print per-file: shape, null count per column, duplicate (warehouse_id, sku_id) count.
    """
    print("\n" + "=" * 72)
    print("SUMMARY STATISTICS")
    print("=" * 72)
    for role, df in dfs.items():
        print(f"\n[{role}]  shape={df.shape}")
        # Null counts
        null_counts = df.isna().sum()
        null_str = ", ".join(
            f"{col}:{n}" for col, n in null_counts.items() if n > 0
        ) or "none"
        print(f"  nulls      : {null_str}")
        # Duplicate WH+SKU
        key_cols = [c for c in ("warehouse_id", "sku_id") if c in df.columns]
        if len(key_cols) == 2:
            dup_count = df.duplicated(subset=key_cols).sum()
            print(f"  dup wh+sku : {dup_count}")
    print("=" * 72 + "\n")


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate_to_wh_sku(df: pd.DataFrame, role: str) -> pd.DataFrame:
    """
    Aggregate VM+SKU granularity files up to WH+SKU by summing metrics.
    `wh_vm_os` and `pr` are already at WH+SKU — returned unchanged.
    """
    group_keys = ["warehouse_id", "sku_id"]

    agg_map: dict[str, dict[str, str]] = {
        "calc_direct_refill": {"calc_direct_refill": "sum"},
        "kit_prepared":       {"kit_prepared_qty": "sum"},
        "ops":                {"extra": "sum", "remove": "sum", "expire": "sum"},
        "sales":              {"sales": "sum"},
    }

    if role not in agg_map:
        # wh_vm_os and pr — no aggregation needed
        return df

    agg = agg_map[role]
    # Keep only the columns we need
    needed_cols = group_keys + list(agg.keys())
    df_sub = df[[c for c in needed_cols if c in df.columns]].copy()

    aggregated = df_sub.groupby(group_keys, as_index=False).agg(agg)
    return aggregated


# ---------------------------------------------------------------------------
# Base spine
# ---------------------------------------------------------------------------

def build_base(dfs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Union all (warehouse_id, sku_id) pairs from all source DataFrames,
    deduplicate, and sort.
    """
    pairs = []
    for role, df in dfs.items():
        if "warehouse_id" in df.columns and "sku_id" in df.columns:
            pairs.append(df[["warehouse_id", "sku_id"]].drop_duplicates())

    base = pd.concat(pairs, ignore_index=True).drop_duplicates()
    base = base.sort_values(["warehouse_id", "sku_id"]).reset_index(drop=True)
    return base


# ---------------------------------------------------------------------------
# Merge
# ---------------------------------------------------------------------------

def merge_all(base: pd.DataFrame, agg_dfs: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Left-join each aggregated source onto the base spine.
    After merging, fill numeric NaNs with 0 (absent = zero contribution).
    """
    df = base.copy()

    merge_order = ["wh_vm_os", "pr", "calc_direct_refill", "kit_prepared", "ops", "sales"]

    for role in merge_order:
        if role not in agg_dfs:
            continue
        right = agg_dfs[role]
        df = df.merge(right, on=["warehouse_id", "sku_id"], how="left")

    # Fill numeric columns with 0
    numeric_cols = [
        "wh_cs_actual", "vm_cs_actual", "pr_qty",
        "calc_direct_refill", "kit_prepared_qty",
        "extra", "remove", "expire", "sales",
    ]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = df[col].fillna(0)

    # Rename OS columns to match output spec
    df.rename(columns={"wh_cs_actual": "wh_os", "vm_cs_actual": "vm_os"}, inplace=True)

    return df


# ---------------------------------------------------------------------------
# Derived columns
# ---------------------------------------------------------------------------

def compute_derived(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute helper, total_fresh, wh_cs_calc, vm_cs_calc.

    Formulas (per spec):
      helper      = f"{warehouse_id}|{sku_id}"
      total_fresh = kit_prepared_qty + calc_direct_refill
      wh_cs_calc  = (wh_os + pr_qty) - (total_fresh - extra - remove)
      vm_cs_calc  = vm_os - (sales + expire) + (total_fresh - extra - remove)
    """
    df = df.copy()

    df["helper"] = df["warehouse_id"].astype(str) + "|" + df["sku_id"].astype(str)

    df["total_fresh"] = df["kit_prepared_qty"] + df["calc_direct_refill"]

    # net_refill = units that actually moved from WH to VMs (net of returns)
    net_refill = df["total_fresh"] - df["extra"] - df["remove"]

    df["wh_cs_calc"] = (df["wh_os"] + df["pr_qty"]) - net_refill
    df["vm_cs_calc"] = df["vm_os"] - (df["sales"] + df["expire"]) + net_refill

    return df


# ---------------------------------------------------------------------------
# Guardrail #4 — duplicate WH+SKU keys in pre-aggregated files
# ---------------------------------------------------------------------------

def validate_pre_aggregated_keys(dfs: dict[str, pd.DataFrame]) -> None:
    """
    `pr` and `wh_vm_os` must have unique (warehouse_id, sku_id) keys before
    any aggregation — they are already supposed to be at WH+SKU granularity.
    Hard stop if duplicates found.
    """
    for role in ("pr", "wh_vm_os"):
        if role not in dfs:
            continue
        df = dfs[role]
        key_cols = ["warehouse_id", "sku_id"]
        dup_count = df.duplicated(subset=key_cols).sum()
        if dup_count > 0:
            sys.exit(
                f"ERROR: {dup_count} duplicate (warehouse_id, sku_id) key(s) found "
                f"in pre-aggregated file for role '{role}'."
            )


# ---------------------------------------------------------------------------
# Guardrail #5 — column total validation
# ---------------------------------------------------------------------------

def validate_totals(output_df: pd.DataFrame, source_dfs: dict[str, pd.DataFrame]) -> None:
    """
    Verify that the sum of each metric in the output equals the sum in the
    (aggregated) source DataFrame.  Hard stop on any mismatch.

    We compare after aggregation so the reference sums are at WH+SKU level.
    """
    # Map: output column → (role, source column in agg df)
    checks = [
        ("pr_qty",            "pr",               "pr_qty"),
        ("wh_os",             "wh_vm_os",         "wh_cs_actual"),
        ("vm_os",             "wh_vm_os",         "vm_cs_actual"),
        ("kit_prepared_qty",  "kit_prepared",     "kit_prepared_qty"),
        ("calc_direct_refill","calc_direct_refill","calc_direct_refill"),
        ("extra",             "ops",              "extra"),
        ("remove",            "ops",              "remove"),
        ("expire",            "ops",              "expire"),
        ("sales",             "sales",            "sales"),
    ]

    errors = []
    for out_col, role, src_col in checks:
        if role not in source_dfs:
            continue
        src_df = source_dfs[role]
        if src_col not in src_df.columns or out_col not in output_df.columns:
            continue

        src_sum  = pd.to_numeric(src_df[src_col], errors="coerce").sum()
        out_sum  = pd.to_numeric(output_df[out_col], errors="coerce").sum()
        delta    = abs(out_sum - src_sum)

        # Use a small tolerance for floating-point rounding
        if delta > 1e-6:
            errors.append(
                f"  {out_col}: output_sum={out_sum:.4f}, source_sum={src_sum:.4f}, "
                f"delta={delta:.6f}"
            )

    if errors:
        sys.exit(
            "ERROR: Column total mismatch detected (Guardrail #5):\n"
            + "\n".join(errors)
        )


# ---------------------------------------------------------------------------
# Guardrail #7 — negative closing stock (warning only)
# ---------------------------------------------------------------------------

def check_negative_stock(df: pd.DataFrame) -> int:
    """
    Warn if wh_cs_calc < 0 or vm_cs_calc < 0.
    Prints count and per-warehouse breakdown.
    Returns total warning count.
    """
    neg_wh = df[df["wh_cs_calc"] < 0]
    neg_vm = df[df["vm_cs_calc"] < 0]

    warn_count = len(neg_wh) + len(neg_vm)

    if warn_count == 0:
        return 0

    print("\nWARNING: Negative closing stock detected!")
    print(f"  wh_cs_calc < 0 : {len(neg_wh)} row(s)")
    if not neg_wh.empty:
        breakdown = neg_wh.groupby("warehouse_id").size().reset_index(name="count")
        for _, row in breakdown.iterrows():
            print(f"    warehouse {row['warehouse_id']}: {row['count']} SKU(s)")

    print(f"  vm_cs_calc < 0 : {len(neg_vm)} row(s)")
    if not neg_vm.empty:
        breakdown = neg_vm.groupby("warehouse_id").size().reset_index(name="count")
        for _, row in breakdown.iterrows():
            print(f"    warehouse {row['warehouse_id']}: {row['count']} SKU(s)")

    return warn_count


# ---------------------------------------------------------------------------
# Archive inputs
# ---------------------------------------------------------------------------

def archive_inputs(
    folder: Path,
    detected_files: dict[str, Path],
    run_date: date,
) -> None:
    """
    Move all detected input CSVs (those used as source data) into
    archive/<YYYY-MM-DD>/.  Files listed in the non-archivable set are skipped.

    Does NOT move: output files, final-stock-recon.csv, recon_run.log,
    variant-info.csv.
    """
    archive_dir = folder / "archive" / run_date.strftime("%Y-%m-%d")
    archive_dir.mkdir(parents=True, exist_ok=True)

    for role, path in detected_files.items():
        dest = archive_dir / path.name
        shutil.move(str(path), str(dest))
        logging.info("Archived %s → %s", path.name, dest.relative_to(folder))


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

def append_log(
    folder: Path,
    run_date: date,
    files: list[str],
    row_count: int,
    warn_count: int,
    status: str,
) -> None:
    """
    Append a single-line summary to recon_run.log.
    Format: <ISO timestamp> | files: <comma list> | rows: <N> | warnings: <count> | status: OK/FAILED
    """
    log_path = folder / "recon_run.log"
    ts = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    line = (
        f"{ts} | files: {', '.join(files)} | rows: {row_count} "
        f"| warnings: {warn_count} | status: {status}\n"
    )
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(line)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    # Configure Python's standard logging to stdout
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Resolve working folder (default: same directory as this script)
    if len(sys.argv) > 1:
        folder = Path(sys.argv[1]).resolve()
    else:
        folder = Path(__file__).resolve().parent

    if not folder.is_dir():
        sys.exit(f"ERROR: Folder not found: {folder}")

    run_date = date.today()
    warn_count = 0
    status = "FAILED"
    detected: dict[str, Path] = {}
    final: "pd.DataFrame | None" = None

    try:
        # ------------------------------------------------------------------
        # 1. Detect files
        # ------------------------------------------------------------------
        logging.info("Scanning %s for input CSVs...", folder)
        detected = detect_files(folder)

        # ------------------------------------------------------------------
        # 2. Load and normalise all files
        # ------------------------------------------------------------------
        raw_dfs: dict[str, pd.DataFrame] = {}
        for role, path in detected.items():
            logging.info("Loading %-20s (%s)", role, path.name)
            raw_dfs[role] = load_and_normalise(path, role)

        # ------------------------------------------------------------------
        # 3. Guardrail #4 — duplicate keys in pre-aggregated files
        # ------------------------------------------------------------------
        validate_pre_aggregated_keys(raw_dfs)

        # ------------------------------------------------------------------
        # 4. Summary statistics (printed before processing)
        # ------------------------------------------------------------------
        run_summary_stats(raw_dfs)

        # ------------------------------------------------------------------
        # 5. Aggregate VM+SKU → WH+SKU
        # ------------------------------------------------------------------
        agg_dfs: dict[str, pd.DataFrame] = {}
        for role, df in raw_dfs.items():
            agg_dfs[role] = aggregate_to_wh_sku(df, role)

        # ------------------------------------------------------------------
        # 6. Build base spine and merge
        # ------------------------------------------------------------------
        base = build_base(agg_dfs)
        logging.info("Base spine: %d unique (warehouse_id, sku_id) pairs", len(base))

        merged = merge_all(base, agg_dfs)

        # ------------------------------------------------------------------
        # 7. Compute derived columns
        # ------------------------------------------------------------------
        output_df = compute_derived(merged)

        # ------------------------------------------------------------------
        # 8. Guardrail #5 — validate column totals
        #    Note: wh_vm_os columns are renamed to wh_os/vm_os inside merge_all
        #    on an internal copy, so agg_dfs still has the original names
        #    (wh_cs_actual / vm_cs_actual) for comparison.
        # ------------------------------------------------------------------
        validate_totals(output_df, agg_dfs)

        # ------------------------------------------------------------------
        # 9. Guardrail #7 — negative closing stock (warning only)
        # ------------------------------------------------------------------
        warn_count = check_negative_stock(output_df)

        # ------------------------------------------------------------------
        # 10. Write output
        # ------------------------------------------------------------------
        # Ensure all output columns exist (fill missing with 0)
        for col in OUTPUT_COLUMNS:
            if col not in output_df.columns:
                output_df[col] = 0

        final: pd.DataFrame = output_df[OUTPUT_COLUMNS]
        out_filename = f"final-stock-recon-output_{run_date.strftime('%Y-%m-%d')}.csv"
        out_path = folder / out_filename
        final.to_csv(out_path, index=False)
        logging.info("Output written → %s  (%d rows)", out_filename, len(final))

        # ------------------------------------------------------------------
        # 11. Archive inputs
        # ------------------------------------------------------------------
        archive_inputs(folder, detected, run_date)

        status = "OK"
        print(f"\nReconciliation complete. Output: {out_path}")
        if warn_count:
            print(f"  {warn_count} warning(s) — see above for details.")

    except SystemExit:
        # Hard-stop errors (guardrails): log FAILED then re-raise
        append_log(folder, run_date, files=[], row_count=0, warn_count=0, status="FAILED")
        raise

    except Exception as exc:
        # Unexpected runtime errors: log FAILED then re-raise so the traceback is visible
        logging.error("Unexpected error: %s", exc)
        append_log(folder, run_date, files=[], row_count=0, warn_count=0, status="FAILED")
        raise

    finally:
        if status == "OK":
            file_names = [p.name for p in detected.values()]
            row_count  = len(final) if final is not None else 0
            append_log(folder, run_date, file_names, row_count, warn_count, status)


if __name__ == "__main__":
    main()
