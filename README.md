# DC Stock Reconciliation Automation

## Purpose
This repository automates the Monthly/Quarterly Stock Reconciliation process. It collapses multiple operational CSV data exports into a single pipeline, generating unified stock totals across warehouses and SKUs, and mapping variants sharing identical characteristics into grouped keys.

## Environment
* **Python**: 3.13 via `.venv` (created via `python -m venv .venv`).
* **Dependencies**: `pandas` (`pip install pandas`). Use `python` relative to the `.venv`.

## Core Files & Architecture

### 1. `recon.py` (The Engine)
* **Input**: Scans the current directory for CSV files mapping to predefined "role fingerprints" (e.g., `wh_vm_os`, `pr`, `sales`, etc.).
* **Logic**: 
  * Normalizes column names (`space` -> `_`, `lowercase`, `aliases`).
  * Strictly validates column constraints and runs Guardrails (aborts on missing columns, null `warehouse_id`s, or duplicate keys).
  * Merges all files together matching on `warehouse_id` + `sku_id`. 
  * Calculates derived formula metrics: `helper`, `total_fresh`, `wh_cs_calc`, `vm_cs_calc`.
* **Output**: `final-stock-recon-output_YYYY-MM-DD.csv` and stores processed input files in `archive/<DATE>/`.

### 2. `mapper.py` (The Aggregator)
* **Input**: Expects `final-stock-recon-output_*.csv` (as `sys.argv[1]`) and `variant-info.csv`.
* **Logic**: 
  * Parses `variant-info.csv`, stripping illegal commas from `brand_id` and `mvid`.
  * Computes `mapper_variant_id` representing the `min(mvid)` within groups of identical `brand_id` and `offer_price`.
  * Any `sku_id`s missing from `variant-info.csv` (garbage data) are deliberately mapped to `0` (Under the Law of Conservation, this prevents numeric sum discrepancies from dropping records).
  * Groups the recon output by `warehouse_id` and `mapper_variant_id` and perfectly `sum()`s the numeric facts.
* **Output 1 (Aggregated Data)**: `final-stock-recon-mapped-output_YYYY-MM-DD.csv`. Drops `sku_id` and `variant_id` to strictly display the `mapper_variant_id` and its aggregate values.
* **Output 2 (Lookup Dictionary)**: `variant-mapping-reference_YYYY-MM-DD.csv`. An individual itemized cross-reference defining exactly which `sku_id` mapped to which `mapper_variant_id`.

### 3. `handoff.md` (Context Documentation)
* Detailed breakdown of strict accounting formulas, legacy logic definitions, column mappings, and known Data Pipeline problems (e.g. VMs 3034-3043 outputting null `warehouse_id` strings).

### 4. `compare.py`
* Utility for testing and validating the script vs a manual Google Sheets file.

## Expected Workflow Sequence
1. Drop raw CSV data streams and `variant-info.csv` into repo.
2. `python recon.py`
3. `python mapper.py final-stock-recon-output_YYYY-MM-DD.csv`
