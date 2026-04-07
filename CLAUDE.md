# DC Stock Recon — Claude Instructions

## Running scripts
- Always use `.venv/bin/python`, never `python` or `python3`
- Scripts live in `src/`, always run from repo root
- `recon.py` requires `.` passed as folder arg: `.venv/bin/python src/recon.py .`
  (otherwise it defaults to scanning `src/` instead of root)

## Slash commands
- `/process-pr` — cleans Zoho PR exports → `pr_processed_YYYY-MM-DD.csv`
- `/recon YYYY-MM-DD YYYY-MM-DD` — full pipeline: fetch → recon → mapper

## Data sources
- **PR (purchase receives)**: Zoho export, cannot be automated. User drops raw CSVs manually.
- **kits, direct refill, ops, sales**: Redshift via `fetch_data.py`. Credentials in `.env`.
- **wh-vm-os.csv**: Opening stock, fixed per financial year. Provided once in April, reused all year. Get next year's file from user in April — do NOT copy from archive without confirming.
- **variant-info.csv**: SKU → variant mapping. Stable reference, rarely changes.
- **warehouse_lookup.csv**: CF.WAREHOUSE → warehouse_id for PR processing. Stable.

## Redshift / timestamps
- DB timestamps are UTC. IST = UTC+5:30.
- `fetch_data.py` handles the conversion — pass IST dates as `--start`/`--end`.
- Do NOT use `pd.read_sql()` with a raw psycopg2 connection — deprecated in pandas 2.2+. Use cursor: `cur.execute(sql, params); df = pd.DataFrame(cur.fetchall(), columns=[d[0] for d in cur.description])`

## Column naming convention
- `fetch_data.py` saves raw SQL column names (`sku_group_id`, `item_quantity`, `expiry`, etc.)
- `recon.py`'s `COLUMN_ALIASES` normalises them at load time
- Do not rename columns in fetch output — the aliasing layer must stay exercised

## Null warehouse_id
- `fetch_data.py` hard stops on null `warehouse_id` after each query
- Do NOT patch rows manually or assume a mapping — fix must happen in the DB (`dc_prod_db_vending_machines`)

## File lifecycle
- Raw inputs (PR CSVs, fetched CSVs) land in root → get processed → archived to `archive/YYYY-MM-DD/` by `recon.py`
- Raw PR files should be moved to `tmp/` after `/process-pr` (gitignored, delete later)
- Never commit `.env` or anything in `tmp/` or `.venv/`

## recon.py fingerprint detection
- Files are detected by column fingerprint, not filename
- `COLUMN_ALIASES` is applied BEFORE fingerprint matching — aliases fire correctly
- `pr_processed_*.csv` is detected as role `pr` (has `warehouse_id`, `sku_id`, `pr_qty`)
- Files ending in `Z.csv` and filenames containing `final-stock-recon`, `variant-info`, `recon_run.log` are excluded from detection
