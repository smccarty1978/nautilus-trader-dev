# Look-Ahead & Timestamp Audit — Pass 02

**Date:** 2026-08-10
**Scope:** reconciliation/reconcile.py (new); implementation/phase0_gate1.py (cosmetic-only, verified)
**Scope hash:** 60d4c0aca7597d54e0cfc62e845bfd73b73a95e033c981298c7bde72c63b55de
**Lint:** 0 critical / 0 warning from causal_lint.py (15 files scanned)
**Verdict:** PASS

## Summary
- Critical: 0
- Warning: 1
- Note: 2 (carried, unaddressed — files not in this pass's diff)

## Prior findings adjudicated
| # | Prior finding | Status | Evidence |
|---|---|---|---|
| N1 | Quantile cutoff computed from full pooled 2021-2025 cross-section, not held out (`landmark_tradeoff.py`, `gate2_ledger.py`) | NOT ADDRESSED — carried, non-blocking | `git diff --stat -- studies/post_confirmation_score_deterioration/analysis/` is empty; these files are untouched this pass. Still not a look-ahead defect per pass-1 reasoning (cross-sectional, not forward-in-time; SPEC frames as characterization). |
| N2 | Tie-break policy for duplicate `checkpoint_decision_ns` within a `regime_id` not explicit | NOT ADDRESSED — carried, non-blocking | Same files unchanged. `reconcile.py` has its own equivalent (`.tail(1)` after `.sort("checkpoint_decision_ns")` in `sample_table()`) which is unambiguous (last by timestamp), but doesn't touch the original `landmark()`/`snapshot()` aggregations N2 refers to. |

## New code audit — reconciliation/reconcile.py

**1. Independence claim (docstring lines 6-8, `post_confirm_rows` line 176-177).**
Verified: `post_confirm_rows()` reads only `STORE/canonical_regime_scores_all.parquet`
and joins against `trades` (itself built from `PRIOR` =
`armed_fade_score_path_progression/results/armed_regime_score_paths.parquet` +
`canonical_regimes_all.parquet`). Grepped the whole file — `results/post_confirm_paths.parquet`
(the study's own panel, written by `build_panel.py:167`) is never opened anywhere in
`reconcile.py`. The independence claim holds; the Codex-count reproduction
(`canonical_coverage_recompute.json`: all four labels + FAIL total match Codex exactly)
is not circular.

**2. Direction→model mapping (`reconcile.py:197-201`).**
`raw_domain_score`/`strict_in_domain` gate bullish iff `direction==1`, identical in
structure and outcome to `build_panel.py:120-122` (`score_b`) and
`phase0_gate1.py:135-137` (`domain_model_raw_score`). All three independently-written
expressions agree. Window filter `[confirmation_ns, terminal_ns]` (line 192-193)
matches `build_panel.py:112-115`'s `[confirm_ns, terminal_ns]`. Confirmed clean.

**3. `landmark_availability()` `score_age_s` (line 260-278).**
`last_raw_ns` is `max(checkpoint_decision_ns)` taken from `upto`, which is already
filtered to `elapsed_s <= h` (line 264-267) *before* the aggregation — so `last_raw_ns`
cannot exceed `confirmation_ns + h*NS` by construction. Empirically confirmed:
`score_age_at_landmark_s` in `landmark_availability_reconciliation.json` is
non-negative at all four landmarks (min 0.0, max 55-85s — consistent with the panel's
documented sparse ~5s cadence). No forward-fill, no as-of join, no negative age.
Confirmed clean.

**4. `sample_table()` per-landmark snapshot (line 393-397).**
`upto = blk.filter(elapsed_s <= h)`, then `last = raw.tail(1)` on a frame pre-sorted
ascending by `checkpoint_decision_ns` — the latest *causally available* dispatch,
never one after the landmark. Confirmed clean.

**5. Empirical `lineage()` claims (line 43-92).**
Reproduced: `score_is_new_all_true` = true for both models over all 5,665,103 RTH
rows; `available_ns_minus_decision_ns` min==max==0 for both models. These are
whole-store facts (stronger than the trade-restricted claim used in the docstring),
correctly computed with `.all()`/`.min()`/`.max()` over the full RTH-filtered frame,
and they do support "causally available, not carried forward": a dispatch that is
always `is_new` and always available at `checkpoint_decision_ns + 0` cannot be a
stale/forward-filled value. `phase0_gate1.py`'s cited landmark coverage (0/4,594,
0/4,403, 61/3,908, 525/3,209) reproduces exactly from `landmark_availability_reconciliation.json`.

## Warnings

### [reconcile.py:413] `sample_table()` reports the wrong model's dispatch-freshness flag for SHORT trades
`"score_is_new": bool(last["bullish_score_is_new"][0])` is unconditional — it does
not branch on `tr["direction"]` the way `study_reported_ood_score` (line 401-403)
correctly does. For a SHORT trade (`direction == -1`), `raw_domain_score` is sourced
from `bearish_probability`, but the reported freshness flag reads
`bullish_score_is_new`, the wrong model.
**Why not CRITICAL:** `lineage()` independently establishes `bullish_score_is_new`
and `bearish_score_is_new` are both `True` for 100% of the 5,665,103 RTH rows
(line 56-58 output), so the mismatched read cannot currently produce a wrong value —
every possible read returns `True`. This field also does not feed
`coverage_recompute()` or `landmark_availability()`; it is diagnostic-only in the
sample parquet. If either model's `*_score_is_new` ever has a `False` row in future
data, this field would silently misreport for shorts.
**Smallest fix:** `pl.when(direction==1).then(bullish_score_is_new).otherwise(bearish_score_is_new)`, same pattern already used for `study_reported_ood_score`.

## Notes
None new this pass.

## Referred to contract-checker
None identified in this pass.

## Cosmetic-change verification — implementation/phase0_gate1.py
`git diff` shows exactly: (a) docstring expansion citing the reconciliation, correcting
prior mislabeled prose ("OUT-OF-DOMAIN score" → "raw, ungated probability of the
domain-matching model" — a documentation-accuracy fix, not a semantics change), and
(b) a pure identifier rename `in_domain_score` → `domain_model_raw_score` at three
call sites (`build_panel()`, `main()` dict keys, `main()` print loop). The
`pl.when(direction==1).then(bullish_probability).otherwise(bearish_probability)`
expression is byte-identical before and after. Re-ran `results/phase0_gate1.json`:
`domain_model_raw_score` AUC-last at the four horizons is 0.6843 / 0.7353 / 0.7527 /
0.7801 — matches the reported bit-identical values exactly. Confirmed cosmetic only.

## Clean checks
A1-A5 (n/a, no NT strategy/bar code), B1-B7 (no shift(-N)/bfill/center in
`reconcile.py`), C1-C3 (population/window construction mirrors already-audited
`build_panel.py`, no new label logic), F1-F2 (RTH pre-filter preserved, same
`[confirm_ns, terminal_ns]` window), G1-G4 (reads canonical store unchanged, no
new resampling), H1-H4 (no bracket/trigger simulation in `reconcile.py` — pure
provenance arithmetic).
