# P90-Primed 5-Second Regime Impulse

Does the P90 / Top-10 fade arm become tradable if you require the 5-second regime
to already agree, and exit when it stops agreeing — instead of waiting out the
1-minute lifecycle?

**Verdict: `F4_NO_USEFUL_5S_EDGE`.** 26/26 validation gates pass. See `REPORT.md`.

## Status

| Phase | State |
|---|---|
| 0 — lineage reconciliation | **PASS** — every SPEC 2.2 target reproduced exactly |
| 5s regime build | **PASS** — bucket grid and row counts both reconcile |
| 5s regime parity vs literal engine replay | **PASS** — 7/7 tests, bit-equal |
| 1–11 — policy, controls, diagnostics | **complete** |
| gates V1–V14 | **26/26 pass** |
| `causal_lint` | **PASS** — 0 CRITICAL, 0 WARNING |
| `lookahead-auditor` | see `audit/status.json` |
| `contract-checker` | see `audit/status.json` |

## Headline

| | net / entered trade | net / ORIGINAL arm | **gross** / original arm |
|---|---:|---:|---:|
| A — accepted P90 lifecycle | −0.0518 | **−0.0516** | **+0.0057** |
| B — S1 (5s aligned, 1.00 ATR) | −0.0746 | **−0.0698** | **−0.0161** |
| C — S075 (5s aligned, 0.75 ATR) | −0.0735 | **−0.0688** | **−0.0151** |
| PLACEBO_EXIT (length-blind hold) | −0.0698 | −0.0654 | −0.0116 |

ATR units, cost = the accepted 2-tick round turn. Neither variant beats the
accepted lifecycle and neither is positive — **not even gross**, so this is not a
cost problem. **S1 minus PLACEBO_EXIT is −0.0045 ATR/arm, CI [−0.0159, +0.0078]:
it spans zero.** The 5s exit is statistically indistinguishable from a random
hold of the same length distribution.

## Run it

```bash
# 1. build the 5s regime timeline (writes _work/, not committed)
python -m studies.p90_5s_regime_impulse.implementation.regime_5s

# 2. prove it equals a literal aggregator + engine replay
python -m pytest studies/p90_5s_regime_impulse/tests -q

# 3. Phase 0 -- reproduce the accepted lineage or ABORT
python -m studies.p90_5s_regime_impulse.implementation.lineage

# 4. everything else
python -m studies.p90_5s_regime_impulse.run_study
```

Step 1 takes about 90s over 61.5M 1s rows; step 4 about 12s.

## What is new here, and what is inherited

**Inherited verbatim, not rebuilt:** the P90 arm. "P90" and the accepted "Top-10
arm" are the same population — `p80_p90_opportunity_continuation_ml/SPEC.md:76`
maps `P90 → top_10` at the same frozen thresholds. All 8,950 arms come from
`armed_fade_score_path_progression`, and Phase 0 reproduces its confirmation
rate, returns, MFE and MAE exactly before anything else runs.

**New in this study:** the 5-second regime. No 5s regime existed anywhere in the
canonical store — its "5s checkpoints" are model-scoring dispatch slots. SPEC
section 3 freezes it as the *same* sticky EMA3/EMA9 rule the 1m regime uses,
applied to 5s buckets built from the store's own 1s rows, with the engine running
continuously across ETH for warmup continuity. `tests/` proves the vectorised
build is bit-equal to a literal `TimeframeAggregator` + `RegimeStateEngine`
replay.

## This is not the prior 5s scalp study

`backtests/studies/regime_5s_scalps/` traded 5s flips **aligned with** the 1m
regime, with no prime. Here the P90 arm is the prime and the trade is **against**
the 1m regime; the 5s regime is a timing and holding state, not the signal.

The prior study is still the relevant adverse prior, and the report carries it:
it measured this exact exit rule — the 5s regime held to its next opposite flip —
at **gross +$0.66/trade, 45% win rate, net −$6.84** over 183,827 NQ scalps.

## Layout

```text
SPEC.md            the frozen contract; read this first
REPORT.md          the 15 answers, and why the verdict is F4
implementation/
  regime_5s.py     builds and queries the 5s regime timeline
  lineage.py       Phase 0 -- reproduce or ABORT
  policy.py        the impulse walk, both stops, both controls
  analysis.py      Phases 1-11 tables
  validate.py      gates V1-V14 and the computed verdict
tests/             5s regime parity vs a literal engine replay
results/           the SPEC section 6 deliverables
_work/             generated data, not committed
```
