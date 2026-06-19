#!/usr/bin/env python3
"""
phase_a_prep.py  --  Phase A: Data Preparation  --  Maharashtra  --  v2
========================================================================
Converts the raw Maharashtra GeoPackage into a clean, aggregated,
helmet-SPI-enriched section table ready for scoring in Phase B.

Steps
-----
  A1  Load GeoPackage, cast types, add quality flags, impute speed limits.
  A2  Aggregate micro-segments to road sections (group by DISSOLVE_ID).
  A3  Spatial join helmet SPI from the Boundaries_4helmet polygon layer.

Outputs  -->  results/Analysis/Analysisv2/Maharashtra/v2/
---------------------------------------------------------
  sections_maharashtra.gpkg    Road sections with all Phase A columns
  sections_maharashtra.parquet Same table with geometry (faster to reload)
  phase_a_manifest.json        Input hashes, row counts, coverage report
"""

import subprocess, sys, os, warnings, json, hashlib
warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

subprocess.check_call(
    [sys.executable, "-m", "pip", "install",
     "geopandas", "pandas", "numpy", "openpyxl", "pyarrow", "fiona"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)

import geopandas as gpd
import pandas as pd
import numpy as np
import fiona

# ── Paths and config ──────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from config import (
    REGION, SEGMENT_ID, GPKG_SEG_LAYER, GPKG_HELM_LAYER,
    SPI_ALL_COL, SPI_DRV_COL, SPI_PASS_COL,
    N_VALID_THRESHOLD, MIN_SECTION_LENGTH_M,
    SPEED_DEFAULTS, SPEED_DEFAULT_FALLBACK,
)

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.dirname(
              os.path.dirname(os.path.dirname(SCRIPT_DIR)))))
GPKG_PATH   = os.path.join(BASE_DIR, "Data", "Archive",
              "Road_Safety_Performance_Indicators__Maharashtra_(Feature).gpkg")
RESULTS_DIR = os.path.join(BASE_DIR, "results", "Analysis", "Analysisv2", "Maharashtra", "v2")
os.makedirs(RESULTS_DIR, exist_ok=True)

print(f"Project root : {BASE_DIR}")
print(f"Results dir  : {RESULTS_DIR}\n")


# =============================================================================
# A1 -- INGEST AND QUALITY FLAG
# =============================================================================
print("=" * 65)
print("STEP A1 -- INGEST AND QUALITY FLAG")
print("=" * 65)

# List available layers so we can verify the expected names exist.
available_layers = fiona.listlayers(GPKG_PATH)
print(f"GeoPackage layers: {available_layers}")

# Load the segment-level layer (one row per micro-segment).
gdf = gpd.read_file(GPKG_PATH, layer=GPKG_SEG_LAYER)
print(f"Loaded {len(gdf):,} segments  |  {len(gdf.columns)} columns")
print(f"CRS: {gdf.crs}")

# ── Cast SpeedLimit to numeric ─────────────────────────────────────────────
# The source column is TEXT; non-parseable entries become NaN.
gdf["SpeedLimit_num"] = pd.to_numeric(gdf["SpeedLimit"], errors="coerce")
n_null_limit = gdf["SpeedLimit_num"].isna().sum()
print(f"\nSpeedLimit nulls before imputation : {n_null_limit:,} / {len(gdf):,}")

# ── Quality flag 1: n_valid ────────────────────────────────────────────────
# True when the segment has enough probe observations to be statistically reliable.
gdf["n_valid"] = gdf["Sample_Size_Total"].fillna(0) >= N_VALID_THRESHOLD

# ── Quality flag 2: limit_plausible ───────────────────────────────────────
# A speed limit below 40 km/h on a motorway or trunk road is almost certainly
# a data error (e.g. a work-zone limit stored as the permanent limit).
high_class = gdf["RoadClass"].str.lower().isin(["motorway", "trunk"])
low_limit  = gdf["SpeedLimit_num"].fillna(999) < 40
gdf["limit_plausible"] = ~(high_class & low_limit)

# ── Quality flag 3: limit_imputed ─────────────────────────────────────────
# Will be set True for any row where we apply the legal default.
gdf["limit_imputed"] = False

# ── Impute missing / implausible speed limits ─────────────────────────────
# Uses the legal defaults table from config, with substring matching on
# RoadClass so "primary" also matches "unclassified primary", etc.
def impute_speed(row):
    rc = str(row["RoadClass"]).lower() if pd.notna(row["RoadClass"]) else ""
    lu = str(row["LandUse"]).upper()   if pd.notna(row["LandUse"])   else "RURAL"
    for (class_key, lu_key), speed in SPEED_DEFAULTS.items():
        if class_key in rc and lu_key == lu:
            return speed
    return SPEED_DEFAULT_FALLBACK

needs_imputation = gdf["SpeedLimit_num"].isna() | ~gdf["limit_plausible"]
gdf.loc[needs_imputation, "SpeedLimit_num"] = (
    gdf[needs_imputation].apply(impute_speed, axis=1)
)
gdf.loc[needs_imputation, "limit_imputed"] = True

n_imputed = gdf["limit_imputed"].sum()
print(f"Speed limits imputed               : {n_imputed:,} / {len(gdf):,}")
print(f"n_valid segments                   : {gdf['n_valid'].sum():,} / {len(gdf):,}")


# =============================================================================
# A2 -- AGGREGATE MICRO-SEGMENTS TO ROAD SECTIONS
# =============================================================================
print("\n" + "=" * 65)
print("STEP A2 -- AGGREGATE TO ROAD SECTIONS  (group by DISSOLVE_ID)")
print("=" * 65)

# Weight all speed statistics by Sample_Size_Total (probe observation count).
# Mode (most frequent value) is used for categorical columns.
def weighted_mean(values, weights):
    w = weights.fillna(1)
    if w.sum() == 0:
        return values.mean()
    return (values * w).sum() / w.sum()

def safe_mode(series):
    m = series.dropna().mode()
    return m.iloc[0] if len(m) > 0 else None

agg_records = []
for section_id, grp in gdf.groupby(SEGMENT_ID):
    w = grp["Sample_Size_Total"].fillna(1)

    # Weighted speed statistics.
    med_speed = weighted_mean(grp["MedianSpeed"].fillna(0), w)
    f85_speed = weighted_mean(grp["F85thPercentileSpeed"].fillna(0), w)
    pct_over  = weighted_mean(grp["PercentOverLimit"].fillna(0), w)
    sp_limit  = weighted_mean(grp["SpeedLimit_num"].fillna(0), w)

    # Mode (most common) for categorical columns.
    road_class = safe_mode(grp["RoadClass"])
    land_use   = safe_mode(grp["LandUse"])

    # Mixed-class and mixed-landuse flags (are there multiple classes within
    # this DISSOLVE_ID group?).
    mixed_class   = grp["RoadClass"].nunique() > 1
    mixed_landuse = grp["LandUse"].nunique() > 1

    # Section totals.
    total_sample  = grp["Sample_Size_Total"].fillna(0).sum()
    total_length  = grp["RoadLength"].fillna(0).sum()
    n_valid_frac  = grp["n_valid"].mean()        # share of micro-segs that are valid
    n_imputed_frac= grp["limit_imputed"].mean()  # share with imputed limit

    # Dissolve geometry into a single LineString/MultiLineString.
    dissolved_geom = grp.geometry.unary_union

    # Section midpoint and bearing for Street View heading.
    try:
        midpoint = dissolved_geom.interpolate(0.5, normalized=True)
        mid_lon, mid_lat = midpoint.x, midpoint.y
        # Bearing from start to end of the dissolved geometry.
        coords = list(dissolved_geom.geoms[0].coords) if hasattr(dissolved_geom, "geoms") \
                 else list(dissolved_geom.coords)
        if len(coords) >= 2:
            dx = coords[-1][0] - coords[0][0]
            dy = coords[-1][1] - coords[0][1]
            import math
            bearing = (math.degrees(math.atan2(dx, dy)) + 360) % 360
        else:
            bearing = 0.0
    except Exception:
        mid_lon, mid_lat, bearing = 0.0, 0.0, 0.0

    agg_records.append({
        "section_id":     section_id,
        "RoadClass":      road_class,
        "LandUse":        land_use,
        "SpeedLimit_num": round(sp_limit, 1),
        "MedianSpeed":    round(med_speed, 2),
        "F85thPercentileSpeed": round(f85_speed, 2),
        "PercentOverLimit":     round(pct_over, 4),
        "SampleSizeTotal":      total_sample,
        "RoadLength_m":         round(total_length, 1),
        "n_valid_share":        round(n_valid_frac, 3),
        "limit_imputed_share":  round(n_imputed_frac, 3),
        "mixed_class_flag":     mixed_class,
        "mixed_landuse_flag":   mixed_landuse,
        "midpoint_lon":         mid_lon,
        "midpoint_lat":         mid_lat,
        "bearing_deg":          round(bearing, 1),
        "geometry":             dissolved_geom,
    })

sections = gpd.GeoDataFrame(agg_records, crs=gdf.crs)

# Drop sections shorter than the minimum threshold.
before_filter = len(sections)
sections = sections[sections["RoadLength_m"] >= MIN_SECTION_LENGTH_M].copy()
sections = sections.reset_index(drop=True)

print(f"Sections before length filter : {before_filter:,}")
print(f"Sections after  length filter : {len(sections):,}  (>= {MIN_SECTION_LENGTH_M} m)")
print(f"  Share with n_valid >= threshold : "
      f"{(sections['n_valid_share'] >= 0.5).sum():,} / {len(sections):,}")
print(f"  Share with imputed limit        : "
      f"{(sections['limit_imputed_share'] > 0).sum():,} / {len(sections):,}")

# Reproject midpoints to WGS84 so lat/lon are in decimal degrees for Street View API.
# The source CRS is UTM (metres), not decimal degrees.
sections_wgs84 = sections.to_crs("EPSG:4326")
centroids_wgs84 = sections_wgs84.geometry.centroid
sections["midpoint_lat"] = centroids_wgs84.y.round(6)
sections["midpoint_lon"] = centroids_wgs84.x.round(6)
print(f"  Midpoints reprojected to WGS84  : "
      f"lat range [{sections['midpoint_lat'].min():.3f}, {sections['midpoint_lat'].max():.3f}], "
      f"lon range [{sections['midpoint_lon'].min():.3f}, {sections['midpoint_lon'].max():.3f}]")


# =============================================================================
# A3 -- SPATIAL JOIN HELMET SPI
# =============================================================================
print("\n" + "=" * 65)
print("STEP A3 -- SPATIAL JOIN HELMET SPI")
print("=" * 65)

# Load the Boundaries_4helmet polygon layer from the same GeoPackage.
# This gives AllRidersSPI, DriverSPI, PassengerSPI for four zones:
# Mumbai, Pune, Maharashtra Rural, Maharashtra Urban.
helmet_zones = gpd.read_file(GPKG_PATH, layer=GPKG_HELM_LAYER)
print(f"Helmet zones loaded : {len(helmet_zones)} polygons")
print(helmet_zones[[SPI_ALL_COL, SPI_DRV_COL, SPI_PASS_COL]].to_string())

# Reproject sections to match helmet zones CRS for the spatial join.
if sections.crs != helmet_zones.crs:
    helmet_zones = helmet_zones.to_crs(sections.crs)

# Use section centroid for the spatial join (faster than full line geometry).
sections_pts = sections.copy()
sections_pts = sections_pts.set_geometry(sections_pts.geometry.centroid)

# Spatial join: each section centroid finds the zone it falls within.
joined = gpd.sjoin(
    sections_pts[["section_id", "geometry"]],
    helmet_zones[[SPI_ALL_COL, SPI_DRV_COL, SPI_PASS_COL, "geometry"]],
    how="left",
    predicate="within",
)
joined = joined.drop_duplicates(subset="section_id")

# Map SPI values back onto the sections table.
spi_map = joined.set_index("section_id")[[SPI_ALL_COL, SPI_DRV_COL, SPI_PASS_COL]]
sections = sections.join(spi_map, on="section_id")
sections = sections.rename(columns={
    SPI_ALL_COL:  "HelmetSPI",
    SPI_DRV_COL:  "HelmetSPI_Driver",
    SPI_PASS_COL: "HelmetSPI_Passenger",
})
sections.drop(columns=["centroid"], inplace=True, errors="ignore")

# Flag sections where no zone was matched (will use fallback in Phase B).
sections["helmet_imputed"] = sections["HelmetSPI"].isna()

# Load helmet Excel for trend slope calculation.
HELMET_EXCEL = os.path.join(BASE_DIR, "Data", "Archive",
    "Road_Safety_Performance_Indicators_(Helmet_Wearing_results)_(adb_dashboard_data_v02).xlsx")
if os.path.exists(HELMET_EXCEL):
    helmet_df = pd.read_excel(HELMET_EXCEL)
    mh_yr = helmet_df[
        (helmet_df["Location"] == REGION) &
        (helmet_df["User"] == "All Riders") &
        (helmet_df["Year"] != "All")
    ].copy()
    mh_yr["Year"] = pd.to_numeric(mh_yr["Year"], errors="coerce")
    mh_yr = mh_yr.dropna(subset=["Year", "SPI"])
    if len(mh_yr) >= 2:
        # Linear trend slope (SPI points per year).
        from numpy.polynomial.polynomial import polyfit
        slope = polyfit(mh_yr["Year"], mh_yr["SPI"], 1)[1]
        sections["helmet_trend"] = round(float(slope), 5)
        print(f"\nHelmet trend slope (SPI/year) : {slope:.4f}")
    else:
        sections["helmet_trend"] = 0.0

# Fallback: where helmet_imputed, use national mean from Excel.
if sections["helmet_imputed"].any():
    national_spi = sections["HelmetSPI"].mean()
    for col in ["HelmetSPI", "HelmetSPI_Driver", "HelmetSPI_Passenger"]:
        sections.loc[sections["helmet_imputed"], col] = (
            sections.loc[sections["helmet_imputed"], col].fillna(national_spi)
        )
    print(f"Helmet SPI fallback applied to  : {sections['helmet_imputed'].sum():,} sections")

# Normalise SPI to 0-1 range (some sources store as percentage 0-100).
for col in ["HelmetSPI", "HelmetSPI_Driver", "HelmetSPI_Passenger"]:
    if sections[col].max() > 1.5:
        sections[col] = sections[col] / 100

spi_coverage = sections["HelmetSPI"].notna().mean()
print(f"HelmetSPI coverage : {spi_coverage:.1%}")


# =============================================================================
# SAVE OUTPUTS
# =============================================================================
print("\n" + "=" * 65)
print("SAVING PHASE A OUTPUTS")
print("=" * 65)

gpkg_out    = os.path.join(RESULTS_DIR, "sections_maharashtra.gpkg")
parquet_out = os.path.join(RESULTS_DIR, "sections_maharashtra.parquet")

# Convert boolean columns to int for GeoPackage compatibility.
for col in sections.select_dtypes(include="bool").columns:
    sections[col] = sections[col].astype(int)

sections.to_file(gpkg_out, driver="GPKG", layer="sections")
print(f"  [Saved] sections_maharashtra.gpkg  ({len(sections):,} sections)")

sections.to_parquet(parquet_out, index=False)
print(f"  [Saved] sections_maharashtra.parquet")

# ── Phase A manifest ──────────────────────────────────────────────────────────
manifest = {
    "region":                REGION,
    "phase":                 "A",
    "input_gpkg":            GPKG_PATH,
    "input_gpkg_md5":        hashlib.md5(open(GPKG_PATH, "rb").read()).hexdigest(),
    "raw_segments":          len(gdf),
    "sections_after_agg":    len(sections),
    "sections_with_n_valid": int((sections["n_valid_share"] >= 0.5).sum()),
    "sections_limit_imputed":int((sections["limit_imputed_share"] > 0).sum()),
    "helmet_spi_coverage_pct": round(100 * spi_coverage, 1),
}
with open(os.path.join(RESULTS_DIR, "phase_a_manifest.json"), "w") as f:
    json.dump(manifest, f, indent=2)
print(f"  [Saved] phase_a_manifest.json")

print(f"\nPhase A complete.  {len(sections):,} road sections ready for Phase B.")
print(f"Outputs: {RESULTS_DIR}")
