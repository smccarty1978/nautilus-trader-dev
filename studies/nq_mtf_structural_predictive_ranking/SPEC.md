# nq_mtf_structural_predictive_ranking

Derived from `research_decision.yaml`. Question: # NQ MTF + Structural Geometry Predictive Ranking (lean modeling follow-up)

PRIMARY QUESTION. Can the JOINT continuous entry-time information in 1m/5m/15m/1h regime orientation,
current 5m/15m/1h regime geometry, immediately prior 5m/15m/1h regime geometry, ATR-normalized distances to
current/prior structural levels, and regime age/progress/excursion state RANK 1m V_A flips into economically
different lifecycle populations OUT OF SAMPLE?

The completed atlas (studies/nq_mtf_regime_structural_geometry_atlas, verdict D_NOT_FOUND) tested HUMAN-DEFINED
rectangular segmentation only. JOINT PREDICTIVE INFORMATION IN THE CONTINUOUS SURFACE IS UNTESTED and is what
this study tests.

KEY EXPERIMENT. TRAIN = 2023 only. Freeze model, feature order, preprocessing, hyperparameters, score definition
and the 2023 score-bucket boundaries. Score untouched 2024 ONCE. Decide whether the frozen score creates
economically ordered 2024 populations, against direction-only and exact-MTF controls.

NOT: another NT collection, another bucket search, exit/stop/target optimization, post-entry management, ML zoo.
One primary nonlinear tabular model (LightGBM) plus one simple baseline; fixed modest configuration; no sweeps.

TARGETS (predeclared): A terminal_gross_pnl_atr > 0 (+ continuous g for economics); B reach +2A before the
opposite 1m flip; C reach +3A; D (diagnostic) +5A; E reach -2A.

STOP CONDITION. Stop after the frozen 2024 evaluation, diagnostics and descriptive top-50/30/20/10 retention
surfaces. 2025 and 2026 remain untouched. Verdict is one of NO_INFORMATION / WEAK_RANKING /
TARGET_SPECIFIC_INFORMATION / REPRODUCIBLE_ECONOMIC_RANKING.

REUSE CONSTRAINT (owner). Do not recollect the already-audited 2023/2024 atlas frame. If the workflow forces a
recollection of identical bars, STOP and resolve reuse.

## Population

## Target

## Features

## Chronology

## Deliverables Manifest
