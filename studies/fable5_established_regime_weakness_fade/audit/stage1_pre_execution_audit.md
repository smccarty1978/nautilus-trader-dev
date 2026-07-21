# Stage-1 Pre-Execution Lookahead / Timestamp Audit

**Scope:** `SPEC.md`, `common.py`, `build_stage1.py`, and `analyze_stage1.py` only  
**Audit phase:** pre-execution; the new Stage-1 pipeline has not been run  
**Final status:** **PASS — STAGE 1 MAY RUN**  
**Open findings:** **0 CRITICAL, 0 WARNING**

## Executive conclusion

The final Stage-1 implementation passes the mandatory lookahead/timestamp gate. The score-feature path loads no retrospective outcome columns; W4 scores are attached only after their 1-second-bar information is causally available; descriptive outcome labels remain isolated from score inputs and any future live filter; 2026 is sealed by an explicit timestamp firewall; the decisive W4-rise gate is paired within regime and has frozen minimum paired sample sizes; and regime/path timestamps use completed-bar boundaries.

Stage 1 contains no trades. The proposed Stage-2 fill/stop/exit contract is documented, but any Stage-2 implementation must receive its own pre-execution audit before it runs.

## Mandated audit checks

| Check | Result | Evidence |
|---|---|---|
| No future MFE/final-PnL labels enter live filters | **PASS** | `build_stage1.py:40-42,55-59` reads only the frozen model feature list plus causal gate/identity/time fields. It does not load opposing-flip labels, final PnL, future MFE, or terminal-outcome columns. Retrospective `final_flip_pnl_atr`, `peak_mfe_atr`, and cohort membership are constructed later and are used only for descriptive characterization/gating, never as W4 inputs or a live filter. The inspected frozen W4 feature manifest contains current/rolling state fields, not final outcome labels. |
| No 2026 information used for selection | **PASS** | `build_stage1.py:44-52` excludes every checkpoint at or after 2026-01-01 UTC by `observation_time`, independent of the upstream period label; `build_stage1.py:85` asserts the firewall. `load_regime_population` restricts regimes to `year <= 2025`, and `main` characterizes only `range(2021, 2026)`. `analyze_stage1.py` therefore cannot summarize or gate on a 2026 row. |
| All filtering features known at decision time | **PASS for Stage 1** | Stage 1 implements no trading filter. The candidate Stage-2 features declared in `SPEC.md:98-102` are running age/MFE/progress/retention plus a W4 crossing, all defined as causal state. Implementation remains subject to the Stage-2 audit. |
| W4 score causally available | **PASS** | A checkpoint observed at `T` includes the open-stamped `[T,T+1s)` bar and is treated as available at `T+1s`. `attach_w4` selects only `observation_time + 1s <= target`. It also requires the selected score to be no older than one native checkpoint cadence (30s in 2021-2024, 5s in 2025), preventing a capped 1,800-second score from being carried to a late-regime target. |
| Entry/exit timestamps causal | **N/A / PASS** | Stage 1 submits no orders. Descriptive entry/exit anchors use the last completed 1-second close strictly before each flip boundary, and regime path bars are sliced `[start,end)`. Touch and peak timestamps are reported at the 1-second bar-close boundary, not the open timestamp. |
| Stop/fill semantics documented | **PASS for specification** | `SPEC.md:30-33,103-110` declares market-FOK entry, fill-anchored 1.5-ATR resting GTC stop, gap-through handling, stop-first same-bar races, flip exits, costs, and censoring. No executable-validation claim is made by Stage 1. |
| Chronological splits preserved | **PASS** | Metrics label 2021-2024 as train and 2025 as validation. The gate is evaluated separately for each and requires both to pass. The upstream `secondary_oos` label overlaps Jun-Dec 2025 and 2026, so the final implementation correctly uses the actual UTC observation timestamp—not the upstream label—to retain all 2025 while excluding all 2026. |
| Exact score attachment timing | **PASS** | Scores are stable-sorted by `(regime_start_ns, observation_time)` and searched only within the exact regime key. The selected observation satisfies both causal availability and freshness. The NumPy slice-index optimization is semantically equivalent to per-regime DataFrame lookup. |
| Cohort math | **PASS** | All eight requested cohort masks match the prompt. Counts and percentages use the applicable split population as denominator. The key W4-rise statistic is now `median(w4_flip - w4_m60)` on paired winner rows, with frozen minima of 250 pairs in discovery and 50 in 2025 and a fail-closed insufficient-sample outcome. |
| Regime anchoring | **PASS** | F1 start/end flip boundaries define each completed regime; the final right-censored regime per year is excluded; ATR is frozen at the start flip; anchor/exit prices are completed closes before their boundaries; MFE uses bars after the start boundary and before the end boundary. |
| Gate leakage | **PASS** | Future path values define retrospective cohorts and the predeclared descriptive divergence gate only. They do not enter the W4 feature matrix or a live policy. The paired W4 comparison avoids differing-missingness population leakage. 2026 cannot be exposed by this run. |
| Path boundaries / isolation | **PASS** | The study writes only to its own `_work`, `results`, and `audit` directories. Upstream atlas/model inputs are read-only. `ROOT = Path(__file__).resolve().parents[2]` resolves to the repository root. |

## Gate and timestamp details

### Score feature provenance

- The frozen W4 bundle was fit on 2021-2024 checkpoints; the D10 threshold provenance records Jan-Feb 2025 calibration.
- Stage 1 does not retrain or tune W4.
- The score builder's read column set is derived from the frozen bundle feature list and contains no future outcome labels.
- `regime_start_ns = observation_time - round(regime_age) * 1s` matches the upstream fixed-grid checkpoint convention.
- Any pre-existing score cache is deleted and rebuilt, preventing stale pre-fix or 2026-contaminated cache reuse.

### Databento / 1-second timing

- Raw 1-second timestamps identify bar opens.
- A high/low touch or peak within the bar opening at `T` is causally known at `T+1s`; qualification/peak targets and reported elapsed times now use that close boundary.
- Retained ratios select only path bars whose opens are strictly before the decision target, so those bars have completed by the target.
- A W4 checkpoint at observation `T` is eligible for a target only when `T+1s <= target`.
- W4-at-target metrics additionally enforce one-cadence freshness, so missing late-regime coverage is represented as unavailable rather than stale forward-fill.

### Cohorts and gate

- Cohort 7 (`MFE >= 1.0 ATR and flip PnL >= +0.5 ATR`) and cohort 6 (`MFE >= 1.0 ATR and flip PnL < +0.5 ATR`) are retrospective labels, as intended.
- Structural metrics are evaluated independently on discovery and validation, with at least three of four conditions required.
- Winner count and paired-W4 count thresholds are frozen in `common.py` before results.
- The W4-rise condition is a paired within-regime median, not a difference of marginal medians.
- Failure of either split produces `NO_CLEAR_ESTABLISHED_REGIME_FILTER` and stops the study.

## Resolved findings across audit passes

### Resolved CRITICAL — premature 2026 exposure

The initial version scored and characterized 2026 during Stage 1. It now applies an exclusive 2026-01-01 UTC score cutoff, filters the regime population to 2025 or earlier, and loops only through 2025. A hard maximum-observation assertion protects the score artifact. No 2026 outcome can be written by Stage 1.

### Resolved CRITICAL — unpaired W4-rise gate

The initial version subtracted the median flip score from a separately populated median m60 score. It now takes the median of per-regime paired differences and reports paired count/fraction, with frozen minimum paired counts.

### Resolved CRITICAL — upstream period-label overlap

An intermediate fix excluded all rows labeled `secondary_oos`, but upstream defines that label as 2025-06-01 through 2026-04-29. That would have removed Jun-Dec 2025 W4 validation coverage. The final code filters by actual observation timestamp, retaining the full 2025 validation year while sealing 2026.

### Resolved WARNING — one-second timing offset

Time-to-touch and peak-to-flip metrics now use the close boundary of the 1-second touch/peak bar, matching causal observability and the score-target definition.

### Resolved WARNING — stale cache reuse

The builder now deletes and rebuilds any existing causal-score cache rather than accepting an unverifiable artifact from an earlier chronology/feature contract.

## Final disposition

**PASS.** Stage 1 may execute. Before any Stage-2 strategy/backtest code is run, invoke the lookahead/timestamp auditor again on the exact filter state machine, W4 crossing dispatch, NT entry/fill behavior, stop activation/fill behavior, and exit sequencing.
