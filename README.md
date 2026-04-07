# DC Stock Reconciliation Automation

## Purpose
Automates the annual financial year stock reconciliation across warehouses and SKUs. Fetches operational data from Redshift, processes Zoho purchase records, and produces a unified closing stock report per warehouse × SKU, then a second pass mapping SKU variants by price group.

## Environment
- **Python**: 3.13 via `.venv` (`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`)
- **Credentials**: copy `.env.example` → `.env` and fill in Redshift credentials

## Workflow

### Step 1 — Process Purchase Receives (Zoho, manual)
Drop raw `*PurchaseReceive*.csv` exports from Zoho into root, then:
```
/process-pr
```
Produces `pr_processed_YYYY-MM-DD.csv` in root.

### Step 2 — Run Reconciliation (Redshift, automated)
```
/recon 2025-04-01 2026-03-01
```
Dates are IST. Start is inclusive, end is exclusive — match the financial year boundary.

This single command:
1. Fetches kits prepared, calc direct refill, ops, and sales from Redshift
2. Runs the reconciliation engine
3. Runs the variant mapper

Outputs: `final-stock-recon-output_YYYY-MM-DD.csv` and `final-stock-recon-mapped-output_YYYY-MM-DD.csv`

---

## Scripts (`src/`)

| Script | Purpose |
|--------|---------|
| `fetch_data.py` | Fetches 4 datasets from Redshift for a given IST date range |
| `recon.py` | Detects input CSVs by column fingerprint, merges, computes closing stock |
| `mapper.py` | Aggregates recon output by mapper variant (min mvid per brand+price group) |
| `process_pr.py` | Cleans and aggregates Zoho PR exports |
| `validate_fetch.py` | QA checks on fetched CSVs — run before recon if you want to inspect totals |
| `compare.py` | Manual utility for comparing two recon outputs |

## Core Formulas

```
total_fresh = kit_prepared_qty + calc_direct_refill
wh_cs_calc  = (wh_os + pr_qty) - (total_fresh - extra - remove)
vm_cs_calc  = vm_os - (sales + expire) + (total_fresh - extra - remove)
```

## Permanent Files

| File | Notes |
|------|-------|
| `wh-vm-os.csv` | Opening stock — fixed for the financial year, provided once in April |
| `variant-info.csv` | SKU → variant mapping reference for mapper.py |
| `warehouse_lookup.csv` | CF.WAREHOUSE → warehouse_id lookup for PR processing |

## Archive
After each successful `recon.py` run, all input CSVs are automatically moved to `archive/YYYY-MM-DD/`. Raw PR files should be moved to `tmp/` (gitignored) and deleted after processing.
