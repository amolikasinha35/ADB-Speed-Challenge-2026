#!/usr/bin/env python3
"""
phase_d_final.py  --  Phase D: Final Scoring & Deliverables  --  Thailand  --  v2
==================================================================================
Combines all Phase A-C signals into the final Speed Safety Score,
assigns intervention types, quantifies Power Model safety benefits,
and produces three spatial outputs and a country comparison.

Steps
-----
  D1  Recompute Speed Safety Score with VLM-refined benchmark and forgivingness.
  D2  Assign intervention type using Signal A and Signal B diagnostic matrix.
  D3  Generate three spatial outputs (segment map, province choropleth, top-100 CSV).
  D4  Country comparison using helmet trend data from both regions.

Outputs  -->  results/Analysis/Analysisv2/Thailand/v2/
------------------------------------------------------
  speed_safety_scores_thailand.gpkg    Final scored sections
  speed_safety_scores_thailand.parquet
  priority_top100_thailand.csv         Top 100 with Power Model benefits
  map_segment_thailand.html            Segment-level interactive map
  map_aggregate_thailand.html          Province-level choropleth
  country_comparison.csv               Thailand vs Maharashtra summary
  phase_d_manifest.json
"""

import subprocess, sys, os, warnings, json
warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

subprocess.check_call(
    [sys.executable, "-m", "pip", "install",
     "geopandas", "pandas", "numpy", "pyarrow", "folium", "branca", "openpyxl"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)

import geopandas as gpd
import pandas as pd
import numpy as np
import folium
import branca.colormap as cm
import folium.plugins

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from config import (
    REGION, ZOOM, POWER_MODEL_EXPONENT,
    VRU_WEIGHT_URBAN, VRU_WEIGHT_RURAL,
    SIGNAL_A_THRESHOLD_KMH, SIGNAL_B_THRESHOLD_KMH,
    TOP_N_PRIORITY, GPKG_HELM_LAYER,
    PROVINCE_NAME_COL, PROVINCE_INCLUDE_COL,
    SPI_ALL_COL,
)

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.dirname(
              os.path.dirname(os.path.dirname(SCRIPT_DIR)))))
RESULTS_DIR = os.path.join(BASE_DIR, "results", "Analysis", "Analysisv2", "Thailand", "v2")
GPKG_PATH   = os.path.join(BASE_DIR, "Data", "Archive",
              "Road_Safety_Performance_Indicators__Thailand_(Feature).gpkg")
os.makedirs(RESULTS_DIR, exist_ok=True)
print(f"Results dir : {RESULTS_DIR}\n")

# Load the most enriched available output: Phase C if it exists, else Phase B.
enriched_path = os.path.join(RESULTS_DIR, "sections_enriched_thailand.parquet")
scored_path   = os.path.join(RESULTS_DIR, "sections_scored_thailand.parquet")
input_path    = enriched_path if os.path.exists(enriched_path) else scored_path
phase_source  = "C" if os.path.exists(enriched_path) else "B"

sections = gpd.read_parquet(input_path)
print(f"Loaded {len(sections):,} sections from Phase {phase_source} output")


# =============================================================================
# D1 -- FINAL SPEED SAFETY SCORE
# =============================================================================
print("\n" + "=" * 65)
print("STEP D1 -- FINAL SPEED SAFETY SCORE")
print("=" * 65)

benchmark    = sections.get("adjusted_benchmark_kmh", sections["base_benchmark_kmh"])
benchmark    = benchmark.clip(lower=1)
median_speed = sections["MedianSpeed"].clip(lower=1)

sections["final_severity"] = (median_speed / benchmark) ** POWER_MODEL_EXPONENT

# VRU weight: use VLM vru_activity refinement where available.
vru_weight = np.where(
    sections["LandUse"].str.upper() == "URBAN",
    VRU_WEIGHT_URBAN, VRU_WEIGHT_RURAL,
)
if "vru_activity" in sections.columns:
    vru_weight = np.where(
        sections["vru_activity"] == "frequent",
        vru_weight * 1.3, vru_weight,
    )

sections["final_exposure"] = 1 + (
    1 - sections["HelmetSPI"].fillna(sections["HelmetSPI"].mean())
) * vru_weight

forgiveness = sections.get(
    "forgivingness_index", pd.Series(0.5, index=sections.index)
)
sections["final_consequence"] = (2 - forgiveness).clip(lower=1.0, upper=2.0)

sections["final_score"]     = (
    sections["final_severity"] *
    sections["final_exposure"] *
    sections["final_consequence"]
).round(4)
sections["final_score_log"] = np.log10(
    sections["final_score"].clip(lower=1e-6)
).round(4)

print(f"Final Score summary:")
print(sections["final_score"].describe().round(3).to_string())

def _score_band(s):
    if s <= 0:      return "No Data"
    elif s < 1.5:   return "Low"
    elif s < 4.0:   return "Moderate"
    elif s < 10.0:  return "High"
    else:           return "Critical"
sections["final_score_band"] = sections["final_score"].apply(_score_band)
print(f"\nScore band breakdown:")
print(sections["final_score_band"].value_counts().sort_index().to_string())


# =============================================================================
# D2 -- ASSIGN INTERVENTION TYPE
# =============================================================================
print("\n" + "=" * 65)
print("STEP D2 -- INTERVENTION TYPE")
print("=" * 65)

sections["signal_A"] = (
    sections["SpeedLimit_num"] -
    sections.get("adjusted_benchmark_kmh", sections["base_benchmark_kmh"])
)
sections["signal_B"] = (
    sections["F85thPercentileSpeed"] - sections["SpeedLimit_num"]
)

def assign_intervention(row):
    A  = row["signal_A"]
    B  = row["signal_B"]
    vc = str(row.get("visual_speed_character", ""))
    if pd.isna(A) or pd.isna(B):
        return "insufficient_data"
    if A >= SIGNAL_A_THRESHOLD_KMH:
        return "lower_limit"
    if -5 <= A < SIGNAL_A_THRESHOLD_KMH:
        if B >= SIGNAL_B_THRESHOLD_KMH:
            return "traffic_calming" if vc in ("open", "motorway_like") else "enforcement"
        return "monitor"
    if A < -5 and B >= SIGNAL_B_THRESHOLD_KMH:
        return "enforcement_crisis"
    return "monitor"

sections["intervention_type"] = sections.apply(assign_intervention, axis=1)

STAR_UPLIFT = {
    "lower_limit":        "+1 star (limit reduction)",
    "traffic_calming":    "+1 to +2 stars (engineering)",
    "enforcement":        "+0.5 star (compliance)",
    "enforcement_crisis": "+1 star (combined response)",
    "monitor":            "no change",
    "insufficient_data":  "—",
}
sections["target_star_uplift"] = sections["intervention_type"].map(STAR_UPLIFT)

print(f"Intervention type distribution:")
print(sections["intervention_type"].value_counts().to_string())


# =============================================================================
# D3 -- SPATIAL OUTPUTS
# =============================================================================
print("\n" + "=" * 65)
print("STEP D3 -- SPATIAL OUTPUTS")
print("=" * 65)

map_data  = sections[sections["geometry"].notna()].copy()
centroids = map_data.geometry.centroid
map_center = [centroids.y.mean(), centroids.x.mean()]

score_log  = map_data["final_score_log"].dropna()
cmap_score = cm.LinearColormap(
    colors=["#1a9850", "#fee08b", "#d73027"],
    vmin=score_log.quantile(0.05),
    vmax=score_log.quantile(0.95),
    caption="Speed Safety Score (log10)",
)

INTERVENTION_COLORS = {
    "lower_limit":        "#d73027",
    "traffic_calming":    "#fc8d59",
    "enforcement":        "#fee08b",
    "enforcement_crisis": "#7b0000",
    "monitor":            "#1a9850",
    "insufficient_data":  "#aaaaaa",
}

# ── Output 1: Segment-level interactive map ───────────────────────────────────
m1 = folium.Map(location=map_center, zoom_start=ZOOM, tiles="CartoDB positron")
folium.TileLayer("CartoDB dark_matter", name="Dark Mode").add_to(m1)

score_fg = folium.FeatureGroup(name="Speed Safety Score", show=True)
sub = map_data[[
    "section_id", "final_score_log", "final_score",
    "MedianSpeed", "SpeedLimit_num", "base_benchmark_kmh",
    "intervention_type", "final_score_band", "geometry",
]].dropna(subset=["final_score_log"]).copy()
sub["_color"] = sub["final_score_log"].apply(lambda v: cmap_score(float(v)))

folium.GeoJson(
    sub.to_json(),
    style_function=lambda f: {
        "color":   f["properties"].get("_color", "#aaaaaa"),
        "weight":  2.5, "opacity": 0.85,
    },
    tooltip=folium.GeoJsonTooltip(
        fields=["section_id", "final_score", "MedianSpeed",
                "SpeedLimit_num", "base_benchmark_kmh", "intervention_type"],
        aliases=["Section", "Score", "Median Speed (km/h)",
                 "Posted Limit", "Benchmark", "Intervention"],
        sticky=True,
    ),
).add_to(score_fg)
score_fg.add_to(m1)
cmap_score.add_to(m1)

int_fg = folium.FeatureGroup(name="Intervention Type", show=False)
for itype, color in INTERVENTION_COLORS.items():
    sub_i = map_data[map_data["intervention_type"] == itype].copy()
    if sub_i.empty:
        continue
    folium.GeoJson(
        sub_i[["section_id", "intervention_type", "geometry"]].to_json(),
        name=itype,
        style_function=lambda f, c=color: {"color": c, "weight": 3, "opacity": 0.8},
        tooltip=folium.GeoJsonTooltip(
            fields=["section_id", "intervention_type"],
            aliases=["Section", "Intervention"],
        ),
    ).add_to(int_fg)
int_fg.add_to(m1)

folium.LayerControl(collapsed=False).add_to(m1)
map1_path = os.path.join(RESULTS_DIR, "map_segment_thailand.html")
m1.save(map1_path)
print(f"  [Saved] map_segment_thailand.html")

# ── Output 2: Province-level choropleth ───────────────────────────────────────
try:
    provinces = gpd.read_file(GPKG_PATH, layer=GPKG_HELM_LAYER)
    if provinces.crs != sections.crs:
        provinces = provinces.to_crs(sections.crs)

    # Spatial join: assign each section to a province by centroid.
    sections_pts = sections.copy()
    sections_pts.geometry = sections_pts.geometry.centroid
    joined = gpd.sjoin(
        sections_pts[["section_id", "final_score", "HelmetSPI",
                      "final_score_band", "geometry"]],
        provinces[[PROVINCE_NAME_COL, "geometry"]],
        how="left", predicate="within",
    ).drop_duplicates(subset="section_id")

    prov_agg = joined.groupby(PROVINCE_NAME_COL).agg(
        mean_score      = ("final_score",      "mean"),
        mean_helmet_spi = ("HelmetSPI",         "mean"),
        n_sections      = ("section_id",         "count"),
        pct_critical    = ("final_score_band",
                           lambda x: round(100 * (x == "Critical").mean(), 1)),
    ).reset_index()

    prov_geo = provinces[[PROVINCE_NAME_COL, "geometry"]].merge(
        prov_agg, on=PROVINCE_NAME_COL, how="left"
    )
    prov_geo["mean_score"] = prov_geo["mean_score"].fillna(0)

    # Save province aggregate CSV.
    prov_agg.to_csv(
        os.path.join(RESULTS_DIR, "province_aggregate_thailand.csv"), index=False
    )
    print(f"  [Saved] province_aggregate_thailand.csv")

    # Build choropleth map.
    m2 = folium.Map(location=map_center, zoom_start=ZOOM - 1, tiles="CartoDB positron")
    score_cmap2 = cm.LinearColormap(
        colors=["#1a9850", "#fee08b", "#d73027"],
        vmin=prov_geo["mean_score"].quantile(0.05),
        vmax=prov_geo["mean_score"].quantile(0.95),
        caption="Mean Speed Safety Score by Province",
    )

    folium.GeoJson(
        prov_geo[prov_geo["mean_score"] > 0].to_json(),
        style_function=lambda f: {
            "fillColor":   score_cmap2(float(f["properties"].get("mean_score") or 0)),
            "color":       "#444444",
            "weight":      0.8,
            "fillOpacity": 0.75,
        },
        tooltip=folium.GeoJsonTooltip(
            fields=[PROVINCE_NAME_COL, "mean_score", "mean_helmet_spi",
                    "n_sections", "pct_critical"],
            aliases=["Province", "Mean Score", "Mean Helmet SPI",
                     "Sections", "% Critical"],
            sticky=True,
        ),
    ).add_to(m2)
    score_cmap2.add_to(m2)
    folium.LayerControl().add_to(m2)
    map2_path = os.path.join(RESULTS_DIR, "map_aggregate_thailand.html")
    m2.save(map2_path)
    print(f"  [Saved] map_aggregate_thailand.html")

except Exception as e:
    print(f"  [WARN] Province choropleth skipped: {e}")
    prov_agg = pd.DataFrame()

# ── Output 3: Top-100 priority CSV with Power Model benefits ──────────────────
def power_model_reduction(row):
    v_op = row.get("MedianSpeed", 0)
    if pd.isna(v_op) or v_op <= 0:
        return None
    itype = row.get("intervention_type", "monitor")
    bench = row.get("adjusted_benchmark_kmh", row.get("base_benchmark_kmh", v_op))
    if itype == "lower_limit":
        v_post = bench
    elif itype == "traffic_calming":
        v_post = (v_op + bench) / 2
    elif itype in ("enforcement", "enforcement_crisis"):
        v_post = bench
    else:
        v_post = v_op
    return round(float((1 - (v_post / max(v_op, 1)) ** POWER_MODEL_EXPONENT) * 100), 2)

top100 = sections.nlargest(TOP_N_PRIORITY, "final_score").copy().reset_index(drop=True)
top100["rank"]            = top100.index + 1
top100["delta_fatal_pct"] = top100.apply(power_model_reduction, axis=1)
top100["google_maps_link"] = top100.apply(
    lambda r: f"https://www.google.com/maps?q={r['midpoint_lat']},{r['midpoint_lon']}",
    axis=1,
)

OUT_COLS = [
    "rank", "section_id", "RoadClass", "LandUse",
    "SpeedLimit_num", "MedianSpeed", "F85thPercentileSpeed",
    "base_benchmark_kmh", "HelmetSPI", "final_score",
    "intervention_type", "target_star_uplift", "delta_fatal_pct",
    "google_maps_link",
]
OUT_COLS = [c for c in OUT_COLS if c in top100.columns]
top100_path = os.path.join(RESULTS_DIR, "priority_top100_thailand.csv")
top100[OUT_COLS].to_csv(top100_path, index=False)
print(f"  [Saved] priority_top100_thailand.csv  ({len(top100)} sections)")
print(f"  Mean ΔFatal% : {top100['delta_fatal_pct'].mean():.1f}%")


# =============================================================================
# D4 -- COUNTRY COMPARISON
# =============================================================================
print("\n" + "=" * 65)
print("STEP D4 -- COUNTRY COMPARISON")
print("=" * 65)

HELMET_EXCEL = os.path.join(BASE_DIR, "Data", "Archive",
    "Road_Safety_Performance_Indicators_(Helmet_Wearing_results)_(adb_dashboard_data_v02).xlsx")

comparison_rows = []
for region_label in [REGION, "Maharashtra"]:
    try:
        h = pd.read_excel(HELMET_EXCEL)
    except Exception:
        print(f"  [WARN] Helmet Excel not found — skipping trend for {region_label}")
        continue

    h_yr = h[
        (h["Location"] == region_label) &
        (h["User"] == "All Riders") &
        (h["Year"] != "All")
    ].copy()
    h_yr["Year"] = pd.to_numeric(h_yr["Year"], errors="coerce")
    h_yr = h_yr.dropna(subset=["Year", "SPI"]).sort_values("Year")

    if len(h_yr) >= 2:
        from numpy.polynomial.polynomial import polyfit
        slope      = polyfit(h_yr["Year"], h_yr["SPI"], 1)[1]
        latest_spi = h_yr["SPI"].iloc[-1]
        vulnerability_index = float(latest_spi) * (1 + abs(float(slope)) * 5)
    else:
        slope = 0.0
        latest_spi = h_yr["SPI"].mean() if len(h_yr) else 0.5
        vulnerability_index = float(latest_spi)

    if region_label == REGION:
        mean_score = float(sections["final_score"].mean())
        n_sections = len(sections)
    else:
        mh_path = os.path.join(
            BASE_DIR, "results", "Analysis", "Analysisv2",
            "Maharashtra", "v2", "speed_safety_scores_maharashtra.parquet",
        )
        if os.path.exists(mh_path):
            mh = gpd.read_parquet(mh_path)
            mean_score = float(mh["final_score"].mean())
            n_sections = len(mh)
        else:
            mean_score, n_sections = None, None

    comparison_rows.append({
        "region":              region_label,
        "n_sections":          n_sections,
        "mean_final_score":    round(mean_score, 4) if mean_score else None,
        "latest_helmet_spi":   round(float(latest_spi), 3),
        "helmet_trend_slope":  round(float(slope), 5),
        "trend_direction":     ("Improving" if slope > 0.01
                                else ("Declining" if slope < -0.01 else "Stable")),
        "vulnerability_index": round(float(vulnerability_index), 3),
    })

if comparison_rows:
    comparison_df = pd.DataFrame(comparison_rows)
    comp_path = os.path.join(RESULTS_DIR, "country_comparison.csv")
    comparison_df.to_csv(comp_path, index=False)
    print(f"  [Saved] country_comparison.csv")
    print(comparison_df.to_string(index=False))


# =============================================================================
# SAVE FINAL SCORED GPKG + PARQUET
# =============================================================================
print("\n" + "=" * 65)
print("SAVING PHASE D OUTPUTS")
print("=" * 65)

for col in sections.select_dtypes(include="bool").columns:
    sections[col] = sections[col].astype(int)
for col in sections.select_dtypes(include="category").columns:
    sections[col] = sections[col].astype(str)

sections.to_file(
    os.path.join(RESULTS_DIR, "speed_safety_scores_thailand.gpkg"),
    driver="GPKG", layer="speed_safety_scores",
)
print(f"  [Saved] speed_safety_scores_thailand.gpkg  ({len(sections):,} sections)")

sections.to_parquet(
    os.path.join(RESULTS_DIR, "speed_safety_scores_thailand.parquet"), index=False
)
print(f"  [Saved] speed_safety_scores_thailand.parquet")

with open(os.path.join(RESULTS_DIR, "phase_d_manifest.json"), "w") as f:
    json.dump({
        "region":                       REGION,
        "phase":                        "D",
        "phase_source":                 phase_source,
        "sections_scored":              len(sections),
        "mean_final_score":             round(float(sections["final_score"].mean()), 4),
        "top100_mean_delta_fatal_pct":  round(float(top100["delta_fatal_pct"].mean()), 2),
        "intervention_counts":          sections["intervention_type"].value_counts().to_dict(),
    }, f, indent=2)
print(f"  [Saved] phase_d_manifest.json")

print(f"\nPhase D complete.  All deliverables saved to:\n  {RESULTS_DIR}")
