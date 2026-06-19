#!/usr/bin/env python3
"""
run_pipeline.py  --  Speed Safety Score Pipeline  --  End-to-end Runner
========================================================================
Executes the full A→B→C→D pipeline for Maharashtra, Thailand, or both.

Usage
-----
  python run_pipeline.py                        # both countries, all phases
  python run_pipeline.py --region thailand      # Thailand only
  python run_pipeline.py --region maharashtra   # Maharashtra only
  python run_pipeline.py --skip-vlm            # skip Phase C (no API keys needed)
  python run_pipeline.py --phases A,B,D        # run specific phases only
  python run_pipeline.py --skip-vlm --phases A,B,D  # combined

API keys (only needed if Phase C is included)
---------------------------------------------
  Windows PowerShell:
    $env:GOOGLE_MAPS_API_KEY = "AIza..."
    $env:GEMINI_API_KEY      = "AIza..."
  bash / WSL:
    export GOOGLE_MAPS_API_KEY="AIza..."
    export GEMINI_API_KEY="AIza..."

Phase outputs (per country)
----------------------------
  Phase A → results/.../sections_{country}.gpkg
  Phase B → results/.../sections_scored_{country}.gpkg  +  imagery_sample.csv
  Phase C → results/.../sections_enriched_{country}.gpkg  (requires API keys)
  Phase D → speed_safety_scores_{country}.gpkg
             priority_top100_{country}.csv
             map_segment_{country}.html
             map_aggregate_{country}.html
             country_comparison.csv
"""

import argparse, subprocess, sys, os, time, json
from datetime import datetime

# ── Load API keys from ~/.env (outside OneDrive, never synced) ───────────────
_dotenv = os.path.join(os.path.expanduser("~"), ".env")
if os.path.exists(_dotenv):
    with open(_dotenv) as _f:
        for _line in _f:
            _line = _line.strip()
            if _line and not _line.startswith("#") and "=" in _line:
                _k, _, _v = _line.partition("=")
                os.environ[_k.strip()] = _v.strip().strip('"').strip("'")
    print(f"Loaded env vars from {_dotenv}")

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

PHASE_SCRIPTS = {
    "Maharashtra": {
        "A": os.path.join(SCRIPT_DIR, "Maharashtra", "v2", "phase_a_prep.py"),
        "B": os.path.join(SCRIPT_DIR, "Maharashtra", "v2", "phase_b_score.py"),
        "C": os.path.join(SCRIPT_DIR, "Maharashtra", "v2", "phase_c_vlm.py"),
        "D": os.path.join(SCRIPT_DIR, "Maharashtra", "v2", "phase_d_final.py"),
    },
    "Thailand": {
        "A": os.path.join(SCRIPT_DIR, "Thailand", "v2", "phase_a_prep.py"),
        "B": os.path.join(SCRIPT_DIR, "Thailand", "v2", "phase_b_score.py"),
        "C": os.path.join(SCRIPT_DIR, "Thailand", "v2", "phase_c_vlm.py"),
        "D": os.path.join(SCRIPT_DIR, "Thailand", "v2", "phase_d_final.py"),
    },
}


def separator(text):
    width = 70
    print("\n" + "=" * width)
    print(f"  {text}")
    print("=" * width)


def run_phase(region, phase, script_path):
    """Run a single phase script and return (success, elapsed_seconds)."""
    separator(f"{region}  |  Phase {phase}  --  {os.path.basename(script_path)}")

    if not os.path.exists(script_path):
        print(f"  [ERROR] Script not found: {script_path}")
        return False, 0

    start = time.time()
    result = subprocess.run(
        [sys.executable, script_path],
        env=os.environ.copy(),
    )
    elapsed = time.time() - start

    if result.returncode == 0:
        print(f"\n  [OK] Phase {phase} completed in {elapsed:.1f}s")
        return True, elapsed
    else:
        print(f"\n  [FAIL] Phase {phase} exited with code {result.returncode} "
              f"({elapsed:.1f}s)")
        return False, elapsed


def check_api_keys():
    google = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    gemini = os.environ.get("GEMINI_API_KEY", "")
    if not google or not gemini:
        print("\n  [WARN] API keys not set. Phase C (VLM enrichment) will fail.")
        print("  Set them before running Phase C:")
        print("    $env:GOOGLE_MAPS_API_KEY = 'AIza...'")
        print("    $env:GEMINI_API_KEY      = 'AIza...'")
        return False
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Speed Safety Score Pipeline runner"
    )
    parser.add_argument(
        "--region",
        choices=["maharashtra", "thailand", "both"],
        default="both",
        help="Which country to run (default: both)",
    )
    parser.add_argument(
        "--skip-vlm",
        action="store_true",
        help="Skip Phase C (Street View + Gemini). Runs A→B→D only.",
    )
    parser.add_argument(
        "--phases",
        default="A,B,C,D",
        help="Comma-separated phases to run, e.g. A,B,D (default: A,B,C,D)",
    )
    args = parser.parse_args()

    requested_phases = [p.strip().upper() for p in args.phases.split(",")]
    if args.skip_vlm and "C" in requested_phases:
        requested_phases.remove("C")

    regions = (
        ["Maharashtra", "Thailand"] if args.region == "both"
        else [args.region.capitalize()]
    )
    # Normalise "maharashtra" → "Maharashtra"
    region_map = {r.lower(): r for r in PHASE_SCRIPTS}
    regions = [region_map.get(r.lower(), r) for r in regions]

    print(f"\nSpeed Safety Score Pipeline")
    print(f"  Regions  : {', '.join(regions)}")
    print(f"  Phases   : {', '.join(requested_phases)}")
    print(f"  Started  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    if "C" in requested_phases:
        check_api_keys()

    run_log = []
    all_ok  = True

    for region in regions:
        if region not in PHASE_SCRIPTS:
            print(f"\n[ERROR] Unknown region: {region}")
            continue
        for phase in ["A", "B", "C", "D"]:
            if phase not in requested_phases:
                continue
            script = PHASE_SCRIPTS[region][phase]
            ok, elapsed = run_phase(region, phase, script)
            run_log.append({
                "region": region, "phase": phase,
                "success": ok, "elapsed_s": round(elapsed, 1),
            })
            if not ok:
                all_ok = False
                print(f"\n  [ABORT] Stopping {region} pipeline at Phase {phase}.")
                break   # don't run later phases if an earlier one failed

    # ── Final summary ─────────────────────────────────────────────────────────
    separator("PIPELINE SUMMARY")
    total_time = sum(r["elapsed_s"] for r in run_log)
    for entry in run_log:
        status = "OK  " if entry["success"] else "FAIL"
        print(f"  [{status}] {entry['region']:<15} Phase {entry['phase']}  "
              f"({entry['elapsed_s']}s)")

    print(f"\n  Total wall time : {total_time:.1f}s")
    print(f"  Finished        : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Save run log next to this script.
    log_path = os.path.join(SCRIPT_DIR, "run_log.json")
    with open(log_path, "w") as f:
        json.dump(run_log, f, indent=2)
    print(f"  Run log saved   : {log_path}")

    if not all_ok:
        print("\n  [WARN] One or more phases failed. Check output above.")
        sys.exit(1)
    else:
        print("\n  Pipeline completed successfully.")


if __name__ == "__main__":
    main()
