# Regime-sequence tradability: executive summary

**VERDICT: NO_SEQUENCE_HETEROGENEITY**

**"Can we prospectively identify when the regime-flip indicator is in an economically poor rotational/churn
state?"** No. The recent sequence of completed 1m regimes (efficiency, overlap, flip density, progress,
flip-price clustering, level memory, range expansion, HTF progress) carries no reproducible information about the
economics of the next regime or the next 2–4 regimes. Across 18 features, the largest Spearman correlation with
any forward outcome is |ρ| = 0.053.

**"Is the effect strong enough to justify building a classifier/gate?"** No. Only 5 of 18 features even keep the
sign of their next-regime effect from block A to block B. The best a-priori composite (ROTATION, 14.7% of trades)
is −0.12A worse in both blocks, but the 95% CI includes zero ([−0.24, +0.04] pooled), and forward efficiency and
flip rate do not differ at all. Excluding ROTATION leaves retained net at −0.10A/trade.

The chart distinction is real **in hindsight**: forward 3-regime escape distance correlates ρ = +0.68 with
forward P&L. It cannot be seen **in advance** because ATR-normalised regime statistics have no memory. Regime
duration, |displacement|/A, range/A and P&L all have lag-1 autocorrelation of 0.00–0.04, and a rotational
3-regime window predicts nothing about the next one (ρ = −0.015). Volatility clusters in points (ρ 0.37), but the
engine's ATR normalisation absorbs it (ATR lag-1 ρ 0.91).

## Answers to the report questions

| # | question | answer |
|---|---|---|
| 1 | Can completed-regime history distinguish expansion from rotation prospectively? | No |
| 2 | Which variables carry the most information? | None materially. Largest pooled next-3 spreads: `prog_same_last` +0.39A (A +0.48, B +0.07), `fails_at_level` −0.31A (same sign in both blocks, CI includes zero per block), `eff_5` −0.50A (the *wrong* direction for the hypothesis, B −0.05) |
| 3 | Low sequence efficiency → worse next regime? | No. Top-minus-bottom `eff_5`: A −0.17, B +0.08 |
| 4 | High overlap → worse economics? | No. `terr_ratio_5`: A +0.11, B −0.16 |
| 5 | High flip density → continued churn? | No. Duration lag-1 ρ = −0.001; `flips_30m` vs forward flip rate ρ = 0.034 |
| 6 | Lack of same-direction progress → continued rotation? | No. `frac_new_ext_4` and `prog_*` vs forward efficiency: |ρ| ≤ 0.01 |
| 7 | Clustered turning levels beyond efficiency? | No. `flip_disp_6` and `n_near_0p5_6`: signs flip between blocks |
| 8 | "Already tried and failed here" → another poor regime? | One same-sign residual: `fails_at_level ≥ 1` (25% of trades) is −0.09A (A) / −0.22A (B) on next gross. Per-block CIs include zero and it has no mechanism signature. It is a lead only |
| 9 | Does an expansion state persist? | Only through the feature window: 52% → 23% same-state after 1 → 3 flips, against a 20% base. The *outcome* does not persist |
| 10 | Does a rotation state persist? | Same: 50% → 27% (window overlap); forward rotation ρ(i, i+3) = −0.015 |
| 11 | Visible in the next regime? | No |
| 12 | Stronger over the next 2–4 regimes? | No. Next-3 spreads are larger in A units only because they sum 3 trades; signs agree 10/18 |
| 13 | Share of trades in the worst rotational state | 14.7% (883 of 6,024) |
| 14 | Their economics | gross −0.132, net −0.221 (A −0.146 / −0.238; B −0.087 / −0.168) |
| 15 | Retained population | gross −0.010, net −0.097 (A −0.026 / −0.116; B +0.039 / −0.043) |
| 16 | Replication across blocks? | No (sign agreement 5/18 next gross) |
| 17 | Symmetric long/short? | No consistent ordering: B shorts EXP +0.30 / ROT −0.12, B longs EXP −0.14 / ROT −0.05 |
| 18 | Does MTF add anything after sequence state? | Cannot say: cells of 22–271 with inconsistent signs; subdivision stopped |
| 19 | Enough heterogeneity for a regime-process classifier? | No |
| 20 | Smallest next model | None justified. At most, a two-contrast, pre-registered test of `fails_at_level ≥ 1` and composite ROTATION on next gross in the dark 20% (needs your approval; expected to be null) |
| 21 | Explicit negative | **The visually obvious expansion/channel distinction is not prospectively economically useful when measured from completed 1m regime history.** It is a hindsight description of paths whose ATR-normalised increments are memoryless |

## Implication for the proposed architecture

Step #1 (a regime-process gate built from 1m regime history) is not supported. That does not rule out a gate
built on something *outside* the ATR-normalised 1m regime sequence. The one ingredient that does persist is
raw volatility in points (range ρ 0.37 at lag 1). Because cost is fixed in points, that could matter for the
*net* economics of low-volatility sessions. That is a cost/volatility question, not a rotation question, and
this study did not test it. The earlier result `nq_conditional_future_value_2023` (LOCATION_ONLY) and this one
agree: neither the in-trade path nor the pre-flip sequence carries value information.

The NO_HISTORY group (fewer than 6 completed regimes or less than 30 min of segment history, i.e. mostly the start of RTH and just after a hole) has the best
economics in both blocks (gross +0.015 / +0.041, MFE 2.4A against 2.0–2.1A). That is a time-of-day effect, not a
sequence effect, and it was not investigated further.

## Integrity

- Population: 6,024 regimes = the audited `TRADE_EVENT_TIMELINE` (205 development sessions). The final 20% of
  2023, 2024, 2025 and 2026 were never loaded. Blocks come from `TEMPORAL_SPLIT_2023.json` (154 / 51 sessions).
- Parity (`artifacts/EXTRACT_AUDIT.json`): 0 mismatches on direction, ATR, entry open/timestamp, gross
  recomputed from the audited exit price, and the engine anchor (`start_price_1m` == detection-bar open). The
  chain has 5,735 contiguous links, and the 84 in-session holes are treated as history breaks.
- Causality: features use only regimes that are complete at the flip, 1m closes at or before it, and the
  audited T0 snapshot. Quintile/state cuts come from block A only.
- Cost: `terminal_cost_points` is NULL in the audited frame, so ntr `nq_default_v1` (0.725 pt round trip ≈
  0.09A) was used.
- The flat result was checked against positive controls: features correlate with each other (ρ −0.87, +0.63),
  and hindsight forward shape correlates with forward P&L (+0.34, +0.68).

## Runtime by phase

| phase | wall time |
|---|---|
| 0: reuse + parity + one raw-1s pass (5.38M bars) → `_work/REGIMES.parquet` | 15.5 s |
| 1–6: regime table, 18 features, 21 outcomes, atlas, bootstraps (300 session reps), composite, persistence, robustness | 1.7 s |
| Session overhead: locating the population/split/cost, and two parity-convention corrections | about 35 min of the session |

**Reused:** `TRADE_EVENT_TIMELINE.parquet` (population, gross, first touches, MTF alignment),
`TEMPORAL_SPLIT_2023.json`, the audited merged frame (hash-checked; HTF T0 snapshot, exit prices, engine anchor),
and the NQ 1s catalog through `CausalDataLoader`.

**Newly computed:** flip-close prices, regime high/low, trade MFE/MAE from entry, and the 1m close grid.

**What was unnecessarily expensive:**
1. There is no shared **regime ledger** (one row per completed regime: flip close, end close, high/low,
   duration, links). Each of the last five studies rebuilt part of one from the collector frame plus a 1s pass.
2. Conventions are undocumented in the audited table. `start_price_1m` is the detection-bar *open*, not the
   close, and the ledger has 84 silent holes. Two failed parity runs were needed to discover this.
3. The audited frame leaves `terminal_cost_points` and `terminal_net_pnl_*` NULL, so every study picks its own
   cost convention.

**Candidate shared primitive:** `research_workflow` regime-ledger materialisation. Per timeframe, one row per
completed regime with flip close / anchor / end close / high / low / duration / predecessor link, plus explicit
hole records, and costs applied from a declared contract. With it, this study is a 2-second query.

## Deliverables

`REGIME_SEQUENCE_FEATURE_DEFINITIONS.md`, `REGIME_SEQUENCE_STATE_TABLE.md`, `REGIME_SEQUENCE_REPLICATION.md`,
`REGIME_SEQUENCE_VERDICT.json`, `artifacts/REGIME_SEQUENCE_ATLAS.parquet` (feature × block × quintile),
`artifacts/REGIME_SEQUENCE_FORWARD_OUTCOMES.parquet` (one row per regime: features, outcomes, state), plus
`artifacts/FEATURE_SPREADS.csv`, `STATE_TABLE.csv`, `GATE_ARITHMETIC.csv`, `STATE_PERSISTENCE.csv`,
`ROBUSTNESS_DIR_MTF.csv`, `CONTROLS_AND_PERSISTENCE.json`, `EXTRACT_AUDIT.json`, `SEQUENCE_RUN.json`.
Reproduce with `python studies/nq_regime_sequence_tradability_2023/extract.py && python studies/nq_regime_sequence_tradability_2023/sequence.py`.
