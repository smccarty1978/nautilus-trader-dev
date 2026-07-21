# NQ Regime DNA + Archetype-Aware KNN — SPEC

## Objective
Separate three things the prior atlas conflated: (1) **regime origin story / DNA**
(frozen pre-flip context), (2) **live regime state**, (3) **tradeable forward payoff**.
Test whether DNA + live state improves *monetizable* PT-before-SL calibration and
OOS policy results — not next-bar continuation (which the prior atlas showed is a
volatility/persistence tautology, [[regime_state_transition_atlas_dead]]).

Core hypothesis: a 1m regime flip is the *resolution*, not the setup. Two regimes
identical at bar 6 can have different futures depending on their origin
(compression / exhaustion / failed breakout / reversal / late continuation).

## Data split
Discovery/training 2021–2024; OOS validation 2025–2026. All scoring walk-forward
(year Y scored only vs strictly-prior years; 2025/2026 vs 2021–2024). No same-regime
neighbors. No OOS leakage anywhere.

## Pipeline (files)
- `build_regime_dna.py` — one 1s replay → **regime_dna.parquet** (frozen pre-flip DNA per regime) AND **dna_race_labels.parquet** (per-bar tradeable race labels + velocity). DNA uses ONLY bars strictly before the flip.
- `cluster_regime_dna.py` — cluster on DNA only (winsorize 1/99, RobustScaler, k-sweep 4–16, silhouette, year-stability) → **regime_dna_clusters.parquet** + soft-archetype classifier (walk-forward DNA→cluster, predict_proba) → **dna_archetype_report.md**.
- `build_dna_live_states.py` — merge live state (reuse audited `regime_state_transition_atlas/state_rows.parquet`) + frozen DNA + soft-archetype probs → **dna_live_state_rows.parquet**.
- `score_dna_knn.py` — block-wise walk-forward KNN → **dna_knn_scores.parquet** + **dna_calibration.md**.
- `policy_dna_gate.py` — bracket × threshold × entry-mode × cost sweep, strict gate, velocity → **dna_policy_gate.md** + **decile_9_10_diagnostic.md**.
- `audit_dna_pipeline.py` — static causal-invariant checks (+ run lookahead-auditor subagent).

## Engineering amendments (implemented)
1. **Block-wise distance.** DNA / Live blocks scaled *independently* with RobustScaler; soft-archetype probs kept in [0,1] (not standardized). Block weighting `0.40 DNA / 0.50 Live / 0.10 Arch` (and sweeps 20/70/10, 40/50/10, 60/30/10) implemented as **weighted-squared-Euclidean**: each RobustScaled block ×`√weight`, then a single NearestNeighbors gives `D²=Σ wᵦ·Dᵦ²`. (Tractable equivalent of the linear block-sum; ranking-equivalent in practice. Documented deviation.)
2. **ATR floor.** Every ATR-normalized feature uses `atr_norm = max(current_atr, 0.5·rolling_atr_60)` (rolling mean of last 60 1m ATRs) to prevent low-vol denominator blow-ups (the prior atlas showed 90-ATR artifacts). Affected: all `*_atr` DNA + label brackets.
3. **Soft archetype.** Hard KMeans label is a discovery artifact only. A walk-forward multiclass classifier maps DNA→cluster; `predict_proba` gives the soft vector. Bars 1–4 of a regime use a uniform `1/K` vector; bars 5+ use the classifier proba (per the amendment). Hard label retained for reporting only.
4. **Friction robustness.** Primary entry0/exit0.5tick; Stress entry0.5/exit0.5; Severe entry1.0/exit1.0; all + $5 RT. All policy results reported under all three.
5. **Velocity.** avg/median bars-to-PT, bars-to-SL, bars-to-regime-flip in every calibration/policy report.
6. **Stability audit.** Per DNA archetype: yearly prevalence, yearly outcome profile, drift; flag stable-vs-mutating archetypes.

## Frozen DNA features
Windows pre_5 / pre_15 / pre_30 (1m bars strictly before the flip), direction-normalized
to the NEW regime direction, ATR-floored. Price/structure (return, range, body-sum,
realized-vol, efficiency, chop, hh/ll count, failed-breakout count); compression/expansion
(atr_mean, atr_ratio_vs_60, range_ratio_vs_60, compression/expansion score); slope/trend
(lr_slope, ema9/21 slope, slope-accel, dist-to-ema9/21); volume (ratio, trend, zscore,
signed proxy); session context (time-of-day bucket, minutes since RTH open / to close,
is_rth, dist-to-VWAP, dist-to-session H/L, dist-to-overnight H/L).

## Forward labels (tradeable races, from next executable open, never across opposite 1m flip)
Brackets `pt050/sl025`, `pt075/sl050`, `pt100/sl050`, `pt150/sl075`, `pt200/sl100` — until
regime flip; plus 3/5/10-bar horizon variants for the tighter ones. Per bracket: pt_hit,
exit_px, reason {PT,SL,regime_flip,timeout}, bars_to_resolution. Plus bars_to_regime_flip.

## Strict deployment gate
OOS net>0 AND 2025 net>0 AND 2026 net>0 AND PF>1.05 AND passes under first-entry-only AND
max DD materially better than benchmark — under PRIMARY cost, robustness-checked under
stress/severe. Otherwise: non-deployable.

## Interpretation rule
Success ONLY if frozen origin + live state improves *monetizable forward payoff* (race +
money), not next-bar continuation. If no policy passes the gate, close the OHLCV
regime-memory branch and preserve the framework for future orderflow/microstructure features.
