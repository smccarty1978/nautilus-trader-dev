# Look-Ahead & Timestamp Audit — fable5_short_rth_threshold_ladder

**Date:** 2026-07-17 (Pass 4 — final)
**Scope:** `studies/fable5_short_rth_threshold_ladder/run_ladder.py`, plus its direct imports read for
comparison:
- `studies/CODEX_5_X_weakness_atlas_repair/CODEX_5_X_run_established_fade.py`
  (`canonical_regime_timeline`, `is_rth`, `load_checkpoint_stream`, `progress_window_counts`,
  `strict_threshold_cross`, `validate_raw_bars`, and reference `build_candidates`/`simulate`)
- `studies/codex_5_w4_multi_candidate_reentry/run_study.py` (`collect_candidates` — reference for the
  `candidate` basis) and its frozen `_work/candidates_{year}.parquet` (provenance verified)
- `studies/fable5_specialized_w4/fable5_common.py` (`simulate_trade_arrays`, the already-audited
  Policy A management replay)
- `studies/CODEX_5_X_weakness_atlas_repair/CODEX_5_X_established_fade_policy.json` (frozen filter +
  direction thresholds)
- `studies/fable5_nt_short_rth_policy_a/build_schedule.py` and the frozen
  `short_rth_schedule_{2025,2026}.parquet` artifacts (`fixed807` basis / `executed_regimes` source)
- `studies/codex_5_w4_fade_confirmation_clock_isolation/results/isolation_trade_diffs.parquet`
  (`gate_fixed807`'s Policy A reconciliation target)

**Auditor:** lookahead-auditor v1 — pre-execution/near-execution gate per CLAUDE.md.

## Revision history

- **Pass 1:** 0 CRITICAL, 1 WARNING (`entry_fill_ts >= confirm_flip_ns` ungated for the three
  experimental thresholds), 2 Notes.
- **Pass 2:** WARNING verified closed (guard + assertion, all four thresholds). Note 1 accepted.
  Note-2 cleanup introduced a `NameError` regression in `decide()` — reported as non-causal but
  blocking.
- **Pass 3:** `NameError` verified fixed; study executed end-to-end. Study grew a second basis
  (`candidate` vs `fixed807`) with two new reconciliation gates (`gate_candidate`, `gate_fixed807`)
  and a rewritten `decide()`. Reviewed directly and found one new WARNING: `decide()`'s
  `EARLIER_THRESHOLD_PROMISING`/`..._HURTS_DD` branch did not cross-check the deployable `candidate`
  basis against the hindsight-filtered `fixed807` basis, unlike the symmetric check present in the
  `beats.empty` branch.
- **Pass 4 (this revision, final):** Re-read `decide()` after the coordinator's fix. Verified
  independently (not accepted from description alone):
  - `beats` is now computed on the deployable `candidate` basis.
  - The `fx.loc[tau, "net_pnl"] <= ctrl_f.net_pnl` check now executes **before** any of
    `UNSTABLE_BY_YEAR`, `HURTS_DD`, or `PROMISING` can be returned — gating all three promotion paths,
    not just the `beats.empty` path.
  - Docstring corrected to describe `fixed807` as a hindsight-filtered diagnostic pocket, not
    "deployment-relevant."
  - `ast.parse` confirms no syntax defects.
  - Cross-checked the regenerated manifest directly: `runner_sha256` matches the current file's hash
    exactly; `decision` = `EARLIER_THRESHOLD_ADDS_TOO_MANY_FALSE_STARTS`; gate counts are candidate
    650/222 and fixed807 604/203, `net_pnl` 20304.00 + 6709.10 = 27013.10 (≈ +$27,013), both bases
    0 mismatches — matching the reported figures exactly.

  **WARNING closed.**

## Summary

- Critical: 0
- Warning: 0
- Note: 1 (dormant, accepted, no action required)

## Resolved findings (all verified directly against the current file, not accepted from description)

### `run_ladder.py:100-124` — fill-at/after-aligning-flip guard (original Pass-1 WARNING)

`if fill_ts >= regime_end: break` plus the post-generation `(entry_fill_ts < confirm_flip_ns).all()`
assertion, applied inside `generate_entries` for all four thresholds. Matches the reference
`CODEX_5_X_run_established_fade.py:370-373` invariant. **Closed.**

### `run_ladder.py:316` (formerly line 279) — `NameError` regression (Pass-2 finding, non-causal)

`y`/equivalent local variables are correctly scoped in the current `decide()`; confirmed by direct
read and by `ast.parse` succeeding. **Closed.**

### `run_ladder.py:300-329` — `decide()` decision-labeling gap (Pass-3 WARNING)

```python
300 def decide(summary: pd.DataFrame) -> str:
301     """Decision anchors on the DEPLOYABLE candidate basis (what a live lower-tau
302     strategy would actually trade: all first-crossings). The fixed-807 overlay
303     is a hindsight-filtered diagnostic pocket (its regime set is only knowable
304     from the executed higher-threshold run) that isolates PURE entry timing on
305     the confirmed 807 regimes; it is used to tell a genuine entry-timing
306     improvement apart from mere added-trade volume / false starts."""
307     cand = summary[(summary.basis == "candidate") & (summary.split == "combined")].set_index("threshold")
308     fx = summary[(summary.basis == "fixed807") & (summary.split == "combined")].set_index("threshold")
309     ctrl_c, ctrl_f = cand.loc[CONTROL], fx.loc[CONTROL]
310     beats = cand[(cand.index < CONTROL) & (cand.net_pnl > ctrl_c.net_pnl)]
311     if beats.empty:
312         return "CURRENT_THRESHOLD_STILL_BEST"
313     for tau, r in beats.sort_index(ascending=False).iterrows():
314         if fx.loc[tau, "net_pnl"] <= ctrl_f.net_pnl:
315             return "EARLIER_THRESHOLD_ADDS_TOO_MANY_FALSE_STARTS"
316         cy = summary[(summary.basis == "candidate") & (summary.threshold == tau)
317                      & (summary.split.isin(["2025", "2026"]))].set_index("split")
318         cc = summary[(summary.basis == "candidate") & (summary.threshold == CONTROL)
319                      & (summary.split.isin(["2025", "2026"]))].set_index("split")
320         if not all(cy.loc[sp, "net_pnl"] > cc.loc[sp, "net_pnl"] for sp in ("2025", "2026")):
321             return "EARLIER_THRESHOLD_UNSTABLE_BY_YEAR"
322         if r.max_closed_dd > ctrl_c.max_closed_dd:
323             return "EARLIER_THRESHOLD_IMPROVES_ENTRY_BUT_HURTS_DD"
324         return "EARLIER_THRESHOLD_PROMISING"
325     return "CURRENT_THRESHOLD_STILL_BEST"
```

The `fixed807`-vs-control check (line 314) now runs unconditionally for every candidate-beating `tau`,
**before** any of `UNSTABLE_BY_YEAR`/`HURTS_DD`/`PROMISING` can be reached — so it is no longer
possible for `decide()` to return a promotion verdict based solely on the non-deployable `fixed807`
population without the deployable `candidate` population's improvement first being established
(`beats` itself is candidate-anchored) and the entry-timing-isolation check on `fixed807` also passing.
Both-year stability (`cy`/`cc`) is checked on the `candidate` basis, consistent with `beats` being
candidate-anchored. Docstring now accurately reflects `fixed807`'s role as a diagnostic discriminator,
not a deployable population. **Closed — no objection.**

### Note 1 (busy_until / cross-regime overlap) — still dormant, still accepted

Unchanged from Pass 2/3: regimes are sequential and non-overlapping by construction, each trade's
scheduled exit is anchored at the next regime's start, and the 120s `regime_age_s_min` floor prevents
realistic overlap. No causal or look-ahead concern. Documented, no code change required.

## Clean checks (causal/look-ahead scope, cumulative across all passes)

- **Causal state only.** `generate_entries` uses only causal fields: frozen W4 score stream,
  checkpoint's own atlas row, `progress_window_counts` (imported unmodified), `running` as a causal
  cumulative max over raw highs strictly within `[a:b)`. `k` is verified as the last completed bar
  strictly before `decision`. The unconditional `running[k] ≈ cp.current_mfe` assertion is intact.
- **Entry fill timing.** Fill is the first raw bar with `ts >= decision`, additionally guarded to
  precede `confirm_flip_ns` for all four thresholds. `MAX_AGE_NS` horizon cap matches the reference
  `collect_candidates` exactly.
- **Threshold-lowering cannot introduce look-ahead.** The same fixed causal checkpoint stream is
  reused across all four τ values; regime timeline and opposing-flip lookups are computed identically
  regardless of τ.
- **Both control gates are genuine independent-provenance checks, not tautologies.**
  `gate_candidate` reconciles against `codex_5_w4_multi_candidate_reentry`'s independently-produced
  `collect_candidates` output (verified: 650 rows for 2025 match `YEAR_CAND_COUNT`). `gate_fixed807`
  reconciles entry, exit timestamp, exit reason, and net PnL against
  `codex_5_w4_fade_confirmation_clock_isolation`'s re-simulated Policy A output over the same frozen
  807-entry population — a stronger, full-trade-level gate than the original entry-only check.
  `executed_regimes` (defining the `fixed807` population) is fixed once per year from a pre-existing,
  τ-independent frozen artifact, outside the threshold loop — no data-snooping or circularity.
- **Policy A replay inputs are causal/frozen.** `replay()` passes only already-causal, already-fixed
  fields into `fable5_common.simulate_trade_arrays` (the already-audited engine). `entry_timing()`,
  `metrics()`, `monthly()` run strictly after all trades are generated/replayed and feed nothing back
  into entry/exit logic.
- **`decide()` cannot silently select a 2026-only winner.** Both-year stability check (candidate basis)
  requires improvement over control in both 2025 and 2026 individually.
- **RTH filter is entry-only,** applied via the unmodified `is_rth` to the fill timestamp only.
- **Accepted caveats, not re-litigated:** offline 1s-OHLC sim (not NT-native); frozen W4 score stream
  reused as a precomputed causal artifact; gap-through stop fills priced at trigger, inherited from the
  already-audited `simulate_trade_arrays` engine.

## Empirical confirmation (this pass)

- `runner_sha256` in `results/w4_short_rth_threshold_ladder_manifest.json` matches the current
  `run_ladder.py` file hash exactly — the manifest reflects the code actually reviewed here, not a
  stale prior version.
- `decision` = `EARLIER_THRESHOLD_ADDS_TOO_MANY_FALSE_STARTS`.
- `control_parity.candidate_basis`: 650/222 trades, 0 mismatches (2025/2026).
- `control_parity.fixed807_basis`: 604/203 trades, 0 mismatches, `net_pnl` = 20304.00 + 6709.10 =
  27013.10 (≈ +$27,013 as reported).

---

*Audit complete. All causal/look-ahead findings across four passes are resolved and independently
verified against the code and the run manifest, not accepted from description alone. The study's
trade-level outputs (both `candidate` and `fixed807` bases) are causally sound, correctly labeled, and
reconciled exactly against independently-provenanced frozen artifacts. `decide()`'s decision string is
now gated consistently across all promotion branches by the deployable-vs-diagnostic-pocket
cross-check.*

**Status:** **PASS**
**Findings:** **0 CRITICAL, 0 WARNING**
