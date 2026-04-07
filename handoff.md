# DC Stock Reconciliation — Agent Handoff

## What this project does
Automates a monthly/quarterly stock reconciliation previously done manually in Google Sheets.
`recon.py` detects input CSVs by column fingerprint, aggregates them to warehouse+SKU level,
merges, computes closing stock, validates totals, and writes a dated output CSV.

## Repo: `zaidazim/dc-stock-recon` — work on `main`

---

## Folder structure

```
dc-stock-recon/
├── src/
│   ├── recon.py              ← reconciliation engine
│   ├── mapper.py             ← variant aggregation
│   ├── fetch_data.py         ← Redshift data fetcher
│   ├── process_pr.py         ← Zoho PR cleaner
│   ├── validate_fetch.py     ← post-fetch QA checks
│   └── compare.py            ← manual validation utility
├── .claude/commands/
│   ├── recon.md              ← /recon slash command
│   └── process-pr.md         ← /process-pr slash command
├── archive/<YYYY-MM-DD>/     ← input files auto-moved here after a successful run
├── tmp/                      ← raw files staged for deletion (gitignored)
├── variant-info.csv          ← SKU → variant mapping reference
├── warehouse_lookup.csv      ← CF.WAREHOUSE → warehouse_id lookup (PR processing)
├── wh-vm-os.csv              ← opening stock (fixed per financial year)
├── recon_run.log             ← one-line summary appended after each run
├── .env                      ← Redshift credentials (gitignored)
├── .env.example              ← credential template
└── .venv/                    ← Python 3.13 virtualenv (gitignored)
```

**To run:** see slash commands `/process-pr` and `/recon` — or run scripts directly via `.venv/bin/python src/<script>.py`

---

## Input files — detected by column fingerprint, not filename

| Role | Key fingerprint columns | Granularity |
|---|---|---|
| `wh_vm_os` | `wh_cs_actual`, `vm_cs_actual` | WH + SKU |
| `pr` | `sum_of_quantity_received` (alias → `pr_qty`) | WH + SKU |
| `calc_direct_refill` | `calc_direct_refill` | VM + SKU → aggregated |
| `kit_prepared` | `item_quantity` (alias → `kit_prepared_qty`), `sku_group_id` | VM + SKU → aggregated |
| `ops` | `extra`, `remove`, `expiry` (alias → `expire`) | VM + SKU → aggregated |
| `sales` | `manufacturer_variant_id`, `sales` | VM + SKU → aggregated |

All SKU column variants (`sku_group_id`, `manufacturer_variant_id`, `cleaned_sku`) are normalised to `sku_id`.
Files ending in `Z.csv` (ISO-timestamp exports) are automatically excluded.

---

## Core formulas

```
total_fresh = kit_prepared_qty + calc_direct_refill
wh_cs_calc  = (wh_os + pr_qty) - (total_fresh - extra - remove)
vm_cs_calc  = vm_os - (sales + expire) + (total_fresh - extra - remove)
```

Where `wh_os` = `wh_cs_actual` and `vm_os` = `vm_cs_actual` from the `wh_vm_os` file.

---

## Guardrails (hard stops unless noted)

1. Missing mandatory input file
2. Multiple CSVs matching the same role fingerprint (duplicate / mixed-period files)
3. Null `warehouse_id` or `sku_id` in any source file
4. Duplicate `(warehouse_id, sku_id)` keys in `pr` or `wh_vm_os`
5. Output column totals don't match source totals after merge
6. Schema drift — fingerprint columns missing after normalisation
7. Negative `wh_cs_calc` or `vm_cs_calc` — **warning only**, not a hard stop

---

## Open issue — null warehouse_ids

`fetch_data.py` performs a null `warehouse_id` check after each Redshift query. If any rows
return null (e.g. VMs with no `warehouse_id` set in `dc_prod_db_vending_machines`), the script
hard stops and prints the affected VM IDs. Fix the mapping in the DB before re-running.

Do NOT patch rows manually — the root cause must be fixed at source.

---

## Next session — run FY 2025-26 recon (Apr 2025 – Mar 2026)

**Status as of 2026-04-07:** pipeline is built and ready. The following is already done:
- PR processed: `pr_processed_2026-04-07.csv` is in root (covers Apr 2025 – Mar 2026, both half-year Zoho exports combined)
- Opening stock: `wh-vm-os.csv` is in root (Apr 2025 opening, reused from prior run)

**What's needed to run:**
1. Create `.env` from `.env.example` and fill in Redshift credentials
2. Run: `.venv/bin/python src/fetch_data.py --start 2025-04-01 --end 2026-03-01`
   - Optionally run `.venv/bin/python src/validate_fetch.py` after to spot-check fetched totals
3. Run: `.venv/bin/python src/recon.py .`
4. Run: `.venv/bin/python src/mapper.py <recon_output_file> --variant-info variant-info.csv`

Or just use the slash command (Claude Code only): `/recon 2025-04-01 2026-03-01`

**Watch out for:**
- Null `warehouse_id` rows — `fetch_data.py` will hard stop and print the affected VM IDs. Fix in DB, re-run.
- `recon.py` must be called with `.` as folder arg so it scans root, not `src/`
- Python: always use `.venv/bin/python`, not system python

**No valid reference output exists yet for the full FY.** Do not compare against `archive/2026-03-31/` — that was Apr 2025–Feb 2026 only.

---

## Validation baseline

The script's first successful run produced `final-stock-recon-output_2026-03-31.csv` (11,711 rows).
The reference `final-stock-recon.csv` has 14,050 rows — the delta is because the reference was
built from an older data extract where warehouses 11, 24, and 74 were active. This is expected;
all 10 column grand totals matched exactly between script output and reference.
