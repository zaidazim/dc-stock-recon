import csv
import sys

def get_totals(filepath):
    totals = {}
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        columns = reader.fieldnames
        for row in reader:
            for col, val in row.items():
                if val:
                    try:
                        num = float(val.replace(',', ''))
                        totals[col] = totals.get(col, 0) + num
                    except ValueError:
                        pass
    return columns, totals

ref_file = 'final-stock-recon.csv'
out_file = 'final-stock-recon-output_2026-03-31.csv'

ref_cols, ref_totals = get_totals(ref_file)
out_cols, out_totals = get_totals(out_file)

print("=== Column Comparison ===")
ref_col_set = set(ref_cols)
out_col_set = set(out_cols)

if ref_col_set == out_col_set:
    print("Columns match exactly!")
else:
    print("Columns in Reference but not Output:", ref_col_set - out_col_set)
    print("Columns in Output but not Reference:", out_col_set - ref_col_set)

print("\n=== Numeric Column Totals ===")
format_str = "{:<25} | {:<15} | {:<15} | {:<15}"
print(format_str.format("Column Name", "Reference Total", "Output Total", "Difference"))
print('-' * 77)

all_numeric_cols = set(ref_totals.keys()).union(set(out_totals.keys()))

for col in sorted(list(all_numeric_cols)):
    r_val = ref_totals.get(col, 0)
    o_val = out_totals.get(col, 0)
    # Round to avoid float precision issues in display
    diff = round(o_val - r_val, 4)
    print(format_str.format(col, round(r_val, 2), round(o_val, 2), diff))
