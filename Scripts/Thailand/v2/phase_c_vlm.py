#!/usr/bin/env python3
"""
phase_c_vlm.py  --  Phase C: VLM Enrichment  --  Thailand  --  v2
===================================================================
Fetches Google Street View imagery for sampled sections and uses
Gemini multimodal inference to extract road infrastructure attributes.
Validated attributes adjust Safe System benchmarks and compute a
forgivingness index that refines the Consequence component.

REQUIRES ENVIRONMENT VARIABLES (auto-loaded from ~/.env if present)
--------------------------------------------------------------------
  GOOGLE_MAPS_API_KEY = "AIza..."
  GEMINI_API_KEY      = "AQ.Ab8..."

Steps
-----
  C1  Fetch Street View images concurrently (20 workers).
  C2  Run Gemini 2.5 Flash extraction concurrently (VLM_CONCURRENCY workers).
  C3  Validate VLM outputs (cross-validation, consistency, stability).
  C4  Compute adjusted_benchmark_kmh and forgivingness_index per section.

Outputs  -->  results/Analysis/Analysisv2/Thailand/v2/
------------------------------------------------------
  images/                            Downloaded .jpg files
  gsv_image_locations_thailand.csv   Image name, Lat, Long
  imagery_metadata.csv               Full fetch status log
  vlm_extractions.parquet            Parsed Gemini outputs
  vlm_validation_report.csv         Per-attribute reliability
  sections_enriched_thailand.gpkg
  sections_enriched_thailand.parquet
  phase_c_manifest.json
"""

import subprocess, sys, os, warnings, json, time, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
warnings.filterwarnings("ignore")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── Load API keys from ~/.env ────────────────────────────────────────────────
_dotenv = os.path.join(os.path.expanduser("~"), ".env")
if os.path.exists(_dotenv):
    with open(_dotenv) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ[_k.strip()] = _v.strip().strip('"').strip("'")

# ── Install dependencies ─────────────────────────────────────────────────────
print("Installing / verifying Python dependencies ...")
subprocess.check_call(
    [sys.executable, "-m", "pip", "install",
     "geopandas", "pandas", "numpy", "pyarrow",
     "requests", "google-generativeai", "Pillow"],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
print("Dependencies ready.\n")

import geopandas as gpd
import pandas as pd
import numpy as np
import requests
import google.generativeai as genai
from PIL import Image

# ── Paths and config ─────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from config import (
    REGION, GOOGLE_MAPS_API_KEY, GEMINI_API_KEY,
    VLM_ADJUSTMENTS, FORGIVENESS_WEIGHTS, FORGIVENESS_SCORES,
    VLM_CONFIDENCE_THRESHOLD, BENCHMARK_ADJUSTMENT_CAP_KMH,
    AGREEMENT_RATE_THRESHOLD, STABILITY_FLIP_RATE_THRESHOLD,
    VLM_CONCURRENCY, SV_SIZE, SV_FOV, SV_PITCH,
)

BASE_DIR    = os.path.dirname(os.path.dirname(os.path.dirname(
              os.path.dirname(os.path.dirname(SCRIPT_DIR)))))
RESULTS_DIR = os.path.join(BASE_DIR, "results", "Analysis", "Analysisv2", "Thailand", "v2")
IMAGES_DIR  = os.path.join(RESULTS_DIR, "images")
VLM_DIR     = os.path.join(RESULTS_DIR, "vlm_raw")
os.makedirs(IMAGES_DIR, exist_ok=True)
os.makedirs(VLM_DIR, exist_ok=True)

# ── Check API keys ───────────────────────────────────────────────────────────
if not GOOGLE_MAPS_API_KEY:
    print("ERROR: GOOGLE_MAPS_API_KEY not set.  Add it to ~/.env")
    sys.exit(1)
if not GEMINI_API_KEY:
    print("ERROR: GEMINI_API_KEY not set.  Add it to ~/.env")
    sys.exit(1)
print(f"[OK] API keys loaded  |  Region: {REGION}")
print(f"     Results dir : {RESULTS_DIR}\n")

genai.configure(api_key=GEMINI_API_KEY)

# ── VLM prompt (iRAP rubric) ─────────────────────────────────────────────────
VLM_PROMPT = """You are a road safety auditor trained in iRAP methodology.

Given a Google Street View image of a road segment, classify
each attribute below using ONLY the categories provided. For each
attribute, return both the category and a confidence value 0.0-1.0
reflecting how clearly you can see it.

Return strict JSON with this schema:
{
  "median_type": {"value": "none|painted|flexible|rigid_or_wide", "confidence": <float>},
  "carriageway_division": {"value": "undivided|single_divided|dual", "confidence": <float>},
  "roadside_development": {"value": "open|scattered|ribbon|dense", "confidence": <float>},
  "vru_activity": {"value": "none|occasional|frequent", "confidence": <float>},
  "intersection_density": {"value": "none|one|multiple", "confidence": <float>},
  "land_use": {"value": "rural_open|rural_fringe|peri_urban|urban_built", "confidence": <float>},
  "roadside_hazard": {"value": "clear|minor|severe", "confidence": <float>},
  "roadside_barrier": {"value": "none|rigid|wire_rope", "confidence": <float>},
  "shoulder": {"value": "none|unsealed|sealed", "confidence": <float>},
  "surface_condition": {"value": "poor|fair|good", "confidence": <float>},
  "visual_speed_character": {"value": "constrained|moderate|open|motorway_like", "confidence": <float>},
  "calming_features": {"value": "none|minor|strong", "confidence": <float>},
  "image_usable": <true|false>,
  "image_notes": "<one short sentence>"
}

Rubric:
- median_type rigid_or_wide: concrete barrier OR median wider than 4m
- roadside_hazard severe: trees, walls, deep drops, rigid poles within ~5m of edge
- visual_speed_character: what speed does this road feel like to drive,
  ignoring any signs? constrained = forces slow; motorway_like = invites high speed
- If you cannot see an attribute, return confidence < 0.3"""

VLM_ATTRIBUTES = [
    "median_type", "carriageway_division", "roadside_development",
    "vru_activity", "intersection_density", "land_use",
    "roadside_hazard", "roadside_barrier", "shoulder",
    "surface_condition", "visual_speed_character", "calming_features",
]

SV_META_URL  = "https://maps.googleapis.com/maps/api/streetview/metadata"
SV_IMAGE_URL = "https://maps.googleapis.com/maps/api/streetview"
SV_WORKERS   = 20

import re as _re
_UNSAFE = _re.compile(r'[/\\:*?"<>|]')
def _to_fname(sid): return _UNSAFE.sub('_', str(sid))

pipeline_start = time.time()


# =============================================================================
# C1 -- FETCH STREET VIEW IMAGES  (concurrent, 20 workers)
# =============================================================================
print("=" * 65)
print("STEP C1 -- FETCH STREET VIEW IMAGES")
print("=" * 65)
c1_start = time.time()

sample_path = os.path.join(RESULTS_DIR, "imagery_sample.csv")
if not os.path.exists(sample_path):
    print(f"ERROR: imagery_sample.csv not found.  Run Phase B first.")
    sys.exit(1)

sample         = pd.read_csv(sample_path)
total_sections = len(sample)
PRINT_EVERY_C1 = max(1, total_sections // 20)

print(f"  Sections   : {total_sections:,}")
print(f"  Workers    : {SV_WORKERS}  (concurrent HTTP)")
print(f"  Progress   : every ~5%  ({PRINT_EVERY_C1} sections)\n")

_lock      = threading.Lock()
_meta_recs = []
_gsv_rows  = []
_c1_cnt    = {"downloaded": 0, "cached": 0, "no_coverage": 0, "errors": 0}


def _fetch_one(args):
    _, row    = args
    sid       = row["section_id"]
    lat       = row["midpoint_lat"]
    lon       = row["midpoint_lon"]
    img_name  = f"{_to_fname(sid)}.jpg"
    img_path  = os.path.join(IMAGES_DIR, img_name)

    def _record(status, date="", pano=""):
        with _lock:
            _meta_recs.append({"section_id": sid, "status": status,
                                "image_date": date, "pano_id": pano,
                                "lat": lat, "lon": lon})

    if os.path.exists(img_path):
        _record("cached")
        with _lock:
            _c1_cnt["cached"] += 1
            _gsv_rows.append({"image_name": img_name, "lat": lat, "lon": lon,
                               "status": "cached"})
        return

    try:
        meta = requests.get(SV_META_URL,
                            params={"location": f"{lat},{lon}", "key": GOOGLE_MAPS_API_KEY},
                            timeout=10).json()
    except Exception:
        _record("metadata_error")
        with _lock:
            _c1_cnt["errors"] += 1
        return

    if meta.get("status") != "OK":
        _record("no_coverage")
        with _lock:
            _c1_cnt["no_coverage"] += 1
        return

    try:
        resp = requests.get(SV_IMAGE_URL,
                            params={"location": f"{lat},{lon}",
                                    "heading": row.get("bearing_deg", 0),
                                    "size": SV_SIZE, "fov": SV_FOV,
                                    "pitch": SV_PITCH, "key": GOOGLE_MAPS_API_KEY},
                            timeout=15)
    except Exception:
        _record("fetch_error")
        with _lock:
            _c1_cnt["errors"] += 1
        return

    if resp.status_code == 200:
        with open(img_path, "wb") as f:
            f.write(resp.content)
        _record("ok", meta.get("date", ""), meta.get("pano_id", ""))
        with _lock:
            _c1_cnt["downloaded"] += 1
            _gsv_rows.append({"image_name": img_name, "lat": lat, "lon": lon,
                               "status": "downloaded"})
    else:
        _record(f"http_{resp.status_code}")
        with _lock:
            _c1_cnt["errors"] += 1


done_c1 = 0
with ThreadPoolExecutor(max_workers=SV_WORKERS) as ex:
    futs = {ex.submit(_fetch_one, item): item for item in sample.iterrows()}
    for fut in as_completed(futs):
        fut.result()
        done_c1 += 1
        if done_c1 % PRINT_EVERY_C1 == 0 or done_c1 == total_sections:
            c = _c1_cnt
            print(f"  [{done_c1:>5}/{total_sections}  {100*done_c1//total_sections:3d}%]  "
                  f"downloaded={c['downloaded']}  cached={c['cached']}  "
                  f"no_coverage={c['no_coverage']}  errors={c['errors']}")

meta_df    = pd.DataFrame(_meta_recs)
gsv_loc_df = pd.DataFrame(_gsv_rows)
meta_df.to_csv(os.path.join(RESULTS_DIR, "imagery_metadata.csv"), index=False)
gsv_loc_df.to_csv(os.path.join(RESULTS_DIR, "gsv_image_locations_thailand.csv"), index=False)

c1_elapsed = time.time() - c1_start
c = _c1_cnt
print(f"\n  C1 done  {c1_elapsed:.1f}s ({c1_elapsed/60:.1f} min)  |  "
      f"downloaded={c['downloaded']}  cached={c['cached']}  "
      f"no_coverage={c['no_coverage']}  errors={c['errors']}")
print(f"  [Saved] imagery_metadata.csv  "
      f"|  gsv_image_locations_thailand.csv  ({len(gsv_loc_df):,} rows)")


# =============================================================================
# C2 -- GEMINI VLM EXTRACTION  (concurrent, VLM_CONCURRENCY workers)
# =============================================================================
print("\n" + "=" * 65)
print("STEP C2 -- GEMINI VLM EXTRACTION  (gemini-2.5-flash)")
print("=" * 65)
c2_start = time.time()

model = genai.GenerativeModel(
    model_name="gemini-2.5-flash",
    generation_config={"response_mime_type": "application/json", "temperature": 0.2},
)

valid_ids      = meta_df[meta_df["status"].isin(["ok", "cached"])]["section_id"].tolist()
total_vlm      = len(valid_ids)
PRINT_EVERY_C2 = max(1, total_vlm // 20)

print(f"  Images to extract : {total_vlm:,}")
print(f"  Workers           : {VLM_CONCURRENCY}  (concurrent Gemini calls)")
print(f"  Retry backoff     : up to 4 attempts on rate-limit (429)")
print(f"  Progress          : every ~5%  ({PRINT_EVERY_C2} images)\n")

_extraction_rows = []
_failed          = []
_c2_cnt          = {"extracted": 0, "cached": 0, "failed": 0, "missing": 0}
_write_lock      = threading.Lock()


def _parse_raw(raw):
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    return json.loads(raw)


def _gemini_with_retry(img, max_retries=4):
    for attempt in range(max_retries):
        try:
            return model.generate_content([VLM_PROMPT, img],
                                            request_options={"timeout": 90}).text
        except Exception as e:
            msg = str(e).lower()
            if ("429" in msg or "quota" in msg or "rate" in msg) and attempt < max_retries - 1:
                time.sleep((2 ** attempt) * 5)  # 5s → 10s → 20s → 40s
            else:
                raise


def _extract_one(sid):
    safe       = _to_fname(sid)
    cache_path = os.path.join(VLM_DIR, f"{safe}.json")
    img_path   = os.path.join(IMAGES_DIR, f"{safe}.jpg")

    if os.path.exists(cache_path):
        try:
            with open(cache_path) as f:
                return sid, json.load(f), "cached"
        except (json.JSONDecodeError, ValueError):
            os.remove(cache_path)  # corrupted cache — delete and re-extract

    if not os.path.exists(img_path):
        return sid, None, "missing"

    try:
        img    = Image.open(img_path)
        parsed = _parse_raw(_gemini_with_retry(img))
        with _write_lock:
            with open(cache_path, "w") as f:
                json.dump(parsed, f)
        return sid, parsed, "ok"
    except Exception as e:
        return sid, str(e), "error"


done_c2 = 0
with ThreadPoolExecutor(max_workers=VLM_CONCURRENCY) as ex:
    futs = {ex.submit(_extract_one, sid): sid for sid in valid_ids}
    for fut in as_completed(futs):
        done_c2 += 1
        sid, result, status = fut.result()

        if status in ("ok", "cached"):
            parsed = result
            _c2_cnt["cached" if status == "cached" else "extracted"] += 1
            if parsed.get("image_usable", True):
                row_data = {"section_id": sid}
                for attr in VLM_ATTRIBUTES:
                    d = parsed.get(attr, {})
                    row_data[f"{attr}_value"]      = d.get("value")
                    row_data[f"{attr}_confidence"] = float(d.get("confidence", 0.0))
                row_data["image_notes"] = parsed.get("image_notes", "")
                _extraction_rows.append(row_data)
        elif status == "missing":
            _c2_cnt["missing"] += 1
            _failed.append({"section_id": sid, "error": "image_file_missing"})
        else:
            _c2_cnt["failed"] += 1
            _failed.append({"section_id": sid, "error": result})

        if done_c2 % PRINT_EVERY_C2 == 0 or done_c2 == total_vlm:
            c = _c2_cnt
            print(f"  [{done_c2:>5}/{total_vlm}  {100*done_c2//total_vlm:3d}%]  "
                  f"extracted={c['extracted']}  cached={c['cached']}  "
                  f"failed={c['failed']}  missing={c['missing']}")

extractions = pd.DataFrame(_extraction_rows)
extractions.to_parquet(os.path.join(RESULTS_DIR, "vlm_extractions.parquet"), index=False)
if _failed:
    pd.DataFrame(_failed).to_csv(os.path.join(RESULTS_DIR, "vlm_failures.csv"), index=False)

c2_elapsed = time.time() - c2_start
c = _c2_cnt
print(f"\n  C2 done  {c2_elapsed:.1f}s ({c2_elapsed/60:.1f} min)  |  "
      f"extracted={c['extracted']}  cached={c['cached']}  "
      f"failed={c['failed']}  missing={c['missing']}")
print(f"  [Saved] vlm_extractions.parquet  ({len(extractions):,} rows)")
if _failed:
    print(f"  [Saved] vlm_failures.csv  ({len(_failed):,} rows)")


# =============================================================================
# C3 -- VALIDATE VLM OUTPUTS
# =============================================================================
print("\n" + "=" * 65)
print("STEP C3 -- VALIDATE VLM OUTPUTS")
print("=" * 65)
c3_start = time.time()

sections = gpd.read_parquet(
    os.path.join(RESULTS_DIR, "sections_scored_thailand.parquet")
)
merged = extractions.merge(
    sections[["section_id", "RoadClass", "LandUse"]], on="section_id", how="left"
)
print(f"  Sections: {len(sections):,}  |  VLM rows: {len(extractions):,}  "
      f"|  Merged: {len(merged):,}\n")
print(f"  {'Attribute':<30} {'Conf':>6}  {'Agree':>6}  {'FlipP':>6}  Status")
print(f"  {'-'*65}")

validation_rows = []
for attr in VLM_ATTRIBUTES:
    val_col  = f"{attr}_value"
    conf_col = f"{attr}_confidence"
    if val_col not in extractions.columns:
        continue

    mean_conf = extractions[conf_col].mean() if conf_col in extractions.columns else 0.0
    agreement = None

    if attr == "visual_speed_character":
        mw = merged[merged[val_col].notna()].copy()
        mw["vlm_high"] = mw[val_col].isin(["open", "motorway_like"])
        mw["ref_high"] = mw["RoadClass"].str.lower().isin(["motorway", "trunk"])
        agreement = float((mw["vlm_high"] == mw["ref_high"]).mean())
    elif attr == "land_use":
        mw = merged[merged[val_col].notna()].copy()
        mw["vlm_urban"] = mw[val_col].isin(["peri_urban", "urban_built"])
        mw["ref_urban"] = mw["LandUse"].str.upper() == "URBAN"
        agreement = float((mw["vlm_urban"] == mw["ref_urban"]).mean())

    flip_rate = max(0.0, 1.0 - mean_conf)
    included  = (
        (agreement is None or agreement >= AGREEMENT_RATE_THRESHOLD) and
        flip_rate <= STABILITY_FLIP_RATE_THRESHOLD and
        mean_conf >= 0.3
    )
    agree_str = f"{agreement:.3f}" if agreement is not None else "  n/a"
    print(f"  {attr:<30} {mean_conf:>6.3f}  {agree_str:>6}  "
          f"{flip_rate:>6.3f}  {'INCLUDED' if included else 'EXCLUDED'}")

    validation_rows.append({
        "attribute":             attr,
        "n_extracted":           int(extractions[val_col].notna().sum()),
        "mean_confidence":       round(float(mean_conf), 3),
        "agreement_rate":        round(agreement, 3) if agreement is not None else None,
        "flip_rate_proxy":       round(flip_rate, 3),
        "included_in_pipeline":  included,
    })

validation_df  = pd.DataFrame(validation_rows)
validation_df.to_csv(os.path.join(RESULTS_DIR, "vlm_validation_report.csv"), index=False)
included_attrs = validation_df[validation_df["included_in_pipeline"]]["attribute"].tolist()
included_set   = set(included_attrs)

c3_elapsed = time.time() - c3_start
print(f"\n  C3 done  {c3_elapsed:.1f}s  |  "
      f"included {len(included_attrs)}/{len(VLM_ATTRIBUTES)} attributes: "
      f"{', '.join(included_attrs)}")
print(f"  [Saved] vlm_validation_report.csv")


# =============================================================================
# C4 -- COMPUTE VLM-DERIVED COLUMNS
# =============================================================================
print("\n" + "=" * 65)
print("STEP C4 -- COMPUTE VLM-DERIVED COLUMNS")
print("=" * 65)
c4_start = time.time()


def compute_benchmark_adjustment(row):
    total = 0.0
    for (attr, value), delta in VLM_ADJUSTMENTS.items():
        if attr not in included_set:
            continue
        if str(row.get(f"{attr}_value")) == value:
            total += delta * float(row.get(f"{attr}_confidence", 0.0))
    return np.clip(total, -BENCHMARK_ADJUSTMENT_CAP_KMH, BENCHMARK_ADJUSTMENT_CAP_KMH)


def compute_forgivingness(row):
    score, tw = 0.0, 0.0
    for attr, w in FORGIVENESS_WEIGHTS.items():
        conf = float(row.get(f"{attr}_confidence", 0.0))
        if conf < 0.3:
            continue
        score += FORGIVENESS_SCORES.get(attr, {}).get(
            str(row.get(f"{attr}_value", "")), 0.5) * w
        tw += w
    return round(score / tw, 4) if tw > 0 else 0.5


extractions["benchmark_adjustment"] = extractions.apply(compute_benchmark_adjustment, axis=1)
extractions["forgivingness_index"]  = extractions.apply(compute_forgivingness, axis=1)
extractions["vlm_confidence"] = extractions[
    [f"{a}_confidence" for a in included_set
     if f"{a}_confidence" in extractions.columns]
].mean(axis=1)
if "visual_speed_character_value" in extractions.columns:
    extractions["visual_speed_character"] = extractions["visual_speed_character_value"]

vlm_cols = [c for c in ["section_id", "benchmark_adjustment", "forgivingness_index",
                          "vlm_confidence", "visual_speed_character"]
            if c in extractions.columns]
sections = sections.merge(extractions[vlm_cols], on="section_id", how="left")

low_conf = (
    sections["vlm_confidence"].isna() |
    (sections["vlm_confidence"] < VLM_CONFIDENCE_THRESHOLD)
)
sections["adjusted_benchmark_kmh"] = sections["base_benchmark_kmh"].astype(float)
sections.loc[~low_conf, "adjusted_benchmark_kmh"] = (
    sections.loc[~low_conf, "base_benchmark_kmh"] +
    sections.loc[~low_conf, "benchmark_adjustment"].fillna(0)
).clip(
    lower=sections.loc[~low_conf, "base_benchmark_kmh"] - BENCHMARK_ADJUSTMENT_CAP_KMH,
    upper=sections.loc[~low_conf, "base_benchmark_kmh"] + BENCHMARK_ADJUSTMENT_CAP_KMH,
)
sections["forgivingness_index"] = sections["forgivingness_index"].fillna(0.5)
sections["vlm_enriched"]        = (~low_conf).astype(int)
enriched_n = sections["vlm_enriched"].sum()

c4_elapsed = time.time() - c4_start
print(f"  Enriched : {enriched_n:,} / {len(sections):,} sections  "
      f"({100*enriched_n/len(sections):.1f}%)")
print(f"  Mean benchmark adjustment : "
      f"{sections.loc[sections['vlm_enriched']==1,'benchmark_adjustment'].mean():.2f} km/h")
print(f"  Mean forgivingness index  : "
      f"{sections['forgivingness_index'].mean():.3f}  (0=worst, 1=best)")
print(f"  C4 done  {c4_elapsed:.1f}s")


# =============================================================================
# SAVE OUTPUTS
# =============================================================================
print("\n" + "=" * 65)
print("SAVING PHASE C OUTPUTS")
print("=" * 65)

for col in sections.select_dtypes(include="bool").columns:
    sections[col] = sections[col].astype(int)
for col in sections.select_dtypes(include="category").columns:
    sections[col] = sections[col].astype(str)

sections.to_file(
    os.path.join(RESULTS_DIR, "sections_enriched_thailand.gpkg"),
    driver="GPKG", layer="sections_enriched",
)
print(f"  [Saved] sections_enriched_thailand.gpkg  ({len(sections):,} sections)")

sections.to_parquet(
    os.path.join(RESULTS_DIR, "sections_enriched_thailand.parquet"), index=False
)
print(f"  [Saved] sections_enriched_thailand.parquet")

with open(os.path.join(RESULTS_DIR, "phase_c_manifest.json"), "w") as f:
    json.dump({
        "region":                REGION, "phase": "C",
        "images_downloaded":     _c1_cnt["downloaded"],
        "images_cached":         _c1_cnt["cached"],
        "images_no_coverage":    _c1_cnt["no_coverage"],
        "images_errors":         _c1_cnt["errors"],
        "vlm_extracted":         _c2_cnt["extracted"],
        "vlm_cached":            _c2_cnt["cached"],
        "vlm_failed":            _c2_cnt["failed"],
        "vlm_missing":           _c2_cnt["missing"],
        "attrs_included":        len(included_attrs),
        "sections_enriched":     int(enriched_n),
        "gsv_location_csv_rows": len(gsv_loc_df),
    }, f, indent=2)
print(f"  [Saved] phase_c_manifest.json")

total_elapsed = time.time() - pipeline_start
print(f"\n{'='*65}")
print(f"PHASE C COMPLETE  --  TIMING")
print(f"{'='*65}")
print(f"  C1  Street View fetch  : {c1_elapsed:>7.1f}s  ({c1_elapsed/60:.1f} min)")
print(f"  C2  Gemini extraction  : {c2_elapsed:>7.1f}s  ({c2_elapsed/60:.1f} min)")
print(f"  C3  Validation         : {c3_elapsed:>7.1f}s")
print(f"  C4  Benchmark adjust   : {c4_elapsed:>7.1f}s")
print(f"  ───────────────────────────────────")
print(f"  Total                  : {total_elapsed:>7.1f}s  ({total_elapsed/60:.1f} min)")
print(f"\nOutputs: {RESULTS_DIR}")
