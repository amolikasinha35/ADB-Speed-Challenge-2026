#!/usr/bin/env python3
"""
thailand_data_prep.py  --  v3
==============================
Reads the Thailand GeoJSON road-segment data and combines it with
Helmet SPI (Safety Performance Indicator) data from the ADB Excel file.

PURPOSE
-------
The GeoJSON contains road-level speed and compliance measurements.
The Excel contains helmet-wearing survey rates by region, land use, and year.
This script joins them so every road segment carries the SPI values needed
for downstream risk analysis.

INPUTS
------
  ADB_Innovation_Thailand.geojson
      ~55,884 road segments.  Key columns used here:
        LandUse          -- URBAN or RURAL (used as the SPI join key)
        PercentOverLimit -- share of vehicles exceeding the posted speed limit
  Road_Safety_Performance_Indicators_(Helmet_Wearing_results).xlsx
      Helmet-wearing survey rates.  Columns: Location, LandUse, User, Year, SPI.
      SPI is a proportion (0 = nobody wearing, 1 = everybody wearing).
      Years present: 2021, 2022, 2023, 2024, plus "All" (multi-year aggregate).

IMPORTANT LIMITATION
--------------------
Thailand SPI is national-level only -- there is NO province-level breakdown.
Every segment across all provinces receives the same LandUse-specific SPI.

SPI COLUMNS ADDED TO EACH SEGMENT
-----------------------------------
  HelmetSPI             -- "All"-year aggregate, Rural/Urban specific
  HelmetSPI_Driver      -- same, driver user type
  HelmetSPI_Passenger   -- same, passenger user type
  HelmetSPI_2021 ..2024 -- national Combined rate per survey year (broadcast)
  CompositeRisk         -- (PercentOverLimit / 100) x (1 - HelmetSPI)
  CompositeRisk_Driver      same formula, driver SPI
  CompositeRisk_Passenger   same formula, passenger SPI

COMPOSITE RISK FORMULA
-----------------------
  CompositeRisk = (PercentOverLimit / 100) x (1 - HelmetSPI)

  Dimension 1 : PercentOverLimit / 100  -- share of vehicles speeding (0-1)
  Dimension 2 : 1 - HelmetSPI           -- share of riders NOT helmeted (0-1)
  Result range : 0.0 (no risk) to 1.0 (everyone speeds, nobody wears a helmet)

OUTPUTS  -->  results/thailand_data_prep/v3/
--------------------------------------------
  thailand_combined.csv       All 55,884 segments with SPI columns (no geometry)
  thailand_combined.parquet   Same table WITH geometry preserved (for QGIS / spatial joins)
  spi_all_years.csv           Reference: full SPI table for all years x user x landuse
"""

# ── Standard library ──────────────────────────────────────────────────────────
import subprocess, sys, os, warnings

# Suppress pandas/geopandas FutureWarnings that are not relevant to this script.
warnings.filterwarnings("ignore")

# Force UTF-8 output so Thai road names and Unicode characters do not raise
# UnicodeEncodeError when printing on a Windows console (default cp1252).
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Install dependencies ──────────────────────────────────────────────────────
# pip is idempotent -- safe to re-run even if packages are already installed.
subprocess.check_call(
    [sys.executable, "-m", "pip", "install",
     "geopandas",   # read/write GeoJSON and GeoPackage
     "pandas",      # tabular data manipulation
     "numpy",       # numeric operations
     "openpyxl",    # read .xlsx files
     "pyarrow"],    # write Parquet files
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
)

# ── Third-party imports ───────────────────────────────────────────────────────
import geopandas as gpd   # GeoDataFrame: extends pandas with geometry support
import pandas as pd
import numpy as np

# =============================================================================
# PATHS
# =============================================================================
# __file__ resolves to: .../script/data preparation/Thailand/v3/thailand_data_prep.py
# Four dirname() calls walk up to the project root:
#   v3/  ->  Thailand/  ->  data preparation/  ->  script/  ->  project root
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
BASE_DIR    = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(SCRIPT_DIR))))

GEOJSON     = os.path.join(BASE_DIR, "Data", "ADB_Innovation_Thailand.geojson")
HELMET_FILE = os.path.join(BASE_DIR, "Data", "Archive",
              "Road_Safety_Performance_Indicators_(Helmet_Wearing_results)_(adb_dashboard_data_v02).xlsx")

# All output files go into this folder.  Created automatically if missing.
RESULTS_DIR = os.path.join(BASE_DIR, "results", "Analysis", "data preparation", "Thailand", "v3")
os.makedirs(RESULTS_DIR, exist_ok=True)

REGION = "Thailand"   # must match the "Location" column value in the Excel file

print(f"Project root : {BASE_DIR}")
print(f"Results dir  : {RESULTS_DIR}\n")


# =============================================================================
# STEP 1 -- LOAD GEOJSON ROAD SEGMENTS
# =============================================================================
# The GeoJSON is the primary dataset.  Every row is one road segment.
# We load the full file and keep ALL rows; no filtering is applied here.
# Geometry (LineString coordinates) is preserved in the GeoDataFrame so
# we can write a GeoParquet output at the end.
# =============================================================================
print("=" * 60)
print("STEP 1 -- LOAD GEOJSON")
print("=" * 60)

gdf = gpd.read_file(GEOJSON)

print(f"  Loaded : {len(gdf):,} road segments")
print(f"  Columns: {len(gdf.columns)}")
print(f"  CRS    : {gdf.crs}  (geographic, decimal degrees)")

# Quick preview of the columns most relevant to this pipeline.
preview_cols = ["OBJECTID", "english_ro", "RoadClass", "LandUse",
                "SpeedLimit", "MedianSpeed", "PercentOverLimit", "AnalysisStatus"]
print("\n  Sample (5 rows, key columns):")
print(gdf[preview_cols].head().to_string(index=False))


# =============================================================================
# STEP 2 -- LOAD HELMET SPI EXCEL
# =============================================================================
# The Excel has one row per (Location, LandUse, User, Year) combination.
# We filter to Thailand only and inspect what years are available.
#
# Year = "All" is the multi-year aggregate -- the most stable SPI value
# because it is not tied to a single survey cycle.
# Individual years (2021-2024) capture yearly variation.
# =============================================================================
print("\n" + "=" * 60)
print("STEP 2 -- LOAD HELMET SPI EXCEL")
print("=" * 60)

helmet_raw = pd.read_excel(HELMET_FILE)

# Filter to Thailand rows only.  Other locations (Maharashtra, Mumbai, Pune)
# are present in the same file and must be excluded to prevent accidental join.
helmet_region = helmet_raw[helmet_raw["Location"] == REGION].copy()

# Identify which year values are in the data.
all_years     = sorted(helmet_region["Year"].unique())
# Numeric years are the individual survey rounds; "All" is excluded here.
numeric_years = [y for y in all_years
                 if str(y).isdigit() or
                    (isinstance(y, (int, float)) and not isinstance(y, bool))]

print(f"  Years in Excel for {REGION}: {all_years}")
print(f"  Numeric survey years       : {numeric_years}")
print()
print(helmet_region.to_string(index=False))

# Save the full Thailand SPI table as a reference file so analysts can see
# all year x user x landuse combinations in one place.
spi_all = helmet_region.pivot_table(
    index=["Location", "LandUse", "Year"],
    columns="User",
    values="SPI",
).reset_index()
spi_all.columns.name = None
spi_all.to_csv(os.path.join(RESULTS_DIR, "spi_all_years.csv"), index=False)
print("\n  [Saved] spi_all_years.csv  (reference: all years x user x landuse)")


# =============================================================================
# STEP 3 -- BUILD SPI LOOKUP TABLES
# =============================================================================
# Two lookup tables are built from the Excel data:
#
# Table A -- "All"-year aggregate  (one row per LandUse)
#   Columns: HelmetSPI | HelmetSPI_Driver | HelmetSPI_Passenger
#   Used for: primary join onto segments by LandUse (Rural / Urban).
#   This gives Rural segments one SPI value and Urban segments another.
#
# Table B -- Per-year national rate  (single "Combined" row per year)
#   Columns: HelmetSPI_2021 | HelmetSPI_2022 | HelmetSPI_2023 | HelmetSPI_2024
#   Used for: broadcasting a constant value to ALL segments regardless of LandUse.
#   Why broadcast instead of join?  Because the yearly Excel only has
#   LandUse = "Combined" (national total) -- there is no yearly Rural/Urban split.
#   Attaching it as a constant lets analysts track the trend over time even
#   though it does not vary by land use.
# =============================================================================
print("\n" + "=" * 60)
print("STEP 3 -- BUILD SPI LOOKUP TABLES")
print("=" * 60)

# ── Table A: "All"-year aggregate by LandUse ──────────────────────────────────
# Pivot User types (rows) into separate columns so a single merge attaches
# Driver, Passenger, and All-Riders SPIs in one operation.
helmet_pivot_all = (
    helmet_region[helmet_region["Year"] == "All"]
    .pivot_table(
        index=["Location", "LandUse"],
        columns="User",
        values="SPI",
    )
    .reset_index()
)
helmet_pivot_all.columns.name = None   # remove the "User" label from the column axis

# Rename to descriptive column names used throughout the rest of the script.
helmet_pivot_all = helmet_pivot_all.rename(columns={
    "All Riders": "HelmetSPI",
    "Driver":     "HelmetSPI_Driver",
    "Passenger":  "HelmetSPI_Passenger",
})

print("  Table A -- All-year aggregate (joined by LandUse):")
print(helmet_pivot_all.to_string(index=False))

# ── Table B: Per-year national Combined rate ──────────────────────────────────
# For each numeric year, extract the single "Combined" / "All Riders" row.
# Store as a plain dictionary {column_name: SPI_value} for easy broadcasting.
spi_year_cols      = []    # list of column names added, e.g. ["HelmetSPI_2021", ...]
helmet_year_series = {}    # {column_name: float_value}

if numeric_years:
    # Filter to: numeric years + All Riders + Combined (national) LandUse only.
    helmet_years = helmet_region[
        helmet_region["Year"].isin(numeric_years) &
        (helmet_region["User"] == "All Riders") &
        (helmet_region["LandUse"] == "Combined")
    ].copy()
    helmet_years["Year"] = helmet_years["Year"].astype(str)

    # Build the dict from the filtered rows.
    for _, row in helmet_years.iterrows():
        col = f"HelmetSPI_{row['Year']}"
        helmet_year_series[col] = row["SPI"]
        spi_year_cols.append(col)
    spi_year_cols = sorted(spi_year_cols)   # chronological order

    print(f"\n  Table B -- Per-year national SPI (broadcast to all segments):")
    for col, val in helmet_year_series.items():
        print(f"    {col} : {val}")


# =============================================================================
# STEP 4 -- COMBINE DATASETS
# =============================================================================
# Two join operations attach SPI data onto the road segments GeoDataFrame.
#
# Join 1 (lookup join):
#   Left table  : gdf  (all 55,884 segments)
#   Right table : helmet_pivot_all  (3 rows: Combined, Rural, Urban)
#   Key         : LandUse  (capitalised to match Excel title case)
#   Type        : LEFT JOIN -- every segment is kept.
#                 Segments without a LandUse value (AnalysisStatus = "Not Included")
#                 receive NaN for all SPI columns.
#
# Join 2 (broadcast):
#   No merge operation needed -- each per-year value is assigned directly
#   as a constant scalar column.  All 55,884 rows get the same value per year.
#
# CompositeRisk is then computed on the joined table using the
# "All"-year aggregate HelmetSPI (the most stable value).
# =============================================================================
print("\n" + "=" * 60)
print("STEP 4 -- COMBINE DATASETS")
print("=" * 60)

# Create a temporary capitalised LandUse column for the join key.
# GeoJSON stores LandUse as uppercase ("RURAL", "URBAN").
# Excel uses title case ("Rural", "Urban").
# We normalise without altering the original LandUse column.
gdf["LandUse_join"] = gdf["LandUse"].str.capitalize()

# Also tag each segment with the region name so the join key is unambiguous
# if this script is ever run after combining multiple regions into one file.
gdf["Location"] = REGION

# ── Join 1: "All"-year aggregate SPI by LandUse ───────────────────────────────
gdf = gdf.merge(
    helmet_pivot_all,
    left_on=["Location", "LandUse_join"],   # from GeoJSON
    right_on=["Location", "LandUse"],       # from Excel pivot
    how="left",                             # keep all segments
    suffixes=("", "_helmet"),               # avoid column name clash on LandUse
)

# Drop the duplicate LandUse column that came from the right-hand Excel table
# (suffixed "_helmet") -- the original "LandUse" from the GeoJSON is kept.
gdf.drop(columns=["LandUse_helmet"], errors="ignore", inplace=True)

# The temporary join key is no longer needed.
gdf.drop(columns=["LandUse_join"], errors="ignore", inplace=True)

# ── Join 2: Per-year SPI -- broadcast constant columns ────────────────────────
# Assigning a scalar to a DataFrame column fills every row with that value.
# This is intentional: the yearly SPI is a national aggregate, not segment-level.
for col, val in helmet_year_series.items():
    gdf[col] = val

# ── CompositeRisk calculation ─────────────────────────────────────────────────
# Formula: CompositeRisk = (PercentOverLimit / 100) x (1 - HelmetSPI)
#
# PercentOverLimit is stored as a percentage (0-100), so dividing by 100
# converts it to a proportion (0-1) so both factors are on the same scale.
#
# (1 - HelmetSPI) = the share of riders NOT wearing a helmet.
# A high value means riders are more exposed to fatal head injuries at speed.
#
# Three variants are computed -- one per user type in the survey.
gdf["CompositeRisk"]           = (gdf["PercentOverLimit"] / 100) * (1 - gdf["HelmetSPI"])
gdf["CompositeRisk_Driver"]    = (gdf["PercentOverLimit"] / 100) * (1 - gdf["HelmetSPI_Driver"])
gdf["CompositeRisk_Passenger"] = (gdf["PercentOverLimit"] / 100) * (1 - gdf["HelmetSPI_Passenger"])

# ── Coverage report ───────────────────────────────────────────────────────────
# HelmetSPI (All-year) is NULL for segments without a LandUse value.
# Per-year columns are non-null for all segments (broadcast).
print(f"  Combined table : {len(gdf):,} rows, {len(gdf.columns)} columns")
print()
report_cols = (["HelmetSPI", "HelmetSPI_Driver", "HelmetSPI_Passenger",
                "CompositeRisk", "CompositeRisk_Driver", "CompositeRisk_Passenger"]
               + spi_year_cols)
for col in report_cols:
    if col in gdf.columns:
        n_valid = gdf[col].notna().sum()
        pct     = 100 * n_valid / len(gdf)
        print(f"  {col:<35}: {n_valid:>6,} / {len(gdf):,}  ({pct:.1f}%)")


# =============================================================================
# STEP 5 -- SAVE OUTPUTS
# =============================================================================
# Two formats are saved so this combined table can be used in multiple ways:
#
# CSV (.csv)
#   Geometry is dropped because CSV cannot store spatial data.
#   Use this for: Excel, pandas, any tabular analysis tool.
#
# GeoParquet (.parquet)
#   Geometry is preserved alongside all other columns.
#   Use this for: geopandas, QGIS, spatial joins, map plotting.
#   Parquet is columnar and compressed -- much faster to read than GeoJSON.
# =============================================================================
print("\n" + "=" * 60)
print("STEP 5 -- SAVE OUTPUTS")
print("=" * 60)

# CSV: drop geometry column before writing (CSV has no geometry type).
csv_path = os.path.join(RESULTS_DIR, "thailand_combined.csv")
gdf.drop(columns="geometry").to_csv(csv_path, index=False)
print(f"  [Saved] thailand_combined.csv")
print(f"          {len(gdf):,} rows x {len(gdf.columns) - 1} columns  (geometry excluded)")

# GeoParquet: keep geometry so the file can be loaded into QGIS or used
# in spatial operations without re-reading the original GeoJSON.
parquet_path = os.path.join(RESULTS_DIR, "thailand_combined.parquet")
gdf.to_parquet(parquet_path, index=False)
print(f"\n  [Saved] thailand_combined.parquet")
print(f"          {len(gdf):,} rows x {len(gdf.columns)} columns  (geometry included)")

print(f"\nDone.  All outputs saved to:\n  {RESULTS_DIR}")
