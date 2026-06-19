#!/usr/bin/env python3
"""
check_apis.py  --  Quick API key connectivity check
====================================================
Reads API keys from ~/.env (outside OneDrive, never synced),
then runs a minimal live call to each to confirm they are valid.

~/.env format:
  GEMINI_API_KEY=AQ.Ab8...
  GOOGLE_MAPS_API_KEY=AIza...

Usage:
  python script/check_apis.py
"""

import json, os, sys, requests

CONFIG_PATH = os.path.join(os.path.expanduser("~"), ".claude-code-router", "config.json")
DOTENV_PATH = os.path.join(os.path.expanduser("~"), ".env")

# Load .env from home folder if present (keys not stored in OneDrive)
if os.path.exists(DOTENV_PATH):
    with open(DOTENV_PATH) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ[k.strip()] = v.strip().strip('"').strip("'")
    print(f"Loaded env vars from: {DOTENV_PATH}\n")

PASS = "[OK  ]"
FAIL = "[FAIL]"

# =============================================================================
# 1. Load Gemini key from claude-code-router config.json
# =============================================================================
print("=" * 55)
print("1. Reading claude-code-router config.json")
print("=" * 55)

gemini_key = None
if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH) as f:
        cfg = json.load(f)
    for provider in cfg.get("Providers", []):
        if provider.get("name") == "gemini":
            gemini_key = provider.get("api_key", "")
            print(f"  Found Gemini key : {gemini_key[:8]}...{gemini_key[-4:]}")
            break
    if not gemini_key:
        print(f"  {FAIL} No 'gemini' provider found in config.")
else:
    print(f"  {FAIL} Config not found at: {CONFIG_PATH}")

# Also check if GEMINI_API_KEY env var is set (used by pipeline Phase C)
env_gemini = os.getenv("GEMINI_API_KEY", "")
if env_gemini:
    print(f"  Env GEMINI_API_KEY also set: {env_gemini[:8]}...{env_gemini[-4:]}")
else:
    print(f"  Note: GEMINI_API_KEY env var not set (needed for pipeline Phase C).")

# =============================================================================
# 2. Test Gemini API  (lightweight models/list call)
# =============================================================================
print("\n" + "=" * 55)
print("2. Testing Gemini API")
print("=" * 55)

key_to_test = gemini_key or env_gemini
if not key_to_test:
    print(f"  {FAIL} No Gemini key available to test.")
else:
    try:
        resp = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            params={"key": key_to_test},
            timeout=10,
        )
        if resp.status_code == 200:
            models = [m["name"] for m in resp.json().get("models", [])]
            flash = [m for m in models if "flash" in m.lower()]
            print(f"  {PASS} Gemini API reachable.  Status: {resp.status_code}")
            print(f"         Flash models available: {flash[:3]}")
        else:
            print(f"  {FAIL} Gemini API returned HTTP {resp.status_code}")
            print(f"         Response: {resp.text[:200]}")
    except Exception as e:
        print(f"  {FAIL} Gemini API request failed: {e}")

# =============================================================================
# 3. Test Google Maps Street View API  (from env var)
# =============================================================================
print("\n" + "=" * 55)
print("3. Testing Google Maps Street View API")
print("=" * 55)

maps_key = os.getenv("GOOGLE_MAPS_API_KEY", "")
if not maps_key:
    print(f"  {FAIL} GOOGLE_MAPS_API_KEY env var not set.")
    print( "         Set it with:  $env:GOOGLE_MAPS_API_KEY = 'AIza...'")
    print( "         (needed for pipeline Phase C to fetch road images)")
else:
    print(f"  Found Maps key : {maps_key[:8]}...{maps_key[-4:]}")
    try:
        resp = requests.get(
            "https://maps.googleapis.com/maps/api/streetview/metadata",
            params={"location": "13.7563,100.5018", "key": maps_key},  # Bangkok
            timeout=10,
        )
        if resp.status_code == 200:
            data = resp.json()
            status = data.get("status")
            if status in ("OK", "ZERO_RESULTS"):
                print(f"  {PASS} Street View API reachable.  Status field: {status}")
            else:
                print(f"  {FAIL} API reachable but returned status: {status}")
                print(f"         Message: {data.get('error_message', 'none')}")
        else:
            print(f"  {FAIL} Street View API returned HTTP {resp.status_code}")
            print(f"         Response: {resp.text[:200]}")
    except Exception as e:
        print(f"  {FAIL} Street View API request failed: {e}")

# =============================================================================
# Summary
# =============================================================================
print("\n" + "=" * 55)
print("Summary")
print("=" * 55)
print("  Gemini key in config.json  :", "YES" if gemini_key   else "NO")
print("  GEMINI_API_KEY  env var    :", "YES" if env_gemini   else "NO  <-- set this for Phase C")
print("  GOOGLE_MAPS_API_KEY env var:", "YES" if maps_key     else "NO  <-- set this for Phase C")
print()
if not env_gemini or not maps_key:
    print("  To run pipeline Phase C, set both env vars in PowerShell:")
    print("    $env:GEMINI_API_KEY      = '<your_gemini_key>'")
    print("    $env:GOOGLE_MAPS_API_KEY = '<your_maps_key>'")
