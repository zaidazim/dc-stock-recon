import sys
import argparse
from pathlib import Path
import pandas as pd

def main():
    parser = argparse.ArgumentParser(description="Map and aggregate SKUs based on brand and offer price.")
    parser.add_argument("recon_file", type=str, help="Path to the final recon output CSV.")
    parser.add_argument("--variant-info", type=str, default="variant-info.csv", help="Path to variant info CSV.")
    args = parser.parse_args()

    recon_path = Path(args.recon_file).resolve()
    vinfo_path = Path(args.variant_info).resolve()

    if not recon_path.exists():
        sys.exit(f"ERROR: Recon file not found: {recon_path}")
    if not vinfo_path.exists():
        sys.exit(f"ERROR: Variant info file not found: {vinfo_path}")

    # 1. Load Variant Info
    print(f"Loading variant info from {vinfo_path.name}...")
    vinfo = pd.read_csv(vinfo_path, dtype=str)
    
    # Clean and parse required columns
    vinfo['mvid_clean'] = pd.to_numeric(vinfo['mvid'].astype(str).str.replace(',', '', regex=False), errors='coerce')
    vinfo['offer_price_clean'] = pd.to_numeric(vinfo['offer_price'].astype(str).str.replace(',', '', regex=False), errors='coerce')
    vinfo['brand_id_clean'] = vinfo['brand_id'].fillna('').str.replace(',', '', regex=False).str.strip()

    vinfo['offer_price_clean'] = vinfo['offer_price_clean'].fillna(-1)
    
    # 2. Build Mapper
    valid_vinfo = vinfo.dropna(subset=['mvid_clean']).copy()
    valid_vinfo['mvid_clean'] = valid_vinfo['mvid_clean'].astype(int)

    # Clean variant_id as well so we can find the arithmetic minimum
    valid_vinfo['variant_id_clean'] = pd.to_numeric(valid_vinfo['variant_id'].astype(str).str.replace(',', '', regex=False), errors='coerce')
    valid_vinfo = valid_vinfo.dropna(subset=['variant_id_clean']).copy()
    valid_vinfo['variant_id_clean'] = valid_vinfo['variant_id_clean'].astype(int)

    print("Building variant mapping using minimum variant_id...")
    group_cols = ['brand_id_clean', 'offer_price_clean']
    
    mapper_df = valid_vinfo.groupby(group_cols, as_index=False)['variant_id_clean'].min()
    mapper_df.rename(columns={'variant_id_clean': 'mapper_variant_id'}, inplace=True)

    valid_vinfo = valid_vinfo.merge(mapper_df, on=group_cols, how='left')

    mvid_to_mapper = dict(zip(valid_vinfo['mvid_clean'].astype(str), valid_vinfo['mapper_variant_id'].astype(str)))
    mvid_to_vid = dict(zip(valid_vinfo['mvid_clean'].astype(str), valid_vinfo['variant_id'].fillna('').astype(str)))
    
    # Since mapper_variant_id is now a variant_id, we need to map variant_id -> name
    vid_to_name = dict(zip(valid_vinfo['variant_id_clean'].astype(str), valid_vinfo['variant_name'].fillna('').astype(str)))

    # 3. Load Recon Data
    print(f"Loading recon data from {recon_path.name}...")
    recon = pd.read_csv(recon_path, dtype=str)
    recon = recon.dropna(subset=['sku_id'])

    # 4. Handle missing SKUs
    recon_skus = set(recon['sku_id'])
    vinfo_skus = set(mvid_to_mapper.keys())

    unmapped = recon_skus - vinfo_skus
    if unmapped:
        print(f"\n[INFO] Found {len(unmapped)} sku_id(s) in recon data missing from variant-info.csv.")
        print(f"Unmapped SKUs: {', '.join(sorted(list(unmapped)))}")
        print("Mapping these unmapped/garbage SKUs to mapper_variant_id = 0 to conserve totals.")
        
        for u in unmapped:
            mvid_to_mapper[u] = "0"
            mvid_to_vid[u] = "0"

        # Safe default for missing mapper_variant_ids
        vid_to_name["0"] = "Unknown/Unmapped"

    if recon.empty:
        sys.exit("No data left to process.")

    # 5. Build and Export the Variant Mapper Map File
    # Create a mapping dataframe of ALL unique sku_id from recon file
    unique_skus = sorted(list(recon_skus), key=lambda x: int(float(x)) if x.replace('.', '').isdigit() else x)
    mapping_data = []
    for sku in unique_skus:
        m_vid = mvid_to_mapper.get(sku, "0")
        mapping_data.append({
            "sku_id": sku,
            "variant_id": mvid_to_vid.get(sku, "0"),
            "mapper_variant_id": m_vid,
            "mapper_variant_name": vid_to_name.get(m_vid, "Unknown/Unmapped")
        })
    mapping_df = pd.DataFrame(mapping_data)
    
    if "-output_" in recon_path.name:
        map_out_name = recon_path.name.replace("final-stock-recon-output_", "variant-mapping-reference_")
    else:
        map_out_name = "mapping_reference_" + recon_path.name
        
    map_out_path = recon_path.parent / map_out_name
    mapping_df.to_csv(map_out_path, index=False)
    print(f"Successfully wrote mapping reference file to: {map_out_name}")

    # 6. Apply Mapping to Recon Data
    recon['mapper_variant_id'] = recon['sku_id'].map(mvid_to_mapper)

    numeric_cols = [
        "pr_qty", "wh_os", "vm_os", "kit_prepared_qty", "calc_direct_refill", 
        "total_fresh", "extra", "remove", "expire", "sales", "wh_cs_calc", "vm_cs_calc"
    ]
    for c in numeric_cols:
        if c in recon.columns:
            recon[c] = pd.to_numeric(recon[c], errors='coerce').fillna(0)

    # 7. Aggregate
    print("Aggregating grouped SKUs...")
    agg_funcs = {}
    for c in numeric_cols:
        if c in recon.columns:
            agg_funcs[c] = 'sum'

    grouped = recon.groupby(['warehouse_id', 'mapper_variant_id'], dropna=False).agg(agg_funcs).reset_index()

    # Append mapper_variant_name to the aggregated df
    # Map the unique aggregated mapper_variant_id to its variant_name using vid_to_name
    grouped['mapper_variant_name'] = grouped['mapper_variant_id'].map(vid_to_name).fillna("Unknown/Unmapped")

    grouped['helper'] = grouped['warehouse_id'].astype(str) + "|" + grouped['mapper_variant_id'].astype(str)

    out_cols = ['warehouse_id', 'mapper_variant_id', 'mapper_variant_name', 'helper']
    for c in numeric_cols:
        if c in recon.columns:
            out_cols.append(c)

    final = grouped[out_cols]

    # 8. Write output
    if "-output_" in recon_path.name:
        out_name = recon_path.name.replace("-output_", "-mapped-output_")
    else:
        out_name = "mapped_" + recon_path.name
        
    out_path = recon_path.parent / out_name
    
    final.to_csv(out_path, index=False)
    print(f"Successfully wrote mapped output to: {out_name} ({len(final)} rows)")

if __name__ == "__main__":
    main()
