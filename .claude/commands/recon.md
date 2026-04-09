# Run Stock Reconciliation

Full pipeline: fetch from Redshift → recon → mapper.

## Usage
`/recon YYYY-MM-DD YYYY-MM-DD`

First date = start (inclusive), second = end (exclusive). Both are IST.

Example: `/recon 2025-04-01 2026-03-01` for full FY 2025-26.

## Steps

1. **Validate prerequisites** — check the repo root for:
   - `pr_processed_*.csv` — if missing, tell user to run `/process-pr` first and stop.
   - `wh-vm-os.csv` — if missing, tell user to provide the opening stock file and stop.
   - `.env` — if missing, tell user to copy `.env.example` → `.env` and fill in Redshift credentials.

2. **Fetch data from Redshift:**
   ```
   .venv/bin/python src/fetch_data.py --start <start_date> --end <end_date>
   ```
   - If the script exits with a null `warehouse_id` error, surface the VM IDs printed in stderr/stdout, stop, and tell the user to fix the warehouse mapping in the DB before re-running.
   - On success, 4 CSVs will appear in root: `kit_prepared.csv`, `calc_direct_refill.csv`, `ops.csv`, `sales.csv`.

3. **Run reconciliation:**
   ```
   .venv/bin/python src/recon.py .
   ```
   - Pass `.` as the folder argument so recon.py scans the repo root, not `src/`.
   - Note the output filename from stdout (format: `final-stock-recon-output_YYYY-MM-DD.csv`).
   - If recon fails a guardrail, surface the error clearly and stop.

4. **Run mapper:**
   ```
   .venv/bin/python src/mapper.py <recon_output_file> --variant-info variant-info.csv
   ```
   - Use the output filename from step 3.
   - Pass `--variant-info variant-info.csv` explicitly.

5. **Run export:**
   ```
   .venv/bin/python src/export.py
   ```
   Produces two Excel files in root ready for sharing:
   - `final-stock-recon-YYYY-MM-DD.xlsx` (tabs: FINAL, PR, kit prepared, calc. refill, ops, WH OS, VM OS, Sales, variant info)
   - `stock-recon-mapper-variant-YYYY-MM-DD.xlsx` (tabs: stock-recon-on-mapper-variant, variant-mapper)

6. **Report results:**
   - Excel files produced
   - Recon row count, mapper row count
   - Any warnings (e.g. negative closing stock, unmapped SKUs)
   - Confirm input CSVs have been archived to `archive/<DATE>/`
