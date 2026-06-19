#!/usr/bin/env python3
"""
phase_a_prep.py  --  Phase A: Data Preparation  --  Thailand  --  v2
======================================================================
Converts the raw Thailand GeoPackage into a clean, aggregated,
helmet-SPI-enriched section table ready for scoring in Phase B.

Steps
-----
  A1  Load GeoPackage, cast types, add quality flags, impute speed limits.
  A2  Aggregate micro-segments to road sections (group by english_ro + length cap).
  A3  Spatial join helmet SPI from the Thailand_Province_Boundaries polygon layer.

Outputs  -->  results/Analysis/Analysisv2/Thailand/v2/
------------------------------------------------------
  sections_thailand.gpkg    Road sections with all Phase A columns
  sections_thailand.parquet Same table with geometry (faster to reload)
  phase_a_manifest.json     Input hashes, row counts, coverage report
"""

import subprocess, sys, os, warnings, json, hashlib, math
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
    PROVINCE_JOIN_COL, PROVINCE_INCLUDE_COL, PROVINCE_NAME_COL,
    N_VALID_THRESHOLD, MIN_SECTION_LENGTH_M,
    SPEED_DEFAULTS, SPEED_DEFAULT_FALLBACK,
)

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.dirname(
              os.path.dirname(os.path.dirname(SCRIPT_DIR)))))
GPKG_PATH   = os.path.join(BASE_DIR, "Data", "Archive",
              "Road_Safety_Performance_Indicators__Thailand_(Feature).gpkg")
RESULTS_DIR = os.path.join(BASE_DIR, "results", "Analysis", "Analysisv2", "Thailand", "v2")
os.makedirs(RESULTS_DIR, exist_ok=True)

print(f"Project root : {BASE_DIR}")
print(f"Results dir  : {RESULTS_DIR}\n")


# =============================================================================
# A1 -- INGEST AND QUALITY FLAG
# =============================================================================
print("=" * 65)
print("STEP A1 -- INGEST AND QUALITY FLAG")
print("=" * 65)

available_layers = fiona.listlayers(GPKG_PATH)
print(f"GeoPackage layers: {available_layers}")

gdf = gpd.read_file(GPKG_PATH, layer=GPKG_SEG_LAYER)
print(f"Loaded {len(gdf):,} segments  |  {len(gdf.columns)} columns")
print(f"CRS: {gdf.crs}")

# ── Cast SpeedLimit ────────────────────────────────────────────────────────
gdf["SpeedLimit_num"] = pd.to_numeric(gdf["SpeedLimit"], errors="coerce")
n_null = gdf["SpeedLimit_num"].isna().sum()
print(f"\nSpeedLimit nulls before imputation : {n_null:,} / {len(gdf):,}")

# ── Sample size column (Thailand uses SampleSizeTotal) ───────────────────
sample_col = "SampleSizeTotal" if "SampleSizeTotal" in gdf.columns else "Sample_Size_Total"

# ── Quality flags ─────────────────────────────────────────────────────────
gdf["n_valid"] = gdf[sample_col].fillna(0) >= N_VALID_THRESHOLD

high_class = gdf["RoadClass"].str.lower().isin(["motorway", "trunk"])
low_limit  = gdf["SpeedLimit_num"].fillna(999) < 40
gdf["limit_plausible"] = ~(high_class & low_limit)
gdf["limit_imputed"]   = False

# ── Impute speed limits ────────────────────────────────────────────────────
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
print("STEP A2 -- AGGREGATE TO ROAD SECTIONS  (group by english_ro)")
print("=" * 65)

# Thailand groups by english_ro (road name).  Segments without a road name
# are assigned a synthetic key using ProvinceID + RoadClass + OvertureID prefix.
def make_group_key(row):
    name = str(row.get("english_ro", "")).strip()
    if name and name.lower() not in ("nan", "none", ""):
        return name
    pid = str(row.get("ProvinceID", "XX"))
    rc  = str(row.get("RoadClass", "road"))
    return f"_anon_{pid}_{rc}_{str(row.get(SEGMENT_ID, 0))[:6]}"

gdf["_group_key"] = gdf.apply(make_group_key, axis=1)

def weighted_mean(values, weights):
    w = weights.fillna(1)
    return (values * w).sum() / w.sum() if w.sum() > 0 else values.mean()

def safe_mode(series):
    m = series.dropna().mode()
    return m.iloc[0] if len(m) > 0 else None

def compute_bearing(geom):
    try:
        coords = list(geom.geoms[0].coords) if hasattr(geom, "geoms") \
                 else list(geom.coords)
        if len(coords) >= 2:
            dx = coords[-1][0] - coords[0][0]
            dy = coords[-1][1] - coords[0][1]
            return (math.degrees(math.atan2(dx, dy)) + 360) % 360
    except Exception:
        pass
    return 0.0

agg_records = []
for grp_key, grp in gdf.groupby("_group_key"):
    w = grp[sample_col].fillna(1)

    med_speed = weighted_mean(grp["MedianSpeed"].fillna(0), w)
    f85_speed = weighted_mean(grp["F85thPercentileSpeed"].fillna(0), w)
    pct_over  = weighted_mean(grp["PercentOverLimit"].fillna(0), w)
    sp_limit  = weighted_mean(grp["SpeedLimit_num"].fillna(0), w)

    road_class = safe_mode(grp["RoadClass"])
    land_use   = safe_mode(grp["LandUse"])
    province   = safe_mode(grp.get("ProvinceID"))

    mixed_class   = grp["RoadClass"].nunique() > 1
    mixed_landuse = grp["LandUse"].nunique() > 1

    total_sample = grp[sample_col].fillna(0).sum()
    total_length = grp["RoadLength"].fillna(0).sum() if "RoadLength" in grp.columns else 0.0
    n_valid_frac  = grp["n_valid"].mean()
    n_imputed_frac= grp["limit_imputed"].mean()

    dissolved_geom = grp.geometry.unary_union

    try:
        midpoint = dissolved_geom.interpolate(0.5, normalized=True)
        mid_lon, mid_lat = midpoint.x, midpoint.y
    except Exception:
        mid_lon, mid_lat = 0.0, 0.0

    bearing = compute_bearing(dissolved_geom)

    agg_records.append({
        "section_id":           grp_key,
        "RoadClass":            road_class,
        "LandUse":              land_use,
        "ProvinceID":           province,
        "SpeedLimit_num":       round(sp_limit, 1),
        "MedianSpeed":          round(med_speed, 2),
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

before_filter = len(sections)
sections = sections[sections["RoadLength_m"] >= MIN_SECTION_LENGTH_M].copy()
sections = sections.reset_index(drop=True)

print(f"Sections before length filter : {before_filter:,}")
print(f"Sections after  length filter : {len(sections):,}  (>= {MIN_SECTION_LENGTH_M} m)")
print(f"  With n_valid >= 50% threshold : "
      f"{(sections['n_valid_share'] >= 0.5).sum():,} / {len(sections):,}")
print(f"  With imputed limit            : "
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
# A3 -- SPATIAL JOIN HELMET SPI FROM PROVINCE BOUNDARIES
# =============================================================================
print("\n" + "=" * 65)
print("STEP A3 -- SPATIAL JOIN HELMET SPI  (province boundaries)")
print("=" * 65)

province_gdf = gpd.read_file(GPKG_PATH, layer=GPKG_HELM_LAYER)
print(f"Province polygons loaded : {len(province_gdf)}")
print(f"Provinces with INCLUDE=Y : "
      f"{(province_gdf[PROVINCE_INCLUDE_COL] == 'Y').sum()}")

# Normalise SPI columns to 0-1 if stored as percentage.
for col in [SPI_ALL_COL, SPI_DRV_COL, SPI_PASS_COL]:
    if col in province_gdf.columns and province_gdf[col].max() > 1.5:
        province_gdf[col] = province_gdf[col] / 100

# Reproject to match sections CRS.
if sections.crs != province_gdf.crs:
    province_gdf = province_gdf.to_crs(sections.crs)

# Spatial join via section centroids.
pts = sections.copy()
pts = pts.set_geometry(pts.geometry.centroid)

joined = gpd.sjoin(
    pts[["section_id", "ProvinceID", "geometry"]],
    province_gdf[[PROVINCE_JOIN_COL, PROVINCE_INCLUDE_COL,
                   SPI_ALL_COL, SPI_DRV_COL, SPI_PASS_COL, "geometry"]],
    how="left",
    predicate="within",
)
joined = joined.drop_duplicates(subset="section_id")

spi_map = joined.set_index("section_id")[
    [PROVINCE_INCLUDE_COL, SPI_ALL_COL, SPI_DRV_COL, SPI_PASS_COL]
]
sections = sections.join(spi_map, on="section_id")
sections = sections.rename(columns={
    SPI_ALL_COL:  "HelmetSPI",
    SPI_DRV_COL:  "HelmetSPI_Driver",
    SPI_PASS_COL: "HelmetSPI_Passenger",
})
sections.drop(columns=["centroid"], inplace=True, errors="ignore")

# For excluded provinces (INCLUDE != Y), flag for fallback.
sections["helmet_imputed"] = (
    sections["HelmetSPI"].isna() |
    sections[PROVINCE_INCLUDE_COL].isin(["N", "X"])
)

# Load Excel for helmet trend slope.
HELMET_EXCEL = os.path.join(BASE_DIR, "Data", "Archive",
    "Road_Safety_Performance_Indicators_(Helmet_Wearing_results)_(adb_dashboard_data_v02).xlsx")
if os.path.exists(HELMET_EXCEL):
    helmet_df = pd.read_excel(HELMET_EXCEL)
    th_yr = helmet_df[
        (helmet_df["Location"] == REGION) &
        (helmet_df["User"] == "All Riders") &
        (helmet_df["Year"] != "All")
    ].copy()
    th_yr["Year"] = pd.to_numeric(th_yr["Year"], errors="coerce")
    th_yr = th_yr.dropna(subset=["Year", "SPI"])
    if len(th_yr) >= 2:
        from numpy.polynomial.polynomial import polyfit
        slope = polyfit(th_yr["Year"], th_yr["SPI"], 1)[1]
        sections["helmet_trend"] = round(float(slope), 5)
        print(f"\nHelmet trend slope (SPI/year) : {slope:.4f}")
    else:
        sections["helmet_trend"] = 0.0

# Fallback: use national mean from Excel for excluded / unmatched sections.
if sections["helmet_imputed"].any():
    national_spi = sections["HelmetSPI"].dropna().mean()
    for col in ["HelmetSPI", "HelmetSPI_Driver", "HelmetSPI_Passenger"]:
        sections.loc[sections["helmet_imputed"], col] = (
            sections.loc[sections["helmet_imputed"], col].fillna(national_spi)
        )
    print(f"Helmet SPI fallback applied to  : {sections['helmet_imputed'].sum():,} sections")

spi_coverage = sections["HelmetSPI"].notna().mean()
print(f"HelmetSPI coverage : {spi_coverage:.1%}")


# =============================================================================
# SAVE OUTPUTS
# =============================================================================
print("\n" + "=" * 65)
print("SAVING PHASE A OUTPUTS")
print("=" * 65)

gpkg_out    = os.path.join(RESULTS_DIR, "sections_thailand.gpkg")
parquet_out = os.path.join(RESULTS_DIR, "sections_thailand.parquet")

for col in sections.select_dtypes(include="bool").columns:
    sections[col] = sections[col].astype(int)
for col in sections.select_dtypes(include="object").columns:
    if col not in ("section_id", "RoadClass", "LandUse", "ProvinceID",
                   PROVINCE_INCLUDE_COL, "geometry"):
        sections[col] = sections[col].astype(str)

sections.to_file(gpkg_out, driver="GPKG", layer="sections")
print(f"  [Saved] sections_thailand.gpkg  ({len(sections):,} sections)")

sections.to_parquet(parquet_out, index=False)
print(f"  [Saved] sections_thailand.parquet")

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
