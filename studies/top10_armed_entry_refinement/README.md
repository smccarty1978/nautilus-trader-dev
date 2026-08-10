# Top-10 Armed Entry Refinement

**Entry study only.** Asks whether any causal trigger after a Top-10 arm beats
entering immediately, given that deeper thresholds buy confirmation probability
by entering later and giving up remaining move.

Frozen contract: [`SPEC.md`](SPEC.md) · Results: [`REPORT.md`](REPORT.md)

**Verdict: `A — IMMEDIATE TOP-10 REMAINS THE BEST EARLY ENTRY`.** Confirmation
and remaining move trade off at a near-constant ~0.30 ATR per 0.10 of
probability, across every family tested, and every waiting rule also loses
throughput.

---

## Three things to know before reading a table

### 1. Both denominators matter

`P(confirm | entered)` alone flatters selective triggers. Only 82% of arms ever
reach Top-5 and only 38% reach Top-1, so the primary table also carries
**confirmed trades per 100 arms**. Immediate Top-10 leads it at 52.0; Top-1
manages 27.8 despite a 0.731 conditional rate.

### 2. The arm is a state, not a position

An adverse move before the trigger costs nothing, so later rules can enter in
cases where immediate Top-10 was already stopped out. That **free option**
flatters every waiting rule — 9.3% of `INTERP_L1` entries up to 56.4% of Top-1
entries. Every candidate reports `pct_entries_after_arm_1atr_adverse`. The study's
conclusion is robust to it only because waiting loses anyway.

The armed window is bounded by the **session close**, and structurally by the
armed regime itself: post-arm score rows carry the *old* regime's id, so nothing
can fire at or after the confirming flip. Verified — of 86,278 entries, zero land
strictly after.

### 3. The intermediate levels are NOT percentiles

The frozen calibration distribution is unrecoverable (bullish 216,828 observed vs
171,334 contracted; bearish 172,031 vs 163,397, and that population is a
model-development artifact predating the store). Family A therefore uses
**arithmetic between two frozen contract values** — the ⅓ and ½ points from
Top-10 to Top-5 — labelled `INTERPOLATED RESEARCH LEVEL — NOT A PERCENTILE`
everywhere. They carry no calibration guarantee and may not become contracts.

| Level | Bullish | Bearish |
|---|---:|---:|
| frozen `top_10` | 0.431672 | 0.445591 |
| `INTERP_L1` | 0.456684 | 0.466548 |
| `INTERP_L2` | 0.469190 | 0.477027 |
| frozen `top_5` | 0.506708 | 0.508462 |

---

## Reproducing

```bash
python scripts/causal_lint.py --study studies/top10_armed_entry_refinement \
    --json studies/top10_armed_entry_refinement/audit/lint.json
python -m pytest studies/top10_armed_entry_refinement/tests -q

python -m studies.top10_armed_entry_refinement.implementation.paths      # cache
python -m studies.top10_armed_entry_refinement.analysis.separation       # Phase 2
python -m studies.top10_armed_entry_refinement.analysis.evaluate         # Phases 4-6
python -m studies.top10_armed_entry_refinement.implementation.validate
```

`paths` is the expensive step (~10 min) and is cached; every trigger is a query
over its parquet, so no candidate re-reads the score store.

## Module map

| Path | Role |
|---|---|
| `implementation/paths.py` | cached post-arm true-dispatch stream + Phase 1 diagnostics |
| `implementation/candidates.py` | the 4 baselines, 8 candidates, and the trade walk |
| `analysis/separation.py` | Phase 2 — landmark AUC / effect sizes, SUCCESS vs FAILURE |
| `analysis/evaluate.py` | Phases 4–6 — tradeoff table, both frontiers, stability |
| `implementation/validate.py` | the twelve SPEC §8 gates |

## Two defects worth remembering

> **Bounding the armed window at the arm's terminal event silently imposes
> adverse invalidation.** For failed arms the terminal event *is* the 1 ATR stop,
> so triggers could never fire after it. Populations came out 20–130% too small
> and the baselines did not reproduce the accepted figures — which is how it was
> caught. Baseline parity is a real test, not a formality.

> **A run-length built from row positions is off by one.** The group boundary
> increments *on* the non-qualifying row, so that row joins the next group and
> every streak preceded by a miss reads one too high. Cum-sum the flag inside the
> group instead. Caught by a validation gate at 313/400 mismatches.

## Disclosures

- **2025 is NOT threshold-out-of-sample** — inherited overlap waiver
  `studies/full_trade_path_builder/THRESHOLD_OVERLAP_WAIVER.json`. 2026 untouched.
- **Family E (fast progression) was not nominated.** Slope AUC peaked at
  0.62–0.67, declined with elapsed time, and `slope_60s` had no coverage at any
  landmark. Its slot went to better-supported families.
- **Process deviation:** `causal_lint` ran pre-execution and was clean, but the
  `lookahead-auditor` pass ran after the first full run (before any result was
  finalised). Recorded in REPORT §7.
