# -*- coding: utf-8 -*-
"""
Data Exporter: Extracts custom data from Odoo Studio dump.sql
and exports clean CSV files ready for import into the new it_asset_management module.
"""
import os
import re
import csv
import json

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SQL_PATH = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", "dump.sql"))
OUTPUT_DIR = os.path.join(SCRIPT_DIR, "exported_csv")
os.makedirs(OUTPUT_DIR, exist_ok=True)

def parse_copy_data(content, table_name):
    pattern = rf"COPY (?:public\.)?{table_name} \((.*?)\) FROM stdin;\n(.*?)\\\."
    match = re.search(pattern, content, re.DOTALL)
    if not match:
        return None, []
    cols = [c.strip() for c in match.group(1).split(",")]
    raw_rows = match.group(2).strip().split("\n")
    rows = []
    for line in raw_rows:
        if not line:
            continue
        parts = line.split("\t")
        rows.append(dict(zip(cols, parts)))
    return cols, rows

def clean_val(v):
    if v is None or v == "\\N":
        return ""
    if v.startswith('{"') and v.endswith('}'):
        try:
            d = json.loads(v)
            if "en_US" in d:
                return d["en_US"]
            if "ar_001" in d:
                return d["ar_001"]
            return list(d.values())[0]
        except Exception:
            pass
    return v

def main():
    if not os.path.exists(SQL_PATH):
        print(f"dump.sql not found at {SQL_PATH}")
        return

    with open(SQL_PATH, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # 1. Locations
    cols, loc_rows = parse_copy_data(content, "x_location")
    if loc_rows:
        loc_file = os.path.join(OUTPUT_DIR, "it_asset_location.csv")
        with open(loc_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "name"])
            for r in loc_rows:
                writer.writerow([f"loc_{r['id']}", clean_val(r.get("x_name"))])
        print(f"Exported {len(loc_rows)} locations to {loc_file}")

    # 2. Assets
    cols, asset_rows = parse_copy_data(content, "x_assets")
    if asset_rows:
        asset_file = os.path.join(OUTPUT_DIR, "it_asset.csv")
        type_mapping = {
            "Laptop": "laptop",
            "PC": "pc",
            "Screen": "screen",
            "Tablet": "tablet",
            "Printer": "printer",
            "All-In-One": "all_in_one",
            "Keyboard": "keyboard",
            "Mouse": "mouse"
        }
        with open(asset_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([
                "id", "ref", "name", "asset_type", "serial_no", "model_sku",
                "cpu", "ram", "nvme", "ssd", "hdd", "os", "ms_office", "anti_virus",
                "acquisition_date", "acquisition_price"
            ])
            for r in asset_rows:
                raw_type = clean_val(r.get("x_studio_asset_type"))
                mapped_type = type_mapping.get(raw_type, "other")
                writer.writerow([
                    f"asset_{r['id']}",
                    clean_val(r.get("x_studio_ref")),
                    clean_val(r.get("x_name")),
                    mapped_type,
                    clean_val(r.get("x_studio_asset_serial_no")),
                    clean_val(r.get("x_studio_asset_model_sku")),
                    clean_val(r.get("x_studio_cpu")),
                    clean_val(r.get("x_studio_ram")),
                    clean_val(r.get("x_studio_nvme")),
                    clean_val(r.get("x_studio_ssd")),
                    clean_val(r.get("x_studio_hdd")),
                    clean_val(r.get("x_studio_os")),
                    clean_val(r.get("x_studio_ms_office")),
                    clean_val(r.get("x_studio_anti_virus")),
                    clean_val(r.get("x_studio_acquisition_date")),
                    clean_val(r.get("x_studio_asset_price")),
                ])
        print(f"Exported {len(asset_rows)} assets to {asset_file}")

    # 3. Credentials
    cols, cred_rows = parse_copy_data(content, "x_credentials")
    if cred_rows:
        cred_file = os.path.join(OUTPUT_DIR, "it_credential.csv")
        with open(cred_file, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["id", "name", "url", "password"])
            for r in cred_rows:
                writer.writerow([
                    f"cred_{r['id']}",
                    clean_val(r.get("x_name")),
                    clean_val(r.get("x_studio_url")),
                    clean_val(r.get("x_studio_password")),
                ])
        print(f"Exported {len(cred_rows)} credentials to {cred_file}")

if __name__ == "__main__":
    main()
