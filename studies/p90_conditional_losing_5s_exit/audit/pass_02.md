# Look-Ahead & Timestamp Audit — Pass 02

**Date:** 2026-08-12
**Scope:** implementation/policy.py, implementation/validate.py, implementation/analysis.py, implementation/lineage.py, run_study.py (causality-relevant changes since Pass 01 in policy.py/validate.py; analysis.py/lineage.py re-checked, unchanged causal-path)
**Scope hash:** b45ef745ccfbed6d1623ebb8f44223188ff60ae64ed5352ae6729c3cd2dd88a8
**Lint:** 0 critical / 0 warning from causal_lint.py (8 files scanned)
**Verdict:** PASS

## Summary
- Critical: 0
- Warning: 0
- Note: 0

## Prior findings adjudicated

| # | Prior finding | Status | Evidence |
|---|---|---|---|
| N1 | Placebo `tau` anchored on `arm_ns`, pool values are `seconds_since_entry` — mismatched clock | **FIXED** | `policy.py:172-181`: candidate times now `entry_ns + round(tau*NS)`, window kept as `(cand > entry_ns) & (cand <= ts[-1])`. `times_pool` (`run_study.py:79`, `flips["seconds_since_entry"]`) is computed the same way (`policy.py:195`, `(fts-entry_ns)/NS`) — control and treatment now share one clock (`entry_ns`). No new leakage: `entry_ns` is the trade's own already-realized entry timestamp (verified causal in Pass 01, gate `V8`); the lower bound `cand > entry_ns` excludes self-matching the entry bar; the upper bound is unchanged (the trade's own horizon, already verified clean in Pass 01 item 9). |
| N2 | Exact-timestamp mark matching drops non-matching candidates rather than substituting | **ACCEPTED, closed** | `policy.py:183-185` unchanged (`ok = ts[pos]==flip_ts`, non-matches dropped, not snapped). Still agree this is the causally-safe choice — no substituted/unavailable price is ever credited. Closing per instruction; not re-raised. |

## New verifications (post Pass-01 changes)

1. **`_first_reach(level)` / `adverse_075_ns` / `adverse_100_ns`** (`policy.py:246-248,253`). Computed from `run_mae`, which is `np.maximum.accumulate` over that trade's own HIGH/LOW path from `start` forward — a causal, monotone landmark strictly within the trade's own realized window. `int(ts[int(h[0])])` returns the timestamp of the first bar (own path) reaching the level; nothing later than that bar is read to produce it. Consumption traced via grep: the only reader is `analysis.py:165-166` inside `signal_coverage()`, which builds `results/trade_level_signal_coverage.csv` (Phase 2 descriptive coverage) — not read by `simulate()`, `run_policy()`, any fill/label/idx decision, or any gate that feeds the verdict. CLEAN — matches the code comment ("no policy reads them").

2. **`n_placebo_candidates` / `n_placebo_unreached` → `p_unreached` (observed 0.365, `results/matched_placebo.csv`).** `n_cand` = size of the pooled `k` draw (independent of the trade's own realized count, per Pass-01 item 9, unchanged). `n_unreach` counts how many of those draws fell outside `(entry_ns, ts[-1]]`. The upper bound `ts[-1]` is the same trade-owned horizon (`session_close` or opposing-flip time) already established clean in Pass 01 — it is not additional information beyond what the length-blind construction already used to decide which candidate flips are reachable. Aggregation in `run_study.py:95-104` sums only over `entered` trades and is consumed solely as a disclosure column (`matched_placebo.csv`) and by gate `V13` (checks the pooling *flag*, not the rate). It does not feed `deltas`, `econ`, `paired_delta`, or `determine_verdict`. CLEAN — no dependence beyond the already-accepted per-trade horizon truncation.

3. **Gate `V10` now covers `COND_1.00` and `COND_0.75`** (`validate.py:96-104`, looped over both frames). Confirmed: `results/validation_report.json` shows 28/28 gates passing, including `V10_COND_1.00_fires_on_first_losing_flip` and `V10_COND_0.75_fires_on_first_losing_flip`. Pass-1 referral closed.

## Re-verified Pass-01 conclusions (unchanged code paths)

| Item | File:line | Status |
|---|---|---|
| Exact mark selection (`ts[pos]==flip_ts`) | `policy.py:183-185` | Unchanged, CLEAN |
| Fill = mark index + 1 (`start+idx+1`, open price) | `policy.py:213-214,229-234` | Unchanged, CLEAN |
| Stop/conditional tie → stop (`stop_fill<=cond_fill`) | `policy.py:213-221` | Unchanged, CLEAN |
| Confirmation absent from every exit rule (`confirm_idx` only labels/diagnostics) | `policy.py:219-221,259` | Unchanged, CLEAN |
| Fires on first losing flip (ascending loop, `fire_at<0` guard) | `policy.py:191-207`, gate `V10` (now both variants) | Unchanged + strengthened, CLEAN |
| Pooled placebo draws (`k`, `tau` from pooled dists) | `run_study.py:77-84` | Unchanged logic; anchor clock fixed per N1 above |

## Warnings
(none)

## Notes
(none — N1 fixed, N2 closed; no new notes raised)

## Referred to contract-checker
- `tests/` contains only `__init__.py` — no executable test coverage for `policy.py`/`validate.py` (test quality/completeness, contract-checker scope).

## Clean checks
- A1-A5, B1-B7/B9-B10, C1-C3, F1, G1-G2, H1-H4 — all re-verified clean on current tree (no causal-path changes in `analysis.py`/`lineage.py` since Pass 01).
