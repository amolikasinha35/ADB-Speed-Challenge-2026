"""
SPI Data Explorer
Explores Road_Safety_Performance_Indicators_(Helmet_Wearing_results)_(adb_dashboard_data_v02).xlsx
Results saved to: results/SPIData/
"""

import subprocess
import sys

subprocess.check_call([sys.executable, "-m", "pip", "install",
                       "pandas", "numpy", "matplotlib", "seaborn", "openpyxl"])

import os
import warnings
warnings.filterwarnings("ignore")

import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mtick
import seaborn as sns

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
SCRIPT_DIR  = os.path.dirname(os.path.abspath(__file__))
BASE_DIR    = os.path.dirname(os.path.dirname(SCRIPT_DIR))      # ADB Challenge 2026T4
SCRIPT_NAME = os.path.splitext(os.path.basename(__file__))[0]   # spi_explorer
DATA_FILE   = os.path.join(BASE_DIR, "Data", "Archive",
              "Road_Safety_Performance_Indicators_(Helmet_Wearing_results)_(adb_dashboard_data_v02).xlsx")
RESULTS_DIR = os.path.join(BASE_DIR, "results", "SPIData")
os.makedirs(RESULTS_DIR, exist_ok=True)

sns.set_theme(style="whitegrid", palette="muted")

# ---------------------------------------------------------------------------
# Column metadata
# ---------------------------------------------------------------------------
COLUMN_META = {
    "Location": {
        "definition": "Geographic area the SPI value applies to: Thailand (national), Maharashtra (state), Mumbai (city), or Pune (city).",
        "importance": "HIGH — the primary grouping variable; enables comparison of helmet wearing rates across countries and cities."
    },
    "LandUse": {
        "definition": "Land use classification of the observation: Combined (urban + rural together), Urban, or Rural.",
        "importance": "HIGH — rural and urban areas have very different helmet wearing rates; always stratify by this when comparing."
    },
    "User": {
        "definition": "Rider type the SPI applies to: All Riders (aggregate), Driver (motorcycle driver), or Passenger (pillion passenger).",
        "importance": "HIGH — passenger compliance is typically far lower than driver compliance; disaggregating by user type reveals hidden risk."
    },
    "Year": {
        "definition": "Year of observation, or 'All' for the multi-year aggregate SPI. Available years vary by location.",
        "importance": "HIGH — year-over-year trends show whether helmet wearing is improving or declining over time."
    },
    "SPI": {
        "definition": "Safety Performance Indicator — the proportion of riders observed wearing a helmet (0.0 = no one, 1.0 = everyone). Measured via roadside observation surveys.",
        "importance": "HIGH — the core metric of this dataset; directly measures helmet compliance as a road safety outcome."
    },
    "FID": {
        "definition": "Feature ID — a unique integer row identifier assigned by the GIS/database system.",
        "importance": "LOW — internal record identifier; not used in analysis."
    },
}

# ---------------------------------------------------------------------------
# 1. Load data
# ---------------------------------------------------------------------------
print("=" * 70)
print("SPI DATA EXPLORER")
print("=" * 70)
print(f"\nLoading: {DATA_FILE}")

xl       = pd.ExcelFile(DATA_FILE)
df       = xl.parse(xl.sheet_names[0])
print(f"Loaded successfully.\n")

# ---------------------------------------------------------------------------
# 2. Sheet & structure overview
# ---------------------------------------------------------------------------
print("=" * 70)
print("1. FILE & SHEET OVERVIEW")
print("=" * 70)
print(f"  Sheet names   : {xl.sheet_names}")
print(f"  Active sheet  : {xl.sheet_names[0]}")
print(f"  Rows          : {len(df)}")
print(f"  Columns       : {len(df.columns)}  →  {list(df.columns)}")

# ---------------------------------------------------------------------------
# 3. Column overview
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print("2. COLUMN OVERVIEW")
print("=" * 70)
overview = []
for col in df.columns:
    non_null   = int(df[col].notna().sum())
    pct_filled = 100 * non_null / len(df)
    unique_n   = df[col].nunique()
    sample     = str(df[col].dropna().iloc[0]) if non_null > 0 else "N/A"
    overview.append({
        "Column":        col,
        "DType":         str(df[col].dtype),
        "Non-Null":      non_null,
        "% Filled":      f"{pct_filled:.1f}%",
        "Unique Values": unique_n,
        "Sample Value":  sample,
    })
df_overview = pd.DataFrame(overview)
print(df_overview.to_string(index=False))
df_overview.to_csv(os.path.join(RESULTS_DIR, "column_overview.csv"), index=False)
print("\n  [Saved] column_overview.csv")

# ---------------------------------------------------------------------------
# 4. Column definitions & importance
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print("3. COLUMN DEFINITIONS & ANALYTICAL IMPORTANCE")
print("=" * 70)
meta_rows = []
for col in df.columns:
    m = COLUMN_META.get(col, {"definition": "No definition available.", "importance": "UNKNOWN"})
    print(f"\n  [{col}]")
    print(f"    Definition : {m['definition']}")
    print(f"    Importance : {m['importance']}")
    meta_rows.append({"Column": col, "Definition": m["definition"], "Importance": m["importance"]})

pd.DataFrame(meta_rows).to_csv(os.path.join(RESULTS_DIR, "column_definitions.csv"), index=False)
print("\n  [Saved] column_definitions.csv")

# ---------------------------------------------------------------------------
# 5. Unique values per categorical column
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print("4. UNIQUE VALUES PER CATEGORICAL COLUMN")
print("=" * 70)
for col in ["Location", "LandUse", "User", "Year"]:
    vals = sorted(df[col].dropna().unique().tolist(), key=str)
    print(f"\n  {col} ({len(vals)} unique): {vals}")

# ---------------------------------------------------------------------------
# 6. Statistical summary of SPI
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print("5. SPI STATISTICAL SUMMARY")
print("=" * 70)
print(df["SPI"].describe().round(4).to_string())

# ---------------------------------------------------------------------------
# 7. Full data table
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print("6. FULL DATA TABLE")
print("=" * 70)
print(df.to_string(index=False))
df.to_csv(os.path.join(RESULTS_DIR, "spi_full_data.csv"), index=False)
print("\n  [Saved] spi_full_data.csv")

# ---------------------------------------------------------------------------
# 8. Pivot: SPI by Location × LandUse  (All Riders, All years)
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print("7. PIVOT — SPI by Location × LandUse  (All Riders, All years)")
print("=" * 70)
pivot_loc_lu = df[
    (df["User"] == "All Riders") & (df["Year"] == "All")
].pivot_table(index="Location", columns="LandUse", values="SPI").round(3)
print(pivot_loc_lu.to_string())
pivot_loc_lu.to_csv(os.path.join(RESULTS_DIR, "pivot_location_landuse.csv"))
print("\n  [Saved] pivot_location_landuse.csv")

# ---------------------------------------------------------------------------
# 9. Pivot: SPI by Location × User  (Combined land use, All years)
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print("8. PIVOT — SPI by Location × User Type  (Combined, All years)")
print("=" * 70)
pivot_loc_user = df[
    (df["LandUse"] == "Combined") & (df["Year"] == "All")
].pivot_table(index="Location", columns="User", values="SPI").round(3)
print(pivot_loc_user.to_string())
pivot_loc_user.to_csv(os.path.join(RESULTS_DIR, "pivot_location_user.csv"))
print("\n  [Saved] pivot_location_user.csv")

# ---------------------------------------------------------------------------
# 10. Year trend  (All Riders, Combined — only locations with year data)
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print("9. YEAR TREND — All Riders, Combined LandUse")
print("=" * 70)
trend = df[
    (df["User"] == "All Riders") &
    (df["LandUse"] == "Combined") &
    (df["Year"] != "All")
].copy()
trend["Year"] = trend["Year"].astype(int)
print(trend[["Location", "Year", "SPI"]].sort_values(["Location", "Year"]).to_string(index=False))
trend.to_csv(os.path.join(RESULTS_DIR, "year_trend.csv"), index=False)
print("\n  [Saved] year_trend.csv")

# ---------------------------------------------------------------------------
# 11. Visualisations
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print("10. GENERATING CHARTS")
print("=" * 70)

# ── Chart 1: SPI by Location (All Riders, Combined, All years) ─────────────
agg = df[(df["User"] == "All Riders") & (df["LandUse"] == "Combined") & (df["Year"] == "All")]
fig, ax = plt.subplots(figsize=(8, 5))
bars = ax.bar(agg["Location"], agg["SPI"],
              color=sns.color_palette("muted", len(agg)), edgecolor="white", width=0.5)
ax.bar_label(bars, fmt="%.3f", padding=4, fontsize=10)
ax.set_ylim(0, 1.1)
ax.yaxis.set_major_formatter(mtick.PercentFormatter(xmax=1))
ax.set_title("Helmet Wearing Rate by Location\n(All Riders · Combined Land Use · All Years)", fontsize=13)
ax.set_xlabel("Location")
ax.set_ylabel("Helmet Wearing Rate (SPI)")
plt.tight_layout()
plt.savefig(os.path.join(RESULTS_DIR, "chart1_spi_by_location.png"), dpi=150)
plt.close()
print("  [Saved] chart1_spi_by_location.png")

# ── Chart 2: SPI by User Type per Location (Combined, All years) ───────────
fig, ax = plt.subplots(figsize=(10, 5))
user_data = df[(df["LandUse"] == "Combined") & (df["Year"] == "All")]
pivot2 = user_data.pivot_table(index="Location", columns="User", values="SPI")
pivot2.plot(kind="bar", ax=ax, width=0.6, edgecolor="white")
ax.set_ylim(0, 1.1)
ax.yaxis.set_major_formatter(mtick.PercentFormatter(xmax=1))
ax.set_title("Helmet Wearing Rate by User Type and Location\n(Combined Land Use · All Years)", fontsize=13)
ax.set_xlabel("Location")
ax.set_ylabel("Helmet Wearing Rate (SPI)")
ax.legend(title="User Type", bbox_to_anchor=(1.01, 1), loc="upper left")
plt.xticks(rotation=0)
plt.tight_layout()
plt.savefig(os.path.join(RESULTS_DIR, "chart2_spi_by_user_location.png"), dpi=150)
plt.close()
print("  [Saved] chart2_spi_by_user_location.png")

# ── Chart 3: Urban vs Rural SPI per Location (All Riders, All years) ───────
fig, ax = plt.subplots(figsize=(10, 5))
lu_data = df[(df["User"] == "All Riders") & (df["Year"] == "All") & (df["LandUse"] != "Combined")]
pivot3 = lu_data.pivot_table(index="Location", columns="LandUse", values="SPI")
pivot3.plot(kind="bar", ax=ax, width=0.5, edgecolor="white",
            color=["#2ecc71", "#e67e22"])
ax.set_ylim(0, 1.1)
ax.yaxis.set_major_formatter(mtick.PercentFormatter(xmax=1))
ax.set_title("Helmet Wearing Rate: Urban vs Rural\n(All Riders · All Years)", fontsize=13)
ax.set_xlabel("Location")
ax.set_ylabel("Helmet Wearing Rate (SPI)")
ax.legend(title="Land Use", bbox_to_anchor=(1.01, 1), loc="upper left")
plt.xticks(rotation=0)
plt.tight_layout()
plt.savefig(os.path.join(RESULTS_DIR, "chart3_urban_vs_rural.png"), dpi=150)
plt.close()
print("  [Saved] chart3_urban_vs_rural.png")

# ── Chart 4: Year-on-year trend ─────────────────────────────────────────────
if not trend.empty:
    fig, ax = plt.subplots(figsize=(9, 5))
    for loc, grp in trend.groupby("Location"):
        ax.plot(grp["Year"], grp["SPI"], marker="o", linewidth=2, label=loc)
        for _, row in grp.iterrows():
            ax.annotate(f"{row['SPI']:.3f}", (row["Year"], row["SPI"]),
                        textcoords="offset points", xytext=(0, 8), ha="center", fontsize=8)
    ax.set_ylim(0, 1.0)
    ax.yaxis.set_major_formatter(mtick.PercentFormatter(xmax=1))
    ax.set_title("Helmet Wearing Rate Trend Over Time\n(All Riders · Combined Land Use)", fontsize=13)
    ax.set_xlabel("Year")
    ax.set_ylabel("Helmet Wearing Rate (SPI)")
    ax.legend(title="Location")
    plt.tight_layout()
    plt.savefig(os.path.join(RESULTS_DIR, "chart4_year_trend.png"), dpi=150)
    plt.close()
    print("  [Saved] chart4_year_trend.png")

# ── Chart 5: Driver vs Passenger gap heatmap ────────────────────────────────
fig, ax = plt.subplots(figsize=(7, 4))
heat_data = df[
    (df["User"].isin(["Driver", "Passenger"])) &
    (df["LandUse"] == "Combined") &
    (df["Year"] == "All")
].pivot_table(index="Location", columns="User", values="SPI").round(3)
sns.heatmap(heat_data, annot=True, fmt=".3f", cmap="RdYlGn",
            vmin=0, vmax=1, linewidths=0.5, ax=ax, cbar_kws={"label": "SPI"})
ax.set_title("Helmet Wearing Rate: Driver vs Passenger\n(Combined · All Years)", fontsize=12)
plt.tight_layout()
plt.savefig(os.path.join(RESULTS_DIR, "chart5_driver_vs_passenger_heatmap.png"), dpi=150)
plt.close()
print("  [Saved] chart5_driver_vs_passenger_heatmap.png")

# ---------------------------------------------------------------------------
# Done
# ---------------------------------------------------------------------------
print("\n" + "=" * 70)
print("COMPLETE — all outputs saved to:")
print(f"  {RESULTS_DIR}")
print("=" * 70)
