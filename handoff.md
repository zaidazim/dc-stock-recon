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
├── recon.py                          ← the automation script (run this)
├── final-stock-recon.csv             ← reference output (manually built in Google Sheets)
├── final-stock-recon-output_*.csv    ← script outputs (excluded from detection)
├── variant-info.csv                  ← SKU reference table (not used in recon, excluded)
├── recon_run.log                     ← one-line summary appended after each run
├── archive/<YYYY-MM-DD>/             ← input files auto-moved here after a successful run
└── old/                              ← backup/timestamped exports (excluded from detection)
```

**To run the script:** drop input CSVs into the root folder, then `python recon.py`

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

Three source files (`sales`, `ops`, `calc_direct_refill`) have rows where `warehouse_id` is null
for VMs 3034–3043. The user believes this is a data pipeline issue and is investigating.
Until fixed at source, these rows will trigger Guardrail #3 and block the run.

Workaround (temporary, do not automate): patch those rows to `warehouse_id = 9`
based on cross-referencing the timestamped backup exports in `old/`.

---

## Validation baseline

The script's first successful run produced `final-stock-recon-output_2026-03-31.csv` (11,711 rows).
The reference `final-stock-recon.csv` has 14,050 rows — the delta is because the reference was
built from an older data extract where warehouses 11, 24, and 74 were active. This is expected;
all 10 column grand totals matched exactly between script output and reference.
