# p80_p90_opportunity_continuation_ml

Signal-feasibility study, **2024 only**. Two independent questions:

* **Model A** — at a P80/P90 prime, does an attractive 2:1 forward payoff exist *now*?
* **Model B** — at a profitable post-confirmation rung, is favourable continuation likely?

**Verdicts: A3 NO USEFUL SIGNAL · B2 WEAK BUT PLAUSIBLE · P4 NEITHER WARRANTS EXPANSION.**
Read `REPORT.md` for the answers to Q1–Q20 and `SPEC.md` for the frozen contract.

## Reproduce

```bash
python scripts/causal_lint.py --study studies/p80_p90_opportunity_continuation_ml \
    --json studies/p80_p90_opportunity_continuation_ml/audit/lint.json
python -m studies.p80_p90_opportunity_continuation_ml.run_study 1 2 3 4 5 6
python -m pytest studies/p80_p90_opportunity_continuation_ml/tests/ -q
```

Stages are checkpointed to `results/`: 1 populations+labels · 2 baselines (before
any fit) · 3 Model A temporal OOS · 4 Model B temporal OOS · 5 ablations ·
6 validation + advancement gates + `summary.json`. Whole run ≈ 80 s.

## What it reads

`data/canonical/regime_complete_v1/` (scores, paths, regimes, threshold contracts),
the accepted arm table from `armed_fade_score_path_progression`, and the accepted
rung events from `post_confirm_profit_ratchet`. **2021, 2022, 2023, 2025 and 2026
are never opened** — every loader filters `entry_year == 2024` at the source scan
and every produced frame is re-asserted on America/Chicago calendar year.

## Two things a future reader should not have to rediscover

**1. `p80_to_p90_seconds` is look-ahead at a P80 candidate.** It is the elapsed gap
between the two crossings, so at a P90 candidate both events are past — but at a
P80 candidate the P90 crossing has not happened yet. It carried **+0.267
permutation AUC** and was the entire first-run P80 result (AUC 0.734 → 0.531 once
removed). Gate **V14** now hard-asserts that no cross-prime field references a
future timestamp. The tell was the P80/P90 *asymmetry*, not the magnitude.

**2. P90 is essentially a subset of P80, not a stronger population.** 1,764 of
2024's regimes carry both primes; 299 are P80-only; **7** are P90-only. P80 leads
by a median 60 s. Anyone tempted to treat "P80 → P90 escalation" as a funnel should
know the funnel is almost the same set of regimes 60 seconds apart.

## Frozen decisions worth knowing before extending this

* **Feature set is the canonical inline 25, not Top-100** — the Top-100 vectors
  are not in the canonical store, and the per-year surfaces that hold them cover
  only 75.1% SHORT / 81.4% LONG of 2024 in-domain checkpoints on a *different*
  established-regime filter, with an unfixed 1s look-ahead on the SHORT side only.
  SPEC §3 records the full reasoning. This is the study's largest untested axis.
* **Model A is two separate models** (one per prime), never pooled.
* **Model B pools all six rungs** with `rung_atr` as a feature — 2024 alone cannot
  support six per-rung models — and every table breaks out by rung.
* **Model B's exit-warning score is the OPPOSITE model.** After confirmation the
  prevailing regime has flipped into the trade, so the in-domain model is the one
  whose flip would *end* the trade.
* Folds are calendar (train Jan–Jun / eval Jul–Sep; train Jan–Sep / eval Oct–Dec),
  assigned at **trade level** for Model B. There is no random split in the code.
