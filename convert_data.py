#!/usr/bin/env python3
"""
Convert RDS data to CSV format for Django import
Run this script to convert the poi_nairobi.rds file to CSV
"""

import pandas as pd
import geopandas as gpd
import os
import sys

def convert_rds_to_csv(rds_path, csv_path):
    """Convert RDS file to CSV (placeholder - you'll need to implement actual conversion)"""
    try:
        # This is a placeholder - you would need to use rpy2 or similar to read RDS
        # For now, this assumes you have manually converted the data

        print(f"Expected to convert {rds_path} to {csv_path}")
        print("Please manually convert the RDS file to CSV format with columns:")
        print("name, category, major_category, ward_name, lat, lon")
        print("Then run: python manage.py load_data --data-dir ../data")

        return False

    except Exception as e:
        print(f"Error converting RDS: {e}")
        return False

def main():
    data_dir = "../data"
    rds_file = os.path.join(data_dir, "poi_nairobi.rds")
    csv_file = os.path.join(data_dir, "poi_nairobi.csv")

    if not os.path.exists(rds_file):
        print(f"Error: {rds_file} not found")
        sys.exit(1)

    if convert_rds_to_csv(rds_file, csv_file):
        print(f"Successfully converted {rds_file} to {csv_file}")
    else:
        print("Conversion failed. Please convert manually.")

if __name__ == "__main__":
    main()