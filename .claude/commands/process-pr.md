# Process Purchase Receive Files

Run this when raw Purchase Receive CSV exports are in the repo root.

## Steps

1. Check that at least one `*PurchaseReceive*.csv` file exists in the repo root. If none found, tell the user to drop the files in root and try again.

2. Check that the warehouse ID lookup file exists in root (matches `*lookup warehouse ID*.csv`). If missing, ask the user to provide it.

3. Run the processing script:
   ```
   .venv/bin/python src/process_pr.py
   ```

4. Report the output:
   - How many files were processed
   - Total rows loaded
   - How many invalid SKUs were cleaned
   - How many aggregated rows (warehouse × sku)
   - Output filename

5. If there are unmatched warehouse values in the output, surface them clearly and ask the user whether to update the lookup file.

## Output
Produces `pr_processed_YYYY-MM-DD.csv` in root — aggregated by `warehouse_id` + `sku_id` with `pr_qty` (sum of quantity received).
