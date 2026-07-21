# 5s Regime Scalp Study Inside Active 1m Regimes — SPEC

## Objective
Evaluate whether 5s regime flips that align with the active 1m regime direction exhibit positive bracket-race expectancy. We evaluate each aligned 5s flip as an independent scalp trade (not as an add-on to the 1m trade) to determine if this can be a repeatable, profitable intraregime scalp strategy.

## Timeframes and Engines
* **1s clock**: Replays 1s bars chronologically for execution and path evaluation.
* **5s clock**: Dictates the scalp entry trigger. Flips to align with 1m regime.
* **1m clock**: Dictates the parent trend regime direction.
* **5m clock**: Latest completed 5m bar provides macro-alignment context.

## Entries
* **Trigger**: A 5s bar closes at `tse_5s`, causing the 5s regime to flip (change from previous and non-zero) and match the active 1m regime direction:
  * `regime_5s == regime_1m` and `regime_1m != 0`.
* **Fill Price**: Open price of the first 1s bar after the 5s bar close (next-1s-open; signal bar ≠ fill bar → no same-bar leakage).
* **Entry Slippage**: 0.0 ticks.
* **Direction**: Aligned with the 1m regime (+1 for bullish, -1 for bearish).
* **Session**: RTH-only. The fill bar's wall-clock (ts_event in Central Time) must fall in [08:30, 15:00) CT; ETH triggers are dropped (thin overnight liquidity makes the 0.5-tick slippage assumption unrealistic and pools a structurally different market).
* The primary unit of analysis is the **aligned 5s flip**, not the parent 1m trade. Multiple scalps may occur within one 1m regime. Every 5s flip is also recorded as a "no-bracket held-to-flip" candidate so the side question (is the 5s regime profitable held to its next opposite flip?) is answered directly.

## Brackets and Normalizations
We evaluate 8 bracket combinations under 2 different ATR normalizations:

### Brackets
* **Symmetric 1:1**:
  * PT 0.25 ATR / SL 0.25 ATR
  * PT 0.50 ATR / SL 0.50 ATR
  * PT 0.75 ATR / SL 0.75 ATR
  * PT 1.00 ATR / SL 1.00 ATR
* **Positive RR**:
  * PT 0.50 ATR / SL 0.25 ATR
  * PT 1.00 ATR / SL 0.50 ATR
  * PT 1.50 ATR / SL 0.75 ATR
  * PT 2.00 ATR / SL 1.00 ATR

### ATR Normalization
* **ATR_5s**: Using the Wilder ATR(14) of the triggering 5s bar.
* **ATR_1m**: Using the Wilder ATR(14) of the latest closed 1m bar.

## Termination Rules
Each scalp trade terminates at the earliest of:
1. **PT hit** (checked on 1s OHLC).
2. **SL hit** (checked on 1s OHLC, stop-first if both hit in the same bar).
3. **5s regime flips against us** (`regime_5s == -direction`). This rule is only applied in the `bracket-or-5s-flip` exit flavor.
4. **Parent 1m regime flips against us** (`regime_1m == -direction` or `regime_1m == 0`).
5. **Max hold reached**: Checked for 30s, 60s, 90s, 120s, and 300s.

## Cost Model (Friction)
* **Gross**: 0 slippage, 0 commission.
* **Primary Cost**: 0.5-tick exit slippage ($2.50 per contract), $5 round-trip commission. Total cost: $7.50/contract.
* **Stress Cost**: 1.0-tick exit slippage ($5.00 per contract), $5 round-trip commission. Total cost: $10.00/contract.

## Selection vs Validation (no in-sample overfit)
* **In-sample (IS):** 2021–2024. The single best bracket config and all tertile bucket edges are selected/fit on IS only.
* **Out-of-sample (OOS):** 2025, never used for any selection. The IS-best config and the IS-fitted bucket edges are applied **unchanged** to OOS and reported side-by-side. The OOS number is the deployment-relevant one. Any IS bucket "winner" that does not survive OOS is treated as multiple-comparisons noise (per MEMORY `grid_tune_vs_validate_separation`).

## Instruments (config-driven)
The same audited pipeline runs per instrument via `--instrument {NQ,ES}`. Only the catalog, bar type, and dollar economics change — the causal replay logic is identical, so the look-ahead audit carries over (changing `$/pt` cannot introduce look-ahead). Outputs are prefixed: NQ → `5s_scalp_*`, ES → `es_5s_scalp_*`.
* **NQ**: `NQ_v0_2020_2026`, $20/pt, $5/tick → 0.5-tick = $2.50.
* **ES**: `ES_v0_2020_2026`, $50/pt, $12.50/tick → 0.5-tick = $6.25.
* Commission $5 RT for both. RTH window 08:30–15:00 CT (same CME equity-index cash session).

## Causality & Audit
* All MTF state (5s/1m/5m regime, ATR, EMA) comes only from the `CompletedBarRegistry`, which enforces `state.close_ts <= decision_ts`. `_snapshot_features` asserts `audit_provenance(decision_ts)` before reading.
* Regime-flip exits fill at the bar **open** (the price at the instant the opposing bucket's close is known), preceding that same bar's intrabar PT/SL. No phantom fills (every exit price lies within the bar's OHLC).
* Audited with the `lookahead-auditor` subagent over two cycles → **0 CRITICAL, 0 WARNING**. Acknowledged NOTES (do not affect the Q1/Q2 verdict): (N-A) same-bar PT+SL ties resolve pessimistically to SL; (N-B) parent-1m MFE/MAE segmentation features track 1s closes (not intrabar H/L), so parent-quality buckets slightly understate excursions; (N-C) ATR=NaN/0 → 1.0 fallback, ~0 in-year trades affected due to the 5-day warmup lead-in.

## Critical Questions
* **Q1**: Do aligned 5s regime flips inside active 1m regimes have positive expectancy?
* **Q2**: Are they positive after realistic costs?
* **Q3**: Do they work better as 1:1 scalps or positive-RR scalps?
* **Q4**: Does performance depend on position inside the parent 1m regime?
* **Q5**: Are recovery flips after early 5s opposition better than immediate aligned flips?
* **Q6**: Does 5m alignment materially improve performance?
* **Q7**: Do EMA slope/distance features identify better 5s flips?
* **Q8**: Do volume/participation features identify better 5s flips?
* **Q9**: Are results stable by year and side?
* **Q10**: Can this become a repeatable intraregime scalp strategy, or is it another near-scratch gross edge consumed by costs?
