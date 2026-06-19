"""
config.py  --  Thailand  --  Analysisv2 / v2
=============================================
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
REGION          = "Thailand"
SEGMENT_ID      = "OvertureID"
GPKG_SEG_LAYER  = "ADB_Results_D4"
GPKG_HELM_LAYER = "Thailand_Province_Boundaries"

# Province boundary column names
PROVINCE_JOIN_COL = "ADMIN_ID1"         # join key against ProvinceID in segments
SPI_ALL_COL       = "overall_helmet_use_pct"
SPI_DRV_COL       = "driver_helmet_use_pct"
SPI_PASS_COL      = "passenger_helmet_use_pct"
PROVINCE_INCLUDE_COL = "INCLUDE"        # Y = valid, N/X = excluded
PROVINCE_NAME_COL    = "NAME_ENG1"

ZOOM = 6   # Thailand is larger; zoom out one level

# =============================================================================
# API KEYS  (read from environment; never hard-code here)
# =============================================================================
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "")
GEMINI_API_KEY      = os.getenv("GEMINI_API_KEY", "")

# =============================================================================
# PHASE A  --  DATA PREPARATION
# =============================================================================

N_VALID_THRESHOLD    = 30
MIN_SECTION_LENGTH_M = 0

# Legal default speed limits (km/h) for Thailand.
SPEED_DEFAULTS = {
    ("motorway", "URBAN"):    120,
    ("motorway", "RURAL"):    120,
    ("trunk",    "URBAN"):     80,
    ("trunk",    "RURAL"):     90,
    ("primary",  "URBAN"):     80,
    ("primary",  "RURAL"):     90,
    ("secondary","URBAN"):     60,
    ("secondary","RURAL"):     80,
    ("tertiary", "URBAN"):     50,
    ("tertiary", "RURAL"):     60,
    ("residential","URBAN"):   30,
    ("residential","RURAL"):   40,
    ("local",    "URBAN"):     30,
    ("local",    "RURAL"):     40,
}
SPEED_DEFAULT_FALLBACK = 60

# =============================================================================
# PHASE B  --  PRELIMINARY SCORING
# =============================================================================

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

VRU_WEIGHT_URBAN      = 1.5
VRU_WEIGHT_RURAL      = 0.8
CONSEQUENCE_DEFAULT   = 1.5
POWER_MODEL_EXPONENT  = 4

IMAGERY_PRIORITY_SAMPLE    = 5000
IMAGERY_CALIBRATION_SAMPLE = 2000

# =============================================================================
# PHASE C  --  VLM ENRICHMENT
# =============================================================================

VLM_CONFIDENCE_THRESHOLD      = 0.5
BENCHMARK_ADJUSTMENT_CAP_KMH  = 20
AGREEMENT_RATE_THRESHOLD      = 0.70
STABILITY_FLIP_RATE_THRESHOLD = 0.20

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

FORGIVENESS_WEIGHTS = {
    "roadside_hazard": 0.4,
    "roadside_barrier": 0.3,
    "shoulder": 0.2,
    "surface_condition": 0.1,
}
FORGIVENESS_SCORES = {
    "roadside_hazard":  {"clear": 1.0, "minor": 0.5, "severe": 0.0},
    "roadside_barrier": {"wire_rope": 1.0, "rigid": 0.5, "none": 0.0},
    "shoulder":         {"sealed": 1.0, "unsealed": 0.5, "none": 0.0},
    "surface_condition":{"good": 1.0, "fair": 0.5, "poor": 0.0},
}

VLM_CONCURRENCY = 10
SV_SIZE  = "640x640"
SV_FOV   = 90
SV_PITCH = 0

# =============================================================================
# PHASE D  --  FINAL SCORING AND DELIVERABLES
# =============================================================================

SIGNAL_A_THRESHOLD_KMH = 15
SIGNAL_B_THRESHOLD_KMH = 15
TOP_N_PRIORITY         = 100
