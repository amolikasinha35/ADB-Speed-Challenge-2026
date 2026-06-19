"""
config.py  --  Maharashtra  --  Analysisv2 / v2
================================================
Central parameter store for the Speed Safety Score pipeline.
All hard-coded values live here; no magic numbers in phase scripts.

Set API keys as environment variables before running Phase C:
  $env:GOOGLE_MAPS_API_KEY = "your_key_here"
  $env:GEMINI_API_KEY      = "your_key_here"
"""

import os

# =============================================================================
# REGION IDENTITY
# =============================================================================
REGION          = "Maharashtra"
SEGMENT_ID      = "DISSOLVE_ID"          # unique segment ID column in GeoPackage
GPKG_SEG_LAYER  = "OvertureNetwork_wResults"   # segment-level layer name
GPKG_HELM_LAYER = "Boundaries_4helmet"   # helmet SPI polygon layer name

# SPI column names inside the boundary polygon layer
SPI_ALL_COL  = "AllRidersSPI"
SPI_DRV_COL  = "DriverSPI"
SPI_PASS_COL = "PassengerSPI"

ZOOM = 7   # folium map default zoom

# =============================================================================
# API KEYS  (read from environment; never hard-code here)
# =============================================================================
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY", "")

# =============================================================================
# PHASE A  --  DATA PREPARATION
# =============================================================================

# Minimum probe sample size for a segment to be considered high-confidence.
N_VALID_THRESHOLD = 30

# Sections shorter than this are discarded after aggregation.
MIN_SECTION_LENGTH_M = 0

# Legal default speed limits (km/h) used when SpeedLimit is null or implausible.
# Key: (road_class_lowercase_substring, LANDUSE_UPPERCASE)
# The lookup uses substring matching so "primary" matches "primary", etc.
SPEED_DEFAULTS = {
    ("motorway", "URBAN"):    120,
    ("motorway", "RURAL"):    120,
    ("trunk",    "URBAN"):     70,
    ("trunk",    "RURAL"):    100,
    ("primary",  "URBAN"):     70,
    ("primary",  "RURAL"):    100,
    ("secondary","URBAN"):     50,
    ("secondary","RURAL"):     80,
    ("tertiary", "URBAN"):     40,
    ("tertiary", "RURAL"):     60,
    ("residential","URBAN"):   30,
    ("residential","RURAL"):   40,
    ("local",    "URBAN"):     30,
    ("local",    "RURAL"):     40,
}
SPEED_DEFAULT_FALLBACK = 60   # used when no class/landuse match found

# =============================================================================
# PHASE B  --  PRELIMINARY SCORING
# =============================================================================

# Safe System base benchmark speeds (km/h) by (road_class_lower, LANDUSE_UPPER).
# Source: WHO Safe System / iRAP methodology.
SAFE_SYSTEM_BENCHMARKS = {
    ("motorway",  "URBAN"): 80,
    ("motorway",  "RURAL"): 100,
    ("trunk",     "URBAN"): 50,
    ("trunk",     "RURAL"): 70,
    ("primary",   "URBAN"): 50,
    ("primary",   "RURAL"): 70,
    ("secondary", "URBAN"): 50,
    ("secondary", "RURAL"): 60,
    ("tertiary",  "URBAN"): 40,
    ("tertiary",  "RURAL"): 50,
    ("residential","URBAN"):30,
    ("residential","RURAL"):40,
    ("local",     "URBAN"): 30,
    ("local",     "RURAL"): 40,
}
BENCHMARK_FALLBACK_URBAN = 50
BENCHMARK_FALLBACK_RURAL = 60

# Vulnerable road user (VRU) exposure weights used in the Exposure component.
VRU_WEIGHT_URBAN = 1.5
VRU_WEIGHT_RURAL = 0.8

# Default Consequence value before VLM enrichment (Phase C).
CONSEQUENCE_DEFAULT = 1.5

# Nilsson's Power Model exponent for fatal crashes.
POWER_MODEL_EXPONENT = 4

# Imagery sample sizes for Phase C.
IMAGERY_PRIORITY_SAMPLE    = 5000
IMAGERY_CALIBRATION_SAMPLE = 2000

# =============================================================================
# PHASE C  --  VLM ENRICHMENT
# =============================================================================

# Sections with mean VLM confidence below this retain Phase B values.
VLM_CONFIDENCE_THRESHOLD = 0.5

# Maximum cumulative benchmark adjustment from VLM (km/h, applied as ±cap).
BENCHMARK_ADJUSTMENT_CAP_KMH = 20

# Per-attribute thresholds for including an attribute in the pipeline.
AGREEMENT_RATE_THRESHOLD     = 0.70   # min cross-validation agreement vs existing data
STABILITY_FLIP_RATE_THRESHOLD = 0.20  # max flip rate between two Gemini runs

# VLM benchmark adjustments (km/h) per extracted attribute value.
# Positive = road can safely sustain higher speed; Negative = reduce benchmark.
VLM_ADJUSTMENTS = {
    ("median_type",          "rigid_or_wide"):  +10,
    ("carriageway_division", "dual"):           +5,
    ("vru_activity",         "frequent"):       -15,
    ("vru_activity",         "occasional"):      -7,
    ("roadside_development", "ribbon"):         -10,
    ("roadside_development", "dense"):          -15,
    ("intersection_density", "multiple"):       -10,
    ("intersection_density", "one"):             -5,
    ("calming_features",     "strong"):          -5,
}

# Forgivingness index weights (Group B attributes).
FORGIVENESS_WEIGHTS = {
    "roadside_hazard": 0.4,
    "roadside_barrier": 0.3,
    "shoulder": 0.2,
    "surface_condition": 0.1,
}
# Score mapping: {attribute: {value: score_0_to_1}}
FORGIVENESS_SCORES = {
    "roadside_hazard":  {"clear": 1.0, "minor": 0.5, "severe": 0.0},
    "roadside_barrier": {"wire_rope": 1.0, "rigid": 0.5, "none": 0.0},
    "shoulder":         {"sealed": 1.0, "unsealed": 0.5, "none": 0.0},
    "surface_condition":{"good": 1.0, "fair": 0.5, "poor": 0.0},
}

# Number of concurrent Gemini API requests.
VLM_CONCURRENCY = 10

# Street View image parameters.
SV_SIZE    = "640x640"
SV_FOV     = 90
SV_PITCH   = 0

# =============================================================================
# PHASE D  --  FINAL SCORING AND DELIVERABLES
# =============================================================================

# Signal A threshold: SpeedLimit - adjusted_benchmark gap that triggers lower_limit.
SIGNAL_A_THRESHOLD_KMH = 15

# Signal B threshold: F85 - SpeedLimit gap that triggers calming or enforcement.
SIGNAL_B_THRESHOLD_KMH = 15

# Number of top priority sections to include in the final CSV output.
TOP_N_PRIORITY = 100
