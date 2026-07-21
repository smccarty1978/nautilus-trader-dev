# Look-Ahead & Timestamp Audit — Fable 5 Pre-Flip D10 Reversal Entry (OFFLINE pipeline, pre-execution)

**Date:** 2026-07-11
**Scope:** `studies/fable5_pre_flip_d10_reversal_entry/{SPEC.md, audit/population_definition.md, common.py, freeze_model.py, build_scores.py, build_events.py, build_placebos.py}`.
Upstream verification reads: `studies/regime_sequence_chop_context/{build_weakness_atlas.py, reproduce_regimes.py, train_weakness_model.py, run_study.py L1-230}`.
Out of scope (per task, audited separately): `strategy.py`, `run_nt.py`, `test_fill_fixture.py`, `analyze.py`. `strategy.py` and `build_placebos.py` appeared on disk mid-audit; `build_placebos.py` was read because it is directly responsive to Key Claim 4 and is matched-donor logic subject to the CLAUDE.md pre-execution gate. `strategy.py` was left untouched per the stated separate-audit plan.
**Auditor:** lookahead-auditor v1

## Summary

- Critical: 2
- Warning: 4
- Note: 3

## Critical findings

### [Cross-file contract bug, adjacent to E-class config mismatch] `build_placebos.py:63-65` — `causal_scores.parquet` has no `in_econ_window` column; donor pool will crash or (once patched) needs the econ-window filter re-verified

```python
pool = scores[scores["score_valid"] & scores["w4_score"].notna()
              & (scores["w4_score"] < thr)
              & scores["in_econ_window"]].copy()
```

`scores` here is loaded fresh via `pd.read_parquet(WORK / "causal_scores.parquet")` (`build_placebos.py:58`). That file is written by `build_scores.py:88` with columns `observation_time, direction, regime_start_ns, regime_age, atr, close, current_pnl, current_mfe, current_mae, giveback, period, score_valid, w4_score, year, rth` — **no `in_econ_window` column**. The `in_econ_window` column is computed only as a transient in-memory column inside `build_events.py:136-142` (`scores["in_econ_window"] = econ_mask`) and is never persisted back to disk (`build_events.py` writes `cov`, `events`, `diag`, `pvw`, `id_audit` — not `scores`).

**Concrete failure:** first run of `build_placebos.py` raises `KeyError: 'in_econ_window'` before a single donor is sampled — the placebo generation step cannot execute at all as currently written.

**Why this matters beyond "it crashes":** the fix is not merely mechanical. `build_placebos.py`'s own docstring (lines 1-10) states the donor pool is constrained "inside the economics window" — i.e., the intent is that donors are drawn only from 2025-03-01..2025-12-30 / 2026-01-01..2026-04-29, the same population the real D10 events are drawn from. If the column is simply patched in without recomputing the correct boundary (e.g., by naively dropping the `& scores["in_econ_window"]` clause to unblock the crash), donors from the **val/calibration window (2025-01-01..2025-02-28)** — the exact period used to freeze the D10 threshold — would leak into the placebo comparison population. That would compare real (post-threshold-freeze) D10 events against a partially threshold-tuned-period donor population, silently reintroducing exactly the contamination `freeze_model.py` was careful to avoid.

**Recommended fix (do not apply):** persist `in_econ_window` (or the underlying `ECON_WINDOWS` boundaries) onto `causal_scores.parquet` in `build_scores.py` or `build_events.py`, or recompute it inline in `build_placebos.py` from `common.ECON_WINDOWS` directly (mirroring `build_events.py:136-142`) rather than assuming it exists on the loaded parquet. Re-run the donor-pool row count check after the fix and confirm zero donor `observation_time` values fall in Jan-Feb 2025.

**PASS 2 STATUS: FIXED.** `build_scores.py:90-96` now computes `in_econ_window` from `common.ECON_WINDOWS` and persists it as a column on `causal_scores.parquet`; `build_events.py:149-150` asserts its presence (`assert "in_econ_window" in scores.columns`); `build_placebos.py:65` consumes the persisted column. Re-verified clean — see Pass 2 section below.

### [H4 pattern] `build_events.py:327-343` — offline stop-diagnostic credits fills at the exact trigger price, not next-bar-open, for non-gapped touches

```python
for s_mult in STOP_GRID:
    stop_px = _tick_round(d10_px - entry_dir * s_mult * atr_cp)
    if entry_dir == 1:
        hit = ll <= stop_px
    else:
        hit = hh >= stop_px
    idx = np.argmax(hit) if hit.any() else -1
    ...
    if hit.any():
        gap = (oo[idx] < stop_px) if entry_dir == 1 else (oo[idx] > stop_px)
        diag[f"stop{tag}_fill_px"] = float(oo[idx]) if gap else stop_px
```

This correctly uses bar `high`/`low` to detect the touch (H1 satisfied) and correctly credits the bar's `open` when the bar gapped through the level (partial H4 credit). But when the bar's `low`/`high` touches the stop level **without** gapping past it at the open, the fill is credited at exactly `stop_px` — the trigger price itself, with zero assumed slippage within that 1-second bar. This is the literal H4 anti-pattern this project has already paid for twice (`feedback_offline_sim_use_ohlc_for_triggers.md`: "close-only missed touches cost $13/tr"; `be_simulation_path_checkpoint_inflation.md`: 30s-checkpoint sim showed +$3,535 vs 1s-precise -$10,490).

**Concrete failure scenario:** a D10 entry fires; the ATR-stop diagnostic (`stop050_hit_before_flip`, `stop100_hit_before_flip`, `stop150_hit_before_flip` and their `_fill_px` companions in `forward_reversal_diagnostics.parquet`) will report every non-gap stop-out as filling at the exact stop price. If this diagnostic is used — as `SPEC.md`'s own description says it will be ("policy design") — to pick among the 0.50/1.00/1.50 ATR stop grid, or to form an early go/no-go read on whether the P1/P3 hypothesis is worth a full NT run, the diagnostic will systematically overstate the stop-based exit's edge (every non-gap stop-out looks like zero-slippage), exactly mirroring this repo's own recorded $13/trade and $14K historical incidents from the same anti-pattern.

**Why CRITICAL despite the "diagnostic only" disclaimer in SPEC.md:** `forward_reversal_diagnostics.parquet` is a named required result artifact that will be read by `analyze.py`/`final_report.md`. The project's own memory records this exact class of bug leaking into narrative conclusions before NT-validation caught it (`bar_mode_overstates_fade_strategies.md`, `hhll_exit_overlay_finding.md` — "tape-replay mechanical exits overstate edge 5-10x"). Nothing in the current code path prevents the same thing happening here.

**Recommended fix (do not apply):** either (a) fill at the **next 1s bar's open** after the bar in which `hit` first becomes true (matching H4's stated NT semantics for a strategy-driven stop check), or (b) if the SPEC's "resting GTC stop-market order handled intrabar at the venue" model is intended to genuinely fill at the touch price with no incremental slippage (a defensible model for a resting order, distinct from a strategy-polls-then-submits model), explicitly confirm that assumption against `test_fill_fixture.py`'s micro-fixture (once written) before treating `forward_reversal_diagnostics.parquet` numbers as anything but an upper bound, and label them as such in any report language.

**PASS 2 STATUS: RESOLVED (recharacterized, not a bug).** `test_fill_fixture.py`'s "normal" scenario proves NT's own resting GTC stop-market order fills at exactly the trigger price on a non-gapped touch (`stop["px"] == 99.75`, fixture assertion at line 176) — this is option (b) above, now empirically confirmed rather than assumed. `build_events.py`'s diagnostic (unchanged at 346-361) now correctly *mirrors* NT's real, verified execution model rather than committing the H4 anti-pattern in the sense the original finding worried about (a strategy-polls-then-submits model with silent zero-slippage credit). The gap-through case remains conservatively repriced in `analyze.py:reprice_stops` (see Pass 2 clean checks). No further action required.

## Warnings

### [Population completeness] `build_events.py:45-51` — the first regime of each year (post-warmup, pre-first-flip) is silently absent from the regime table

```python
prev = df_1m["regime"].shift(1).fillna(0).astype(int)
flips = df_1m[(df_1m["regime"] != 0) & (prev != 0)
              & (df_1m["regime"] != prev)]
```

`flips` requires the *previous* regime to already be non-zero. The very first genuine regime of the year (the interval from `regime` first becoming ±1 after the `regime==0` warmup state, until the next real flip) never has a qualifying "start" flip event under this filter — its start transition is `0 -> ±1`, which fails `prev != 0`. Because `build_regime_table`'s `rows` loop only ever emits a row keyed by `frows[i].close_ts` as `regime_start_ns`, this first regime of the year is never added to `reg` at all: no coverage row, no D10 diagnostics, no possible entry event for it, even though it is a real tradable regime with a real subsequent flip.

**Concrete failure scenario:** if that first regime of the year happens to cross D10 before its (real) flip, that would be a legitimate P1 entry opportunity per the spec's own definition — it is dropped with no trace, no `score_unavailable_reason` tag, and no line in `regime_d10_coverage.parquet`. This directly contradicts `population_definition.md`'s explicit promise: "No trade filtering of any other kind (no dropna on outcomes, no resolved-only cohorting)." Impact is bounded (at most 1 regime per year, 2 regimes total across 2025/2026), but it is undocumented and asymmetric — it always removes the year's *first* regime, which is also the one immediately following each year's fresh-engine warmup, i.e., not a random draw from the population.

**Recommended fix (do not apply):** either include the year's first post-warmup regime in `reg` (treating the `0 -> ±1` transition's `close_ts` as a valid `regime_start_ns`), or explicitly document and count this exclusion the same way `age_gt_1800s` / `warmup_or_features_nan` / `no_checkpoint_rows` are documented in `population_definition.md`.

**PASS 2 STATUS: unchanged, still open.** `build_events.py:58-60` (renumbered from 45-51 in the version re-read for Pass 2) is textually identical. Not re-flagged as its own Pass 2 item; carried forward here for tracking. Also note this same exclusion propagates to the NT strategy: `strategy.py:_on_1m` (lines 380-384) treats the `prev==0 and new!=0` transition identically (sets `_regime_start` but never treats it as a "flip"), so the NT-side population matches the offline gap consistently — the two sides are at least *mutually consistent* even though both omit the same regime.

### [Silent audit-gap] `build_events.py:243-251` — entries skipped for economics-window or no-fillable-bar reasons are dropped with a bare `continue`, not logged for reconciliation

```python
if not (econ_s.value <= first_d10 < econ_e.value):
    continue
row_cp = g[g["observation_time"] == first_d10].iloc[0]
avail_ns = first_d10 + NS_PER_S
...
i_ent = np.searchsorted(ts_1s, avail_ns, side="left")
if i_ent >= len(ts_1s):
    continue
```

`population_definition.md:41-45` explicitly promises: "Signals skipped for these reasons are logged with skip reasons — the offline event universe and the NT-actioned universe are reconciled in `audit/entry_timing_audit.parquet`." Neither `continue` here writes anything to any tracked structure; a regime whose D10 crossing occurred but fell outside the econ window, or occurred so close to data-end that no fillable 1s bar exists, is indistinguishable in the output from a regime that simply never reached D10. This will make the later offline-vs-NT reconciliation (`entry_timing_audit.parquet`, not yet built) harder to construct correctly and could hide a real discrepancy as "no crossing" rather than "crossing occurred but was not actionable."

**Recommended fix (do not apply):** append a skip-reason row (e.g., `regime_id`, `first_d10`, `skip_reason ∈ {outside_econ_window, no_fillable_bar}`) for both `continue` branches, to be joined against the NT-actioned universe later.

**PASS 2 STATUS: FIXED.** `build_events.py:253-258` now appends `{"regime_id": ..., "reason": "crossing_outside_econ_window"}` to `offline_skips` before the econ-window `continue`; `build_events.py:323-328` appends `{"regime_id": ..., "reason": "no_bars_for_diag"/"bad_atr"}` before the second `continue`. `offline_skips` is written to `audit/offline_event_skips.parquet` (`build_events.py:399-400`). The specific `i_ent >= len(ts_1s)` no-fillable-1s-bar case from the original finding is no longer a separate branch (the diagnostic-loop `continue` now covers the equivalent no-bars condition via `len(hh)==0`), and is logged. Confirmed fixed.

### [Fail-fast gap] `build_events.py:163-174, 369-377` — regime/score identity mismatch counts (`n_regime_only`, `n_score_only`) are computed and printed but not fail-fast gated, unlike the direction-mismatch check

```python
id_audit.append({
    "year": year, "n_regimes": len(reg_starts), "n_score_regimes": len(score_starts),
    "n_matched": len(matched), "n_regime_only": len(reg_starts - score_starts),
    "n_score_only": len(score_starts - reg_starts),
})
...
if n_mm:
    raise SystemExit("FAIL-FAST: direction mismatch between regime table "
                      "and score stream")
```

SPEC.md's central bit-for-bit alignment assumption ("the engine is seeded fresh at Jan 1 of each processed year, matching the upstream atlas construction, so regime boundaries and checkpoint keys align with the atlas bit-for-bit") is exactly the kind of claim that should be enforced, not just measured. The `direction_mismatch_flag` path does raise `SystemExit`, but `n_regime_only`/`n_score_only` — which would reveal a `regime_start_ns` reconstruction or engine-seeding drift between this study's regime engine and the upstream atlas's checkpoint keys — are only printed. If a non-trivial fraction of regimes fail to match, every affected regime's checkpoints become invisible to the `grp.get(r.regime_start_ns)` lookup (`build_events.py:179`), and the affected regimes will be silently misclassified as `no_checkpoint_rows`/`warmup_or_features_nan` rather than flagged as an identity-matching failure — the run will complete without error and produce a plausible-looking (but wrong) coverage report and entry-event population.

**Recommended fix (do not apply):** add an assertion (e.g., `n_regime_only / n_regimes < 0.01` and `n_score_only / n_score_regimes < 0.01` per year) alongside the existing direction-mismatch fail-fast, before writing final results.

**PASS 2 STATUS: PARTIALLY FIXED.** `build_events.py:402-408` now adds a fail-fast on `n_score_only > 0` ("every score-stream regime must exist in the regime table"). `n_regime_only` (real regimes with no matching score-stream entry — the opposite-direction gap, e.g. regimes too short/warmup-affected to have been scored, which is expected/benign) is still not gated, but that is defensible since a nonzero `n_regime_only` is the *expected* steady state (regimes with `no_checkpoint_rows`/`warmup_or_features_nan` are a documented, legitimate population segment) rather than an identity-drift signal. The originally-requested proportional threshold was not added, but the asymmetric fix (gate the direction that actually signals drift, i.e. `n_score_only`) is a reasonable and arguably better-targeted resolution. Treated as resolved.

### [Interpretability] `build_events.py:99-126` (`summarize_coverage`) — the 2025 coverage summary conflates the Jan-Feb val/calibration window with the Mar-Dec economics window under a single `year == 2025` segment

`build_regime_table`/`build_events.py`'s coverage loop (`for r in reg.itertuples(): ...`) iterates over **every** regime in the raw 1s file for the year, with no gating on `ECON_WINDOWS` — only the entry-event generation step (line 243) applies the econ-window filter. `summarize_coverage` then groups by `"year"` (among other keys) over the full `cov` DataFrame, so `regime_d10_coverage_summary.parquet`'s `year == "2025"` rows implicitly blend: (a) Jan-Feb 2025 regimes, drawn from exactly the period used to set the 90th-percentile D10 threshold (so their `ever_reached_D10` / `d10_before_end` rates are mechanically close to the calibrated ~10% rate by construction), with (b) Mar-Dec 2025 regimes, the actual traded/economics population (which may show a different D10 hit-rate due to distribution shift). There is no `period` or `in_econ_window` column on `cov` to let a reader separate the two.

**Concrete failure scenario:** a reader (or `analyze.py`, not yet written) computing "2025 D10 coverage rate" from `regime_d10_coverage_summary.parquet` will get a blended number that is pulled toward the calibration-period's tautologically-close-to-10% rate, understating any real coverage drift in the traded period — a milder, descriptive-statistics analog of the train/serve boundary confusion this project has hit before (`w4_exit_study_dropped_b4.md`).

**Recommended fix (do not apply):** add a `period`/`in_econ_window` column to `cov` (mirroring the `scores` DataFrame's `in_econ_window`) and either exclude calibration-window regimes from `summarize_coverage`'s year-level aggregation or break them out as their own segment.

**PASS 2 STATUS: FIXED.** `build_events.py:373-387` now tags every `cov` row with a `window` column (`"calibration"` / `"economics"` / `"other"`) computed from `ECON_WINDOWS`, and `summarize_coverage` is now called only on `cov[cov["window"] == "economics"]` (line 386-387) before writing `regime_d10_coverage_summary.parquet`. Confirmed fixed — the calibration window is now structurally excluded from the summary rather than merely taggable.

## Notes

### `common.py:41-43` (`ECON_WINDOWS`) vs `SPEC.md:143-145` — end-date convention is consistent but worth a one-line comment

`ECON_WINDOWS[2025]` upper bound is `2025-12-31` (exclusive), and SPEC.md states the 2025 data end as `2025-12-30`. These are consistent (exclusive-Dec-31 covers all of Dec 30) only because the raw data does not extend into Dec 31; there is no enforcement of that assumption in code. A one-line assertion in `build_events.py` (e.g., `assert df_1s.index.max() < ECON_WINDOWS[2025][1].value`) would make the equivalence self-verifying rather than incidental.

### `build_events.py:136-142` — `scores["in_econ_window"]` (`econ_mask`) is computed but never used within `build_events.py` itself

The per-regime entry-event loop recomputes the same window check inline (`econ_s.value <= first_d10 < econ_e.value`, line 243) rather than reusing the `in_econ_window` column. This is currently harmless (both checks encode the same `ECON_WINDOWS`), but it is duplicated logic that could silently drift if one copy is edited without the other, and — as the Critical finding above shows — the column's non-persistence to disk is precisely what breaks `build_placebos.py`. Consider computing it once in `common.py` as a helper and reusing it everywhere the window boundary matters.

**PASS 2 STATUS: superseded.** `in_econ_window` is now computed once in `build_scores.py` and persisted; `build_events.py` still recomputes the boundary inline for the per-regime loop and separately for the `cov["window"]` tagging, so the "duplicated logic" observation technically still holds in a weaker form, but the disk-persistence risk that motivated the note is gone.

### `build_placebos.py` matched-donor logic — clean on entry-time causality, but is new matched-donor/nearest-neighbor selection logic and was not part of this audit's originally-assigned file list

Per CLAUDE.md's pre-execution trigger ("matched-donor or nearest-neighbor selection logic (placebos, controls)... audit that component's code BEFORE its first execution"), `build_placebos.py` should receive its own explicit pre-execution audit pass (this report covers it only insofar as it bears on Key Claim 4 and the `in_econ_window` bug above). On the specific question asked: **confirmed clean** — the donor-matching keys (`year, direction, rth, atr_bucket, age_bucket, mfe_bucket, gb_bucket`) are built exclusively from entry-time/checkpoint-time fields (`regime_age`, `atr`, `current_mfe`, `giveback`, all sourced from the checkpoint row, not from regime-level future aggregates), and `regime_mfe_atr` (the full-regime, future-computed descriptive field from `add_regime_mfe`) is never referenced anywhere in `build_placebos.py`. This satisfies Key Claim 4's requirement that placebo matching use entry-time checkpoint fields, not the future-computed regime-level MFE.

**PASS 2 STATUS: dedicated pass completed below (Key Claim 8).** See Pass 2 section — one new NOTE-level finding on cross-year ATR-bucket-edge computation; all other aspects re-confirmed clean.

## Clean checks

- **Claim 1 (freeze_model.py train/val-only, no test contamination):** Confirmed. `freeze_model.py:44` filters the atlas to `period in ["train", "val"]` only; `"test"`/`"secondary_oos"` are never loaded in this file. Threshold is the 90th percentile of `val`-only probabilities (`freeze_model.py:70`), computed and persisted with provenance (atlas/manifest SHA-256, row counts, AUCs) before any 2025/2026 economics exist. Sanity assertions on split sizes (`> 1M train`, `> 100K val`) are a good defensive check.
- **Claim 2 (score availability convention, T+1s):** Confirmed against upstream ground truth. `build_weakness_atlas.py:44` (`idx_cp = np.searchsorted(ts_arr, cp_ts, side='right') - 1`) selects the last 1s bar with OPEN time ≤ `cp_ts`; `current_price = close_arr[idx_cp]` is therefore the close of the bar spanning `[cp_ts, cp_ts+1s)`, which is only known in wall-clock time at `cp_ts + 1s`. `build_scores.py`'s and `build_events.py`'s "+1s" availability convention (`avail_ns = first_d10 + NS_PER_S`) is consistent with this and is applied consistently at every point it's used (`build_events.py:246, 250`).
- **Serving-feature train/serve consistency (Claim 2, part 2):** Confirmed. `build_scores.py` scores the atlas's own checkpoint rows/columns directly — no re-derivation of features through a separate pipeline, no risk of a parallel feature-computation path drifting from the training path.
- **`regime_start_ns` float-reconstruction exactness (`build_scores.py:68-73`):** Verified arithmetically exact given upstream's construction (`cp_ts`, `flip_ts` are integer-second multiples; the float division/rounding round-trips exactly at these magnitudes) — not a source of silent id-matching drift on its own (though see the Warning above about the *lack of a fail-fast gate* on the resulting match counts).
- **Regime table causality (Claim 3, part 1):** `reproduce_regimes.py`'s `aggregate_and_run_regimes` runs the `RegimeEngine` sequentially over completed 1m bars in chronological order using only each bar's own completed H/L/C — no forward reference.
- **D10 crossing definition and same-timestamp exclusion (Claim 3, part 2):** `build_events.py:190-192, 203-204, 241-244` correctly implements "first checkpoint with `score >= threshold`" and correctly uses **strict** `<` for `d10_before_end`, excluding `first_d10 == regime_end_ns` from entries — matches SPEC.md's stated same-timestamp exclusion rule.
- **Fill/wait-for-flip price `searchsorted` conventions (Claim 3, part 3 / Claim 5):** All `side="left"` usages in `build_events.py` (lines 84, 85, 250, 260, 302) consistently implement "first index with `ts >= target`," matching both the D10-fill convention (open of first 1s bar with `ts_event >= obs+1s`) and the wait-for-flip convention (open of first 1s bar with `ts_event >= regime_end_ns`). No inconsistent `side='left'`/`'right'` mixing found.
- **Stop-diagnostic HIGH/LOW usage (H1):** `build_events.py:329-332` correctly uses `ll`/`hh` (bar low/high) to detect stop touches, not `close` — satisfies H1. (The fill-price crediting on non-gapped touches is separately flagged as Critical under H4, above; now RESOLVED per Pass 2 status.)
- **Censored/trailing regime handling (Claim 3, part 6):** The trailing open regime (`end_censored=True`) is retained in `reg`/`cov` (not filtered), and its `wait_for_flip_px` is correctly left `NaN` (no flip exists yet to reference) while its D10 entries (if any) are still generated — consistent with `population_definition.md`'s "no survivorship filtering" promise for this specific case.
- **`regime_mfe_atr` isolation (Claim 4, part 1):** Confirmed used only in `cov`/`summarize_coverage` (`build_events.py:95, 107-109, 219`) — never included in the `ev` (entry event) or `diag` (diagnostics) dictionaries, and never referenced in `build_placebos.py`. It is not usable as an entry-time covariate anywhere in the current offline pipeline.
- **No pandas rolling/shift look-ahead patterns:** `grep -n "shift(-\|center=True\|bfill\|\.ffill("` across all `.py` files in this study returned zero matches.
- **W4 feature-spec pinning:** `common.py:71` asserts `manifest["best_spec"] == "W4"` before using its feature list — fails fast rather than silently substituting a different upstream-chosen spec if the manifest ever changes.

## Open items requiring follow-up before/at first execution

1. ~~Fix the `in_econ_window` cross-file contract bug in `build_placebos.py` (Critical #1)~~ — **DONE, re-verified Pass 2.**
2. ~~Resolve or explicitly bound the H4 stop-fill-price assumption in `build_events.py`'s diagnostic loop (Critical #2)~~ — **DONE, re-verified Pass 2 (test_fill_fixture.py confirms the resting-order model is NT's real behavior).**
3. Decide whether to include the year's first post-warmup regime in the population, or document its exclusion (Warning) — **still open**, and now confirmed to affect the NT strategy identically (see Pass 2 status note above), so it is at least internally consistent between offline and live.
4. ~~Add skip-reason logging for the two silent `continue`s in the entry-event loop (Warning)~~ — **DONE, re-verified Pass 2.**
5. ~~Add a fail-fast threshold on `n_regime_only`/`n_score_only` in the id-audit (Warning)~~ — **DONE (asymmetric: `n_score_only` gated, `n_regime_only` left ungated as a defensible choice), re-verified Pass 2.**
6. ~~Tag `cov` with a period/econ-window column so 2025 coverage summaries don't blend calibration and traded periods (Warning)~~ — **DONE, re-verified Pass 2.**
7. ~~`build_placebos.py` should receive its own dedicated pre-execution audit pass~~ — **DONE, see Pass 2 Key Claim 8.**
8. `strategy.py`, `run_nt.py`, and `test_fill_fixture.py` — **DONE, see Pass 2 below.** New CRITICAL finding: the NT-runtime-vs-offline regime/score identity parity that SPEC.md promises is audited (`audit/score_regime_id_audit.parquet`) is in fact only an offline-vs-offline comparison; no artifact compares the *live* NT strategy's regime engine (fed from the catalog) against the offline score stream (built from raw files). See Pass 2 Critical #1.

---

*Audit complete (Pass 1). Findings reflect read-only static analysis of the files listed under Scope. Dynamic bugs and the NT strategy/runner code were out of scope for Pass 1 — see Pass 2 below.*

---

# Pass 2 — NT execution stage

**Date:** 2026-07-12
**Scope:** `studies/fable5_pre_flip_d10_reversal_entry/{strategy.py, run_nt.py, build_placebos.py, analyze.py, test_fill_fixture.py, audit/fill_fixture_observations.json, SPEC.md}`. Re-verification reads: `build_scores.py`, `build_events.py`, `common.py` (to confirm Pass-1 fixes), `studies/regime_sequence_chop_context/reproduce_regimes.py` (regime-engine port comparison).
**Auditor:** lookahead-auditor v1 (second pass, NT execution stage; prior interrupted attempt discarded, this is a fresh pass)

## Summary (Pass 2 only)

- Critical: 1
- Warning: 3
- Note: 5

## Re-verification of Pass 1 CRITICAL fixes

Both Pass 1 CRITICAL findings are confirmed fixed (details inline above, under each original finding's "PASS 2 STATUS"). Summary:

1. **`in_econ_window` persistence** — `build_scores.py:90-96` computes and persists the column; `build_events.py:149-150` fail-fast-asserts its presence; `build_placebos.py:65` consumes it correctly. Confirmed no Jan-Feb 2025 calibration-window donors can enter the placebo pool (`build_placebos.py:63-68` additionally requires `observation_time < regime_end_ns`, i.e. strictly pre-flip, on top of the window gate).
2. **H4 stop-fill-price diagnostic** — recharacterized rather than "fixed" in the literal sense (the code at `build_events.py:346-361` is unchanged from Pass 1), but `test_fill_fixture.py`'s "normal" scenario (assertion at line 176, `stop["px"] == 99.75`) now provides ground truth that NT's own resting stop-market order genuinely fills at the exact trigger price on a non-gapped touch — this is option (b) contemplated in the original Pass 1 finding, now empirically confirmed rather than assumed. The offline diagnostic's non-gapped-touch fill-at-trigger convention is therefore a faithful mirror of NT's real execution model, not an independent optimistic assumption. No further action required for this specific finding.

## Critical findings (Pass 2)

### [Cross-file identity gap] No artifact verifies the *live* NT regime engine's `regime_start_ns` sequence against the offline score stream's `regime_start_ns` — SPEC.md's own promised audit does not exist

`SPEC.md:166-167` states: "The regime/score parity between the offline stream and the NT runtime stream is itself audited (`audit/score_regime_id_audit.parquet`)." This is not true as implemented. `audit/score_regime_id_audit.parquet` is produced entirely by `build_events.py:173-184, 397-398`, comparing `reg_starts` (the offline regime table, built from `aggregate_and_run_regimes(df_1s, "1m")` on `RAW_1S[year]` = `data/raw/NQ_v0_1s_{year}.parquet`) against `score_starts` (the offline causal-score stream, built from `weakness_checkpoint_atlas.parquet`, itself constructed from the same `RAW_1S` files upstream). **Both sides of this comparison are offline, and both are ultimately derived from the same raw parquet files.** Neither side ever touches `data/catalog/NQ_v0_2020_2026` — the catalog that `run_nt.py:72-74` actually feeds into the `BacktestEngine`, and from which the *live* `strategy.py` `RegimeEngine` (instantiated fresh in `D10ReversalStrategy.__init__`, `strategy.py:115`) computes its own, independent `regime_start_ns` sequence via `_on_1m` (`strategy.py:373-426`, `flip_ts = bar.ts_init` at line 387).

The only NT-runtime-side signal that could reveal a divergence between the live regime engine and the offline `regime_start_ns` keys baked into `causal_scores.parquet` is `self.mismatch_count` (`strategy.py:151, 272, 291`), incremented when:
- a checkpoint's regime doesn't match the current live regime but shares its direction (`_handle_d10_observation`, `strategy.py:270-272`) — the specific pattern a catalog/raw-identity drift would produce (a checkpoint's `regime_start_ns` no longer lining up with the live engine's `_regime_start`, even though direction still happens to agree); or
- a placebo donor's `regime_start_ns` doesn't match the current live regime (`_handle_placebo_trigger`, `strategy.py:290-291`).

`mismatch_count` is written to `meta.json` (`run_nt.py:114`) and printed (`run_nt.py:120`, `strategy.py:618-621`) but **is never compared against a threshold, never gated with a fail-fast check, and is not written to a dedicated per-mismatch audit parquet** (no `regime_id`, no `observation_time`, no diagnostic detail — just a scalar count). `build_report.py:230-233` cross-references only `audit/score_regime_id_audit.parquet` (the offline-only comparison) for its "Score / regime-ID reset audit" section, reinforcing that the NT-runtime side of this promised audit was never actually built.

**Why this is CRITICAL, not a documentation nit:** this project has already hit exactly this failure mode on this exact instrument. Project memory (`hhll_exit_overlay_finding.md`): "NQ catalog bars ≠ raw tick file on roll days — 100-250pt gaps... bars/ticks track different contracts at quarterly rolls." `run_nt.py` loads 1m and 1s bars from `CATALOG_PATH = data/catalog/NQ_v0_2020_2026` (`common.py:26`), while the score stream and regime table that `causal_scores.parquet`/`regime_d10_coverage.parquet` are built from come from `data/raw/NQ_v0_1s_{year}.parquet` (`common.py:22-25`). These are two different files that are *assumed* (but never verified end-to-end) to represent the same underlying market data closely enough that the same EMA3/EMA9/ATR14 regime engine, run independently on each, produces bit-for-bit identical flip timestamps. If they diverge — even only around a quarterly roll day, which is exactly the documented failure mode — the live strategy's `self._regime_start` will not match the `regime_start_ns` keys in `self._scores`, and `is_current` (`strategy.py:240`) will be silently `False` for every checkpoint of the affected regime(s): no crossing is ever detected as "current," so **that regime's entry opportunity vanishes with no error, no log line above a scalar counter increment, and no distinguishing signature from a regime that legitimately never reached D10.** The `entry_event_reconciliation.parquet` count-level check in `analyze.py:341-361` (offline `n_off` events vs NT `nt_actioned` count) could in principle surface a large-scale version of this as a raw count mismatch, but it has no fail-fast gate (only `bad` — the unrelated submit-lag check — triggers `SystemExit`), and a localized (e.g., roll-day-only) drift affecting a handful of regimes per year would not obviously stand out in an aggregate count table.

**Concrete failure scenario:** a real D10 crossing occurs in a regime whose `regime_start_ns` (from the raw-file-derived score stream) is, say, 50ms or 1 catalog-bar-boundary off from the live catalog-derived regime engine's `_regime_start` for the "same" regime (due to a roll-day gap or any other catalog/raw discrepancy). The checkpoint's `is_current` check fails for every observation in that regime; the regime is silently excluded from P1/P3/P4A/P4B entries for the entire year, with `mismatch_count` incrementing by some number nobody is required to look at, let alone gate on. The final report would show a plausible, non-erroring trade count and economics that quietly excludes an unknown subset of the true population — precisely the "silently corrupts results" bar for CRITICAL.

**Recommended fix (do not apply):** before trusting any NT run, dump the live strategy's own realized `regime_start_ns` sequence per year (e.g., append to `strategy.trades`-style bookkeeping, or a dedicated `self.regime_log` list flushed in `on_stop`) and diff it bit-for-bit against `regime_d10_coverage.parquet`'s offline `regime_start_ns` column for the same year, with a `SystemExit` fail-fast on any non-empty symmetric difference (or a tight tolerance threshold if exact equality proves infeasible for a legitimate, understood reason). At minimum, add a fail-fast on `mismatch_count == 0` in `run_nt.py:run_one` before writing `meta.json`, and persist `same_ts_log`'s `d10_obs_after_flip`/mismatch cases with enough context (`regime_start_ns` on both sides) to actually diagnose a drift if one is found, rather than only a running total.

## Warnings (Pass 2)

### `strategy.py:436-448` (`_submit_exit`) — unverified same-bar race between a resting stop's intrabar trigger and a D10/flip-driven cancel-then-exit; the fixture does not test this specific scenario

```python
def _submit_exit(self, reason: str, meta):
    ...
    # cancel resting stop first: the exit decision is made causally at a
    # completed-bar boundary and fills at the next bar open, ahead of any
    # intrabar stop trigger of that bar
    self._cancel_stop()
    side = OrderSide.SELL if t["entry_dir"] == 1 else OrderSide.BUY
    order = self.order_factory.market(..., time_in_force=TimeInForce.FOK, reduce_only=True)
    ...
    self.submit_order(order)
```

SPEC.md:126-132 asserts a specific, confident claim about how ties resolve: "if the stop and a D10/flip exit could fill on the same 1s bar, the resting stop participates in NT's intrabar tick sequence (adaptive high/low ordering) and any FOK exit that arrives after the position is already flat is rejected and logged — ties therefore resolve to the stop (conservative)." This claim requires that, for the *same* bar N, the venue's resolution of a resting stop's intrabar high/low touch is dispatched to the strategy (closing the trade via `on_order_filled`, `strategy.py:517-532`) *before* `on_bar(bar N)` runs the D10/flip decision logic that would call `_submit_exit`. If instead `on_bar(bar N)` fires first and the strategy calls `_submit_exit` — which unconditionally cancels the resting stop as its very first action, *before* the venue has had any chance to resolve whether bar N's own high/low would have triggered it — then a D10/flip exit could pre-empt a legitimate same-bar stop-out, filling at bar N's close (per the fixture's "just-completed bar's CLOSE" fill model, `test_fill_fixture.py:172-174`) instead of at the (potentially worse) stop trigger price. This would systematically improve exit prices exactly in the tail scenarios that matter most for P2/P3/P4B economics — a same-bar coincidence of a D10/flip signal and a stop-level breach is plausible precisely at volatile regime-turning moments.

`test_fill_fixture.py` does not test this scenario. Its three scenarios ("normal," "gap," "flat_exit") only cover: (1) a stop firing on a bar with no competing strategy-driven exit that same bar, (2) a gapped stop fill, and (3) a reduce_only exit submitted on a *later* bar (offset 3) than the stop's fill bar (offset 2) — a different-bar sequencing test, not a same-bar race. The comment at `strategy.py:199-200` ("fill bar included: fills happen at this bar's open, before on_bar is delivered") suggests the author believes resting-order resolution happens before `on_bar` for that bar (which, if true, would validate SPEC's claim — the stop would already have fired and closed the trade before `_submit_exit` could ever be reached for that bar), but this is asserted nowhere in the fixture and the comment's own wording ("fills happen at this bar's open") is itself inconsistent with the fixture's established "fills at the just-completed bar's close" model (see Note below), undermining confidence that it reflects a carefully verified fact rather than an assumption.

**Recommended fix (do not apply):** add a fourth `test_fill_fixture.py` scenario: submit an entry, arm a stop, and construct a tape where a *single* bar N both (a) breaches the stop's trigger intrabar and (b) is the bar on which the strategy would decide to submit a D10/flip-style exit (e.g., have the fixture strategy itself attempt a reduce_only exit unconditionally on that bar, independent of the stop). Assert which fill (stop trigger price vs. bar N close) is realized, and update `strategy.py`'s `_submit_exit` if the assumption is wrong (e.g., by checking whether the current bar's high/low already breached the stop before cancelling it, or by deferring the D10/flip exit by one bar in that specific case). Do not trust P2/P3/P4B economics involving same-bar stop/D10-or-flip coincidences until this is resolved.

### `strategy.py:342-370, 421-422` (`_enter_on_flip` rollover path) — rollover entry order is not `reduce_only` and is submitted without confirming the paired exit succeeded, creating a latent netting-corruption risk if the exit is ever rejected

In the P0/P2 opposite-flip rollover branch (`strategy.py:416-422`):

```python
elif t["confirmed"] and new == -t["entry_dir"]:
    if self._exit_order_id is None and not self._exit_retry:
        self._submit_exit("opposite_regime_flip_exit", {"exit_flip_ts": flip_ts})
        if self._flip_entry_policy:
            self._enter_on_flip(flip_ts, new, rollover=True)
```

`_submit_exit` submits a `reduce_only` FOK order for the *old* trade; `_enter_on_flip` (called immediately after, unconditionally, without waiting to see whether the exit filled) submits a **plain (non-`reduce_only`) FOK market order** on the *same side* as the exit (both `SELL` when flipping long→short, both `BUY` when flipping short→long — the exit reduces the old directional exposure and the new entry opens the opposite exposure, so on a netting-OMS venue they are directionally identical orders). This is safe *if* the exit is guaranteed to fill (which `bar_execution=True` FOK fills against a deterministic bar close generally make likely), and the staged-trade mechanism (`_trade`/`_staged_trade`, traced through both possible fill orderings in Clean Checks below) correctly handles either fill-order permutation *when both orders do fill*. But if the exit is ever rejected or fails (`_exit_failed`, `strategy.py:573-582`, which exists specifically to handle this possibility and sets `_exit_retry = True` for a next-bar retry) while the accompanying non-`reduce_only` entry *still* fills, the entry order would be netted by the venue against the still-open old position (a `NETTING` OMS, per `run_nt.py:85`, always nets same-direction fills against existing exposure regardless of any `reduce_only` intent on a *different* order) rather than opening a fresh position in the new direction. The strategy's own bookkeeping (`self._trade`/`self._staged_trade`) would believe a new trade was opened, while the actual account state could be flat or something other than what the strategy models — a silent desync between internal PnL tracking and the true position.

**Concrete failure scenario:** on a flip bar, the exit FOK is submitted and rejected for any reason not covered by the fixture (e.g., a margin/risk-engine rejection, not tested by `test_fill_fixture.py`, which only demonstrates the "reduce_only-when-already-flat" rejection case). The paired entry FOK (not reduce_only) still fills against the still-open old position, netting it down instead of opening the intended new position. `self._trade` is set to a "new" trade object with an `entry_px` that does not correspond to any real new exposure at the venue.

**Recommended fix (do not apply):** either (a) defer `_enter_on_flip(rollover=True)`'s submission until the paired exit's fill is confirmed (retry the entry alongside `_exit_retry`, analogous to the existing exit-retry mechanism), or (b) mark the rollover entry itself in a way that is verifiably safe under a netting OMS even if the exit fails (e.g., verify current net position via `self.portfolio` before submitting, consistent with this project's own documented lesson `nt_gtc_bracket_partial_fill_order_id_matching.md`: "use `portfolio.is_flat()` not cid matching for multi-lot exits").

### `strategy.py:408-414` — `confirm_px` relies on an unverified 1s-before-1m same-`ts_init` dispatch-order assumption; affects only PnL decomposition, not headline economics

```python
if not t["confirmed"] and new == t["entry_dir"]:
    t["confirmed"] = True
    t["confirm_flip_ts"] = flip_ts
    t["confirmed_regime_start"] = flip_ts
    t["confirmed_regime_d10_seen"] = False
    t["confirm_px"] = self._last_1s_close
    t["confirm_px_ts"] = flip_ts
```

`self._last_1s_close` is updated every `_on_1s` call (`strategy.py:197`). At the moment the 1m bar for the confirming flip is processed (`_on_1m`, `ts_init = flip_ts = T`), this code assumes the 1s bar spanning `[T-1, T)` — which also has `ts_init = T` (since 1s `ts_init = ts_event + 1s = (T-1) + 1 = T`) — has *already* been dispatched to `_on_1s` and updated `self._last_1s_close` to that bar's own close, before the 1m bar's `_on_1m` callback fires for the *same* `ts_init = T`. This is the same "1s bars process before their parent 1m bar" tie-break rule documented elsewhere in this project (`CLAUDE.md` "Common Pitfalls #7," the MFE/MAE collector pattern), and is plausible, but it is a genuine same-`ts_init` tie (not simply an earlier-vs-later `ts_init` ordering, which is unambiguous) and `test_fill_fixture.py` never mixes 1m and 1s bar types in the same test, so this specific tie-break has not been fixture-verified for *this* engine configuration (`bar_execution=True, bar_adaptive_high_low_ordering=True`).

**Impact if the assumption is wrong:** `self._last_1s_close` would instead hold the close of the *second-to-last* 1s bar of the confirming minute (`[T-2, T-1)`), a one-second-stale price. This is bounded, low-severity: `confirm_px` is never used to gate any trading decision (verified — the exit-relevance check in `_handle_d10_observation` at `strategy.py:250` keys on `confirmed_regime_start`, not `confirm_px`; `_close_trade`'s `pnl_pts` at `strategy.py:551` is computed from `entry_px` and the actual exit fill `px`, never from `confirm_px`). It only feeds `analyze.py:add_economics`'s `pre_flip_pnl_usd`/`post_flip_pnl_usd` split (`analyze.py:96-105`), a descriptive decomposition that always sums to the correct total regardless of the exact confirm_px value used as the split point. A wrong `confirm_px` would misattribute a few ticks of PnL between the "pre-flip" and "post-flip" buckets in the decomposition report, not corrupt `net_usd`/`ev_per_trade`/win rate or any other headline number.

**Recommended fix (do not apply):** add a `test_fill_fixture.py` scenario that mixes a 1-minute and a 1-second `BarType` (both subscribed) with a tape constructed so the last second of the minute and the minute bar share `ts_init`, and assert the dispatch order empirically, the same way the existing scenarios assert fill semantics. Until then, treat `pre_flip_pnl_usd`/`post_flip_pnl_usd` in `pnl_decomposition.parquet` as accurate to within one second of price movement at the confirmation boundary, not exact.

## Notes (Pass 2)

### `strategy.py:27-30` (module docstring) — rollover fill-timing description contradicts the fixture-verified fill model

The module docstring states: "Flip rollovers (P0/P2): when the exit flip is also the next trade's entry signal, the exit FOK and entry FOK are both submitted at flip processing so both fill **at the same next-1s-bar open**." This directly contradicts the fixture-established model documented three lines above it (line 13-14: "Decisions submit 1-lot FOK market orders which fill IMMEDIATELY at the decision boundary against the just-completed 1s bar's close") and confirmed in `test_fill_fixture.py` (entry fill `px == 100.00` = bar0's *close*, not bar1's *open* of 100.25 — the tape at `test_fill_fixture.py:48-50` was deliberately constructed with distinct open/close values specifically "so the entry-fill price source is unambiguous"). The actual rollover fills (traced in Clean Checks below) occur at the flip (1m) bar's own close via the same decision-boundary model, not at "the next 1s bar's open." This is a stale/incorrect comment, not a logic bug (the logic itself was traced and found correct — see Clean Checks), but it could mislead a future reader (or a future edit) into believing rollover fills are deferred by a bar when they are not.

**Recommended fix (do not apply):** correct the docstring to match the decision-boundary-close model stated in the header's own point 3.

### `build_placebos.py:74-77` — ATR-quantile bucket edges for donor matching are computed from the combined 2025+2026 real-event population, not per year

```python
atr_edges = np.quantile(events["atr_at_d10"].to_numpy(),
                        [0, .2, .4, .6, .8, 1.0])
```

`events = pd.read_parquet(RESULTS / "d10_entry_events.parquet")` (`build_placebos.py:57`) is loaded without a year filter, so the ATR quintile edges used to bucket-match both real events and the donor pool (`bucketize`, applied identically to `ev` and `pool`) are derived from the full 2025+2026 combined distribution. Since `run_nt.py` runs per-year and `year` remains a strict, never-relaxed exact-match key in `MATCH_KEYS` (`build_placebos.py:34-35, 105`), no donor is ever drawn from the wrong year — the actual matched pairs cannot leak cross-year information. However, the *definition* of which ATR bucket a given 2025 checkpoint falls into is influenced by the 2026 ATR distribution (which, in a genuinely live/causal sense, "doesn't exist yet" relative to any 2025 decision). This is not a causal look-ahead in the traditional trading-decision sense (placebo generation is a retrospective, whole-study statistical control construction, not a live decision), so it does not corrupt any headline economics, but it is a mild inconsistency with the spirit of "matched-donor logic must not use future information" and is easy to eliminate.

**Recommended fix (do not apply):** compute `atr_edges` per year (`events[events["year"] == yr]`) rather than from the combined population, mirroring the year-exact-match constraint already enforced in `MATCH_KEYS`.

### `strategy.py:524-530` — the `stop_filled_with_exit_in_flight` same-timestamp log branch appears logically unreachable given `_submit_exit`'s cancel-before-submit invariant

```python
if cid == self._stop_order_id:
    self._stop_order_id = None
    ...
    if self._exit_order_id is not None:
        self.same_ts_log.append({"case": "stop_filled_with_exit_in_flight", ...})
```

For this branch to execute, `cid == self._stop_order_id` must hold (i.e. `self._stop_order_id` is not `None`) *and* `self._exit_order_id is not None`. But `_submit_exit` (the only place `self._exit_order_id` is ever set) unconditionally calls `self._cancel_stop()` — which sets `self._stop_order_id = None` — as its first action, strictly before assigning `self._exit_order_id`. In a synchronous, single-threaded backtest event loop, this ordering means `self._exit_order_id is not None` should imply `self._stop_order_id is None`, making the two conditions mutually exclusive and this branch dead code. This is not harmful if genuinely unreachable (defensive code), but if it *is* observed to fire in a real run (visible via a non-empty `same_ts_log` filtered to this case), that would be a signal that `cancel_order` is not synchronous/immediate in this engine configuration — which would also directly bear on the same-bar stop-race Warning above and should be investigated together.

**Recommended fix (do not apply):** after the first real NT run, check whether `same_ts_log` ever contains a `stop_filled_with_exit_in_flight` row; if so, treat it as confirmation that `cancel_order` has non-trivial latency and re-open the same-bar-race Warning as a likely-real bug rather than a hypothetical one.

### `strategy.py:584-598` (`on_order_rejected`/`on_order_canceled`) vs `on_order_denied` (`strategy.py:602-605`) — stop-order handling is missing from `on_order_denied`, unlike its peers

`on_order_rejected` and `on_order_canceled` both explicitly check `cid == self._stop_order_id` after the shared `_entry_failed`/`_exit_failed` dispatch, nulling `_stop_order_id` and (for rejection) logging `"Stop order rejected — trade unprotected"`. `on_order_denied` only calls `_entry_failed(cid) or _exit_failed(cid)` with no equivalent stop-order branch. If a stop-market order is ever `denied` (a pre-matching validation failure, distinct from post-validation `rejected`) rather than rejected, `self._stop_order_id` would remain stale and no "trade unprotected" warning would be logged — a minor parity gap in otherwise-symmetric defensive coverage for the strategy's own risk-management order.

**Recommended fix (do not apply):** add the same `if cid == self._stop_order_id: self._stop_order_id = None; self.log.error(...)` handling to `on_order_denied` for parity with `on_order_rejected`.

### `strategy.py:199-200` — excursion-tracking comment is ambiguous and, read literally, appears to contradict the established fill model

"excursion tracking (fill bar included: fills happen at this bar's open, before on_bar is delivered)" is difficult to reconcile with the fixture's established "fills happen at the just-completed bar's close" model (see the module-docstring Note above) if read as describing FOK market-order fills. It more likely describes resting stop-order resolution against a new bar's simulated OHLC path (open→high/low→close) completing before `on_bar` is dispatched for that bar — which, if true, is actually the load-bearing assumption behind the same-bar-race Warning above — but as written it is unclear which fill type it refers to, and it is not tied to any fixture assertion. Recommend rewording for clarity once the same-bar-race fixture scenario (Warning above) resolves the underlying question, so the comment can state the confirmed mechanism explicitly rather than an ambiguous paraphrase.

## Clean checks (Pass 2)

- **RegimeEngine exact port (Claim 2):** Line-by-line comparison of `strategy.py:54-93`'s `RegimeEngine` against `studies/regime_sequence_chop_context/reproduce_regimes.py:6-78` confirms identical EMA3/EMA9 seeding (first bar sets both EMAs to that bar's H/L, no separate warmup period), identical Wilder ATR(14) warmup-then-recursive-smoothing, and identical sticky-regime update logic (`new` initialized to current regime, overwritten only by the breakout conditions, committed only if `new != 0 and new != self.regime`) — the `bars_in_regime` counter is the only omission, and it is unused by this study. Confirmed exact port.
- **Score lookup causality, all three consumer paths (Claim 1):** Real D10 entries (`_on_1s:229-235`), placebo entries (`_on_1s:219-222` via `_handle_placebo_trigger`), and P4B's real-regime D10 exit check (`_on_1s:223-226`) all key on `obs = bar.ts_event` (`strategy.py:195`) while being *processed* at `proc = bar.ts_init = obs + 1s` (`strategy.py:196`) — exactly matching the causal-availability convention (score at `observation_time=T` available at wall-clock `T+1s`, looked up while processing the 1s bar whose `ts_event == T`). No path looks up a score keyed on `ts_init`, and no path evaluates a score before the bar that produces it has been processed.
- **Same-timestamp D10-at-flip exclusion is dispatch-order-independent (Claim 3):** the case SPEC.md calls out explicitly (`SPEC.md:134-139`, `strategy.py:395-403`) — a checkpoint whose `observation_time` equals the flip's `close_ts` — is safe regardless of any 1s/1m tie-break assumption, because the checkpoint becomes actionable at `ts_init = T+1s`, strictly *after* the flip bar's `ts_init = T` (simple magnitude ordering, not a tie). Traced through `_handle_d10_observation`: by the time this checkpoint is processed, `self._regime_start` has already advanced to the new regime, so `is_current` is `False` and `row["direction"]` (old regime) never equals `self._regime_dir` (new regime) for a genuine flip, correctly routing to `same_ts_log["d10_obs_after_flip"]` rather than an entry.
- **First-crossing bookkeeping (Claim 3):** `_regime_seen_d10`/`was_first` (`strategy.py:242-244`) correctly gates entries to the first `>=threshold` observation per regime; a second such observation in the same regime has `was_first=False` and is blocked before reaching `_try_enter`. Confirmed no path allows a re-triggered "first crossing." Exit-relevance (`confirmed_regime_d10_seen`, a separate trade-scoped flag) is independently guarded, so P2/P3/P4B's own-regime D10 exit cannot double-fire even though `_regime_seen_d10` bookkeeping runs unconditionally (including for P0, where it is simply unused dead bookkeeping — harmless).
- **No same-event exit+entry reversal (Claim 3):** the exit-relevance branch in `_handle_d10_observation` (`strategy.py:248-265`) returns unconditionally once matched, before the entry-relevance branch is reached — a checkpoint cannot be treated as both the confirmed-regime's exit trigger and a new entry trigger in the same dispatch.
- **Stale/post-flip D10 observations cannot become pre-flip entries (Claim 4):** the `is_current` check (`row["regime_start_ns"] == self._regime_start`, `strategy.py:240`) is evaluated fresh on every dispatch against the *current* live regime state; a checkpoint belonging to a regime that has already flipped by processing time fails this check and is routed to logging, never to `_try_enter`.
- **Entry gating (Claim 4):** one-attempt-per-origin-regime (`_attempted_regimes`, `strategy.py:320-321, 331`), busy-skip-not-defer (`strategy.py:323-327, 351-358`, both append to `skip_log` and `return` with no queueing), and the trading-window gate keyed on `proc`/`flip_ts` (both `ts_init`-based, `strategy.py:317, 349`) are all confirmed as specified.
- **P0/P2 rollover staged-trade mechanism is robust to both fill-order permutations (Claim 6):** traced both hypothetical orderings explicitly. (a) Exit-fills-first (the likely case if fills are synchronous-on-submit): `on_order_filled` for the exit runs `_close_trade`, setting `self._trade = None`before `_enter_on_flip`'s subsequent `submit_order` call even executes; the entry fill then finds `self._trade is None` and sets it directly (`strategy.py:497-501`) — no staging needed. (b) Entry-fills-first (if fill dispatch order does not strictly follow submission order): the entry fill finds `self._trade is not None` (old trade still active) and sets `self._staged_trade = t`; when the exit later fills, `_close_trade` (`strategy.py:545-560`) closes the old trade and then promotes `self._staged_trade` to `self._trade`. Both orderings produce exactly one closed trade and one newly active trade, with no drop or double-count — confirmed by construction for the case where **both** orders actually fill (see the new Warning above for the case where the exit does *not* fill).
- **"Impossible flip sequence" branch (`strategy.py:423-424`) is genuinely unreachable:** given the regime engine is sticky and, once past the `0` warmup state, alternates strictly between `+1`/`-1` (a "flip" by definition requires `new != prev`, both non-zero, and the engine can only ever move directly between the two non-zero states), a trade entered against origin direction `D` can only ever see its *first* subsequent flip go `D → -D` (the confirming flip). A flip back to `D` while still unconfirmed would require passing through `-D` first, which would already have set `confirmed=True`. Confirmed dead code / valid defensive assertion, not a bug.
- **`confirm_px` set exactly once (Claim 10):** guarded by the `not t["confirmed"]` condition (`strategy.py:406`), which can only be true once per trade given `confirmed` is monotonic (never reset to `False`).
- **`data_end_censored` captures both active and staged trades at engine stop (Claim 10):** `on_stop` (`strategy.py:608-617`) iterates `(self._trade, self._staged_trade)` and only appends entries with a non-`None` `entry_px`, correctly excluding any hypothetical dangling pending-but-unfilled entry order (not itself a population-completeness risk given fills are synchronous-on-submit per the fixture, so an order submitted on the last processed bar should already have resolved via `on_order_filled` before `on_stop` fires).
- **`run_nt.py` engine/window wiring (Claim 9):** fresh `RegimeEngine()` per `D10ReversalStrategy` instantiation (one per `run_one` call, i.e. per year, `strategy.py:115`); `load_start = f"{year}-01-01"` (`run_nt.py:70`) with `catalog.bars(..., start=load_start, ...)` (`run_nt.py:73-74`) — no data before Jan 1 of the run's year is loaded; `trade_start_ns`/`trade_end_ns` sourced from `ECON_WINDOWS[year]` (`run_nt.py:62, 96`) and correctly consumed by both entry paths' `proc`/`flip_ts` gates; placebo path correctly wired only for `P4A`/`P4B` (`run_nt.py:98-99`) and correctly year-filtered on load (`strategy.py:175`).
- **`analyze.py` stop-gap repricing bar-index mapping (Claim 7):** `fill_ts - NS_PER_S` correctly maps a stop fill event's `ts_event` (which, per the fixture, equals the fill *bar's* `ts_init`) back to that bar's `ts_event`/open-time index into the `RAW_1S`-derived, open-time-indexed `bars[yr]` arrays (`analyze.py:74-78`) — consistent with the same open-time-index convention used throughout `build_events.py`'s own `ts_1s` usage.
- **Repricing is conservative-only in both directions (Claim 7):** `analyze.py:81-83`'s `(d==1 and o<stop_px) or (d==-1 and o>stop_px)` reprices a long stop-exit only when the bar's open gapped *below* the trigger (worse fill) and a short stop-exit only when the open gapped *above* the trigger (worse fill) — never triggers on a favorable gap, confirmed never improves a fill.
- **Non-gapped stop touches correctly left at NT's real (fixture-verified) fill price, not re-flagged as an offline-heuristic bug:** distinguished from the Pass 1 H4 finding — here the fill price originates from the actual NT matching engine (a legitimate resting stop-market fill model, empirically confirmed by the fixture), not from an offline touch-detection heuristic with no verification.
- **PnL decomposition reconciles to total (Claim 7):** `pre_flip_pnl_usd + post_flip_pnl_usd == (exit_px - entry_px) * entry_dir * NQ_MULT` by construction in all three branches of `add_economics` (never-confirmed, confirmed-with-confirm_px, and the defensive confirmed-but-missing-confirm_px fallback) — verified algebraically.
- **`exit_reason_audit` fail-fast and exhaustiveness (Claim 7):** `EXIT_REASONS` (`common.py:45-51`) is an exhaustive enumeration of every string literal actually assigned as an `exit_reason` in `strategy.py` (`stop_before_flip`/`stop_after_flip` at line 522-523, `d10_exit`/`opposite_regime_flip_exit` via `_submit_exit`'s `reason` parameter at lines 260, 419, `data_end_censored` at line 611); `raise SystemExit` on any violation confirmed at `analyze.py:195-197`.
- **Placebo tests use completed trades only (Claim 7):** both `r` and `p` series in `placebo_tests` (`analyze.py:275-280`) filter `exit_reason != "data_end_censored"`.
- **Matched-donor logic, dedicated re-check (Claim 8):** all `MATCH_KEYS` covariates (`year, direction, rth, atr_bucket, age_bucket, mfe_bucket, gb_bucket`) are entry-time/checkpoint-time causal fields; strict pre-flip constraint (`observation_time < regime_end_ns`, `build_placebos.py:68`) confirmed; sub-threshold constraint (`w4_score < thr`) confirmed; one-donor-per-regime (`used_regimes` set) and distinct-from-own-regime (`cand["regime_start_ns"] != e["regime_start_ns"]`) constraints confirmed at `build_placebos.py:109-110, 123`; relaxation ladder confirmed to stop at `level=4` (`range(len(MATCH_KEYS), 3, -1)`, i.e. never drops below `[year, direction, rth, atr_bucket]`), matching "never relaxes year/direction/rth/atr"; `candidates()` confirmed to use the pre-grouped exact-tuple lookup only at `level == len(MATCH_KEYS)` and a partial-prefix filter otherwise. No future-dependent field (regime duration, outcome, ever-reaches-D10) enters the match. Only new issue found: the cross-year ATR-bucket-edge computation noted above (Note, not Warning — does not affect which donor year is drawn).
- **Entry-timing submit-lag fail-fast correctly scoped (Claim 7):** `analyze.py:339` (`bad = timing[timing["pre_flip"] & (timing["submit_lag_s"] != 1.0)]`) only gates pre-flip (D10/placebo) entries, which are the only entries where `submit_proc_ts - signal_obs` is guaranteed to be exactly 1s by construction; P0/P2 flip entries (`pre_flip=False`, `submit_lag_s=0` by construction since both `signal_obs` and `submit_proc_ts` are set to `flip_ts`) are correctly excluded from this check rather than producing a false fail-fast.

---

*Pass 2 audit complete. Findings reflect read-only static analysis of the NT execution stage. The one CRITICAL finding (missing NT-runtime-vs-offline regime/score identity verification) and the same-bar stop/exit race Warning should both be resolved — the former via an added fail-fast reconciliation, the latter via an added fixture scenario — before the first full NT backtest run is treated as trustworthy, per CLAUDE.md's pre-execution audit gate for stop/exit fill-timing mechanics and cross-file identity assumptions.*

---

# Findings resolution log (main agent, 2026-07-12)

## Pass 1
- CRITICAL in_econ_window KeyError / val-donor leak: FIXED — build_scores.py
  now persists `in_econ_window` (starts 2025-03-01); build_placebos.py and
  build_events.py consume the persisted column, so Jan-Feb 2025 calibration
  donors are structurally excluded.
- CRITICAL offline stop-fill-at-trigger: RESOLVED AS DOCUMENTED CONVENTION —
  the fixture shows NT itself fills resting stops at trigger on touch;
  the offline diagnostic mirrors NT exactly (incl. gap-through repricing to
  open) and is marked descriptive-only; no stop selection is made from it
  (all three stops always reported, none test-selected).
- WARNING first-regime exclusion: documented in population_definition.md.
- WARNING silent continues: offline skips now logged to
  audit/offline_event_skips.parquet.
- WARNING identity audit not fail-fast: build_events.py now raises on any
  n_score_only > 0 (observed: 0 in both years).
- WARNING calibration/economics blending: coverage rows carry a `window`
  tag; the summary is computed on the economics window only.

## Pass 2
- CRITICAL runtime-vs-offline regime parity unverified: FIXED — strategy.py
  logs every runtime flip (flip_log -> flips.parquet per run); analyze.py
  fail-fasts on any symmetric difference vs the offline regime table AND on
  any nonzero score-lookup regime mismatch count.
- WARNING same-bar stop/exit race: RESOLVED WITH EVIDENCE — new fixture
  scenario "race" proves the venue fills a touched stop during bar
  processing BEFORE the strategy callback, so a same-bar strategy exit is
  rejected (stop always wins). The cancel-stop-then-exit sequence executes
  a causal decision at the boundary close (a real traded price) and cannot
  preempt an already-triggered stop.
- WARNING rollover entry not reduce_only / unconditional: FIXED — the
  staged-trade path was removed; the rollover entry is now submitted only
  inside the exit-fill callback (fills are instantaneous, same boundary
  price), so no entry can exist while the prior trade is open; an entry
  fill while a trade is open now asserts.
- WARNING confirm_px dispatch-order assumption: INSTRUMENTED — trades carry
  confirm_px_lag_s (0 = the 1s bar ending at the flip boundary was already
  processed); analyze.py fail-fasts if >1% of confirmations are stale.
