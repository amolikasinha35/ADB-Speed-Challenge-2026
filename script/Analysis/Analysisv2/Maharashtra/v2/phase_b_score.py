#!/usr/bin/env python3
"""
phase_b_score.py  --  Phase B: Preliminary Scoring  --  Maharashtra  --  v2
=============================================================================
Computes the Speed Safety Score from Phase A sections using the
Safe System Power Model formula.  This is a complete, submission-ready
output; Phase C (VLM) only refines it.

Steps
-----
  B1  Assign Safe System base benchmark per section (RoadClass × LandUse).
  B2  Compute Severity, Exposure, Consequence and the Speed Safety Score.
  B3  Generate imagery sampling plan for Phase C.

Formula
-------
  Severity  = (MedianSpeed / base_benchmark) ^ 4           [Power Model]
  Exposure  = 1 + (1 - HelmetSPI) × VRU_weight
  Consequence = CONSEQUENCE_DEFAULT (1.5, refined in Phase C)
  Speed_Safety_Score = Severity × Exposure × Consequence
  Speed_Safety_Score_log = log10(Speed_Safety_Score)

Outputs  -->  results/Analysis/Analysisv2/Maharashtra/v2/
---------------------------------------------------------
  sections_scored_maharashtra.gpkg    Sections with all score columns
  sections_scored_maharashtra.parquet Same with geometry
  imagery_sample.csv                  Sections selected for Street View + VLM
  phase_b_manifest.json               Coverage and score summary
"""

import subprocess, sys, os, warnings, json
warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

subprocess.check_call(
    [sys.executable, "-m", "pip", "install",
     "geopandas", "pandas", "numpy", "pyarrow"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)

import geopandas as gpd
import pandas as pd
import numpy as np

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from config import (
    REGION, SAFE_SYSTEM_BENCHMARKS,
    BENCHMARK_FALLBACK_URBAN, BENCHMARK_FALLBACK_RURAL,
    VRU_WEIGHT_URBAN, VRU_WEIGHT_RURAL, CONSEQUENCE_DEFAULT,
    POWER_MODEL_EXPONENT,
    IMAGERY_PRIORITY_SAMPLE, IMAGERY_CALIBRATION_SAMPLE,
)

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.dirname(
              os.path.dirname(os.path.dirname(SCRIPT_DIR)))))
RESULTS_DIR = os.path.join(BASE_DIR, "results", "Analysis", "Analysisv2", "Maharashtra", "v2")

print(f"Results dir : {RESULTS_DIR}\n")

# Load Phase A output.
parquet_in = os.path.join(RESULTS_DIR, "sections_maharashtra.parquet")
sections   = gpd.read_parquet(parquet_in)
print(f"Loaded {len(sections):,} sections from Phase A")


# =============================================================================
# B1 -- APPLY SAFE SYSTEM BENCHMARKS
# =============================================================================
print("\n" + "=" * 65)
print("STEP B1 -- SAFE SYSTEM BENCHMARKS")
print("=" * 65)

def get_benchmark(row):
    """Look up the Safe System base benchmark for this section."""
    rc = str(row["RoadClass"]).lower() if pd.notna(row["RoadClass"]) else ""
    lu = str(row["LandUse"]).upper()   if pd.notna(row["LandUse"])   else "RURAL"
    for (class_key, lu_key), speed in SAFE_SYSTEM_BENCHMARKS.items():
        if class_key in rc and lu_key == lu:
            return speed
    # Fallback by land use only.
    return BENCHMARK_FALLBACK_URBAN if "URBAN" in lu else BENCHMARK_FALLBACK_RURAL

sections["base_benchmark_kmh"] = sections.apply(get_benchmark, axis=1)
sections["class_imputed"]      = sections["RoadClass"].isna()

print("Benchmark distribution:")
print(sections["base_benchmark_kmh"].value_counts().sort_index().to_string())
print(f"\nAll sections have benchmark: {sections['base_benchmark_kmh'].notna().all()}")


# =============================================================================
# B2 -- COMPUTE SPEED SAFETY SCORE
# =============================================================================
print("\n" + "=" * 65)
print("STEP B2 -- SPEED SAFETY SCORE")
print("=" * 65)

# Severity: Power Model  (MedianSpeed / benchmark) ^ 4
# Floor speed at 1 km/h to avoid division-by-zero artefacts.
median_speed = sections["MedianSpeed"].clip(lower=1)
benchmark    = sections["base_benchmark_kmh"].clip(lower=1)
sections["severity"] = (median_speed / benchmark) ** POWER_MODEL_EXPONENT

# Exposure: vulnerability multiplier from helmet non-compliance.
# VRU weight is higher in urban environments (more pedestrians/cyclists).
vru_weight = np.where(
    sections["LandUse"].str.upper() == "URBAN",
    VRU_WEIGHT_URBAN,
    VRU_WEIGHT_RURAL,
)
helmet_spi = sections["HelmetSPI"].fillna(sections["HelmetSPI"].mean())
sections["exposure"] = 1 + (1 - helmet_spi) * vru_weight

# Consequence: defaults to 1.5 before VLM enrichment in Phase C.
sections["consequence"] = CONSEQUENCE_DEFAULT

# Final score and log-transformed version.
sections["speed_safety_score"]     = (
    sections["severity"] * sections["exposure"] * sections["consequence"]
).round(4)
sections["speed_safety_score_log"] = np.log10(
    sections["speed_safety_score"].clip(lower=1e-6)
).round(4)

# Store score components as JSON for tooltip display in maps.
sections["score_components_json"] = sections.apply(
    lambda r: json.dumps({
        "severity":    round(r["severity"], 4),
        "exposure":    round(r["exposure"], 4),
        "consequence": round(r["consequence"], 4),
        "score":       round(r["speed_safety_score"], 4),
        "benchmark":   r["base_benchmark_kmh"],
        "median_speed":round(r["MedianSpeed"], 1),
    }),
    axis=1,
)

print(f"Speed Safety Score summary:")
print(sections["speed_safety_score"].describe().round(3).to_string())
print(f"\nLog score summary:")
print(sections["speed_safety_score_log"].describe().round(3).to_string())

# Score band breakdown (quartile labels for quick interpretation).
def _score_band(s):
    if s <= 0:      return "No Data"
    elif s < 1.5:   return "Low"
    elif s < 4.0:   return "Moderate"
    elif s < 10.0:  return "High"
    else:           return "Critical"
sections["score_band"] = sections["speed_safety_score"].apply(_score_band)
print(f"\nScore band breakdown:")
print(sections["score_band"].value_counts().sort_index().to_string())


# =============================================================================
# B3 -- GENERATE IMAGERY SAMPLING PLAN
# =============================================================================
print("\n" + "=" * 65)
print("STEP B3 -- IMAGERY SAMPLING PLAN")
print("=" * 65)
print(f"Priority sample : top {IMAGERY_PRIORITY_SAMPLE:,} by score")
print(f"Calibration     : {IMAGERY_CALIBRATION_SAMPLE:,} stratified by RoadClass × LandUse")

# Priority sample: highest-scoring sections.
priority = (
    sections.nlargest(IMAGERY_PRIORITY_SAMPLE, "speed_safety_score")
    [["section_id", "RoadClass", "LandUse", "midpoint_lat", "midpoint_lon",
      "bearing_deg", "speed_safety_score"]]
    .copy()
)
priority["sample_tier"] = "priority"

# Calibration sample: stratified random sample from remaining sections.
remaining = sections[~sections["section_id"].isin(priority["section_id"])].copy()
remaining["stratum"] = (
    remaining["RoadClass"].fillna("unknown") + "_" +
    remaining["LandUse"].fillna("unknown")
)
n_strata   = remaining["stratum"].nunique()
per_stratum = max(1, IMAGERY_CALIBRATION_SAMPLE // n_strata)

cal_parts = []
for _, grp in remaining.groupby("stratum"):
    n = min(per_stratum, len(grp))
    cal_parts.append(grp.sample(n=n, random_state=42))
calibration = pd.concat(cal_parts).head(IMAGERY_CALIBRATION_SAMPLE)
calibration = calibration[priority.columns.tolist()[:-1]].copy()
calibration["sample_tier"] = "calibration"

imagery_sample = pd.concat([priority, calibration], ignore_index=True)
imagery_sample["country"] = REGION
imagery_sample = imagery_sample.drop_duplicates(subset="section_id")

sample_path = os.path.join(RESULTS_DIR, "imagery_sample.csv")
imagery_sample.to_csv(sample_path, index=False)
print(f"  [Saved] imagery_sample.csv  ({len(imagery_sample):,} sections)")
print(f"    Priority    : {(imagery_sample['sample_tier']=='priority').sum():,}")
print(f"    Calibration : {(imagery_sample['sample_tier']=='calibration').sum():,}")


# =============================================================================
# SAVE OUTPUTS
# =============================================================================
print("\n" + "=" * 65)
print("SAVING PHASE B OUTPUTS")
print("=" * 65)

for col in sections.select_dtypes(include="bool").columns:
    sections[col] = sections[col].astype(int)
cat_cols = sections.select_dtypes(include="category").columns
for col in cat_cols:
    sections[col] = sections[col].astype(str)

gpkg_out    = os.path.join(RESULTS_DIR, "sections_scored_maharashtra.gpkg")
parquet_out = os.path.join(RESULTS_DIR, "sections_scored_maharashtra.parquet")

sections.to_file(gpkg_out, driver="GPKG", layer="sections_scored")
print(f"  [Saved] sections_scored_maharashtra.gpkg  ({len(sections):,} sections)")

sections.to_parquet(parquet_out, index=False)
print(f"  [Saved] sections_scored_maharashtra.parquet")

manifest = {
    "region":             REGION,
    "phase":              "B",
    "sections_scored":    len(sections),
    "score_mean":         round(float(sections["speed_safety_score"].mean()), 4),
    "score_max":          round(float(sections["speed_safety_score"].max()), 4),
    "imagery_sample_n":   len(imagery_sample),
}
with open(os.path.join(RESULTS_DIR, "phase_b_manifest.json"), "w") as f:
    json.dump(manifest, f, indent=2)
print(f"  [Saved] phase_b_manifest.json")

print(f"\nPhase B complete.  Preliminary Speed Safety Score computed.")
print(f"Run Phase C to enrich with Street View + Gemini VLM.")
print(f"Outputs: {RESULTS_DIR}")
