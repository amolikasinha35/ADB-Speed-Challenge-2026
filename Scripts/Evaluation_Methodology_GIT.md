**Evaluation Methodology**

**ADB Speed Challenge 2026 Analytical Model**

*Speed Safety Score pipeline for Maharashtra and Thailand*

| Repository | amolikasinha35/ADB-Speed-Challenge-2026 |
| :---- | :---- |
| Analytical model | Speed Safety Score: Severity × Exposure × Consequence |
| Evaluation purpose | Assess whether model outputs are transparent, reproducible, risk-sensitive, and suitable for prioritising speed management interventions. |
| Primary outputs evaluated | Scored GeoPackage/Parquet files, priority top-100 CSV, interactive segment and aggregate maps, run logs and phase manifests. |
| Document status | Submission-ready methodology draft based on the current GitHub code structure. |

**Important interpretation note:** This analytical model is a risk-screening and prioritisation tool. It is iRAP-/Safe-System-aligned in its use of road attributes, forgivingness concepts and speed-risk logic, but it is not presented as a formal iRAP Star Rating replacement or as a substitute for qualified road safety audit judgement.

# **1\. Executive Summary**

This document defines the evaluation methodology for the ADB Speed Challenge 2026 analytical model implemented in the GitHub repository. The model converts probe-speed, road-class, land-use, helmet-wearing and road-infrastructure information into a section-level Speed Safety Score. The score is designed to identify road sections where operating speeds, posted limits, vulnerable road user exposure and infrastructure forgivingness combine to create elevated safety risk.

The evaluation methodology focuses on four questions: (1) whether input data are complete and defensible; (2) whether the Speed Safety Score is calculated consistently from transparent model components; (3) whether optional Street View and vision-language-model enrichment improves infrastructure relevance without introducing uncontrolled noise; and (4) whether final intervention recommendations are traceable to observable model signals rather than black-box judgement.

# **2\. Analytical Model Overview**

The pipeline has four phases. Each phase produces outputs that can be inspected independently, allowing the evaluation to separate data preparation quality, preliminary score quality, VLM enrichment quality and final intervention logic.

| Phase | Script | Purpose | Core evaluation checks | Key outputs |
| :---- | :---- | :---- | :---- | :---- |
| A. Data preparation | phase\_a\_prep.py | Clean and aggregate micro-segments into road sections; add speed limit quality flags; join helmet SPI. | Row counts, geometry validity, speed limit imputation rate, n\_valid coverage, helmet SPI coverage. | sections\_{region}.gpkg/parquet; phase\_a\_manifest.json |
| B. Preliminary scoring | phase\_b\_score.py | Apply Safe System benchmark speeds and compute Severity, Exposure, Consequence and Speed Safety Score. | Benchmark coverage, score distribution, score-band distribution, component traceability. | sections\_scored\_{region}.gpkg/parquet; imagery\_sample.csv; phase\_b\_manifest.json |
| C. VLM enrichment | phase\_c\_vlm.py | Use Street View and Gemini to extract road attributes; validate attributes; adjust benchmark and forgivingness. | Image usability, mean confidence, agreement rate, stability flip rate, adjustment cap compliance. | vlm\_extractions.parquet; vlm\_validation\_report.csv; sections\_enriched\_{region}.gpkg/parquet |
| D. Final scoring and outputs | phase\_d\_final.py | Recompute final score, assign intervention type and generate maps/priority lists. | Final score distribution, intervention logic checks, top-100 plausibility, map/data consistency. | speed\_safety\_scores\_{region}.gpkg/parquet; priority\_top100\_{region}.csv; maps; comparison CSV |

# **3\. Evaluation Objectives**

**Transparency:** Every score should be decomposable into severity, exposure and consequence components, with benchmark speed, median speed and data quality fields retained.

**Reproducibility:** The pipeline should run from the documented scripts and produce auditable phase outputs, manifests and run logs.

**Risk relevance:** High scores should reflect a meaningful combination of excessive speed relative to benchmark, vulnerable road user exposure and non-forgiving infrastructure.

**Calibration and reliability:** VLM-derived attributes should only influence the final model when they meet minimum confidence, agreement and stability thresholds.

**Decision usefulness:** Intervention labels should be linked to clear diagnostic signals: posted limit gap, operating speed non-compliance and visual road character.

# **4\. Data Preparation Evaluation**

Phase A is evaluated as the data-quality gate. A section should not be interpreted only as a map object; it must also carry evidence about the reliability of the speed observations, the plausibility of the posted speed limit and the completeness of exposure data.

| Check | Code basis | Pass criterion | Why it matters |
| :---- | :---- | :---- | :---- |
| Layer and schema check | Read expected GeoPackage segment and helmet layers. | Expected layers are present and columns can be cast to required types. | Prevents silent failure due to renamed or missing layers. |
| Probe-speed reliability | n\_valid is true when Sample\_Size\_Total meets the configured threshold. | Report the share of sections with sufficient underlying probe observations. | Separates reliable speed estimates from low-sample artefacts. |
| Speed-limit plausibility | Implausible high-class low speed limits are flagged and imputed from legal defaults. | Report count/share of imputed speed limits and inspect high-imputation strata. | Avoids misleading benchmark and intervention signals from bad posted-limit values. |
| Aggregation validity | Micro-segments are grouped by DISSOLVE\_ID; speeds are sample-weighted. | Section counts, lengths and mixed-class/mixed-land-use flags are reported. | Keeps the unit of analysis stable and explains heterogeneous sections. |
| Helmet SPI coverage | Helmet SPI is spatially joined by section centroid and normalised to 0-1. | Coverage percentage and fallback use are reported in the manifest. | Exposure scoring relies on helmet non-compliance as a vulnerability multiplier. |

# **5\. Speed Safety Score Methodology**

The model evaluates risk through three interpretable components: Severity, Exposure and Consequence. The preliminary Phase B score is complete on its own; Phase C can refine benchmark speed and consequence where reliable imagery-based attributes are available.

**Speed Safety Score \= Severity × Exposure × Consequence**

| Component | Formula / logic | Input fields | Evaluation check |
| :---- | :---- | :---- | :---- |
| Severity | (MedianSpeed / benchmark speed)^4 | MedianSpeed; base\_benchmark\_kmh or adjusted\_benchmark\_kmh | Check all sections have benchmark values; review severity distribution and outliers. |
| Exposure | 1 \+ (1 \- HelmetSPI) × VRU\_weight | HelmetSPI; LandUse; VLM vru\_activity if available | Check helmet SPI coverage/fallbacks and whether urban/rural weights are applied correctly. |
| Consequence | Phase B: default 1.5. Phase D: 2 \- forgivingness\_index, clipped 1.0 to 2.0. | VLM-derived roadside hazard, barrier, shoulder and surface condition attributes. | Check that forgivingness is only used where VLM reliability criteria are met. |
| Final score band | Low, Moderate, High or Critical thresholds applied to score. | speed\_safety\_score or final\_score | Check score-band counts and map colours for consistency. |

The fourth-power severity term gives strong weight to speed exceedance because the analytical purpose is to identify sections where even moderate speed increases above a Safe System benchmark can create disproportionate injury risk. The evaluation therefore does not only check the final rank order; it also checks whether severity, exposure and consequence each behave sensibly across road classes and land-use settings.

# **6\. Parameter and Benchmark Evaluation**

The central parameter file is evaluated as a transparent model-control register. It keeps benchmark speeds, VRU weights, score thresholds, VLM reliability thresholds and intervention thresholds in one location, reducing hidden assumptions inside phase scripts.

| Parameter group | Examples | Evaluation action | Recommended reporting |
| :---- | :---- | :---- | :---- |
| Speed defaults and benchmarks | SPEED\_DEFAULTS; SAFE\_SYSTEM\_BENCHMARKS; urban/rural fallback benchmarks. | Check every section receives a benchmark and identify sections using fallbacks. | Benchmark distribution table by RoadClass × LandUse. |
| Exposure weights | VRU\_WEIGHT\_URBAN; VRU\_WEIGHT\_RURAL. | Run sensitivity comparison if final rankings are highly driven by helmet SPI. | Exposure summary by urban/rural setting. |
| Power model exponent | POWER\_MODEL\_EXPONENT \= 4\. | Confirm score sensitivity to speed exceedance; optionally test exponent 3 and 4 in appendix. | Severity distribution and top-100 stability check. |
| VLM reliability thresholds | VLM\_CONFIDENCE\_THRESHOLD, AGREEMENT\_RATE\_THRESHOLD, STABILITY\_FLIP\_RATE\_THRESHOLD. | Exclude or down-weight attributes failing thresholds. | vlm\_validation\_report.csv summary. |
| Intervention thresholds | Signal A and Signal B thresholds in km/h. | Check threshold-borderline cases manually. | Counts by intervention type and signal bands. |

# **7\. VLM Enrichment and Validation Methodology**

Phase C is an optional refinement layer. It should improve the infrastructure relevance of the model but should not be allowed to dominate the result unless outputs are reliable. The evaluation therefore treats VLM outputs as calibrated evidence, not as unquestioned truth.

The imagery sample contains two parts: a priority sample made from the highest preliminary Speed Safety Scores, and a calibration sample stratified by RoadClass × LandUse. This design checks both the sections most likely to need action and a broader cross-section of the network.

| VLM validation dimension | Metric | Configured threshold / rule | Evaluation interpretation |
| :---- | :---- | :---- | :---- |
| Image usability | image\_usable flag and image notes | Unusable images should not drive benchmark or consequence changes. | Protects against occlusion, poor view angle, outdated imagery or irrelevant images. |
| Confidence | Mean confidence by attribute | Attributes below confidence threshold retain Phase B values. | Avoids over-interpreting uncertain classifications. |
| Agreement | Agreement versus existing road/land-use data where comparable | Agreement rate should meet the configured minimum. | Checks whether VLM labels are consistent with known data. |
| Stability | Flip rate between repeated Gemini runs | Flip rate should remain below configured maximum. | Flags attributes that are too unstable for scoring. |
| Adjustment cap | Total VLM benchmark adjustment | Capped at \+/- configured km/h. | Prevents one image from causing excessive benchmark movement. |

Only attributes passing validation should be used to adjust the Safe System benchmark or forgivingness index. Attributes such as median type, carriageway division, VRU activity, roadside development, intersection density and calming features are used for benchmark adjustment. Roadside hazard, roadside barrier, shoulder and surface condition contribute to the forgivingness index used in the final consequence component.

# **8\. Final Score and Intervention Evaluation**

Phase D recomputes the model using the best available input: enriched Phase C output if it exists, otherwise the Phase B scored output. This makes the pipeline robust because it can still produce a complete preliminary submission when VLM API keys or image availability are unavailable.

| Diagnostic signal | Formula | Interpretation | Use in intervention logic |
| :---- | :---- | :---- | :---- |
| Signal A | Posted SpeedLimit \- adjusted benchmark | Positive values indicate that the posted limit is above the modelled Safe System benchmark. | High Signal A triggers lower\_limit recommendation. |
| Signal B | F85thPercentileSpeed \- posted SpeedLimit | Positive values indicate that operating speeds exceed the posted limit. | High Signal B triggers traffic calming, enforcement or enforcement\_crisis depending on Signal A and visual character. |
| Visual speed character | VLM categorical attribute where available | Identifies whether road form visually invites high speed or constrains speed. | Distinguishes engineering treatments from enforcement-only responses. |

The final evaluation should include a manual sense-check of the top 100 priority sections. Reviewers should inspect whether high-priority sections have coherent combinations of score components, credible diagnostic signals and intervention labels that match the section context. Borderline sections near the Signal A or Signal B thresholds should be flagged for expert review rather than treated as deterministic outputs.

# **9\. Evaluation Metrics and Acceptance Criteria**

| Area | Metric | Target / expected evidence | Source artefact | Action if not met |
| :---- | :---- | :---- | :---- | :---- |
| Data completeness | Section count, missing key fields, geometry validity | No unexplained missing benchmark, speed or geometry fields for scored sections. | phase\_a\_manifest.json; sections file | Repair schema, re-run Phase A, or exclude affected sections. |
| Speed reliability | n\_valid\_share by section and network share | Low-sample sections identified, not silently treated as equally reliable. | sections\_{region}.parquet | Flag in maps/priority outputs or conduct sensitivity analysis. |
| Imputation transparency | limit\_imputed\_share and helmet\_imputed | Imputed values reported and reviewable. | Phase A manifest and section attributes | Document imputation assumptions and inspect high-imputation groups. |
| Scoring traceability | Component columns and score\_components\_json | Each score can be decomposed into inputs and components. | sections\_scored\_{region}.parquet | Add component fields to outputs before submission. |
| VLM reliability | mean confidence, agreement rate, flip rate | Only passing attributes influence final scoring. | vlm\_validation\_report.csv | Retain Phase B values for failing attributes. |
| Final ranking plausibility | Top-100 review and score-band distribution | High-priority sections show interpretable risk drivers. | priority\_top100\_{region}.csv; maps | Manual review, threshold check or sensitivity test. |
| Reproducibility | End-to-end run log and phase manifests | Run log records phase success/failure and elapsed time. | run\_log.json; phase manifests | Re-run failed phases or clearly state fallback mode. |
| Decision usefulness | Intervention type distribution and signal values | Recommendations trace back to Signal A, Signal B and visual character. | speed\_safety\_scores\_{region}.gpkg/parquet | Flag ambiguous cases for expert engineering review. |

# **10\. Sensitivity, Robustness and Validation Checks**

**With/without VLM comparison:** Run Phase D using Phase B-only outputs and again using Phase C-enriched outputs. Compare final score rank correlation, top-100 overlap and intervention-type shifts. Large unexplained shifts should be reviewed.

**Threshold sensitivity:** Test how the top-100 list changes when Signal A and Signal B thresholds vary by \+/-5 km/h. This shows whether recommendations are stable or overly threshold-sensitive.

**Benchmark sensitivity:** Review benchmark assignment by RoadClass × LandUse and inspect fallbacks. Fallback-heavy strata should be interpreted with lower confidence.

**Exposure sensitivity:** Compare scores under urban/rural VRU weights and helmet SPI fallback values to identify whether exposure dominates rankings in any zone.

**Manual image audit sample:** For a small sample of priority and calibration sections, manually review imagery and compare with VLM labels. Record disagreement themes such as occlusion, old imagery or ambiguous land use.

**Crash-data validation where available:** If observed crash or fatal/serious injury data can be linked later, compare high-score sections against crash concentration. This is recommended for external validation but is not required for a proxy risk-screening model.

# **11\. Reproducibility and Audit Trail**

The submission should make it easy for a reviewer to reproduce or audit the model run. The main runner supports all regions, region-specific runs, skipping the VLM phase and running selected phases only. API keys are required only for Phase C.

**Recommended commands to document in README:**

python run\_pipeline.py

python run\_pipeline.py \--region maharashtra

python run\_pipeline.py \--region thailand

python run\_pipeline.py \--skip-vlm \--phases A,B,D

| Artefact | Purpose | Submission use |
| :---- | :---- | :---- |
| phase\_a\_manifest.json | Input hashes, row counts and coverage report. | Proves data lineage and preprocessing coverage. |
| phase\_b\_manifest.json | Score coverage and score summary. | Proves preliminary model executed and produced interpretable outputs. |
| vlm\_validation\_report.csv | Per-attribute VLM reliability. | Proves AI-derived attributes are evaluated before use. |
| phase\_c\_manifest.json | VLM enrichment summary. | Documents image/API completion and enrichment coverage. |
| phase\_d\_manifest.json | Final scoring and output summary. | Documents final deliverables and intervention distribution. |
| run\_log.json | Phase success/failure and elapsed times. | Provides reproducibility and execution status evidence. |

# **12\. Limitations and Reviewer Guidance**

* The model is a proxy risk-screening approach. It prioritises where speed-related risk is likely to be high; it does not estimate causal treatment effects unless linked to before-after crash or speed outcome data.  
* Probe-speed reliability depends on sample size and representativeness. Low n\_valid\_share sections should be treated with lower confidence.  
* Speed-limit imputation is transparent but still introduces assumption risk. Sections with imputed limits should remain reviewable in the GIS outputs.  
* Helmet SPI is joined through spatial zones and may not represent exact section-level helmet use. It is a useful exposure proxy, not a direct observed behaviour count for every road section.  
* Street View imagery can be outdated, occluded or spatially offset. VLM outputs should pass validation and a manual audit sample before being relied upon for engineering decisions.  
* Intervention labels are screening recommendations. Final treatments should be confirmed by qualified road safety practitioners and local road authorities.

# **13\. Recommended Submission Statement**

**Suggested wording:** The analytical model has been evaluated using a staged methodology covering data quality, transparent component scoring, VLM reliability validation, final intervention logic and reproducibility. Each output section retains component scores and diagnostic signals so that reviewers can understand why a road section is prioritised and what type of speed management response is suggested.

# **14\. Source Files Reviewed**

| Repository file | Role in this methodology |
| :---- | :---- |
| README.md | Repository landing page and external results/documentation links. |
| Scripts/run\_pipeline.py | End-to-end runner, reproducibility commands and phase outputs. |
| Scripts/Maharashtra/v2/config.py | Central parameter store for benchmarks, thresholds, VLM validation rules and intervention thresholds. |
| Scripts/Maharashtra/v2/phase\_a\_prep.py | Data preparation, aggregation, imputation, helmet SPI join and Phase A manifest. |
| Scripts/Maharashtra/v2/phase\_b\_score.py | Preliminary Speed Safety Score formula, score bands and imagery sampling plan. |
| Scripts/Maharashtra/v2/phase\_c\_vlm.py | Street View/Gemini enrichment, VLM prompt, validation report and enriched outputs. |
| Scripts/Maharashtra/v2/phase\_d\_final.py | Final score recomputation, diagnostic signals, intervention assignment and maps/top-100 outputs. |

# **15\. External Methodology References**

* iRAP. Methodology and Specifications: road attribute data, Star Ratings, FSI estimates and investment planning tools for measuring and improving road infrastructure safety.  
* Nilsson / Elvik Power Model literature: relationship between traffic speed changes and road safety outcomes; used here as the basis for the fourth-power severity term.  
* Safe System speed-management principle: roads should be managed so that operating speeds are compatible with crash survivability and forgiving infrastructure design.